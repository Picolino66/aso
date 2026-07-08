"""(b) card ↔ aprovação no Kanban e (c) ConflictDetector avançado + resolução."""

from __future__ import annotations

from aso.control.orchestration_service import OrchestrationService
from aso.governance.models import ContextPatch
from aso.shared.types import ConflictType, PatchType, Phase


def _patch(oid: str, **kw: object) -> ContextPatch:
    base = dict(
        orchestration_id=oid,
        agent="ArchitectureDesignAgent",
        phase=Phase.F2,
        patch_type=PatchType.UPDATE,
        target_path="architecture.pattern",
        content="modular-monolith",
    )
    base.update(kw)
    return ContextPatch(**base)  # type: ignore[arg-type]


def test_card_waits_human_then_released_on_approval() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("x")
    card = svc.get_cards(orch.id)[0]
    # marca o card para exigir aprovação: usamos o executor mock => patch normal aplica.
    # Aqui submetemos um patch requires_approval ligado ao card via run flow simulado:
    svc._submit_with_approval(  # noqa: SLF001 — exercita o vínculo card↔aprovação
        svc._bundle(orch.id),  # noqa: SLF001
        _patch(orch.id, requires_approval=True),
        card_id=card.id,
    )
    svc._bundle(orch.id).board_service.apply_event(card.id, "AgentNeedsInput")  # noqa: SLF001
    assert svc.get_cards(orch.id)[0].status.value == "WaitingHuman"

    approval = next(a for a in svc.list_approvals(orch.id) if a.card_id == card.id)
    svc.decide_approval(approval.id, approved=True)
    assert svc.get_cards(orch.id)[0].status.value == "Testing"  # liberado


def test_reject_blocks_card() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("x")
    card = svc.get_cards(orch.id)[0]
    svc._submit_with_approval(  # noqa: SLF001
        svc._bundle(orch.id),  # noqa: SLF001
        _patch(orch.id, requires_approval=True),
        card_id=card.id,
    )
    approval = next(a for a in svc.list_approvals(orch.id) if a.card_id == card.id)
    svc.decide_approval(approval.id, approved=False)
    assert svc.get_cards(orch.id)[0].status.value == "Blocked"


def test_adr_locked_path_contradiction_and_override() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("x")
    b = svc._bundle(orch.id)  # noqa: SLF001
    # ADR aceita que trava architecture.pattern
    adr = b.adr_registry.create(
        title="Padrão travado",
        decision="Modular Monolith",
        phase=Phase.F2,
        locked_paths=["architecture.pattern"],
    )
    # patch sem referenciar a ADR => ARCHITECTURE_CONFLICT
    denied = b.bus.submit(_patch(orch.id, content="microservices"))
    assert denied.status.value == "rejected"
    assert denied.conflict is not None
    assert denied.conflict.type == ConflictType.ARCHITECTURE
    # referenciando a ADR em linked_adrs => permitido (override sancionado)
    ok = b.bus.submit(_patch(orch.id, content="microservices", linked_adrs=[adr.id]))
    assert ok.status.value == "applied"


def test_contract_removal_blocked() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("x")
    b = svc._bundle(orch.id)  # noqa: SLF001
    b.agent_registry.get("DataApiContractsAgent")
    result = b.bus.submit(
        ContextPatch(
            orchestration_id=orch.id,
            agent="DataApiContractsAgent",
            phase=Phase.F3,
            patch_type=PatchType.REMOVE,
            target_path="contracts.schemas",
        )
    )
    assert result.status.value == "rejected"
    assert result.conflict is not None
    assert result.conflict.type == ConflictType.CONTRACT


def test_resolve_conflict_proposes_and_creates_card() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("x")
    b = svc._bundle(orch.id)  # noqa: SLF001
    b.agent_registry.get("DataApiContractsAgent")
    res = b.bus.submit(
        ContextPatch(
            orchestration_id=orch.id,
            agent="DataApiContractsAgent",
            phase=Phase.F3,
            patch_type=PatchType.UPDATE,
            target_path="contracts.api_version",
            content="v2",
        )
    )
    conflict_id = res.conflict.id  # type: ignore[union-attr]
    before = len(svc.get_cards(orch.id))
    resolved = svc.resolve_conflict(orch.id, conflict_id)
    assert resolved.status == "escalated"
    assert resolved.resolution
    assert len(svc.get_cards(orch.id)) == before + 1  # card ADRTask criado
