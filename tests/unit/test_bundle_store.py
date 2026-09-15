"""MEL-32 passo 1 — `BundleStore`: fonte única de cache, hidratação e lock (ADR-0066)."""

from __future__ import annotations

import threading
from typing import Any

import pytest

from aso.application.bundles import BundleStore, OrchestrationBundle
from aso.control.orchestration_service import OrchestrationService
from aso.persistence.memory import InMemoryOrchestrationRepository
from aso.shared.cache import TTLCache


def _repo_com_orquestracao() -> tuple[InMemoryOrchestrationRepository, str]:
    repo = InMemoryOrchestrationRepository()
    svc = OrchestrationService(repository=repo)
    return repo, svc.create_orchestration("backend").id


def test_hidratacao_concorrente_gera_uma_unica_instancia() -> None:
    repo, oid = _repo_com_orquestracao()
    hidratados: list[OrchestrationBundle] = []
    store = BundleStore(repo, definicoes_ativas=list, ao_hidratar=hidratados.append)
    barreira = threading.Barrier(8)
    vistos: list[OrchestrationBundle] = []

    def pegar() -> None:
        barreira.wait()
        vistos.append(store.get(oid))

    threads = [threading.Thread(target=pegar) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len({id(b) for b in vistos}) == 1
    assert len(hidratados) == 1  # recuperação pós-reidratação roda uma vez


def test_lock_e_unico_e_reentrante_por_orquestracao() -> None:
    store = BundleStore(InMemoryOrchestrationRepository(), definicoes_ativas=list)
    lock = store.lock_for("o1")
    assert store.lock_for("o1") is lock
    assert store.lock_for("o2") is not lock
    with lock, store.lock_for("o1"):  # RLock: o mesmo thread pode reentrar
        pass


def test_persistir_limpa_o_cache_de_leitura_e_grava_no_repositorio() -> None:
    repo, oid = _repo_com_orquestracao()
    cache = TTLCache(ttl_seconds=60)
    cache.set("agregado", {"x": 1})
    store = BundleStore(repo, definicoes_ativas=list, read_cache=cache)
    bundle = store.get(oid)
    bundle.orchestration.status = "paused"
    store.persist(bundle)
    assert cache.get("agregado") is None
    estado: Any = repo.load(oid)
    assert estado.orchestration.status == "paused"


def test_orquestracao_inexistente_levanta_keyerror() -> None:
    store = BundleStore(InMemoryOrchestrationRepository(), definicoes_ativas=list)
    with pytest.raises(KeyError, match="inexistente"):
        store.get("orch_nao_existe")


def test_facade_usa_o_lock_e_o_cache_do_store() -> None:
    svc = OrchestrationService()
    oid = svc.create_orchestration("backend").id
    store = svc._bundle_store  # noqa: SLF001 - a fonte única é o objeto do teste
    assert svc._lock_for(oid) is store.lock_for(oid)  # noqa: SLF001
    assert svc._bundles is store.cache  # noqa: SLF001
    assert svc._bundle(oid) is store.get(oid)  # noqa: SLF001
