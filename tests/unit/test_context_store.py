"""Testes do OrchestratorContextStore (TASK-03)."""

from __future__ import annotations

from aso.governance.context_store import OrchestratorContextStore
from aso.shared.types import PatchType
from tests.unit.conftest import make_patch


def test_apply_patch_increments_version_and_sets_path(store: OrchestratorContextStore) -> None:
    assert store.version == 0
    store.apply_patch(make_patch(target_path="architecture.pattern", content="modular-monolith"))
    assert store.version == 1
    assert store.get_path("architecture.pattern") == "modular-monolith"


def test_history_is_append_only(store: OrchestratorContextStore) -> None:
    store.apply_patch(make_patch(target_path="product.name", content="ASO"))
    store.apply_patch(make_patch(target_path="product.domain", content="AgentOps"))
    assert len(store.history) == 2
    assert [h.version for h in store.history] == [1, 2]
    assert store.history[0].target_path == "product.name"


def test_hash_changes_with_content(store: OrchestratorContextStore) -> None:
    h0 = store.context_hash()
    store.apply_patch(make_patch(target_path="product.name", content="ASO"))
    assert store.context_hash() != h0


def test_get_returns_deep_copy(store: OrchestratorContextStore) -> None:
    store.apply_patch(make_patch(target_path="scope.included", content=["a"]))
    snapshot = store.get()
    snapshot["scope"]["included"].append("b")
    assert store.get_path("scope.included") == ["a"]


def test_apply_propose_raises(store: OrchestratorContextStore) -> None:
    import pytest

    with pytest.raises(ValueError, match="propose"):
        store.apply_patch(make_patch(patch_type=PatchType.PROPOSE))


def test_remove_path(store: OrchestratorContextStore) -> None:
    store.apply_patch(make_patch(target_path="product.name", content="ASO"))
    store.apply_patch(
        make_patch(target_path="product.name", content=None, patch_type=PatchType.REMOVE)
    )
    assert store.get_path("product.name") is None
