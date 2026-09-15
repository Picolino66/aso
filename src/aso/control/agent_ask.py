"""`perguntar_ao_agente` — dispatch comum aos serviços de agente (§2.6/§4.1 do plano4.md).

Extraído porque naming/triage/review/discovery repetiam, cada um, o mesmo bloco:
bifurcar `kind == "llm"` / `kind == "cli"`, rodar o CLI numa pasta temporária
descartável e envolver tudo na mesma tupla de exceções (`ERROS_DE_AGENTE`). Nenhum
destes serviços altera código (só produzem texto/JSON): o CLI roda num diretório vazio e
descartável — ou, quando o serviço pede leitura do repositório (discovery e revisão,
ADR-0069), num worktree destacado de leitura, conferido depois da pergunta.

**Refatoração de forma, não de comportamento**: o prompt de sistema, o `_sanear` e o
fallback continuam em cada serviço — aqui só o transporte até o executor.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from aso.agents.contract import SCHEMA_VERSION, envelope_de_pergunta
from aso.control.models import AgentAssignment
from aso.control.respostas_estruturadas import (
    TENTATIVAS_DE_CORRECAO,
    RespostaInvalida,
    esquema_de,
    instrucao_de_formato,
    pedido_de_correcao,
    validar,
)
from aso.execution.agent_stream import extrair_resposta_final, extrair_uso
from aso.execution.catalog import ExecutorCatalog
from aso.execution.llm_client import LlmError, completar
from aso.execution.llm_provider import parse_llm_json
from aso.execution.precos import precificar
from aso.execution.repositorio_leitura import (
    AcessoAoRepositorio,
    EscritaNoRepositorio,
    alteracoes,
    comando_somente_leitura,
    e_repositorio_git,
    worktree_de_leitura,
)
from aso.observability.agent_runs import KIND_ASK, STATUS_FALHA, STATUS_SUCESSO, AgentRun
from aso.shared.agent_usage import UsoDoAgente
from aso.shared.ids import now_iso


@dataclass(frozen=True)
class ContextoDeRun:
    """Para onde e em nome de quem registrar as perguntas desta chamada (ADR-0065)."""

    registrar: Callable[[AgentRun], None]
    orchestration_id: str = ""
    card_id: str | None = None
    request_id: str = ""
    # Evento de domínio na orquestração (ex.: resposta descartada por escrita, ADR-0069).
    ao_evento: Callable[[str, dict[str, object]], object] | None = None


_CONTEXTO_DE_RUN: ContextVar[ContextoDeRun | None] = ContextVar("aso_contexto_de_run", default=None)


@contextmanager
def contexto_de_run(contexto: ContextoDeRun) -> Iterator[None]:
    """Ativa o registro de `AgentRun` para as perguntas feitas dentro do bloco.

    ContextVar em vez de parâmetro: os serviços de agente (triagem, discovery, spec,
    revisão, nomeação) não conhecem a orquestração; quem os chama sabe. Fora de um
    contexto (serviços usados isoladamente), nada é registrado.
    """
    token = _CONTEXTO_DE_RUN.set(contexto)
    try:
        yield
    finally:
        _CONTEXTO_DE_RUN.reset(token)


def _registrar(contexto: ContextoDeRun | None, run: AgentRun) -> None:
    if contexto is None:
        return
    try:
        contexto.registrar(run)
    except Exception:  # noqa: BLE001 - registro nunca derruba a pergunta
        return


# Qualquer indisponibilidade do agente (timeout, JSON inválido, executor removido do
# catálogo, sandbox sem permissão) cai nesta tupla — cada serviço decide o próprio
# fallback ao capturá-la em volta de `perguntar_ao_agente`.
ERROS_DE_AGENTE = (LlmError, ValueError, KeyError, OSError, subprocess.SubprocessError)


def perguntar_ao_agente(
    catalog: ExecutorCatalog,
    assignment: AgentAssignment,
    *,
    system: str,
    pedido: str,
    kind: str,
    timeout: float,
    repositorio: AcessoAoRepositorio | None = None,
    modelo_resposta: type[BaseModel] | None = None,
) -> dict[str, object]:
    """Pergunta em JSON a um executor do catálogo — LLM ou CLI em pasta temporária.

    `kind` rotula a tarefa no wrapper JSON enviado ao CLI (ex.: "naming", "triagem",
    "revisao", "discovery", "especificacao") — cada serviço usa o próprio rótulo.
    Com `repositorio` e executor CLI, o agente lê um worktree de leitura do ref (ADR-0069);
    se alterar algo, a resposta é descartada (`EscritaNoRepositorio`).

    Com `modelo_resposta` (ADR-0072), o formato vai como JSON Schema gerado do modelo (prompt,
    envelope e saída estruturada nativa) e a resposta é validada: fora do schema, o agente
    recebe **uma** tentativa de correção com os campos que falharam; se falhar de novo,
    `RespostaInvalida` (cai no fallback do serviço, como qualquer erro de agente).
    """
    pedido_atual = pedido
    for tentativa in range(TENTATIVAS_DE_CORRECAO + 1):
        resposta = _perguntar_uma_vez(
            catalog,
            assignment,
            system=system,
            pedido=pedido_atual,
            kind=kind,
            timeout=timeout,
            repositorio=repositorio,
            modelo_resposta=modelo_resposta,
        )
        if modelo_resposta is None:
            return resposta
        try:
            return validar(modelo_resposta, resposta)
        except RespostaInvalida as erro:
            if tentativa == TENTATIVAS_DE_CORRECAO:
                raise
            pedido_atual = pedido_de_correcao(pedido, erro)
    raise AssertionError("inalcançável")  # pragma: no cover


def _perguntar_uma_vez(
    catalog: ExecutorCatalog,
    assignment: AgentAssignment,
    *,
    system: str,
    pedido: str,
    kind: str,
    timeout: float,
    repositorio: AcessoAoRepositorio | None,
    modelo_resposta: type[BaseModel] | None,
) -> dict[str, object]:
    esquema = esquema_de(modelo_resposta) if modelo_resposta is not None else None
    system_com_formato = (
        f"{system}\n{instrucao_de_formato(modelo_resposta)}" if modelo_resposta else system
    )
    leitura = tem_acesso_ao_repositorio(catalog, assignment, repositorio)
    contexto = _CONTEXTO_DE_RUN.get()
    run = AgentRun(
        orchestration_id=contexto.orchestration_id if contexto else "",
        card_id=contexto.card_id if contexto else None,
        kind=KIND_ASK,
        task_type=kind,
        executor=assignment.executor,
        effort=assignment.effort or "",
        effort_aplicado=_effort_da_pergunta(catalog, assignment, estruturada=esquema is not None),
        prompt_version=f"task-envelope-v{SCHEMA_VERSION}",
        prompt=f"{system_com_formato}\n\n{pedido}",
        envelope={
            **envelope_de_pergunta(
                kind, system=system, request=pedido, output_schema=esquema
            ).model_dump(),
            "acesso_repo": leitura,
        },
        request_id=contexto.request_id if contexto else "",
    )
    _registrar(contexto, run)
    inicio = time.perf_counter()
    try:
        resposta, uso = _perguntar(
            catalog,
            assignment,
            system=system,
            pedido=pedido,
            kind=kind,
            timeout=timeout,
            run_id=run.id,
            repositorio=repositorio if leitura else None,
            esquema=esquema,
            system_com_formato=system_com_formato,
        )
    except ERROS_DE_AGENTE as exc:
        if isinstance(exc, EscritaNoRepositorio) and contexto and contexto.ao_evento:
            try:
                contexto.ao_evento(
                    "PerguntaDescartadaPorEscrita",
                    {
                        "run_id": run.id,
                        "tipo": kind,
                        "executor": assignment.executor,
                        "motivo": str(exc)[:500],
                    },
                )
            except Exception:  # noqa: BLE001 - o evento nunca derruba a pergunta
                pass
        _registrar(
            contexto,
            run.model_copy(
                update={
                    "status": STATUS_FALHA,
                    "erro": f"{type(exc).__name__}: {exc}"[:2000],
                    "fim": now_iso(),
                    "duracao_ms": round((time.perf_counter() - inicio) * 1000, 1),
                }
            ),
        )
        raise
    _registrar(
        contexto,
        run.model_copy(
            update={
                "status": STATUS_SUCESSO,
                "saida_resumo": json.dumps(resposta, ensure_ascii=False, default=str)[:4000],
                # Consumo da pergunta (ADR-0070): entra no orçamento da orquestração.
                "tokens_entrada": uso.tokens_entrada,
                "tokens_saida": uso.tokens_saida,
                "tokens_cache": uso.tokens_cache_leitura + uso.tokens_cache_escrita,
                "custo_usd": uso.custo_usd,
                "modelo": uso.modelo,
                "uso_origem": uso.origem,
                "fim": now_iso(),
                "duracao_ms": round((time.perf_counter() - inicio) * 1000, 1),
            }
        ),
    )
    return resposta


def _perguntar(
    catalog: ExecutorCatalog,
    assignment: AgentAssignment,
    *,
    system: str,
    pedido: str,
    kind: str,
    timeout: float,
    run_id: str,
    repositorio: AcessoAoRepositorio | None = None,
    esquema: dict[str, Any] | None = None,
    system_com_formato: str | None = None,
) -> tuple[dict[str, object], UsoDoAgente]:
    profile = catalog.get(assignment.executor)
    if profile is None:
        raise KeyError(f"Executor '{assignment.executor}' não está no catálogo.")
    if profile.kind == "llm":
        client = catalog.llm_client(assignment.executor, effort_override=assignment.effort)
        resposta = completar(
            client, system=system_com_formato or system, user=pedido, esquema=esquema
        )
        uso = precificar(resposta.uso, modelo_padrao=profile.model)
        return parse_llm_json(resposta.texto), uso
    if profile.kind == "cli":
        command = catalog.cli_command(assignment.executor, effort_override=assignment.effort)
        if repositorio is not None:
            saida = _rodar_cli_lendo_repositorio(
                command,
                pedido,
                repositorio,
                system=system,
                kind=kind,
                timeout=timeout,
                run_id=run_id,
                esquema=esquema,
                system_legado=system_com_formato,
            )
        else:
            saida = _rodar_cli(
                command,
                pedido,
                system=system,
                kind=kind,
                timeout=timeout,
                run_id=run_id,
                esquema=esquema,
                system_legado=system_com_formato,
            )
        uso = UsoDoAgente()
        for linha in saida.splitlines():
            encontrado = extrair_uso(linha)
            if encontrado is not None:
                uso = encontrado
        uso = precificar(uso, modelo_padrao=profile.model)
        # NDJSON (`stream-json`) → texto final antes de procurar o JSON (ADR-0059).
        return parse_llm_json(extrair_resposta_final(saida)), uso
    raise ValueError(f"Executor '{assignment.executor}' não sabe produzir texto.")


def _effort_da_pergunta(
    catalog: ExecutorCatalog, assignment: AgentAssignment, *, estruturada: bool
) -> bool | None:
    """Esforço efetivo da pergunta (ADR-0073); na Anthropic, saída estruturada o desliga."""
    perfil = catalog.get(assignment.executor)
    effort = assignment.effort or (perfil.effort if perfil else "")
    if not effort or perfil is None:
        return None
    if perfil.kind == "llm" and perfil.provider == "anthropic" and estruturada:
        return False
    return perfil.suporte_de_effort().suporta


def tem_acesso_ao_repositorio(
    catalog: ExecutorCatalog | None,
    assignment: AgentAssignment | None,
    repositorio: AcessoAoRepositorio | None,
) -> bool:
    """A pergunta vai ler o repositório? Só executor CLI com pasta git; LLM via API não lê."""
    if catalog is None or assignment is None or repositorio is None:
        return False
    profile = catalog.get(assignment.executor)
    return profile is not None and profile.kind == "cli" and e_repositorio_git(repositorio.caminho)


def _rodar_cli_lendo_repositorio(
    command: list[str],
    pedido: str,
    repositorio: AcessoAoRepositorio,
    *,
    system: str,
    kind: str,
    timeout: float,
    run_id: str,
    esquema: dict[str, Any] | None = None,
    system_legado: str | None = None,
) -> str:
    """Roda o CLI num worktree de leitura do ref e confere que nada mudou (ADR-0069)."""
    with worktree_de_leitura(repositorio) as (pasta, sha):
        saida = _rodar_cli(
            comando_somente_leitura(command),
            pedido,
            system=system,
            kind=kind,
            timeout=timeout,
            run_id=run_id,
            cwd=str(pasta),
            esquema=esquema,
            system_legado=system_legado,
        )
        mudancas = alteracoes(pasta, sha)
    if mudancas:
        raise EscritaNoRepositorio(
            "o agente alterou o repositório durante uma pergunta somente leitura — resposta "
            f"descartada: {'; '.join(mudancas[:5])}"
        )
    return saida


def _rodar_cli(
    command: list[str],
    pedido: str,
    *,
    system: str,
    kind: str,
    timeout: float,
    run_id: str = "",
    cwd: str | None = None,
    esquema: dict[str, Any] | None = None,
    system_legado: str | None = None,
) -> str:
    """Roda o agente CLI só para obter texto — em pasta temporária, sem worktree.

    Envia o `TaskEnvelope` v1 (`kind="ask"`, ADR-0059) com o schema da resposta em
    `output_schema` (o renderizador acrescenta ao prompt, ADR-0072) e mantém `kind`/`content`
    no formato antigo — com o formato já no `system` — para wrappers que não leem o envelope.
    """
    envelope = envelope_de_pergunta(kind, system=system, request=pedido, output_schema=esquema)
    tarefa = json.dumps(
        {
            "kind": kind,
            "content": {"request": pedido, "system": system_legado or system},
            "envelope": envelope.model_dump(),
        },
        ensure_ascii=False,
    )
    with tempfile.TemporaryDirectory(prefix=f"aso-{kind}-") as tmp:
        proc = subprocess.run(
            command,
            cwd=cwd or tmp,
            input=tarefa,
            capture_output=True,
            text=True,
            timeout=timeout,
            # `ASO_RUN_ID` liga a execução do agente ao registro (ADR-0065).
            env={**os.environ, "ASO_RUN_ID": run_id} if run_id else None,
        )
    if proc.returncode != 0:
        raise ValueError(f"exit={proc.returncode}: {(proc.stderr or proc.stdout)[-200:]}")
    return proc.stdout
