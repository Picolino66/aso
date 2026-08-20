"""Indicadores e busca do header (wf §2.3) — ADR-0035."""

from __future__ import annotations

from aso.control.orchestration_service import OrchestrationService


def test_header_summary_global_sem_project_id() -> None:
    svc = OrchestrationService()
    svc.create_orchestration("demanda um")
    svc.create_orchestration("demanda dois")
    resumo = svc.header_summary()
    assert resumo["execucoes_ativas"] == 0
    assert resumo["falhas"] == 0
    assert resumo["aprovacoes_pendentes"] == 0


def test_header_summary_escopado_por_projeto(tmp_path: object) -> None:
    svc = OrchestrationService()
    projeto = svc.create_project(
        name="Projeto A", description="", target_path=str(tmp_path), actor="op"
    )
    dentro = svc.create_orchestration("demanda do projeto", project_id=projeto.id)
    svc.create_orchestration("demanda fora do projeto")

    resumo_projeto = svc.header_summary(project_id=projeto.id)

    assert resumo_projeto["execucoes_ativas"] == 0
    # Confirma o escopo: uma orquestração só conta se pertence ao projeto.
    assert dentro.project_id == projeto.id


def test_header_summary_conta_aprovacoes_pendentes() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("demanda com aprovação")
    svc.request_approval(orch.id, action="deploy", reason="risco alto")
    resumo = svc.header_summary()
    assert resumo["aprovacoes_pendentes"] == 1


def test_search_encontra_demanda_card_e_documento() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("implementar cálculo de frete internacional")
    resultados = svc.search("frete")
    tipos = {r.tipo for r in resultados}
    assert "demanda" in tipos
    assert all(r.orchestration_id == orch.id for r in resultados if r.tipo == "demanda")


def test_search_escopada_por_projeto_nao_traz_de_outro_projeto(tmp_path: object) -> None:
    svc = OrchestrationService()
    projeto = svc.create_project(
        name="Projeto B", description="", target_path=str(tmp_path), actor="op"
    )
    svc.create_orchestration("frete dentro do projeto", project_id=projeto.id)
    svc.create_orchestration("frete fora do projeto")

    resultados = svc.search("frete", project_id=projeto.id)
    assert len(resultados) == 1


def test_search_vazia_nao_devolve_tudo() -> None:
    svc = OrchestrationService()
    svc.create_orchestration("qualquer demanda")
    assert svc.search("") == []
