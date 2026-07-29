"""Próximo passo ponta a ponta: endpoint + tela de detalhe dedicada (ADR-0013)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService
from aso.execution.catalog import ExecutorCatalog, ExecutorProfile
from aso.shared.types import ColumnKey, ExecutionMode, Phase


def _client(svc: OrchestrationService) -> TestClient:
    return TestClient(create_app(svc))


def _mock_catalog() -> ExecutorCatalog:
    return ExecutorCatalog([ExecutorProfile(name="mock", kind="mock", is_default=True)])


def _next_step(client: TestClient, oid: str) -> dict[str, Any]:
    response = client.get(f"/v1/orchestrations/{oid}/next-step")
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    return body


def test_next_step_cobra_docs_first_antes_de_executar(tmp_path: Path) -> None:
    """Orquestração recém-criada: a doc que os agentes leem vem antes do código."""
    svc = OrchestrationService(catalog=_mock_catalog())
    orch = svc.create_orchestration(
        "Criar calculadora",
        target_path=str(tmp_path),
        execution_mode=ExecutionMode.CODE_EXECUTION,
        validation_command="echo ok",
    )
    body = _next_step(_client(svc), orch.id)
    assert body["primary_action"]["path"].endswith("/analyze-folder")
    estados = {item["code"]: item["state"] for item in body["checklist"]}
    assert estados["docs_first"] == "atual"


def test_next_step_pede_execucao_quando_ha_card_em_ready(tmp_path: Path) -> None:
    """Estado da tela: docs geradas e cards em Ready → o próximo clique é rodar a fase."""
    svc = OrchestrationService(catalog=_mock_catalog())
    orch = svc.create_orchestration(
        "Criar calculadora",
        target_path=str(tmp_path),
        execution_mode=ExecutionMode.CODE_EXECUTION,
        validation_command="echo ok",
    )
    svc.analyze_folder(orch.id)  # gera a documentação docs-first (scaffold determinístico)
    assert svc.get(orch.id).workspace_prepared is True
    body = _next_step(_client(svc), orch.id)
    assert body["phase"] == "F5"
    assert body["phase_label"] == "Engineering Execution"
    assert body["next_phase"] == "F6"
    assert any(b["code"] == "cards_prontos" for b in body["blockers"])
    assert body["primary_action"]["path"].endswith("/run-phase")
    assert [i["code"] for i in body["checklist"]][:3] == ["workspace", "docs_first", "validacao"]


def test_next_step_cobra_comando_de_validacao(tmp_path: Path) -> None:
    svc = OrchestrationService(catalog=_mock_catalog())
    orch = svc.create_orchestration(
        "Criar calculadora",
        target_path=str(tmp_path),
        execution_mode=ExecutionMode.CODE_EXECUTION,
    )
    body = _next_step(_client(svc), orch.id)
    assert body["blockers"][0]["code"] == "validacao_ausente"
    assert body["primary_action"]["method"] == "PATCH"


def test_next_step_aponta_aprovacao_apos_a_fase(tmp_path: Path) -> None:
    """Gate aprovado abre aprovação humana — e é ela que passa a ser o próximo passo."""
    svc = OrchestrationService(catalog=_mock_catalog())
    orch = svc.create_orchestration("Criar calculadora", target_path=str(tmp_path))
    for card in svc.get_cards(orch.id):
        if card.phase == Phase.F1 and card.status == ColumnKey.READY:
            svc.run_card(orch.id, card.id)
    resultado = svc.run_phase(orch.id, Phase.F1)
    assert resultado["approval_id"] is not None
    body = _next_step(_client(svc), orch.id)
    assert body["blockers"][0]["code"] == "aprovacao_pendente"
    assert body["primary_action"]["role"] == "admin"
    assert body["primary_action"]["path"].startswith("/v1/approvals/")


def test_next_step_de_orquestracao_cancelada_oferece_retomar(tmp_path: Path) -> None:
    svc = OrchestrationService(catalog=_mock_catalog())
    orch = svc.create_orchestration("Criar calculadora", target_path=str(tmp_path))
    svc.cancel(orch.id)
    body = _next_step(_client(svc), orch.id)
    assert [b["code"] for b in body["blockers"]] == ["cancelada"]
    assert body["primary_action"]["path"].endswith("/resume")


def test_next_step_404_em_orquestracao_inexistente() -> None:
    client = _client(OrchestrationService(catalog=_mock_catalog()))
    assert client.get("/v1/orchestrations/orch_nao_existe/next-step").status_code == 404


def test_ui_detalhe_e_dedicada_a_uma_orquestracao() -> None:
    """A tela de detalhe não repete o formulário de criação nem o kanban global."""
    client = _client(OrchestrationService(catalog=_mock_catalog()))
    pagina = client.get("/ui/detalhe")
    assert pagina.status_code == 200
    assert "Próximo passo" in pagina.text
    assert "Esteira F1 → F7" in pagina.text
    assert "NOVA ORQUESTRAÇÃO" not in pagina.text.upper()
    # O console técnico completo continua acessível para auditoria.
    console = client.get("/ui/console")
    assert console.status_code == 200
    assert "Nova orquestração" in console.text
