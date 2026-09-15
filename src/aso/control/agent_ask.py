"""`perguntar_ao_agente` — dispatch comum aos serviços de agente (§2.6/§4.1 do plano4.md).

Extraído porque naming/triage/review/discovery repetiam, cada um, o mesmo bloco:
bifurcar `kind == "llm"` / `kind == "cli"`, rodar o CLI numa pasta temporária
descartável e envolver tudo na mesma tupla de exceções (`ERROS_DE_AGENTE`). Nenhum
destes serviços altera código (só produzem texto/JSON), então nada de
`git worktree add` — o CLI roda num diretório vazio e descartável, e só o stdout
interessa.

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

from aso.agents.contract import SCHEMA_VERSION, envelope_de_pergunta
from aso.control.models import AgentAssignment
from aso.execution.agent_stream import extrair_resposta_final
from aso.execution.catalog import ExecutorCatalog
from aso.execution.llm_client import LlmError
from aso.execution.llm_provider import parse_llm_json
from aso.observability.agent_runs import KIND_ASK, STATUS_FALHA, STATUS_SUCESSO, AgentRun
from aso.shared.ids import now_iso


@dataclass(frozen=True)
class ContextoDeRun:
    """Para onde e em nome de quem registrar as perguntas desta chamada (ADR-0065)."""

    registrar: Callable[[AgentRun], None]
    orchestration_id: str = ""
    card_id: str | None = None
    request_id: str = ""


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
) -> dict[str, object]:
    """Pergunta em JSON a um executor do catálogo — LLM ou CLI em pasta temporária.

    `kind` rotula a tarefa no wrapper JSON enviado ao CLI (ex.: "naming", "triagem",
    "revisao", "discovery", "especificacao") — cada serviço usa o próprio rótulo.
    """
    contexto = _CONTEXTO_DE_RUN.get()
    run = AgentRun(
        orchestration_id=contexto.orchestration_id if contexto else "",
        card_id=contexto.card_id if contexto else None,
        kind=KIND_ASK,
        task_type=kind,
        executor=assignment.executor,
        effort=assignment.effort or "",
        prompt_version=f"task-envelope-v{SCHEMA_VERSION}",
        prompt=f"{system}\n\n{pedido}",
        envelope=envelope_de_pergunta(kind, system=system, request=pedido).model_dump(),
        request_id=contexto.request_id if contexto else "",
    )
    _registrar(contexto, run)
    inicio = time.perf_counter()
    try:
        resposta = _perguntar(
            catalog,
            assignment,
            system=system,
            pedido=pedido,
            kind=kind,
            timeout=timeout,
            run_id=run.id,
        )
    except ERROS_DE_AGENTE as exc:
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
) -> dict[str, object]:
    profile = catalog.get(assignment.executor)
    if profile is None:
        raise KeyError(f"Executor '{assignment.executor}' não está no catálogo.")
    if profile.kind == "llm":
        client = catalog.llm_client(assignment.executor, effort_override=assignment.effort)
        return parse_llm_json(client.complete(system=system, user=pedido))
    if profile.kind == "cli":
        command = catalog.cli_command(assignment.executor, effort_override=assignment.effort)
        saida = _rodar_cli(
            command, pedido, system=system, kind=kind, timeout=timeout, run_id=run_id
        )
        # NDJSON (`stream-json`) → texto final antes de procurar o JSON (ADR-0059).
        return parse_llm_json(extrair_resposta_final(saida))
    raise ValueError(f"Executor '{assignment.executor}' não sabe produzir texto.")


def _rodar_cli(
    command: list[str],
    pedido: str,
    *,
    system: str,
    kind: str,
    timeout: float,
    run_id: str = "",
) -> str:
    """Roda o agente CLI só para obter texto — em pasta temporária, sem worktree.

    Envia o `TaskEnvelope` v1 (`kind="ask"`, ADR-0059) e mantém `kind`/`content` no
    formato antigo para wrappers que ainda não leem o envelope.
    """
    envelope = envelope_de_pergunta(kind, system=system, request=pedido)
    tarefa = json.dumps(
        {
            "kind": kind,
            "content": {"request": pedido, "system": system},
            "envelope": envelope.model_dump(),
        },
        ensure_ascii=False,
    )
    with tempfile.TemporaryDirectory(prefix=f"aso-{kind}-") as tmp:
        proc = subprocess.run(
            command,
            cwd=tmp,
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
