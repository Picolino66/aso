"""Contrato versionado `TaskEnvelope` entre o runtime e agentes CLI (ADR-0059).

Existem dois tipos de chamada a um agente CLI:

- **execute** — implementar um card (ou documentação) num worktree isolado;
- **ask** — responder uma pergunta em JSON (naming, triagem, discovery, especificação,
  revisão), numa pasta temporária, sem tocar em código.

Antes deste contrato o wrapper só reconhecia `naming` como pergunta: para as demais, o
`system` (que carrega o schema JSON esperado) era descartado e o agente recebia a
instrução de implementar — e o serviço caía silenciosamente na heurística. O envelope
torna o tipo de chamada explícito e versionado; o lado agente (`render_prompt.py`) recusa
versão desconhecida em vez de adivinhar.

Compatibilidade: o dicionário da tarefa continua com o formato antigo (`content`,
`kind`) e ganha a chave `envelope`; um wrapper antigo ainda funciona, o novo lê o
envelope.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from aso.agents.context_builder import ContextoDaTarefa

SCHEMA_VERSION = "1"

KIND_EXECUTE: Literal["execute"] = "execute"
KIND_ASK: Literal["ask"] = "ask"

TASK_TYPES_EXECUTE = frozenset({"card", "docs"})
# Rótulos de pergunta conhecidos hoje. Não é lista fechada: cada serviço rotula a própria
# pergunta (`revisao_documental`, por exemplo) e o tipo de chamada é decidido por `kind`.
TASK_TYPES_ASK = frozenset(
    {"naming", "triagem", "discovery", "especificacao", "revisao", "revisao_documental"}
)


class ContratoInvalido(ValueError):
    """Envelope fora do contrato (versão desconhecida, tipo incoerente)."""


class CardBrief(BaseModel):
    """O que o agente precisa saber do card que está implementando."""

    titulo: str = ""
    tipo: str = "Task"
    descricao: str = ""
    criterios: list[str] = Field(default_factory=list)
    correcoes: list[str] = Field(default_factory=list)
    contexto_adicional: list[str] = Field(default_factory=list)


class TaskEnvelope(BaseModel):
    """Envelope v1. `system`/`request` valem para os dois tipos; `card` só para execute."""

    schema_version: str = SCHEMA_VERSION
    kind: Literal["execute", "ask"]
    task_type: str
    system: str = ""
    request: str = ""
    card: CardBrief | None = None
    nudge: str = ""
    effort: str = ""
    validation_command: str | None = None
    commit_subject: str = ""
    output_schema: dict[str, Any] | None = None
    phase: str = ""
    target_path: str = ""
    # Contexto priorizado da tarefa (ADR-0063) — campo aditivo: `schema_version` segue "1"
    # e renderizadores antigos simplesmente o ignoram.
    contexto: ContextoDaTarefa | None = None

    @field_validator("schema_version")
    @classmethod
    def _versao_conhecida(cls, valor: str) -> str:
        if valor != SCHEMA_VERSION:
            raise ContratoInvalido(
                f"schema_version '{valor}' desconhecida (runtime suporta '{SCHEMA_VERSION}')."
            )
        return valor

    def model_post_init(self, __context: Any) -> None:
        if not self.task_type.strip():
            raise ContratoInvalido("task_type vazio.")
        if self.kind == KIND_EXECUTE and self.task_type not in TASK_TYPES_EXECUTE:
            raise ContratoInvalido(
                f"task_type '{self.task_type}' não é de execução "
                f"(esperado um de: {', '.join(sorted(TASK_TYPES_EXECUTE))})."
            )
        if self.kind == KIND_ASK and not self.system.strip():
            # Pergunta sem system = agente sem o schema da resposta: o fallback seria
            # certo e silencioso. Melhor recusar na origem.
            raise ContratoInvalido(f"Pergunta '{self.task_type}' sem system (schema ausente).")


def ler_envelope(dados: dict[str, Any]) -> TaskEnvelope:
    """Valida um envelope recebido; erros de contrato viram `ContratoInvalido`."""
    versao = str(dados.get("schema_version", SCHEMA_VERSION))
    if versao != SCHEMA_VERSION:
        raise ContratoInvalido(
            f"schema_version '{versao}' desconhecida (runtime suporta '{SCHEMA_VERSION}')."
        )
    try:
        return TaskEnvelope.model_validate(dados)
    except ContratoInvalido:
        raise
    except ValueError as exc:  # ValidationError do Pydantic
        raise ContratoInvalido(f"Envelope inválido: {exc}") from exc


def envelope_de_pergunta(
    task_type: str,
    *,
    system: str,
    request: str,
    output_schema: dict[str, Any] | None = None,
) -> TaskEnvelope:
    return TaskEnvelope(
        kind=KIND_ASK,
        task_type=task_type,
        system=system,
        request=request,
        output_schema=output_schema,
    )
