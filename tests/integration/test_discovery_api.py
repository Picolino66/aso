"""Discovery e aprovação pela API (§3/§4 do fluxo.md, ADR-0020)."""

from __future__ import annotations

import shlex
from pathlib import Path

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.api.auth import AuthService, Principal
from aso.control.orchestration_service import OrchestrationService
from aso.control.triage import DemandBrief
from aso.execution.catalog import ExecutorCatalog, ExecutorProfile
from aso.shared.types import RiskLevel


def _orch(
    svc: OrchestrationService,
    tmp_path: Path,
    *,
    risco: RiskLevel = RiskLevel.LOW,
    executor: str | None = None,
) -> str:
    orch = svc.create_orchestration(
        "ajustar cálculo de frete",
        target_path=str(tmp_path),
        executor=executor,
        demand_brief=DemandBrief(problema="frete errado", risco=risco),
    )
    return orch.id


def _catalogo_confiante() -> ExecutorCatalog:
    """Agente de discovery fake que sempre responde com `confianca: alta`."""
    bruto = (
        '{"problema": "frete calculado errado", '
        '"recomendacao_tecnica": "corrigir a fórmula", "confianca": "alta"}'
    )
    script = 'cat > /dev/null; printf %s "$1"; exit 0'
    comando = shlex.join(["bash", "-c", script, "_", bruto])
    return ExecutorCatalog([ExecutorProfile(name="discoverer", kind="cli", command=comando)])


def test_run_sem_target_path_devolve_409() -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    orch = svc.create_orchestration("demanda sem pasta")

    resposta = client.post(f"/v1/orchestrations/{orch.id}/discovery/run", json={})
    assert resposta.status_code == 409


def test_risco_baixo_aprova_automaticamente_e_libera_o_gate_de_f1(tmp_path: Path) -> None:
    """Aprovação automática exige confiança alta — só um agente de verdade produz
    isto (a heurística sem agente é sempre `confianca=baixa`, ver test_discovery.py)."""
    svc = OrchestrationService(catalog=_catalogo_confiante())
    client = TestClient(create_app(svc))
    oid = _orch(svc, tmp_path, risco=RiskLevel.LOW)

    resposta = client.post(f"/v1/orchestrations/{oid}/discovery/run", json={})
    assert resposta.status_code == 200
    assert resposta.json()["discovery_reports"][-1]["status"] == "aprovado"

    gate = client.post(f"/v1/orchestrations/{oid}/quality-gates/run", json={"phase": "F1"})
    assert gate.json()["status"] == "PASSED"


def test_risco_alto_fica_aguardando_aprovacao_e_bloqueia_o_gate(tmp_path: Path) -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid = _orch(svc, tmp_path, risco=RiskLevel.HIGH)

    resposta = client.post(f"/v1/orchestrations/{oid}/discovery/run", json={})
    assert resposta.json()["discovery_reports"][-1]["status"] == "aguardando_aprovacao"

    gate = client.post(f"/v1/orchestrations/{oid}/quality-gates/run", json={"phase": "F1"})
    assert gate.json()["status"] == "FAILED"
    criterios = {c["name"]: c["status"] for c in gate.json()["criteria"]}
    assert criterios["discovery_aprovado"] == "FAILED"


def test_decide_sem_admin_devolve_403(tmp_path: Path) -> None:
    auth = AuthService(
        {
            "o": Principal(actor="op", role="operator"),
            "a": Principal(actor="adm", role="admin"),
        },
        dev_mode=False,
    )
    svc = OrchestrationService()
    client = TestClient(create_app(svc, auth=auth))
    oid = _orch(svc, tmp_path, risco=RiskLevel.HIGH)
    client.post(
        f"/v1/orchestrations/{oid}/discovery/run", json={}, headers={"Authorization": "Bearer a"}
    )

    resposta = client.post(
        f"/v1/orchestrations/{oid}/discovery/decide",
        json={"approved": True},
        headers={"Authorization": "Bearer o"},
    )
    assert resposta.status_code == 403


def test_aprovar_libera_o_gate(tmp_path: Path) -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid = _orch(svc, tmp_path, risco=RiskLevel.HIGH)
    client.post(f"/v1/orchestrations/{oid}/discovery/run", json={})

    decidido = client.post(f"/v1/orchestrations/{oid}/discovery/decide", json={"approved": True})
    assert decidido.status_code == 200
    assert decidido.json()["discovery_reports"][-1]["status"] == "aprovado"

    gate = client.post(f"/v1/orchestrations/{oid}/quality-gates/run", json={"phase": "F1"})
    assert gate.json()["status"] == "PASSED"


def test_reprovar_com_comentario_e_rodar_de_novo_gera_novo_relatorio(tmp_path: Path) -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid = _orch(svc, tmp_path, risco=RiskLevel.HIGH)
    client.post(f"/v1/orchestrations/{oid}/discovery/run", json={})

    reprovado = client.post(
        f"/v1/orchestrations/{oid}/discovery/decide",
        json={"approved": False, "comentario": "faltou avaliar o cache"},
    )
    ultimo = reprovado.json()["discovery_reports"][-1]
    assert ultimo["status"] == "reprovado"
    assert ultimo["revisao_comentarios"] == "faltou avaliar o cache"

    # Decidir de novo sem estar aguardando aprovação recusa (409).
    recusado = client.post(f"/v1/orchestrations/{oid}/discovery/decide", json={"approved": True})
    assert recusado.status_code == 409

    novo = client.post(f"/v1/orchestrations/{oid}/discovery/run", json={})
    assert novo.status_code == 200
    # Sem agente configurado, a heurística sempre reprova de novo (confiança baixa) —
    # mas é um relatório NOVO, não o antigo reaproveitado.
    assert novo.json()["discovery_reports"][-1]["status"] == "aguardando_aprovacao"


def test_get_discovery_vazio_antes_de_rodar(tmp_path: Path) -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid = _orch(svc, tmp_path)

    resposta = client.get(f"/v1/orchestrations/{oid}/discovery")
    assert resposta.status_code == 200
    assert resposta.json()["status"] == "rascunho"


# --------------------------------------------- painel de execução e checklist (ADR-0045)


def test_run_discovery_devolve_painel_de_execucao_real(tmp_path: Path) -> None:
    svc = OrchestrationService(catalog=_catalogo_confiante())
    client = TestClient(create_app(svc))
    oid = _orch(svc, tmp_path, risco=RiskLevel.LOW)

    client.post(f"/v1/orchestrations/{oid}/discovery/run", json={})
    relatorio = client.get(f"/v1/orchestrations/{oid}/discovery").json()

    assert relatorio["started_at"] is not None
    assert relatorio["finished_at"] is not None
    assert relatorio["duration_ms"] >= 0
    assert len(relatorio["log"]) == 2


def test_approval_criteria_devolve_os_sete_rotulos_e_motivos_reais(tmp_path: Path) -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid = _orch(svc, tmp_path, risco=RiskLevel.CRITICAL)
    client.post(f"/v1/orchestrations/{oid}/discovery/run", json={})

    resposta = client.get(f"/v1/orchestrations/{oid}/discovery/approval-criteria")
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert len(corpo["criterios"]) == 7
    assert corpo["aprovacao_automatica"] is False
    assert any("Risco da demanda" in m for m in corpo["motivos_escalada"])


def test_approval_criteria_orquestracao_inexistente_devolve_404() -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    resposta = client.get("/v1/orchestrations/orch_fantasma/discovery/approval-criteria")
    assert resposta.status_code == 404
