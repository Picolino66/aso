"""AgentLogBus — saída ao vivo dos agentes, por orquestração (ADR-0015).

Antes, a saída do agente CLI só existia depois que o processo morria: `subprocess.run`
com `capture_output` lê os pipes no fim, e o runtime guardava 2 000 caracteres num
`artifacts` que nunca era persistido. O operador ficava minutos olhando uma tela parada
sem saber se o agente estava trabalhando, travado esperando permissão, ou morto.

Este módulo é o canal por onde a saída passa **enquanto** acontece. Duas escolhas
deliberadas:

1. **Fora do `EventLog`.** O repositório reescreve todas as tabelas filhas em cada `save`
   (delete + reinsert), então centenas de linhas de log no event log custariam O(n) de
   escrita por mutação. Log de execução é telemetria, não estado governado.
2. **Ring em memória, não asyncio.** O produtor é a thread do agente (a execução roda em
   `ThreadPoolExecutor`) e o consumidor é o handler HTTP. Um `threading.Lock` sobre um
   `deque` resolve isso sem a ponte thread→event-loop que o `EventBroker` exigiria — e
   sem o descarte silencioso dele em fila cheia, que é aceitável para "algo mudou" e
   inaceitável para conteúdo. A leitura é por cursor (`after`), o que dá replay quando o
   operador recarrega a página no meio da execução.

O preço é explícito: o log morre ao reiniciar a API. É telemetria de acompanhamento, não
registro de auditoria — o que precisa sobreviver (falhas, motivo, diff) continua no
`EventLog` e no `block_reason` do card.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any

from aso.shared.agent_output import KIND_BRUTO, KIND_MARCO, STREAM_ASO
from aso.shared.ids import now_iso

# Linhas retidas por orquestração. Um agente verboso em `stream-json` produz algumas
# centenas de linhas por card; 2 000 cobre a execução corrente e um pouco de histórico
# sem deixar a memória crescer sem limite.
MAX_LINHAS = 2000


@dataclass(frozen=True)
class LogLine:
    """Uma linha do log, já pronta para a UI renderizar."""

    seq: int
    at: str
    stream: str
    kind: str
    text: str
    detail: str = ""
    card_id: str | None = None
    agent: str = ""
    executor: str = ""

    def public(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "at": self.at,
            "stream": self.stream,
            "kind": self.kind,
            "text": self.text,
            "detail": self.detail,
            "card_id": self.card_id,
            "agent": self.agent,
            "executor": self.executor,
        }


@dataclass
class Session:
    """Uma execução de agente em andamento (ou encerrada) sobre um card."""

    id: str
    card_id: str | None
    agent: str
    executor: str
    branch: str
    started_at: str
    started_mono: float
    running: bool = True
    ok: bool | None = None
    detail: str = ""
    lines: int = 0
    ended_at: str | None = None
    duration_ms: float | None = None

    def public(self) -> dict[str, Any]:
        elapsed = (
            self.duration_ms
            if self.duration_ms is not None
            else round((time.monotonic() - self.started_mono) * 1000, 1)
        )
        return {
            "id": self.id,
            "card_id": self.card_id,
            "agent": self.agent,
            "executor": self.executor,
            "branch": self.branch,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "running": self.running,
            "ok": self.ok,
            "detail": self.detail,
            "lines": self.lines,
            "elapsed_ms": elapsed,
        }


@dataclass
class _Canal:
    """Estado de uma orquestração: ring de linhas + sessões conhecidas."""

    linhas: deque[LogLine]
    sessoes: dict[str, Session] = field(default_factory=dict)
    ultimo_seq: int = 0


class AgentLogSession:
    """Handle que o provider usa para escrever a saída de UMA execução.

    Context manager: fechar registra o desfecho e a duração, mesmo em exceção — assim
    a UI nunca fica com um `running: true` órfão porque o agente explodiu.
    """

    def __init__(self, bus: AgentLogBus, orchestration_id: str, session: Session) -> None:
        self._bus = bus
        self._orchestration_id = orchestration_id
        self._session = session

    @property
    def id(self) -> str:
        return self._session.id

    def write(self, stream: str, text: str, *, kind: str = KIND_BRUTO, detail: str = "") -> None:
        """Registra uma linha. Chamada da thread do agente, a cada linha lida do pipe."""
        self._bus._append(self._orchestration_id, self._session, stream, text, kind, detail)

    def marco(self, text: str, *, detail: str = "") -> None:
        """Registra um marco do runtime (não é fala do agente)."""
        self.write(STREAM_ASO, text, kind=KIND_MARCO, detail=detail)

    def close(self, *, ok: bool, detail: str = "") -> None:
        self._bus._close(self._orchestration_id, self._session, ok=ok, detail=detail)

    def __enter__(self) -> AgentLogSession:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._session.running:
            self.close(ok=exc_type is None, detail=str(exc) if exc else "")


class AgentLogBus:
    """Ring buffer de saída de agente, por orquestração. Thread-safe."""

    def __init__(self, *, max_linhas: int = MAX_LINHAS) -> None:
        self._max = max_linhas
        self._canais: dict[str, _Canal] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ escrita
    def open(
        self,
        orchestration_id: str,
        *,
        card_id: str | None,
        agent: str,
        executor: str,
        branch: str = "",
    ) -> AgentLogSession:
        """Abre uma sessão de execução e anuncia o início no log."""
        with self._lock:
            canal = self._canais.setdefault(
                orchestration_id, _Canal(linhas=deque(maxlen=self._max))
            )
            sessao = Session(
                id=f"{card_id or 'card'}-{canal.ultimo_seq + 1}",
                card_id=card_id,
                agent=agent,
                executor=executor,
                branch=branch,
                started_at=now_iso(),
                started_mono=time.monotonic(),
            )
            canal.sessoes[sessao.id] = sessao
        handle = AgentLogSession(self, orchestration_id, sessao)
        handle.marco(f"{agent} iniciou em {executor}", detail=branch)
        return handle

    def _append(
        self,
        orchestration_id: str,
        sessao: Session,
        stream: str,
        text: str,
        kind: str,
        detail: str,
    ) -> None:
        limpo = text.rstrip("\n")
        if not limpo.strip():
            return  # linha vazia do pipe não vira ruído na tela
        with self._lock:
            canal = self._canais.setdefault(
                orchestration_id, _Canal(linhas=deque(maxlen=self._max))
            )
            canal.ultimo_seq += 1
            sessao.lines += 1
            canal.linhas.append(
                LogLine(
                    seq=canal.ultimo_seq,
                    at=now_iso(),
                    stream=stream,
                    kind=kind,
                    text=limpo,
                    detail=detail,
                    card_id=sessao.card_id,
                    agent=sessao.agent,
                    executor=sessao.executor,
                )
            )

    def _close(self, orchestration_id: str, sessao: Session, *, ok: bool, detail: str) -> None:
        with self._lock:
            if not sessao.running:
                return
            sessao.running = False
            sessao.ok = ok
            sessao.detail = detail
            sessao.ended_at = now_iso()
            sessao.duration_ms = round((time.monotonic() - sessao.started_mono) * 1000, 1)
        segundos = (sessao.duration_ms or 0) / 1000
        rotulo = "concluiu" if ok else "falhou"
        self._append(
            orchestration_id,
            sessao,
            STREAM_ASO,
            f"{sessao.agent} {rotulo} em {segundos:.1f}s",
            KIND_MARCO,
            detail,
        )

    # ------------------------------------------------------------------ leitura
    def lines(self, orchestration_id: str, *, after: int = 0, limit: int = 500) -> list[LogLine]:
        """Linhas com `seq > after`, em ordem. Cursor: a UI pede só o que ainda não viu."""
        with self._lock:
            canal = self._canais.get(orchestration_id)
            if canal is None:
                return []
            return [linha for linha in canal.linhas if linha.seq > after][-limit:]

    def state(self, orchestration_id: str) -> dict[str, Any]:
        """Retrato para a UI decidir se continua consultando."""
        with self._lock:
            canal = self._canais.get(orchestration_id)
            if canal is None:
                return {"running": False, "sessions": [], "last_seq": 0, "retained": 0}
            sessoes = sorted(canal.sessoes.values(), key=lambda s: s.started_at)
            return {
                "running": any(s.running for s in sessoes),
                "sessions": [s.public() for s in sessoes[-10:]],
                "last_seq": canal.ultimo_seq,
                "retained": len(canal.linhas),
            }

    def forget(self, orchestration_id: str) -> None:
        """Descarta o log de uma orquestração (usado ao excluir/arquivar)."""
        with self._lock:
            self._canais.pop(orchestration_id, None)
