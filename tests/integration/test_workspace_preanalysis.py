"""Pré-análise de workspace: progresso SSE, sem efeitos de escrita."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.application.orchestration_service import OrchestrationService


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


def test_cadastro_de_demanda_oferece_preanalise_da_pasta() -> None:
    """A pré-análise (SSE, sem alterar arquivo) migrou de `nova.html` para o cadastro completo
    quando as páginas legadas saíram (ADR-0078). Ela é informativa: o operador vê o tamanho do
    repositório antes de criar a demanda."""
    pagina = (Path(__file__).parents[2] / "src/aso/api/static/demanda-nova.html").read_text(
        encoding="utf-8"
    )

    assert 'id="btAnalisar"' in pagina
    assert "function analisarPasta()" in pagina
    assert "new EventSource('/v1/fs/analyze/stream?'" in pagina
    assert "Nenhum arquivo foi alterado." in pagina
    assert "/analyze-folder" in pagina  # docs-first continua sendo passo explícito
    assert "onclick=" not in pagina


def test_kanban_mantem_as_colunas_do_board_sem_placeholder_de_executor() -> None:
    """O board do console técnico virou `/ui/kanban` (ADR-0047); as colunas vêm do runtime."""
    from fastapi.testclient import TestClient as _Client

    from aso.api.app import create_app as _create_app

    svc = OrchestrationService()
    client = _Client(_create_app(svc))
    oid = svc.create_orchestration("board do kanban").id
    quadro = client.get(f"/v1/orchestrations/{oid}/kanban").json()
    chaves = {col["coluna"] for col in quadro["colunas"]}
    for esperada in ("Planning", "WaitingAgent", "Archived", "Ready"):
        assert esperada in chaves, esperada

    pagina = (Path(__file__).parents[2] / "src/aso/api/static/kanban.html").read_text(
        encoding="utf-8"
    )
    assert "configCardExec" not in pagina and "_cardExecs" not in pagina
    assert "dados.colunas" in pagina  # colunas do runtime, não lista fixa no HTML
