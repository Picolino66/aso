"""Indicadores e atividade global do Dashboard (wf §3.3, Tela 01) — ADR-0037."""

from __future__ import annotations

from aso.control.orchestration_service import OrchestrationService


def test_dashboard_summary_global_vazio() -> None:
    svc = OrchestrationService()
    resumo = svc.dashboard_summary()
    assert resumo == {
        "demandas_ativas": 0,
        "em_execucao": 0,
        "bloqueadas": 0,
        "falhas_abertas": 0,
        "cards_por_status": {},
        "aprovacoes_por_tipo": {},
    }


def test_demandas_ativas_exclui_concluidas_e_canceladas() -> None:
    svc = OrchestrationService()
    orch1 = svc.create_orchestration("ativa")
    orch2 = svc.create_orchestration("cancelada")
    svc.cancel(orch2.id)
    resumo = svc.dashboard_summary()
    assert resumo["demandas_ativas"] == 1
    assert orch1.id  # orquestração ativa contada


def test_bloqueadas_reaproveita_status_waiting_human() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("aguardando decisão")
    b = svc._bundle(orch.id)  # noqa: SLF001
    b.orchestration.status = "waiting_human"
    svc._persist(b)  # noqa: SLF001
    resumo = svc.dashboard_summary()
    assert resumo["bloqueadas"] == 1
    assert resumo["demandas_ativas"] == 1


def test_aprovacoes_por_tipo_agrupa_pelos_tres_tipos_reais() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("demanda com aprovações")
    svc.request_approval(orch.id, "ação manual via API")
    resumo = svc.dashboard_summary()
    assert resumo["aprovacoes_por_tipo"] == {"manual": 1}


def test_dashboard_summary_escopado_por_projeto(tmp_path: object) -> None:
    svc = OrchestrationService()
    projeto = svc.create_project(
        name="Projeto Dash", description="", target_path=str(tmp_path), actor="op"
    )
    svc.create_orchestration("dentro", project_id=projeto.id)
    svc.create_orchestration("fora")
    resumo = svc.dashboard_summary(project_id=projeto.id)
    assert resumo["demandas_ativas"] == 1


def test_falhas_abertas_reflete_cards_por_status_failed() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("demanda com falha")
    card = svc.get_cards(orch.id)[0]
    svc.move_card(orch.id, card.id, "Failed")
    resumo = svc.dashboard_summary()
    assert resumo["falhas_abertas"] == 1
    assert resumo["cards_por_status"]["Failed"] == 1


def test_recent_activity_vazio_sem_orquestracoes() -> None:
    svc = OrchestrationService()
    assert svc.recent_activity() == []


def test_recent_activity_devolve_tipo_ator_e_horario() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("demanda com atividade")
    atividades = svc.recent_activity(limit=5)
    assert atividades
    assert atividades[0]["orchestration_id"] == orch.id
    assert atividades[0]["tipo"]
    assert atividades[0]["ator"]
    assert atividades[0]["at"]


def test_recent_activity_respeita_limite() -> None:
    svc = OrchestrationService()
    for i in range(5):
        svc.create_orchestration(f"demanda {i}")
    atividades = svc.recent_activity(limit=3)
    assert len(atividades) == 3


def test_recent_activity_ordena_por_mais_recente_primeiro() -> None:
    svc = OrchestrationService()
    svc.create_orchestration("primeira")
    svc.create_orchestration("segunda")
    atividades = svc.recent_activity(limit=100)
    horarios = [str(a["at"]) for a in atividades]
    assert horarios == sorted(horarios, reverse=True)
