"""Telas 22/24/25/27 pela API (aprovação, saúde, rollback, encerramento — wf
§24/§26/§27/§29, ADR-0050)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService
from aso.control.triage import DemandBrief
from aso.shared.types import Phase, RiskLevel


def _orch_pronta(svc: OrchestrationService, tmp_path: Path, *, risco: RiskLevel) -> str:
    orch = svc.create_orchestration(
        "ajustar cálculo de frete",
        target_path=str(tmp_path),
        seed_cards=False,
        demand_brief=DemandBrief(risco=risco),
    )
    svc.run_quality_gate(orch.id, Phase.F5)
    return orch.id


def test_approval_checklist_sem_deploy_ainda_devolve_itens() -> None:
    client = TestClient(create_app(OrchestrationService()))
    oid = client.post("/v1/orchestrations", json={"user_request": "demanda"}).json()["id"]
    resposta = client.get(f"/v1/orchestrations/{oid}/deploy/approval-checklist")
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert len(corpo["checklist"]) == 9
    assert corpo["avaliacao_de_risco"]["aprovacao"] == "pendente"


def test_health_e_rollback_checklist_sem_deploy_devolvem_404() -> None:
    client = TestClient(create_app(OrchestrationService()))
    oid = client.post("/v1/orchestrations", json={"user_request": "demanda"}).json()["id"]
    assert client.get(f"/v1/orchestrations/{oid}/deploy/health").status_code == 404
    assert client.get(f"/v1/orchestrations/{oid}/deploy/rollback-checklist").status_code == 404


def test_fluxo_deploy_risco_baixo_saude_e_checklist_pos_deploy(tmp_path: Path) -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid = _orch_pronta(svc, tmp_path, risco=RiskLevel.LOW)

    client.put(f"/v1/orchestrations/{oid}/deploy/config", json={"command": "bash -c 'exit 0'"})
    executado = client.post(f"/v1/orchestrations/{oid}/deploy/run", json={})
    assert executado.status_code == 200

    saude = client.get(f"/v1/orchestrations/{oid}/deploy/health")
    assert saude.status_code == 200
    assert saude.json()["saude"] == "saudavel"
    assert saude.json()["decisao_sugerida"] == "concluir_implantacao"

    checklist = client.get(f"/v1/orchestrations/{oid}/deploy/approval-checklist").json()
    por_item = {c["item"]: c["ok"] for c in checklist["checklist"]}
    assert por_item["Aprovação humana realizada"] is False  # aceite automático, não humano

    rollback_checklist = client.get(f"/v1/orchestrations/{oid}/deploy/rollback-checklist").json()
    por_item2 = {c["item"]: c["ok"] for c in rollback_checklist}
    assert por_item2["Executar rollback"] is False  # ainda não revertido
    assert por_item2["Abrir análise de causa raiz"] is False  # nenhum incidente ainda


def test_aprovar_com_tipo_aceite_persiste_no_deploy(tmp_path: Path) -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid = _orch_pronta(svc, tmp_path, risco=RiskLevel.HIGH)

    client.put(f"/v1/orchestrations/{oid}/deploy/config", json={"command": "bash -c 'exit 0'"})
    client.post(f"/v1/orchestrations/{oid}/deploy/run", json={})

    aprovado = client.post(
        f"/v1/orchestrations/{oid}/deploy/approve",
        json={"approved": True, "tipo_aceite": "produto"},
    )
    assert aprovado.status_code == 200
    assert aprovado.json()["tipo_aceite_humano"] == "produto"

    checklist = client.get(f"/v1/orchestrations/{oid}/deploy/approval-checklist").json()
    por_item = {c["item"]: c["ok"] for c in checklist["checklist"]}
    assert por_item["Aprovação humana realizada"] is True


def test_rollback_com_estrategia_persiste_e_completa_checklist(tmp_path: Path) -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid = _orch_pronta(svc, tmp_path, risco=RiskLevel.LOW)

    client.put(f"/v1/orchestrations/{oid}/deploy/config", json={"command": "bash -c 'exit 0'"})
    client.post(f"/v1/orchestrations/{oid}/deploy/run", json={})

    revertido = client.post(
        f"/v1/orchestrations/{oid}/deploy/rollback",
        json={"reason": "bug crítico em produção", "estrategia": "voltar_versao"},
    )
    assert revertido.status_code == 200
    assert revertido.json()["rollback_estrategia"] == "voltar_versao"

    checklist = client.get(f"/v1/orchestrations/{oid}/deploy/rollback-checklist").json()
    por_item = {c["item"]: c["ok"] for c in checklist}
    assert por_item["Executar rollback"] is True
    assert por_item["Abrir análise de causa raiz"] is True  # _criar_incidente já rodou


def test_closure_sem_atividade_tem_os_treze_blocos() -> None:
    client = TestClient(create_app(OrchestrationService()))
    oid = client.post("/v1/orchestrations", json={"user_request": "demanda vazia"}).json()["id"]
    resposta = client.get(f"/v1/orchestrations/{oid}/closure")
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert set(corpo["relatorio"].keys()) == {
        "resumo",
        "agentes_utilizados",
        "modelos_utilizados",
        "effort_utilizado",
        "commits",
        "pull_requests",
        "documentos_produzidos",
        "testes_executados",
        "evidencias",
        "data_implantacao",
        "decisoes_tecnicas",
        "riscos_residuais",
        "pendencias_futuras",
    }
    assert corpo["relatorio"]["resumo"] == "demanda vazia"
    assert set(corpo["metricas"].keys()) == {
        "cards_concluidos",
        "agentes_utilizados",
        "execucoes",
        "falhas_corrigidas",
        "intervencoes_humanas",
        "deploys",
    }


def test_closure_export_devolve_markdown_para_download() -> None:
    client = TestClient(create_app(OrchestrationService()))
    criada = client.post("/v1/orchestrations", json={"user_request": "demanda exportável"})
    oid = criada.json()["id"]
    resposta = client.get(f"/v1/orchestrations/{oid}/closure/export")
    assert resposta.status_code == 200
    assert "text/markdown" in resposta.headers["content-type"]
    assert "attachment" in resposta.headers["content-disposition"]
    assert "# Encerramento da demanda" in resposta.text
    assert "## Resumo da entrega" in resposta.text
    assert "## Pendências futuras" in resposta.text


def test_closure_reflete_adrs_como_decisoes_tecnicas() -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    criada = client.post("/v1/orchestrations", json={"user_request": "demanda com decisão"})
    oid = criada.json()["id"]
    corpo = client.get(f"/v1/orchestrations/{oid}/closure").json()
    # `create_orchestration` já registra ao menos 1 ADR de estratégia de execução.
    assert corpo["relatorio"]["decisoes_tecnicas"]
