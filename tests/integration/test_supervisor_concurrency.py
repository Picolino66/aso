"""(a) AgentSupervisor (retry/nudge), execução concorrente e falha → card Failed."""

from __future__ import annotations

from typing import Any

from aso.agents.executor import LocalMockExecutionProvider
from aso.agents.models import AgentOutput, AgentSpec
from aso.application.orchestration_service import OrchestrationService
from aso.control.models import DecisionInput


class FlakyProvider:
    """Falha as primeiras `fail_times` chamadas, depois delega ao mock."""

    id = "flaky"

    def __init__(self, fail_times: int = 1) -> None:
        self.calls = 0
        self.fail_times = fail_times
        self._mock = LocalMockExecutionProvider()

    def execute(self, agent: AgentSpec, task: dict[str, Any]) -> AgentOutput:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("falha transitória")
        return self._mock.execute(agent, task)


class AlwaysFailProvider:
    id = "fail"

    def execute(self, agent: AgentSpec, task: dict[str, Any]) -> AgentOutput:
        raise RuntimeError("falha permanente")


def test_falha_transitoria_e_retentada_pelo_roteamento_e_sucede() -> None:
    """Retry único (ADR-0071): o supervisor não re-tenta; o roteamento de falha decide."""
    provider = FlakyProvider(fail_times=1)
    svc = OrchestrationService(provider=provider)
    orch = svc.create_orchestration("backend X")
    card = svc.get_cards(orch.id)[0]
    results = svc.run_card(orch.id, card.id)
    assert results and results[0].status.value == "applied"
    assert svc.get_cards(orch.id)[0].status.value == "Testing"
    assert provider.calls == 2
    eventos = svc.timeline(orch.id)
    types = {e.type for e in eventos}
    assert "AgentRetry" in types and "FailureRouted" in types
    assert "AgentRetrySucceeded" not in types  # nenhuma tentativa interna do supervisor


def test_terminal_failure_moves_card_to_failed() -> None:
    svc = OrchestrationService(provider=AlwaysFailProvider())
    orch = svc.create_orchestration("backend X")
    card = svc.get_cards(orch.id)[0]
    results = svc.run_card(orch.id, card.id)
    assert results == []
    assert svc.get_cards(orch.id)[0].status.value == "Failed"
    assert any(e.type == "AgentFailed" for e in svc.timeline(orch.id))


def test_concurrent_run_plan_waves() -> None:
    svc = OrchestrationService()  # mock estável (thread-safe)
    orch = svc.create_orchestration(
        "feature ampla",
        decision_input=DecisionInput(
            user_request="f", domains=["backend", "frontend"], parallelizable=True
        ),
    )
    result = svc.run_plan(orch.id, concurrent=True)
    assert result["concurrent"] is True and result["paralelismo"] == 2
    # ADR-0074: workers numa onda; o ReviewAgent aguarda a entrega (Done) deles.
    assert result["waves"] == 1
    assert result["count"] == len(svc.get_plan(orch.id).agents) - 1
    assert len(result["aguardando_dependencia"]) == 1
    executados = [c for c in svc.get_cards(orch.id) if c.id in result["executed"]]
    assert all(c.status.value == "Testing" for c in executados)


def test_uma_chamada_ao_provider_por_decisao_do_roteamento() -> None:
    """MEL-35: sem retry interno, execuções = 1 + decisões de nova tentativa do roteamento."""

    class _Contador(AlwaysFailProvider):
        chamadas = 0

        def execute(self, agent: AgentSpec, task: dict[str, Any]) -> AgentOutput:
            type(self).chamadas += 1
            return super().execute(agent, task)

    svc = OrchestrationService(provider=_Contador(), max_escalonamentos=3)
    orch = svc.create_orchestration("backend X")
    card = svc.get_cards(orch.id)[0]
    svc.run_card(orch.id, card.id)
    retentativas = [
        e
        for e in svc.timeline(orch.id)
        if e.type == "FailureRouted"
        and e.payload["acao"] in ("mesmo_agente", "aumentar_effort", "trocar_executor")
    ]
    assert _Contador.chamadas == 1 + len(retentativas)
    ultimo_erro = [f["mensagem"] for f in svc.get_cards(orch.id)[0].failures][-1]
    assert "falhou após" not in ultimo_erro and "falha permanente" in ultimo_erro


def test_agente_de_nomeacao_e_chamado_no_maximo_uma_vez_por_card() -> None:
    from aso.control.naming import BranchNaming, NamingService

    class _NomeadorContador(NamingService):
        chamadas = 0

        def suggest(self, *args: Any, **kwargs: Any) -> BranchNaming:
            type(self).chamadas += 1
            return BranchNaming(branch_stem="feat/frete", commit_subject="feat: frete")

    svc = OrchestrationService(provider=FlakyProvider(fail_times=1), naming=_NomeadorContador())
    orch = svc.create_orchestration("backend X")
    card = svc.get_cards(orch.id)[0]
    svc.run_card(orch.id, card.id)  # falha + nova tentativa no mesmo run_card
    svc.move_card(orch.id, card.id, "Ready")
    svc.run_card(orch.id, card.id)  # outra execução do mesmo card
    assert _NomeadorContador.chamadas == 1
    atual = svc.get_cards(orch.id)[0]
    assert (atual.branch_stem, atual.commit_subject) == ("feat/frete", "feat: frete")
