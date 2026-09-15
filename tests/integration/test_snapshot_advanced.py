"""(c) Snapshots avançados: diff semântico por seção + restauração seletiva (§23)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService
from aso.shared.types import Phase


def _run_two_snapshots(client: TestClient) -> str:
    # Dois snapshots reais exigem duas fases com trabalho entregue — fase vazia é SKIPPED
    # e não gera snapshot (ADR-0060): cards em F2 (arquitetura) e F5 (backend) → O2 e O5.
    corpo = {"user_request": "X", "demand_brief": {"dominios": ["architecture", "backend"]}}
    oid = client.post("/v1/orchestrations", json=corpo).json()["id"]
    for card in client.get(f"/v1/orchestrations/{oid}/cards").json():
        if card["phase"] in ("F2", "F5"):
            client.post(f"/v1/orchestrations/{oid}/cards/{card['id']}/run")
    client.post(f"/v1/orchestrations/{oid}/quality-gates/run", json={"phase": "F2"})
    client.post(f"/v1/orchestrations/{oid}/quality-gates/run", json={"phase": "F5"})
    return oid


def test_snapshot_diff_has_section_details() -> None:
    client = TestClient(create_app(OrchestrationService()))
    oid = _run_two_snapshots(client)
    diff = client.get(f"/v1/orchestrations/{oid}/snapshots/O2/diff/O5").json()
    assert "section_details" in diff
    # cada seção alterada tem o detalhe adicionado/removido/modificado
    for section in diff["changed_sections"]:
        d = diff["section_details"][section]
        assert set(d) == {"added", "removed", "modified"}


def test_selective_section_restore_service_level() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("backend")
    card = svc.get_cards(orch.id)[0]
    svc.run_card(orch.id, card.id)
    svc.run_quality_gate(
        orch.id, Phase.F5
    )  # gate da fase do card (ADR-0060)  # gera um snapshot com payload completo

    snap = svc.list_snapshots(orch.id)[0]
    section = next(iter(snap.payload.keys()))

    res = svc.restore_section(orch.id, snap.snapshot_version, section)
    assert res["section"] == section
    assert res["from_snapshot"] == snap.snapshot_version
    assert res["context_version"] >= 1
    # rastreabilidade: ADR de restauração seletiva registrada
    assert any("Restauração seletiva" in a.title for a in svc.list_adrs(orch.id))

    with pytest.raises(KeyError):
        svc.restore_section(orch.id, snap.snapshot_version, "secao_inexistente")


def test_restore_section_endpoint() -> None:
    client = TestClient(create_app(OrchestrationService()))
    oid = _run_two_snapshots(client)
    # O5 é o snapshot mais recente (gate F5): seu payload reflete o contexto atual.
    payload = client.get(f"/v1/orchestrations/{oid}/context").json()["payload"]
    section = next(iter(payload.keys()))

    ok = client.post(
        f"/v1/orchestrations/{oid}/snapshots/O5/restore-section", json={"section": section}
    )
    assert ok.status_code == 202
    assert ok.json()["section"] == section

    missing = client.post(
        f"/v1/orchestrations/{oid}/snapshots/O5/restore-section", json={"section": "nao_existe"}
    )
    assert missing.status_code == 404
