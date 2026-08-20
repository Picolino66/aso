"""Implantação governada pela API (§18-22 do fluxo.md, ADR-0023)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.api.auth import AuthService, Principal
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
    svc.run_quality_gate(orch.id, Phase.F5)  # vacuamente PASSED (sem cards)
    return orch.id


def test_put_config_valida_cada_comando(tmp_path: Path) -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid = _orch_pronta(svc, tmp_path, risco=RiskLevel.LOW)

    resposta = client.put(
        f"/v1/orchestrations/{oid}/deploy/config", json={"command": "npm run dev"}
    )
    assert resposta.status_code == 400


def test_run_sem_config_devolve_409(tmp_path: Path) -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid = _orch_pronta(svc, tmp_path, risco=RiskLevel.LOW)

    resposta = client.post(f"/v1/orchestrations/{oid}/deploy/run", json={})
    assert resposta.status_code == 409


def test_fluxo_completo_risco_baixo_aceita_automatico_e_libera_gate(tmp_path: Path) -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid = _orch_pronta(svc, tmp_path, risco=RiskLevel.LOW)

    config = client.put(
        f"/v1/orchestrations/{oid}/deploy/config",
        json={"command": "bash -c 'exit 0'", "environment": "homologacao"},
    )
    assert config.status_code == 200

    executado = client.post(f"/v1/orchestrations/{oid}/deploy/run", json={})
    assert executado.status_code == 200
    corpo = executado.json()
    assert corpo["status"] == "sucesso"
    assert corpo["aceite_status"] == "aprovado"

    gate = client.post(f"/v1/orchestrations/{oid}/quality-gates/run", json={"phase": "F6"})
    assert gate.status_code == 200
    assert gate.json()["status"] == "PASSED"


def test_fluxo_risco_alto_aguarda_aceite_e_reprova_gate_ate_aprovar(tmp_path: Path) -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid = _orch_pronta(svc, tmp_path, risco=RiskLevel.HIGH)

    client.put(f"/v1/orchestrations/{oid}/deploy/config", json={"command": "bash -c 'exit 0'"})
    executado = client.post(f"/v1/orchestrations/{oid}/deploy/run", json={})
    assert executado.json()["aceite_status"] == "aguardando_aprovacao"

    gate = client.post(f"/v1/orchestrations/{oid}/quality-gates/run", json={"phase": "F6"})
    assert gate.status_code == 200
    assert "deploy_aprovado" in gate.json()["blocking_issues"]

    sem_admin = client.post(
        f"/v1/orchestrations/{oid}/deploy/approve",
        json={"approved": True},
        headers={"Authorization": "Bearer viewer-token"},
    )
    # Sem ASO_API_KEYS configurado a API roda em modo dev (sempre admin) —
    # este teste só confirma que a rota EXISTE e aceita a decisão; a garantia
    # de RBAC por sufixo (/approve → admin) já é coberta em test_auth.py.
    assert sem_admin.status_code == 200

    gate_liberado = client.post(f"/v1/orchestrations/{oid}/quality-gates/run", json={"phase": "F6"})
    assert gate_liberado.json()["status"] == "PASSED"


def test_rollback_cria_card_de_incidente_visivel_na_listagem(tmp_path: Path) -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid = _orch_pronta(svc, tmp_path, risco=RiskLevel.LOW)

    client.put(f"/v1/orchestrations/{oid}/deploy/config", json={"command": "bash -c 'exit 0'"})
    client.post(f"/v1/orchestrations/{oid}/deploy/run", json={})

    resposta = client.post(
        f"/v1/orchestrations/{oid}/deploy/rollback", json={"reason": "erro grave detectado"}
    )
    assert resposta.status_code == 200
    assert resposta.json()["status"] == "revertido"

    cards = client.get(f"/v1/orchestrations/{oid}/cards").json()
    incidentes = [c for c in cards if c["type"] == "Incident"]
    assert len(incidentes) == 1
    assert "erro grave detectado" in incidentes[0]["description"]


# ------------------------------------------------------ incidentes (§21, ADR-0032)


def test_rollback_cria_incidente_acessivel_via_api(tmp_path: Path) -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid = _orch_pronta(svc, tmp_path, risco=RiskLevel.CRITICAL)

    client.put(f"/v1/orchestrations/{oid}/deploy/config", json={"command": "bash -c 'exit 0'"})
    client.post(f"/v1/orchestrations/{oid}/deploy/run", json={})
    client.post(f"/v1/orchestrations/{oid}/deploy/rollback", json={"reason": "erro grave"})

    listados = client.get(f"/v1/orchestrations/{oid}/incidents").json()
    assert len(listados) == 1
    incident_id = listados[0]["id"]
    assert listados[0]["gravidade"] == "critica"
    assert listados[0]["status"] == "aberto"

    detalhe = client.get(f"/v1/orchestrations/{oid}/incidents/{incident_id}")
    assert detalhe.status_code == 200
    assert detalhe.json()["id"] == incident_id


def test_get_incidente_inexistente_devolve_404(tmp_path: Path) -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid = _orch_pronta(svc, tmp_path, risco=RiskLevel.LOW)
    resposta = client.get(f"/v1/orchestrations/{oid}/incidents/incident_inexistente")
    assert resposta.status_code == 404


def test_fluxo_completo_investigar_e_resolver_incidente_via_api(tmp_path: Path) -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid = _orch_pronta(svc, tmp_path, risco=RiskLevel.LOW)

    client.put(f"/v1/orchestrations/{oid}/deploy/config", json={"command": "bash -c 'exit 0'"})
    client.post(f"/v1/orchestrations/{oid}/deploy/run", json={})
    client.post(f"/v1/orchestrations/{oid}/deploy/rollback", json={"reason": "erro grave"})
    incident_id = client.get(f"/v1/orchestrations/{oid}/incidents").json()[0]["id"]

    investigado = client.post(
        f"/v1/orchestrations/{oid}/incidents/{incident_id}/investigate",
        json={"detalhe": "checando causa"},
    )
    assert investigado.status_code == 200
    assert investigado.json()["status"] == "investigando"

    resolvido = client.post(
        f"/v1/orchestrations/{oid}/incidents/{incident_id}/resolve",
        json={"causa_raiz": "token expirado"},
    )
    assert resolvido.status_code == 200
    assert resolvido.json()["status"] == "resolvido"
    assert resolvido.json()["causa_raiz"] == "token expirado"

    # resolver de novo é recusado (409) — decisão final
    resposta_dupla = client.post(
        f"/v1/orchestrations/{oid}/incidents/{incident_id}/resolve",
        json={"causa_raiz": "outra causa"},
    )
    assert resposta_dupla.status_code == 409


def test_resolver_sem_causa_raiz_devolve_409(tmp_path: Path) -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid = _orch_pronta(svc, tmp_path, risco=RiskLevel.LOW)
    client.put(f"/v1/orchestrations/{oid}/deploy/config", json={"command": "bash -c 'exit 0'"})
    client.post(f"/v1/orchestrations/{oid}/deploy/run", json={})
    client.post(f"/v1/orchestrations/{oid}/deploy/rollback", json={"reason": "erro grave"})
    incident_id = client.get(f"/v1/orchestrations/{oid}/incidents").json()[0]["id"]

    resposta = client.post(
        f"/v1/orchestrations/{oid}/incidents/{incident_id}/resolve", json={"causa_raiz": "  "}
    )
    assert resposta.status_code == 409


def test_get_deploy_history_traz_o_ring(tmp_path: Path) -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid = _orch_pronta(svc, tmp_path, risco=RiskLevel.LOW)
    client.put(f"/v1/orchestrations/{oid}/deploy/config", json={"command": "bash -c 'exit 0'"})
    client.post(f"/v1/orchestrations/{oid}/deploy/run", json={})
    client.post(f"/v1/orchestrations/{oid}/deploy/run", json={})

    historico = client.get(f"/v1/orchestrations/{oid}/deploy/history").json()
    assert len(historico) == 2
    assert historico[0]["versao"] == 1
    assert historico[1]["versao"] == 2


# ------------------------------------------------------ pipeline (§19, ADR-0029)

_PIPELINE_BODY = {
    "estagios": [
        {"chave": "desenvolvimento", "nome": "Dev", "ordem": 1, "comando": "true"},
        {"chave": "testes", "nome": "Testes", "ordem": 2, "comando": "true"},
        {
            "chave": "producao",
            "nome": "Produção",
            "ordem": 3,
            "comando": "true",
            "requer_aprovacao_humana": True,
        },
    ]
}


def test_get_deploy_pipeline_vazio_por_padrao(tmp_path: Path) -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid = _orch_pronta(svc, tmp_path, risco=RiskLevel.LOW)
    assert client.get(f"/v1/orchestrations/{oid}/deploy/pipeline").json() == []


def test_put_deploy_pipeline_valida_comando_de_cada_estagio(tmp_path: Path) -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid = _orch_pronta(svc, tmp_path, risco=RiskLevel.LOW)
    resposta = client.put(
        f"/v1/orchestrations/{oid}/deploy/pipeline",
        json={"estagios": [{"chave": "dev", "ordem": 1, "comando": "npm run dev"}]},
    )
    assert resposta.status_code == 400


def test_put_deploy_pipeline_recusa_chave_repetida(tmp_path: Path) -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid = _orch_pronta(svc, tmp_path, risco=RiskLevel.LOW)
    resposta = client.put(
        f"/v1/orchestrations/{oid}/deploy/pipeline",
        json={
            "estagios": [
                {"chave": "dev", "ordem": 1},
                {"chave": "dev", "ordem": 2},
            ]
        },
    )
    assert resposta.status_code == 409


def test_fluxo_completo_pipeline_avanca_estagio_a_estagio_e_libera_gate(
    tmp_path: Path,
) -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid = _orch_pronta(svc, tmp_path, risco=RiskLevel.LOW)

    configurado = client.put(f"/v1/orchestrations/{oid}/deploy/pipeline", json=_PIPELINE_BODY)
    assert configurado.status_code == 200

    # Pular direto para produção é recusado — avanço governado (§19).
    pulou = client.post(f"/v1/orchestrations/{oid}/deploy/run", json={"estagio": "producao"})
    assert pulou.status_code == 409

    dev = client.post(f"/v1/orchestrations/{oid}/deploy/run", json={})
    assert dev.status_code == 200
    assert dev.json()["estagio"] == "desenvolvimento"

    testes = client.post(f"/v1/orchestrations/{oid}/deploy/run", json={})
    assert testes.json()["estagio"] == "testes"

    producao = client.post(f"/v1/orchestrations/{oid}/deploy/run", json={})
    assert producao.json()["estagio"] == "producao"
    assert producao.json()["aceite_status"] == "aguardando_aprovacao"

    gate_antes = client.post(f"/v1/orchestrations/{oid}/quality-gates/run", json={"phase": "F6"})
    assert "deploy_aprovado" in gate_antes.json()["blocking_issues"]

    status = client.get(f"/v1/orchestrations/{oid}/deploy/pipeline").json()
    assert [s["status"] for s in status] == ["sucesso", "sucesso", "sucesso"]
    assert [s["concluido"] for s in status] == [True, True, False]

    aprovado = client.post(f"/v1/orchestrations/{oid}/deploy/approve", json={"approved": True})
    assert aprovado.status_code == 200

    gate_depois = client.post(f"/v1/orchestrations/{oid}/quality-gates/run", json={"phase": "F6"})
    assert gate_depois.json()["status"] == "PASSED"


def test_run_deploy_com_estagio_falho_classifica_e_expoe_proxima_acao(
    tmp_path: Path,
) -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid = _orch_pronta(svc, tmp_path, risco=RiskLevel.LOW)
    client.put(
        f"/v1/orchestrations/{oid}/deploy/pipeline",
        json={"estagios": [{"chave": "dev", "ordem": 1, "comando": "npm run build"}]},
    )
    resposta = client.post(f"/v1/orchestrations/{oid}/deploy/run", json={})
    corpo = resposta.json()
    assert corpo["status"] == "falhou"
    assert corpo["diagnostico_falha"] == "build"
    assert corpo["proxima_acao_falha"]


def test_rbac_put_pipeline_exige_operator_get_aberto_a_viewer(tmp_path: Path) -> None:
    svc = OrchestrationService()
    auth = AuthService(
        {
            "v": Principal(actor="viewer", role="viewer"),
            "o": Principal(actor="op", role="operator"),
        },
        dev_mode=False,
    )
    client = TestClient(create_app(svc, auth=auth))
    oid = _orch_pronta(svc, tmp_path, risco=RiskLevel.LOW)

    h_viewer = {"Authorization": "Bearer v"}
    h_operator = {"Authorization": "Bearer o"}
    get_ok = client.get(f"/v1/orchestrations/{oid}/deploy/pipeline", headers=h_viewer)
    assert get_ok.status_code == 200
    assert (
        client.put(
            f"/v1/orchestrations/{oid}/deploy/pipeline", json=_PIPELINE_BODY, headers=h_viewer
        ).status_code
        == 403
    )
    assert (
        client.put(
            f"/v1/orchestrations/{oid}/deploy/pipeline", json=_PIPELINE_BODY, headers=h_operator
        ).status_code
        == 200
    )
