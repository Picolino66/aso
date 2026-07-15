"""Pré-análise de workspace: progresso SSE, sem efeitos de escrita."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService


def test_preanalise_emite_inicio_arquivos_e_conclusao(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "README.md").write_text("# projeto", encoding="utf-8")
    (tmp_path / "src" / "app.py").write_text("print('oi')", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "ignorado.js").write_text("", encoding="utf-8")
    client = TestClient(create_app(OrchestrationService()))

    response = client.get("/v1/fs/analyze/stream", params={"path": str(tmp_path)})

    assert response.status_code == 200
    events = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    assert events[0] == {"percent": 0, "current": 0, "total": 2, "file": None}
    assert [event["file"] for event in events[1:]] == ["README.md", "src/app.py"]
    assert events[-1]["percent"] == 100
    assert events[-1]["current"] == events[-1]["total"] == 2
    assert not (tmp_path / ".git").exists()
    assert not (tmp_path / "docs").exists()


def test_preanalise_pasta_vazia_conclui_em_cem_porcento(tmp_path: Path) -> None:
    client = TestClient(create_app(OrchestrationService()))

    response = client.get("/v1/fs/analyze/stream", params={"path": str(tmp_path)})

    assert response.status_code == 200
    assert json.loads(response.text.removeprefix("data: ").strip()) == {
        "percent": 100,
        "current": 0,
        "total": 0,
        "file": None,
    }


def test_preanalise_rejeita_caminho_invalido(tmp_path: Path) -> None:
    file = tmp_path / "arquivo.txt"
    file.write_text("x", encoding="utf-8")
    client = TestClient(create_app(OrchestrationService()))

    response = client.get("/v1/fs/analyze/stream", params={"path": str(file)})

    assert response.status_code == 400
    assert "não é uma pasta" in response.json()["detail"]


def test_console_exige_preanalise_antes_da_demanda() -> None:
    console = (Path(__file__).parents[2] / "src/aso/api/static/nova.html").read_text(
        encoding="utf-8"
    )

    assert 'id="analyze"' in console
    assert 'id="demandCard" class="card" hidden' in console
    assert "function resetAnalysis()" in console
    assert "function analyzeWorkspace()" in console
    assert "new EventSource('/v1/fs/analyze/stream?'" in console
    assert "/analyze-folder" in console
    assert "echo ok" not in console
    assert "começará" not in console
    assert "Autopilot só começa quando você acioná-lo" in console
    assert "onclick=" not in console


def test_kanban_remove_executor_placeholder_e_mantem_colunas() -> None:
    console = (Path(__file__).parents[2] / "src/aso/api/static/index.html").read_text(
        encoding="utf-8"
    )

    assert "configCardExec" not in console
    assert "_cardExecs" not in console
    assert "'Planning'" in console
    assert "'WaitingAgent'" in console
    assert "'Archived'" in console
    assert "moverParaReady(id, card.id)" in console
