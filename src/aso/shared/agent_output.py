"""Porta de saída ao vivo dos agentes: vocabulário + contratos (ADR-0015).

Fica em `shared` por causa da regra de dependência (`module_map`): `execution` — quem
**produz** a saída, no `CliAgentExecutionProvider` — só pode depender de `shared` e
`agents`, e o ring buffer que a **consome** vive em `observability`. Ports & Adapters:
a porta aqui, o adapter em `observability.agent_log`, a fiação em `control`.

Os Protocols são estruturais: `AgentLogBus`/`AgentLogSession` os satisfazem sem que
`execution` precise importar `observability`, e um teste pode passar um sink de mentira
sem herdar nada.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

# Origem da linha.
STREAM_STDOUT = "stdout"
STREAM_STDERR = "stderr"
STREAM_ASO = "aso"  # marcos do próprio runtime (início, fim, timeout)

# Natureza da linha, já interpretada (ver `aso.execution.agent_stream`).
KIND_TEXTO = "texto"  # o agente falando
KIND_FERRAMENTA = "ferramenta"  # o agente usando uma ferramenta (editar, rodar, ler)
KIND_RESULTADO = "resultado"  # desfecho reportado pelo próprio agente
KIND_BRUTO = "bruto"  # não interpretado: mostra como veio
KIND_MARCO = "marco"  # do runtime, não do agente


@runtime_checkable
class OutputSink(Protocol):
    """Destino das linhas de UMA execução de agente."""

    def write(
        self, stream: str, text: str, *, kind: str = KIND_BRUTO, detail: str = ""
    ) -> None: ...

    def marco(self, text: str, *, detail: str = "") -> None: ...

    def close(self, *, ok: bool, detail: str = "") -> None: ...


@runtime_checkable
class OutputBus(Protocol):
    """Abre um sink por execução. O provider recebe isto, não o ring concreto."""

    def open(
        self,
        orchestration_id: str,
        *,
        card_id: str | None,
        agent: str,
        executor: str,
        branch: str = "",
    ) -> OutputSink: ...
