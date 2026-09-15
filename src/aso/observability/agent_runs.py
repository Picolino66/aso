"""Registro persistido de execuções de agente — `AgentRun` (ADR-0065).

Antes não dava para reconstituir uma execução: prompt, tarefa, saída e custo ficavam
espalhados em eventos, logs em memória (`AgentLogBus`) e `artifacts` descartados. Cada
execução de card e cada pergunta a agente (triagem, discovery, spec, revisão, nomeação) vira
um `AgentRun` append-only, gravado no início (`running`) e completado no fim.

Nada que pareça segredo é persistido: `mascarar_segredos` passa por prompt, envelope, stdout,
resumo e erro antes de gravar (regra inviolável 9).
"""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from pydantic import BaseModel, Field

from aso.shared.ids import gen_id, now_iso

STATUS_RUNNING = "running"
STATUS_SUCESSO = "sucesso"
STATUS_FALHA = "falha"
KIND_EXECUTE = "execute"
KIND_ASK = "ask"

MASCARA = "[SEGREDO REMOVIDO]"
_PADROES = (
    re.compile(r"sk-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{12,}"),
    re.compile(r"(?i)(api[_-]?key|token|secret|password|senha)\s*[=:]\s*[^\s\"',]{8,}"),
)
_NOME_SENSIVEL = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|SENHA", re.IGNORECASE)


def _valores_sensiveis_do_ambiente() -> list[str]:
    return sorted(
        {v for k, v in os.environ.items() if _NOME_SENSIVEL.search(k) and v and len(v) >= 8},
        key=len,
        reverse=True,
    )


def mascarar_segredos(texto: str) -> str:
    """Troca por `[SEGREDO REMOVIDO]` padrões de chave conhecidos e valores de variáveis de
    ambiente com nome sensível (`*KEY*`, `*TOKEN*`, `*SECRET*`, `*PASSWORD*`)."""
    if not texto:
        return texto
    for valor in _valores_sensiveis_do_ambiente():
        texto = texto.replace(valor, MASCARA)
    for padrao in _PADROES:
        texto = padrao.sub(MASCARA, texto)
    return texto


def mascarar_json(valor: dict[str, Any]) -> dict[str, Any]:
    if not valor:
        return valor
    resultado = json.loads(mascarar_segredos(json.dumps(valor, ensure_ascii=False, default=str)))
    return resultado if isinstance(resultado, dict) else {}


class AgentRun(BaseModel):
    id: str = Field(default_factory=lambda: gen_id("run"))
    orchestration_id: str = ""
    card_id: str | None = None
    pr_id: str | None = None
    attempt: int = 0
    kind: str = KIND_EXECUTE
    task_type: str = ""
    papel: str = ""
    executor: str = ""
    modelo: str = ""
    effort: str = ""
    prompt_version: str = ""
    prompt: str = ""
    envelope: dict[str, Any] = Field(default_factory=dict)
    status: str = STATUS_RUNNING
    saida_resumo: str = ""
    stdout_cauda: str = ""
    exit_code: int | None = None
    diff_lines: int | None = None
    branch: str | None = None
    inicio: str = Field(default_factory=now_iso)
    fim: str | None = None
    duracao_ms: float | None = None
    tokens_entrada: int = 0
    tokens_saida: int = 0
    tokens_cache: int = 0
    custo_usd: float = 0.0
    uso_origem: str = ""
    erro: str = ""
    decisao: dict[str, Any] = Field(default_factory=dict)
    request_id: str = ""

    def mascarado(self) -> AgentRun:
        """Cópia pronta para persistir — sem nada que pareça segredo."""
        return self.model_copy(
            update={
                "prompt": mascarar_segredos(self.prompt),
                "envelope": mascarar_json(self.envelope),
                "saida_resumo": mascarar_segredos(self.saida_resumo),
                "stdout_cauda": mascarar_segredos(self.stdout_cauda),
                "erro": mascarar_segredos(self.erro),
                "decisao": mascarar_json(self.decisao),
            }
        )


def retencao_em_dias() -> int | None:
    """`ASO_RUN_RETENCAO_DIAS`: após N dias, prompt/stdout/envelope são limpos (metadados
    ficam). Sem a variável (ou inválida), nada é limpo."""
    try:
        dias = int(os.environ.get("ASO_RUN_RETENCAO_DIAS", ""))
    except ValueError:
        return None
    return dias if dias > 0 else None


def limite_de_retencao(dias: int) -> str:
    return (datetime.now(UTC) - timedelta(days=dias)).isoformat()


class AgentRunRepository(Protocol):
    def salvar(self, run: AgentRun) -> None: ...

    def obter(self, run_id: str) -> AgentRun | None: ...

    def listar(self, orchestration_id: str, *, card_id: str | None = None) -> list[AgentRun]: ...

    def expurgar_textos(self, antes_de: str) -> int: ...


class InMemoryAgentRunRepository:
    """Adapter em memória (testes e modo sem banco)."""

    def __init__(self) -> None:
        self._runs: dict[str, AgentRun] = {}

    def salvar(self, run: AgentRun) -> None:
        self._runs[run.id] = run.mascarado()

    def obter(self, run_id: str) -> AgentRun | None:
        return self._runs.get(run_id)

    def listar(self, orchestration_id: str, *, card_id: str | None = None) -> list[AgentRun]:
        return sorted(
            (
                r
                for r in self._runs.values()
                if r.orchestration_id == orchestration_id
                and (card_id is None or r.card_id == card_id)
            ),
            key=lambda r: r.inicio,
        )

    def expurgar_textos(self, antes_de: str) -> int:
        alterados = 0
        for run_id, run in list(self._runs.items()):
            if run.inicio < antes_de and (run.prompt or run.stdout_cauda or run.envelope):
                self._runs[run_id] = run.model_copy(
                    update={"prompt": "", "stdout_cauda": "", "envelope": {}}
                )
                alterados += 1
        return alterados
