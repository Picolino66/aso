"""MEL-32 passo 2 — `QueryService` extraído; a façade entrega o mesmo resultado (ADR-0066)."""

from __future__ import annotations

from aso.application.queries import QueryService
from aso.control.orchestration_service import OrchestrationService


def test_facade_delega_ao_query_service_com_o_mesmo_cache() -> None:
    svc = OrchestrationService()
    oid = svc.create_orchestration("backend").id
    card = svc.get_cards(oid)[0]
    svc.run_card(oid, card.id)
    queries = svc._queries  # noqa: SLF001 - o serviço extraído é o objeto do teste
    assert isinstance(queries, QueryService)
    assert queries._bundle_store is svc._bundle_store  # noqa: SLF001
    assert [c.id for c in queries.get_cards(oid)] == [c.id for c in svc.get_cards(oid)]
    assert queries.count_cards_by_status(oid) == svc.count_cards_by_status(oid)
    assert [e.type for e in queries.timeline(oid)] == [e.type for e in svc.timeline(oid)]
    assert queries.list_all() == svc.list_all()
    assert queries.header_summary() == svc.header_summary()


def test_query_service_nao_depende_da_facade() -> None:
    import ast
    from pathlib import Path

    fonte = Path(__file__).resolve().parents[2] / "src/aso/application/queries.py"
    importados = {
        n.module
        for n in ast.walk(ast.parse(fonte.read_text(encoding="utf-8")))
        if isinstance(n, ast.ImportFrom)
    }
    assert "aso.control.orchestration_service" not in importados
