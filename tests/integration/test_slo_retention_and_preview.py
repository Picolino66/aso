"""(b) Retenção de amostras de SLO + (c) dry-run da restauração seletiva (§23)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService
from aso.governance.models import SloEvaluation


def test_slo_samples_are_retained_up_to_limit() -> None:
    svc = OrchestrationService(max_slo_samples=3)
    orch = svc.create_orchestration("backend")
    for i in range(6):
        svc.record_slo_evaluation(orch.id, SloEvaluation(orchestration_id=orch.id, burn_rate=i))

    kept = svc.list_slo_evaluations(orch.id)
    assert len(kept) == 3  # só as 3 mais recentes
    assert [e.burn_rate for e in kept] == [3.0, 4.0, 5.0]  # as antigas foram podadas
    # sobrevive à reidratação com o limite já aplicado na escrita
    svc._bundles.clear()  # noqa: SLF001
    assert len(svc.list_slo_evaluations(orch.id)) == 3


def _two_snapshots(client: TestClient) -> str:
    oid = client.post("/v1/orchestrations", json={"user_request": "X"}).json()["id"]
    card_id = client.get(f"/v1/orchestrations/{oid}/cards").json()[0]["id"]
    client.post(f"/v1/orchestrations/{oid}/cards/{card_id}/run")
    client.post(f"/v1/orchestrations/{oid}/quality-gates/run", json={"phase": "F5"})
    client.post(f"/v1/orchestrations/{oid}/quality-gates/run", json={"phase": "F6"})
    return oid


def test_restore_section_preview_is_readonly_and_reports_impact() -> None:
    client = TestClient(create_app(OrchestrationService()))
    oid = _two_snapshots(client)
    section = next(iter(client.get(f"/v1/orchestrations/{oid}/context").json()["payload"].keys()))

    # restaurar do próprio O6 (idêntico ao contexto atual) → sem mudança (no_op)
    prev = client.get(
        f"/v1/orchestrations/{oid}/snapshots/O6/restore-section/preview",
        params={"section": section},
    )
    assert prev.status_code == 200
    body = prev.json()
    assert body["section"] == section
    assert set(body["changes"]) == {"added", "removed", "modified"}
    assert body["no_op"] is True

    # o dry-run não alterou o contexto (nenhuma versão nova por restauração)
    ctx_version = client.get(f"/v1/orchestrations/{oid}/context").json()["version"]
    client.get(
        f"/v1/orchestrations/{oid}/snapshots/O6/restore-section/preview",
        params={"section": section},
    )
    assert client.get(f"/v1/orchestrations/{oid}/context").json()["version"] == ctx_version

    # seção inexistente → 404
    missing = client.get(
        f"/v1/orchestrations/{oid}/snapshots/O6/restore-section/preview",
        params={"section": "nao_existe"},
    )
    assert missing.status_code == 404


def test_preview_reports_changes_when_section_differs() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("backend")
    card = svc.get_cards(orch.id)[0]
    svc.run_card(orch.id, card.id)
    svc.run_quality_gate(orch.id)
    snap = svc.list_snapshots(orch.id)[0]
    section = next(iter(snap.payload.keys()))

    # snapshot inexistente → KeyError; snapshot válido → preview com o delta
    with pytest.raises(KeyError):
        svc.preview_restore_section(orch.id, "OX", section)
    preview = svc.preview_restore_section(orch.id, snap.snapshot_version, section)
    assert preview["from_snapshot"] == snap.snapshot_version
    assert set(preview["changes"]) == {"added", "removed", "modified"}
