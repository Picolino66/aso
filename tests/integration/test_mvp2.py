"""MVP-2: execução multiagente (run_plan) + fluxo requires_approval → aplicação."""

from __future__ import annotations

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.models import DecisionInput
from aso.control.orchestration_service import OrchestrationService
from aso.governance.models import ContextPatch
from aso.shared.types import PatchType, Phase


def test_run_plan_multiagent_respects_dependencies() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration(
        "feature ampla",
        decision_input=DecisionInput(
            user_request="feature", domains=["backend", "frontend"], parallelizable=True
        ),
    )
    # estratégia paralela => workers + ReviewAgent (que depende dos workers)
    plan = svc.get_plan(orch.id)
    assert plan.strategy.value == "parallel_agents"
    order = OrchestrationService._agent_order(plan)
    assert order[-1] == "ReviewAgent"  # review por último (depende dos demais)

    result = svc.run_plan(orch.id)
    assert result["count"] == len(plan.agents)
    # todos os cards executados
    assert all(c.status.value == "Testing" for c in svc.get_cards(orch.id))


def test_requires_approval_flow_pending_then_applied() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("x")
    before = svc.get_context(orch.id)["version"]

    # Patch que exige aprovação => fica pendente e NÃO é aplicado.
    patch = ContextPatch(
        orchestration_id=orch.id,
        agent="ArchitectureDesignAgent",
        phase=Phase.F2,
        patch_type=PatchType.UPDATE,
        target_path="architecture.pattern",
        content="modular-monolith",
        requires_approval=True,
    )
    result = svc.submit_patch(orch.id, patch)
    assert result.status.value == "pending"
    assert svc.get_context(orch.id)["version"] == before  # não aplicado

    # Uma aprovação vinculada ao patch foi criada.
    approval = next(a for a in svc.list_approvals(orch.id) if a.payload.get("patch_id") == patch.id)

    # Ao aprovar, o patch é aplicado (versão do contexto incrementa).
    decided = svc.decide_approval(approval.id, approved=True, approved_by="alice")
    assert decided.status == "approved"
    assert svc.get_context(orch.id)["version"] == before + 1
    assert svc.get_context(orch.id)["payload"]["architecture"]["pattern"] == "modular-monolith"


def test_run_plan_endpoint() -> None:
    client = TestClient(create_app(OrchestrationService()))
    oid = client.post("/v1/orchestrations", json={"user_request": "backend X"}).json()["id"]
    out = client.post(f"/v1/orchestrations/{oid}/run-plan").json()
    assert out["count"] >= 1
    assert out["executed"]


def test_reject_keeps_patch_pending() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("x")
    patch = ContextPatch(
        orchestration_id=orch.id,
        agent="ArchitectureDesignAgent",
        phase=Phase.F2,
        patch_type=PatchType.UPDATE,
        target_path="architecture.pattern",
        content="microservices",
        requires_approval=True,
    )
    svc.submit_patch(orch.id, patch)
    approval = next(a for a in svc.list_approvals(orch.id) if a.payload.get("patch_id") == patch.id)
    svc.decide_approval(approval.id, approved=False)
    # Rejeitado: contexto não recebe o valor.
    assert (
        svc.get_context(orch.id)["payload"].get("architecture", {}).get("pattern")
        != "microservices"
    )
