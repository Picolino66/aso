"""Incident como entidade de primeira classe (§21 do fluxo.md, wf §27/§38) — ADR-0032.

Cobre: criação automática vinculada ao rollback (gravidade derivada do risco,
snapshot do deploy, timeline inicial), transições investigar/resolver, guardas de
estado terminal e listagem/detalhe.
"""

from __future__ import annotations

import pytest

from aso.control.deploy import STATUS_REVERTIDO
from aso.control.orchestration_service import OrchestrationService
from aso.control.triage import DemandBrief
from aso.shared.types import CardType, RiskLevel


def _orch_pronta(svc: OrchestrationService, tmp_path: object, *, risco: RiskLevel) -> str:
    from aso.shared.types import Phase

    orch = svc.create_orchestration(
        "ajustar cálculo de frete",
        target_path=str(tmp_path),
        seed_cards=False,
        demand_brief=DemandBrief(risco=risco),
    )
    svc.run_quality_gate(orch.id, Phase.F5)
    return orch.id


def _orch_com_rollback(
    svc: OrchestrationService, tmp_path: object, *, risco: RiskLevel = RiskLevel.LOW
) -> tuple[str, str]:
    oid = _orch_pronta(svc, tmp_path, risco=risco)
    svc.set_deploy_config(oid, command="bash -c 'exit 0'")
    svc.run_deploy(oid)
    svc.rollback_deploy(oid, reason="erro grave em produção")
    incidente = svc.list_incidents(oid)[0]
    return oid, incidente.id


# ------------------------------------------------------------------------ criação


def test_rollback_cria_incidente_vinculado_ao_card(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = OrchestrationService()
    oid, incident_id = _orch_com_rollback(svc, tmp_path)
    incidente = svc.get_incident(oid, incident_id)
    assert incidente is not None
    cards = svc.get_cards(oid)
    card_incidente = next(c for c in cards if c.type == CardType.INCIDENT)
    assert incidente.card_id == card_incidente.id


def test_gravidade_derivada_do_risco_da_demanda(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = OrchestrationService()
    _oid, incident_id = _orch_com_rollback(svc, tmp_path, risco=RiskLevel.CRITICAL)
    incidente = svc.get_incident(_oid, incident_id)
    assert incidente is not None
    assert incidente.gravidade == "critica"


def test_gravidade_padrao_media_sem_ficha_triada(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = OrchestrationService()
    _oid, incident_id = _orch_com_rollback(svc, tmp_path, risco=RiskLevel.LOW)
    incidente = svc.get_incident(_oid, incident_id)
    assert incidente is not None
    assert incidente.gravidade == "media"


def test_incidente_registra_snapshot_do_deploy(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = OrchestrationService()
    oid, incident_id = _orch_com_rollback(svc, tmp_path)
    incidente = svc.get_incident(oid, incident_id)
    assert incidente is not None
    assert incidente.deploy_ambiente == "producao"
    assert incidente.deploy_versao == 1


def test_incidente_nasce_aberto_com_timeline_inicial(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = OrchestrationService()
    oid, incident_id = _orch_com_rollback(svc, tmp_path)
    incidente = svc.get_incident(oid, incident_id)
    assert incidente is not None
    assert incidente.status == "aberto"
    assert [e["evento"] for e in incidente.timeline] == ["aberto"]


def test_rollback_continua_criando_o_card_exatamente_como_antes(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Regressão: `rollback_deploy` não muda o comportamento do card — só ACRESCENTA
    o `Incident` vinculado."""
    svc = OrchestrationService()
    oid = _orch_pronta(svc, tmp_path, risco=RiskLevel.LOW)
    svc.set_deploy_config(oid, command="bash -c 'exit 0'")
    svc.run_deploy(oid)
    revertido = svc.rollback_deploy(oid, reason="erro grave em produção")
    assert revertido.status == STATUS_REVERTIDO
    cards = svc.get_cards(oid)
    incidentes_card = [c for c in cards if c.type == CardType.INCIDENT]
    assert len(incidentes_card) == 1
    assert "erro grave" in incidentes_card[0].description


# --------------------------------------------------------------------- transições


def test_investigate_incident_muda_status_e_acrescenta_timeline(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = OrchestrationService()
    oid, incident_id = _orch_com_rollback(svc, tmp_path)
    atualizado = svc.investigate_incident(
        oid, incident_id, detalhe="checando renovação de token", actor="op"
    )
    assert atualizado.status == "investigando"
    assert [e["evento"] for e in atualizado.timeline] == ["aberto", "investigando"]
    assert atualizado.timeline[-1]["actor"] == "op"


def test_resolve_incident_grava_causa_raiz_e_fecha(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = OrchestrationService()
    oid, incident_id = _orch_com_rollback(svc, tmp_path)
    resolvido = svc.resolve_incident(
        oid, incident_id, causa_raiz="token expirado não renovado", actor="op"
    )
    assert resolvido.status == "resolvido"
    assert resolvido.causa_raiz == "token expirado não renovado"
    assert resolvido.resolved_at is not None
    assert [e["evento"] for e in resolvido.timeline] == ["aberto", "resolvido"]


def test_resolve_incident_recusa_causa_raiz_vazia(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = OrchestrationService()
    oid, incident_id = _orch_com_rollback(svc, tmp_path)
    with pytest.raises(ValueError, match="causa raiz"):
        svc.resolve_incident(oid, incident_id, causa_raiz="   ", actor="op")


def test_resolve_incident_ja_resolvido_recusa(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = OrchestrationService()
    oid, incident_id = _orch_com_rollback(svc, tmp_path)
    svc.resolve_incident(oid, incident_id, causa_raiz="causa raiz identificada")
    with pytest.raises(ValueError, match="já resolvido"):
        svc.resolve_incident(oid, incident_id, causa_raiz="outra causa")


def test_investigate_incident_ja_resolvido_recusa(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = OrchestrationService()
    oid, incident_id = _orch_com_rollback(svc, tmp_path)
    svc.resolve_incident(oid, incident_id, causa_raiz="causa raiz identificada")
    with pytest.raises(ValueError, match="já resolvido"):
        svc.investigate_incident(oid, incident_id)


def test_investigate_e_resolve_incidente_inexistente_levanta_keyerror(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = OrchestrationService()
    oid = _orch_pronta(svc, tmp_path, risco=RiskLevel.LOW)
    with pytest.raises(KeyError):
        svc.investigate_incident(oid, "incident_inexistente")
    with pytest.raises(KeyError):
        svc.resolve_incident(oid, "incident_inexistente", causa_raiz="x")


# ------------------------------------------------------------------------ listagem


def test_list_incidents_vazio_sem_rollback(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = OrchestrationService()
    oid = _orch_pronta(svc, tmp_path, risco=RiskLevel.LOW)
    assert svc.list_incidents(oid) == []


def test_get_incident_inexistente_devolve_none(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = OrchestrationService()
    oid = _orch_pronta(svc, tmp_path, risco=RiskLevel.LOW)
    assert svc.get_incident(oid, "incident_inexistente") is None


def test_multiplos_rollbacks_em_orquestracoes_diferentes_nao_se_misturam(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = OrchestrationService()
    oid1, _ = _orch_com_rollback(svc, tmp_path)
    oid2 = _orch_pronta(svc, tmp_path, risco=RiskLevel.LOW)
    assert len(svc.list_incidents(oid1)) == 1
    assert svc.list_incidents(oid2) == []
