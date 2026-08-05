"""Bateria de validações pela API (§12 do fluxo.md, ADR-0022)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService
from aso.shared.types import Phase


def _orch(svc: OrchestrationService, tmp_path: Path) -> str:
    orch = svc.create_orchestration(
        "ajustar cálculo de frete", target_path=str(tmp_path), seed_cards=False
    )
    return orch.id


def test_put_bateria_e_gate_reprova_nomeando_a_verificacao(tmp_path: Path) -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid = _orch(svc, tmp_path)

    resposta = client.put(
        f"/v1/orchestrations/{oid}/validation-checks",
        json={
            "checks": [
                {"nome": "lint", "comando": "bash -c 'exit 1'", "categoria": "lint"},
                {"nome": "testes", "comando": "bash -c 'exit 0'", "categoria": "testes"},
            ]
        },
    )
    assert resposta.status_code == 200
    assert [c["nome"] for c in resposta.json()["validation_checks"]] == ["lint", "testes"]

    gate = client.post(f"/v1/orchestrations/{oid}/quality-gates/run", json={"phase": "F5"})
    assert gate.status_code == 200
    corpo = gate.json()
    assert corpo["status"] == "FAILED"
    assert "lint" in corpo["blocking_issues"]
    por_nome = {c["name"]: c for c in corpo["criteria"]}
    assert por_nome["lint"]["status"] == "FAILED"
    assert por_nome["testes"]["status"] == "PASSED"


def test_put_com_comando_continuo_e_recusado(tmp_path: Path) -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid = _orch(svc, tmp_path)

    resposta = client.put(
        f"/v1/orchestrations/{oid}/validation-checks",
        json={"checks": [{"nome": "dev", "comando": "npm run dev"}]},
    )
    assert resposta.status_code == 400
    assert client.get(f"/v1/orchestrations/{oid}/validation-checks").json() == []


def test_get_suggest_nao_altera_a_orquestracao(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid = _orch(svc, tmp_path)

    sugestao = client.get(f"/v1/orchestrations/{oid}/validation-checks/suggest")
    assert sugestao.status_code == 200
    assert {c["nome"] for c in sugestao.json()} == {"lint", "formatacao", "tipos", "testes"}
    # Nada foi gravado — a bateria efetiva continua vazia.
    assert client.get(f"/v1/orchestrations/{oid}/validation-checks").json() == []


def test_card_que_falha_no_lint_e_roteado_como_falha_trivial_sem_subir_effort(
    tmp_path: Path,
) -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    orch = svc.create_orchestration("ajustar cálculo de frete", target_path=str(tmp_path))
    oid = orch.id
    card = svc.get_cards(oid)[0]
    svc.run_card(oid, card.id)  # sai de Ready, produz output do mock

    client.put(
        f"/v1/orchestrations/{oid}/validation-checks",
        json={"checks": [{"nome": "lint", "comando": "bash -c 'exit 1'", "categoria": "lint"}]},
    )
    gate = svc.run_quality_gate(oid, Phase.F5)
    assert gate.status.value == "FAILED"

    resposta = client.post(f"/v1/orchestrations/{oid}/retry")
    assert resposta.status_code == 200

    atualizado = svc.get_cards(oid)[0]
    ultima_falha = atualizado.failures[-1]
    assert ultima_falha["check"] == "lint"
    assert ultima_falha["categoria"] == "lint"
    # falha_trivial nunca sobe effort na 1ª tentativa — a etapa não ganhou
    # atribuição nova de effort por causa desta falha.
    depois = svc.get(oid)
    assignment = depois.agent_assignments.get("F5")
    assert assignment is None or assignment.effort is None


def test_orquestracao_antiga_so_com_validation_command_continua_funcionando(
    tmp_path: Path,
) -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    orch = svc.create_orchestration(
        "ajustar cálculo de frete",
        target_path=str(tmp_path),
        validation_command="bash -c 'exit 0'",
        seed_cards=False,
    )
    # Nunca chamou PUT .../validation-checks — a bateria efetiva é o legado.
    checks = client.get(f"/v1/orchestrations/{orch.id}/validation-checks").json()
    assert [c["nome"] for c in checks] == ["testes"]

    gate = client.post(f"/v1/orchestrations/{orch.id}/quality-gates/run", json={"phase": "F5"})
    assert gate.status_code == 200
    assert gate.json()["status"] == "PASSED"
