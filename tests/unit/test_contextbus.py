"""Testes do ContextBus e do pipeline de 7 etapas (TASK-09, §19)."""

from __future__ import annotations

from aso.governance.adr_registry import ADRRegistry
from aso.governance.context_store import OrchestratorContextStore
from aso.governance.contextbus import ContextBus, PermissionPolicy
from aso.shared.types import ADRStatus, ConflictType, PatchStatus, PatchType, Phase
from tests.unit.conftest import ORCH_ID, make_patch


def _bus(store: OrchestratorContextStore, **kwargs: object) -> ContextBus:
    permissions = PermissionPolicy({"ArchitectureDesignAgent": ["architecture"]})
    return ContextBus(store, permissions=permissions, **kwargs)  # type: ignore[arg-type]


def test_valid_patch_is_applied(store: OrchestratorContextStore) -> None:
    bus = _bus(store)
    result = bus.submit(make_patch())
    assert result.status == PatchStatus.APPLIED
    assert result.version == 1
    assert store.get_path("architecture.pattern") == "modular-monolith"
    assert bus.event_log.of_type("ContextPatchApplied")


def test_permission_denied_raises_tool_permission_conflict(store: OrchestratorContextStore) -> None:
    bus = _bus(store)
    result = bus.submit(make_patch(agent="BackendDevelopmentAgent"))
    assert result.status == PatchStatus.REJECTED
    assert result.conflict is not None
    assert result.conflict.type == ConflictType.TOOL_PERMISSION
    assert store.version == 0  # nada foi aplicado


def test_frozen_section_rejected_without_adr(store: OrchestratorContextStore) -> None:
    bus = _bus(store)
    bus.submit(make_patch())
    store.freeze(["architecture"])
    result = bus.submit(make_patch(content="microservices"))
    assert result.status == PatchStatus.REJECTED
    assert result.conflict is not None
    assert result.conflict.type == ConflictType.SNAPSHOT_LOCK


def test_frozen_section_allowed_with_adr_override(store: OrchestratorContextStore) -> None:
    registry = ADRRegistry(ORCH_ID)
    adr = registry.create(
        title="Override arquitetura", decision="Migrar", phase=Phase.F2, status=ADRStatus.ACCEPTED
    )
    permissions = PermissionPolicy({"ArchitectureDesignAgent": ["architecture"]})
    bus = ContextBus(store, permissions=permissions, adr_registry=registry)
    bus.submit(make_patch())
    store.freeze(["architecture"])
    result = bus.submit(
        make_patch(content="microservices", requires_adr=True, linked_adrs=[adr.id])
    )
    assert result.status == PatchStatus.APPLIED
    assert store.get_path("architecture.pattern") == "microservices"


def test_requires_adr_without_link_is_rejected(store: OrchestratorContextStore) -> None:
    bus = _bus(store)
    result = bus.submit(make_patch(requires_adr=True))
    assert result.status == PatchStatus.REJECTED
    assert result.conflict is not None
    assert result.conflict.type == ConflictType.ARCHITECTURE


def test_missing_content_rejected(store: OrchestratorContextStore) -> None:
    bus = _bus(store)
    result = bus.submit(make_patch(content=None, patch_type=PatchType.UPDATE))
    assert result.status == PatchStatus.REJECTED
    assert result.conflict is not None
    assert result.conflict.type == ConflictType.DATA_MODEL


def test_propose_patch_is_not_applied_but_pending(store: OrchestratorContextStore) -> None:
    bus = _bus(store)
    result = bus.submit(make_patch(patch_type=PatchType.PROPOSE))
    assert result.status == PatchStatus.PENDING
    assert store.version == 0  # proposta não muta o contexto
    assert bus.event_log.of_type("ContextPatchPendingApproval")


def test_requires_approval_patch_pending(store: OrchestratorContextStore) -> None:
    bus = _bus(store)
    result = bus.submit(make_patch(requires_approval=True))
    assert result.status == PatchStatus.PENDING
    assert store.version == 0  # ação crítica não é aplicada sem aprovação


def test_default_policy_denies_all(store: OrchestratorContextStore) -> None:
    bus = ContextBus(store)  # sem política => deny-by-default
    result = bus.submit(make_patch())
    assert result.status == PatchStatus.REJECTED
    assert result.conflict is not None
    assert result.conflict.type == ConflictType.TOOL_PERMISSION


def test_contract_version_immutable(store: OrchestratorContextStore) -> None:
    permissions = PermissionPolicy({"DataApiContractsAgent": ["contracts"]})
    bus = ContextBus(store, permissions=permissions)
    result = bus.submit(
        make_patch(agent="DataApiContractsAgent", target_path="contracts.api_version", content="v2")
    )
    assert result.status == PatchStatus.REJECTED
    assert result.conflict is not None
    assert result.conflict.type == ConflictType.CONTRACT
