"""Implantação governada via `OrchestrationService` (§18-22, ADR-0023).

Cobre: pré-condições de `run_deploy` (§18), decisão auto-vs-humana após a
execução (§19/§22), validação pós-implantação revertendo um aceite automático
(§20), decisão humana (§22), rollback abrindo um card de incidente (§21) e a
não-regressão do critério novo do gate de F6.
"""

from __future__ import annotations

import pytest

from aso.control.deploy import (
    ACEITE_AGUARDANDO_HUMANO,
    ACEITE_APROVADO,
    ACEITE_REPROVADO,
    STATUS_FALHOU,
    STATUS_REVERTIDO,
    STATUS_SUCESSO,
    VALIDACAO_REPROVADA,
)
from aso.control.models import ValidationCheck
from aso.control.orchestration_service import OrchestrationService
from aso.control.triage import DemandBrief
from aso.shared.types import CardType, ColumnKey, Phase, RiskLevel


def _orch_pronta(
    svc: OrchestrationService, tmp_path: object, *, risco: RiskLevel = RiskLevel.LOW
) -> str:
    """Orquestração com pasta + gate mais recente PASSED (§18: "testes aprovados")."""
    orch = svc.create_orchestration(
        "ajustar cálculo de frete",
        target_path=str(tmp_path),
        seed_cards=False,
        demand_brief=DemandBrief(risco=risco),
    )
    svc.run_quality_gate(orch.id, Phase.F5)  # vacuamente PASSED (sem cards)
    return orch.id


# --------------------------------------------------------------- run_deploy


