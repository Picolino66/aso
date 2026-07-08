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
