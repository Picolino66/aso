"""Fixtures compartilhadas dos testes de unidade do core de governança."""

from __future__ import annotations

import pytest

from aso.governance.context_store import OrchestratorContextStore
from aso.governance.models import ContextPatch
from aso.shared.types import PatchType, Phase

ORCH_ID = "orch_test"


@pytest.fixture
def store() -> OrchestratorContextStore:
    return OrchestratorContextStore(ORCH_ID)


def make_patch(
    *,
    agent: str = "ArchitectureDesignAgent",
    target_path: str = "architecture.pattern",
    content: object = "modular-monolith",
    patch_type: PatchType = PatchType.UPDATE,
    phase: Phase = Phase.F2,
    requires_adr: bool = False,
    requires_approval: bool = False,
    linked_adrs: list[str] | None = None,
) -> ContextPatch:
    return ContextPatch(
        orchestration_id=ORCH_ID,
        agent=agent,
        phase=phase,
        patch_type=patch_type,
        target_path=target_path,
        content=content,
        requires_adr=requires_adr,
        requires_approval=requires_approval,
        linked_adrs=linked_adrs or [],
    )
