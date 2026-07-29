"""Drift-check contínuo de docs (F5/F6) + self-heal, ponta a ponta."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService
from aso.execution.catalog import ExecutorCatalog, ExecutorProfile
from aso.execution.docs_scaffold import write_scaffold
from aso.execution.workspace import WorkspaceService
from aso.shared.types import ColumnKey, GateStatus, Phase


def _mock_catalog() -> ExecutorCatalog:
    return ExecutorCatalog([ExecutorProfile(name="mock", kind="mock", is_default=True)])


def _fill(feature: Path) -> None:
    feature.write_text(
        feature.read_text(encoding="utf-8").replace("_A preencher._", "conteúdo real"),
        encoding="utf-8",
    )


def _run_phase_cards(svc: OrchestrationService, oid: str, phase: Phase) -> None:
    """Roda os cards Ready da fase (mock) para gerar output — o gate exige output."""
    for card in svc.get_cards(oid):
        if card.phase == phase and card.status == ColumnKey.READY:
            svc.run_card(oid, card.id)


def test_gate_f5_avisa_drift_sem_reprovar(tmp_path: Path) -> None:
    svc = OrchestrationService(catalog=_mock_catalog())
    orch = svc.create_orchestration("backend", target_path=str(tmp_path))
    WorkspaceService().ensure_git(tmp_path)
    write_scaffold(tmp_path, ["core"])  # doc com placeholder → drift
    _run_phase_cards(svc, orch.id, Phase.F5)  # gera output p/ o gate passar
    result = svc.run_quality_gate(orch.id, Phase.F5)
    assert result.status == GateStatus.PASSED  # drift é aviso, não reprova
    assert "docs_in_sync" in result.warnings


def test_gate_f5_sem_drift_nao_avisa(tmp_path: Path) -> None:
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "a.py").write_text("x=1\n", encoding="utf-8")
    write_scaffold(tmp_path, ["core"])
    _fill(tmp_path / "docs" / "modules" / "core" / "core.md")
    svc = OrchestrationService(catalog=_mock_catalog())
    orch = svc.create_orchestration("backend", target_path=str(tmp_path))
    WorkspaceService().ensure_git(tmp_path)
    _run_phase_cards(svc, orch.id, Phase.F5)
    result = svc.run_quality_gate(orch.id, Phase.F5)
    assert result.status == GateStatus.PASSED
    assert "docs_in_sync" not in result.warnings


def test_heal_docs_cria_doc_de_modulo_sem_doc(tmp_path: Path) -> None:
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "a.py").write_text("x=1\n", encoding="utf-8")
    write_scaffold(tmp_path, [])  # só o módulo neutro "projeto"
    svc = OrchestrationService(catalog=_mock_catalog())
    orch = svc.create_orchestration("backend", target_path=str(tmp_path))
    before = svc.docs_drift(orch.id)
    assert "core" in before["undocumented_modules"]
    out = svc.heal_docs(orch.id)  # mock → self-heal determinístico (scaffold)
    assert out["mode"] == "scaffold"
    assert (tmp_path / "docs" / "modules" / "core" / "core.md").is_file()


def test_endpoints_docs_drift_e_heal(tmp_path: Path) -> None:
    svc = OrchestrationService(catalog=_mock_catalog())
    client = TestClient(create_app(svc))
    oid = client.post(
        "/v1/orchestrations", json={"user_request": "x", "target_path": str(tmp_path)}
    ).json()["id"]
    client.post(f"/v1/orchestrations/{oid}/analyze-folder", json={})  # gera docs
    drift = client.get(f"/v1/orchestrations/{oid}/docs-drift")
    assert drift.status_code == 200
    assert drift.json()["has_docs"] is True
    heal = client.post(f"/v1/orchestrations/{oid}/docs-heal", json={})
    assert heal.status_code == 201
    assert "after" in heal.json()


def test_docs_drift_sem_pasta_conflita(tmp_path: Path) -> None:
    svc = OrchestrationService(catalog=_mock_catalog())
    client = TestClient(create_app(svc))
    oid = client.post("/v1/orchestrations", json={"user_request": "x"}).json()["id"]
    r = client.get(f"/v1/orchestrations/{oid}/docs-drift")
    assert r.status_code == 409


def test_run_phase_f5_autoheal_cria_doc_de_modulo(tmp_path: Path) -> None:
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "a.py").write_text("x=1\n", encoding="utf-8")
    write_scaffold(tmp_path, [])  # docs geradas, mas 'core' sem doc → drift
    svc = OrchestrationService(catalog=_mock_catalog())
    orch = svc.create_orchestration("backend", target_path=str(tmp_path))
    WorkspaceService().ensure_git(tmp_path)
    result = svc.run_phase(orch.id, Phase.F5)
    assert result["docs_autoheal"] is not None  # auto-sincronizou ao fim de F5
    assert (tmp_path / "docs" / "modules" / "core" / "core.md").is_file()


def test_run_phase_autoheal_desligavel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASO_AUTOHEAL_DOCS", "0")
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "a.py").write_text("x=1\n", encoding="utf-8")
    write_scaffold(tmp_path, [])
    svc = OrchestrationService(catalog=_mock_catalog())
    orch = svc.create_orchestration("backend", target_path=str(tmp_path))
    WorkspaceService().ensure_git(tmp_path)
    result = svc.run_phase(orch.id, Phase.F5)
    assert result["docs_autoheal"] is None
    assert not (tmp_path / "docs" / "modules" / "core").exists()


def test_run_phase_f1_nao_autoheal(tmp_path: Path) -> None:
    write_scaffold(tmp_path, ["core"])  # drift (placeholder), mas fase F1 não sincroniza
    svc = OrchestrationService(catalog=_mock_catalog())
    orch = svc.create_orchestration("backend", target_path=str(tmp_path))
    WorkspaceService().ensure_git(tmp_path)
    result = svc.run_phase(orch.id, Phase.F1)
    assert result["docs_autoheal"] is None
