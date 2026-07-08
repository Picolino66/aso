"""(d) Regressão de concorrência: escrita do contexto atômica + bundle único.

Cobre os dois vetores de corrupção apontados pela revisão adversarial:
- `OrchestratorContextStore.apply_patch` sob execução concorrente não perde
  incremento nem duplica versão/history (achado 1.1).
- `_bundle()` sob requisições concorrentes hidrata uma única instância — sem
  divergência de bundle nem lost-update (achado 4.1).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from aso.control.orchestration_service import OrchestrationService
from aso.governance.context_store import OrchestratorContextStore
from aso.governance.models import ContextPatch
from aso.shared.types import PatchType, Phase


def test_apply_patch_is_atomic_under_concurrency() -> None:
    store = OrchestratorContextStore("orch-x")
    n = 200

    def apply(i: int) -> int:
        return store.apply_patch(
            ContextPatch(
                orchestration_id="orch-x",
                agent="tester",
                phase=Phase.F5,
                patch_type=PatchType.UPDATE,
                target_path=f"engineering.k{i}",
                content=i,
            )
        )

    with ThreadPoolExecutor(max_workers=16) as pool:
        returned = list(pool.map(apply, range(n)))

    # nenhum incremento perdido nem versão duplicada
    assert store.version == n
    assert len(store.history) == n
    assert sorted(e.version for e in store.history) == list(range(1, n + 1))
    assert sorted(returned) == list(range(1, n + 1))


def test_bundle_hydrates_single_instance_under_concurrency() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("backend")
    # esvazia o cache em memória para forçar hidratação concorrente a partir do repo
    svc._bundles.clear()  # noqa: SLF001 — exercita o caminho de hidratação

    with ThreadPoolExecutor(max_workers=16) as pool:
        bundles = list(pool.map(lambda _: svc._bundle(orch.id), range(32)))  # noqa: SLF001

    # todas as threads recebem exatamente a mesma instância (sem divergência)
    assert all(b is bundles[0] for b in bundles)
    assert svc._bundles[orch.id] is bundles[0]  # noqa: SLF001


def test_concurrent_mutators_keep_state_consistent() -> None:
    """Stress multi-endpoint na mesma orquestração: sem lost-update após reload."""
    svc = OrchestrationService()
    orch = svc.create_orchestration("backend")
    oid = orch.id
    cards = svc.get_cards(oid)
    n_pr = len(cards)
    n_ap = 20

    def op(i: int) -> None:
        if i < n_pr:
            svc.open_pr(oid, cards[i].id)  # append em pull_requests + _persist
        else:
            svc.request_approval(oid, action=f"ação-{i}", risk="high")  # append em approvals

    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(op, range(n_pr + n_ap)))

    # força reidratação a partir do repositório e confere que nada se perdeu
    svc._bundles.clear()  # noqa: SLF001
    assert len(svc.list_pulls(oid)) == n_pr
    assert len(svc.list_approvals(oid)) == n_ap
