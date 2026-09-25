"""`RecoveryService` — retomada de cards: retry e roteamento manual de falha (ADR-0066).

MEL-32, passo 7: separado do `WorkflowService` (limite de ~800 linhas por módulo); reusa a
execução governada (`run_card`, claim e freios) e a política de falha (ADR-0019).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from aso.application.bundles import BundleStore, OrchestrationBundle
from aso.application.execution import ExecutionService
from aso.control.failure import (
    ACAO_AUMENTAR_EFFORT,
    ACAO_TROCAR_EXECUTOR,
    ETAPA_GATE,
    FailureRecord,
    decidir,
    diagnosticar,
    registrar,
)
from aso.control.models import AgentAssignment
from aso.control.validation import checks_efetivos
from aso.execution.catalog import ExecutorCatalog
from aso.governance.contextbus import BusResult
from aso.shared.types import ColumnKey, GateStatus


class RecoveryService:
    """Retry de cards em falha/pendentes e roteamento manual (`route_card`)."""

    def __init__(
        self,
        store: BundleStore,
        *,
        execution: ExecutionService,
        max_escalonamentos: int,
        catalogo: Callable[[], ExecutorCatalog | None],
        effective_executor: Callable[..., str | None],
    ) -> None:
        self._bundle_store = store
        self._execution = execution
        self._max_escalonamentos = max_escalonamentos
        self._catalogo = catalogo
        self._executor_de = effective_executor

    @property
    def _catalog(self) -> ExecutorCatalog | None:
        return self._catalogo()

    def _bundle(self, orchestration_id: str) -> OrchestrationBundle:
        return self._bundle_store.get(orchestration_id)

    def _effective_executor(self, *args: Any, **kwargs: Any) -> str | None:
        return self._executor_de(*args, **kwargs)

    def run_card(self, *args: Any, **kwargs: Any) -> list[BusResult]:
        return self._execution.run_card(*args, **kwargs)

    def retry(self, orchestration_id: str) -> list[str]:
        """Reexecuta cards pendentes/falhos (req §28.1), respeitando o ponto certo (fluxo §13).

        Gate reprovado roteia só os cards da fase que ainda não chegaram a `Done` —
        não reinicia a fase inteira (Princípio central do fluxo.md: "retorna
        exatamente ao ponto responsável pelo erro"). Fora desse caso, cai na varredura
        genérica de cards prontos/falhos/bloqueados de sempre.
        """
        b = self._bundle(orchestration_id)
        targets = self._gate_retry_targets(b)
        if targets is None:
            retryable = {ColumnKey.READY, ColumnKey.FAILED, ColumnKey.BLOCKED}
            targets = [c.id for c in b.board_service.cards_of(b.board.id) if c.status in retryable]
        for card_id in targets:
            try:
                self.run_card(orchestration_id, card_id)
            except (KeyError, ValueError):
                # Card inválido ou com dependência ainda pendente: não derruba o resto
                # do retry — o `run_card` já registrou o motivo no próprio card.
                continue
        return targets

    def _gate_retry_targets(self, b: OrchestrationBundle) -> list[str] | None:
        """Cards da fase do último gate reprovado (se houver e ainda for o mais
        recente daquela fase) que ainda não chegaram a `Done`. `None` = não se aplica
        (cai na varredura genérica de `retry`).

        Desde a ADR-0022, a reprovação também passa pelo roteamento de falha (fluxo §13,
        ADR-0019): a verificação nomeada que reprovou primeiro dá `categoria` ao
        diagnóstico — fato, não heurística por palavra-chave (`diagnosticar` prefere
        a categoria quando ela existe). A escalada (effort maior/outro executor) é
        da ETAPA, não do card isolado: grava em `agent_assignments[fase]`, então a
        próxima chamada de `run_card` de qualquer card dessa fase já nasce com o
        degrau novo — sem isto, cada card escalaria isoladamente e do zero.
        """
        ultimo = b.gate_results[-1] if b.gate_results else None
        if ultimo is None or ultimo.status != GateStatus.FAILED:
            return None
        pendentes = [
            c
            for c in b.board_service.cards_of(b.board.id)
            if c.phase == ultimo.phase and c.status != ColumnKey.DONE
        ]
        if not pendentes:
            return None
        falhados = [
            c.failure_reason or c.name for c in ultimo.criteria if c.status == GateStatus.FAILED
        ]
        detalhe = " · ".join(ultimo.required_actions or ultimo.blocking_issues or falhados)
        categorias = {c.nome: c.categoria for c in checks_efetivos(b.orchestration)}
        nomes_falhados = ultimo.blocking_issues or [
            c.name for c in ultimo.criteria if c.status == GateStatus.FAILED
        ]
        primeiro_check = next((nome for nome in nomes_falhados if nome in categorias), "")
        categoria = categorias.get(primeiro_check, "")
        diagnostico = diagnosticar(FailureRecord(check=primeiro_check, categoria=categoria))
        tentativa_fase = sum(
            1 for g in b.gate_results if g.phase == ultimo.phase and g.status == GateStatus.FAILED
        )
        assignment_atual = b.orchestration.agent_assignments.get(ultimo.phase.value)
        executor_atual = (
            (assignment_atual.executor if assignment_atual else None)
            or self._effective_executor(b, None, phase=ultimo.phase)
            or ""
        )
        effort_atual = (assignment_atual.effort if assignment_atual else None) or ""
        decisao = decidir(
            diagnostico,
            tentativa_fase,
            executor_atual=executor_atual,
            effort_atual=effort_atual,
            catalogo=self._catalog,
            max_escalonamentos=self._max_escalonamentos,
        )
        if decisao.acao == ACAO_AUMENTAR_EFFORT and decisao.effort:
            b.orchestration.agent_assignments[ultimo.phase.value] = AgentAssignment(
                executor=executor_atual, effort=decisao.effort
            )
        elif decisao.acao == ACAO_TROCAR_EXECUTOR and decisao.executor:
            b.orchestration.agent_assignments[ultimo.phase.value] = AgentAssignment(
                executor=decisao.executor, effort=effort_atual or None
            )
        b.event_log.append(
            "FailureRouted",
            {
                "orchestration_id": b.orchestration.id,
                "etapa": ETAPA_GATE,
                "fase": ultimo.phase.value,
                "diagnostico": diagnostico,
                "acao": decisao.acao,
                "check": primeiro_check,
                "categoria": categoria,
            },
        )
        nudge = decisao.nudge or (f"O gate reprovou: {detalhe}"[:500] if detalhe else "")
        for card in pendentes:
            record = FailureRecord(
                etapa=ETAPA_GATE,
                tentativa=len(card.failures) + 1,
                comando="quality-gate",
                mensagem=f"Quality gate de {ultimo.phase.value} reprovado",
                saida=detalhe,
                check=primeiro_check,
                categoria=categoria,
            )
            card.failures = registrar(card.failures, record)
            if nudge:
                card.correction_actions = [nudge]
        return [c.id for c in pendentes]

    def route_card(self, orchestration_id: str, card_id: str) -> list[BusResult]:
        """Aciona o roteamento de falha manualmente (ADR-0019) — para quando o
        automático parou por limite (`bloquear`/`escalar_humano`) e o operador já
        corrigiu a causa (ex.: ajustou o perfil do executor). Sem isto, "escalar para
        humano" seria um beco sem saída: `run_card` reaproveita o mesmo laço."""
        return self.run_card(orchestration_id, card_id)
