"""Testes de performance/escala: leitura leve, paginação e agregação sem hidratar."""

from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService
from aso.db.repository import SqlAlchemyOrchestrationRepository


def _seed(svc: OrchestrationService, n: int) -> None:
    for i in range(n):
        orch = svc.create_orchestration(f"demanda {i}")
        card = svc.get_cards(orch.id)[0]
        svc.run_card(orch.id, card.id)


def test_list_all_is_lightweight_at_scale(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'perf.db'}"
    svc = OrchestrationService(repository=SqlAlchemyOrchestrationRepository(url))
    _seed(svc, 40)

    # Nova instância (sem cache de bundles) para medir leitura pura do repositório.
    fresh = OrchestrationService(repository=SqlAlchemyOrchestrationRepository(url))
    start = time.perf_counter()
    items = fresh.list_all()
    elapsed = time.perf_counter() - start
    assert len(items) == 40
    # list_all NÃO deve hidratar aggregates (nenhum bundle em cache) e ser rápido.
    assert not fresh._bundles  # noqa: SLF001
    assert elapsed < 1.0


def test_aggregate_metrics_no_hydration(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'agg.db'}"
    svc = OrchestrationService(repository=SqlAlchemyOrchestrationRepository(url))
    _seed(svc, 10)
    fresh = OrchestrationService(repository=SqlAlchemyOrchestrationRepository(url))
    agg = fresh.aggregate_metrics()
    assert agg["orchestrations_total"] == 10
    assert agg["cards_by_status"].get("Testing") == 10
    assert agg["adrs_total"] == 10
    assert not fresh._bundles  # noqa: SLF001 — agregação não hidrata


def test_pagination_api(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'pag.db'}"
    svc = OrchestrationService(repository=SqlAlchemyOrchestrationRepository(url))
    _seed(svc, 12)
    client = TestClient(create_app(svc))

    full = client.get("/v1/orchestrations")
    assert len(full.json()) == 12
    assert full.headers["X-Total-Count"] == "12"

    page = client.get("/v1/orchestrations?page=1&page_size=5")
    assert len(page.json()) == 5
    assert page.headers["X-Total-Count"] == "12"
    assert len(client.get("/v1/orchestrations?page=3&page_size=5").json()) == 2


def test_read_cache_serves_repeated_aggregation() -> None:
    svc = OrchestrationService()
    svc.create_orchestration("x")
    a = svc.aggregate_metrics()
    b = svc.aggregate_metrics()  # servido do cache TTL
    assert a == b
    svc.create_orchestration("y")  # escrita invalida o cache
    assert svc.aggregate_metrics()["orchestrations_total"] == 2