def test_run_deploy_sem_comando_configurado_recusa(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = OrchestrationService()
    oid = _orch_pronta(svc, tmp_path)
    with pytest.raises(ValueError, match="Configure o comando"):
        svc.run_deploy(oid)


def test_run_deploy_sem_gate_passado_recusa(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = OrchestrationService()
    orch = svc.create_orchestration(
        "ajustar cálculo de frete", target_path=str(tmp_path), seed_cards=False
    )
    svc.set_deploy_config(orch.id, command="bash -c 'exit 0'")
    with pytest.raises(ValueError, match="Quality gate"):
        svc.run_deploy(orch.id)


def test_run_deploy_que_falha_reprova_direto_sem_humano(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = OrchestrationService()
    oid = _orch_pronta(svc, tmp_path, risco=RiskLevel.LOW)
    svc.set_deploy_config(oid, command="bash -c 'exit 1'")
    deploy = svc.run_deploy(oid)
    assert deploy.status == STATUS_FALHOU
    assert deploy.aceite_status == ACEITE_REPROVADO


def test_run_deploy_sucesso_risco_baixo_aceita_automatico(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = OrchestrationService()
    oid = _orch_pronta(svc, tmp_path, risco=RiskLevel.LOW)
    svc.set_deploy_config(oid, command="bash -c 'exit 0'")
    deploy = svc.run_deploy(oid)
    assert deploy.status == STATUS_SUCESSO
    assert deploy.aceite_status == ACEITE_APROVADO
    assert deploy.origem_decisao == "automatico"


def test_run_deploy_sucesso_risco_alto_aguarda_humano(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = OrchestrationService()
    oid = _orch_pronta(svc, tmp_path, risco=RiskLevel.HIGH)
    svc.set_deploy_config(oid, command="bash -c 'exit 0'")
    deploy = svc.run_deploy(oid)
    assert deploy.status == STATUS_SUCESSO
    assert deploy.aceite_status == ACEITE_AGUARDANDO_HUMANO


def test_run_deploy_versiona_no_ring(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = OrchestrationService()
    oid = _orch_pronta(svc, tmp_path)
    svc.set_deploy_config(oid, command="bash -c 'exit 0'")
    d1 = svc.run_deploy(oid)
    d2 = svc.run_deploy(oid)
    assert d1.versao == 1
    assert d2.versao == 2
    assert len(svc.get_deploy_history(oid)) == 2


def test_set_deploy_config_recusa_comando_continuo(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from aso.execution.gate_validation import GateCommandError

    svc = OrchestrationService()
    orch = svc.create_orchestration(
        "ajustar cálculo de frete", target_path=str(tmp_path), seed_cards=False
    )
    with pytest.raises(GateCommandError):
        svc.set_deploy_config(orch.id, command="npm run dev")


# ------------------------------------------------------------- validate_deploy


def test_validate_deploy_sem_deploy_runs_levanta(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = OrchestrationService()
    orch = svc.create_orchestration(
        "ajustar cálculo de frete", target_path=str(tmp_path), seed_cards=False
    )
    with pytest.raises(KeyError):
        svc.validate_deploy(orch.id)


def test_validate_deploy_reprovada_reabre_aceite_automatico(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = OrchestrationService()
    oid = _orch_pronta(svc, tmp_path, risco=RiskLevel.LOW)
    svc.set_deploy_config(
        oid,
        command="bash -c 'exit 0'",
        health_checks=[ValidationCheck(nome="health", comando="bash -c 'exit 1'", bloqueante=True)],
    )
    deploy = svc.run_deploy(oid)
    assert deploy.aceite_status == ACEITE_APROVADO  # automático, sem validação ainda
    validado = svc.validate_deploy(oid)
    assert validado.validacao_status == VALIDACAO_REPROVADA
    assert validado.aceite_status == ACEITE_AGUARDANDO_HUMANO


# --------------------------------------------------------------- decide_deploy


def test_decide_deploy_fora_de_aguardando_aprovacao_levanta(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = OrchestrationService()
    oid = _orch_pronta(svc, tmp_path, risco=RiskLevel.LOW)
    svc.set_deploy_config(oid, command="bash -c 'exit 0'")
    svc.run_deploy(oid)  # aceite automático — não está aguardando
    with pytest.raises(ValueError, match="não está aguardando"):
        svc.decide_deploy(oid, approved=True)


def test_decide_deploy_aprova(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = OrchestrationService()
    oid = _orch_pronta(svc, tmp_path, risco=RiskLevel.HIGH)
    svc.set_deploy_config(oid, command="bash -c 'exit 0'")
    svc.run_deploy(oid)
    decidido = svc.decide_deploy(oid, approved=True, comentario="ok, aprovado manualmente")
    assert decidido.aceite_status == ACEITE_APROVADO
    assert decidido.origem_decisao == "humano"


# ------------------------------------------------------------- rollback_deploy


def test_rollback_deploy_cria_card_de_incidente(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = OrchestrationService()
    oid = _orch_pronta(svc, tmp_path, risco=RiskLevel.LOW)
    svc.set_deploy_config(oid, command="bash -c 'exit 0'")
    svc.run_deploy(oid)
    revertido = svc.rollback_deploy(oid, reason="erro grave em produção")
    assert revertido.status == STATUS_REVERTIDO
    cards = svc.get_cards(oid)
    incidentes = [c for c in cards if c.type == CardType.INCIDENT]
    assert len(incidentes) == 1
    assert incidentes[0].status == ColumnKey.BACKLOG
    assert "erro grave" in incidentes[0].description


def test_rollback_deploy_ja_revertido_levanta(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = OrchestrationService()
    oid = _orch_pronta(svc, tmp_path, risco=RiskLevel.LOW)
    svc.set_deploy_config(oid, command="bash -c 'exit 0'")
    svc.run_deploy(oid)
    svc.rollback_deploy(oid, reason="primeiro rollback")
    with pytest.raises(ValueError, match="já revertida"):
        svc.rollback_deploy(oid, reason="segundo rollback")


# -------------------------------------------------------------- gate de F6


def test_gate_f6_sem_deploy_runs_nao_ganha_criterio_novo(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Não-regressão: orquestração que nunca chamou /deploy/run não muda de
    comportamento no gate de F6."""
    svc = OrchestrationService()
    orch = svc.create_orchestration(
        "ajustar cálculo de frete", target_path=str(tmp_path), seed_cards=False
    )
    resultado = svc.run_quality_gate(orch.id, Phase.F6)
    assert "deploy_aprovado" not in {c.name for c in resultado.criteria}
    assert resultado.status.value == "PASSED"


def test_gate_f6_com_deploy_aprovado_ganha_criterio_passando(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = OrchestrationService()
    oid = _orch_pronta(svc, tmp_path, risco=RiskLevel.LOW)
    svc.set_deploy_config(oid, command="bash -c 'exit 0'")
    svc.run_deploy(oid)
    resultado = svc.run_quality_gate(oid, Phase.F6)
    por_nome = {c.name: c for c in resultado.criteria}
    assert por_nome["deploy_aprovado"].status.value == "PASSED"


def test_gate_f6_com_deploy_aguardando_aprovacao_reprova(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = OrchestrationService()
    oid = _orch_pronta(svc, tmp_path, risco=RiskLevel.HIGH)
    svc.set_deploy_config(oid, command="bash -c 'exit 0'")
    svc.run_deploy(oid)
    resultado = svc.run_quality_gate(oid, Phase.F6)
    assert "deploy_aprovado" in resultado.blocking_issues
