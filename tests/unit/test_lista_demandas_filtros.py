"""Filtros e ações da Tela 02 (Lista de demandas, wf §4) — ADR-0038."""

from __future__ import annotations

import pytest

from aso.control.orchestration_service import OrchestrationService
from aso.control.triage import DemandBrief
from aso.shared.types import RiskLevel


def _orch_com_brief(svc: OrchestrationService, texto: str, **brief_kwargs: object) -> str:
    orch = svc.create_orchestration(texto, demand_brief=DemandBrief(**brief_kwargs))
    return orch.id


# --------------------------------------------------------- filtros baratos (SQL)


def test_filtro_status() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("demanda um")
    svc.create_orchestration("demanda dois")
    b = svc._bundle(orch.id)  # noqa: SLF001
    b.orchestration.status = "running"
    svc._persist(b)  # noqa: SLF001
    resultado = svc.list_orchestrations_page(status="running")
    assert [o.id for o in resultado["items"]] == [orch.id]


def test_filtro_texto_busca_substring_no_user_request() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("implementar cálculo de frete internacional")
    svc.create_orchestration("corrigir login")
    resultado = svc.list_orchestrations_page(q="frete")
    assert [o.id for o in resultado["items"]] == [orch.id]


def test_filtro_executor() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("com executor", executor="claude")
    svc.create_orchestration("sem executor")
    resultado = svc.list_orchestrations_page(executor="claude")
    assert [o.id for o in resultado["items"]] == [orch.id]


def test_filtro_data_de_criacao() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("demanda")
    futuro = "2999-01-01T00:00:00+00:00"
    passado = "2000-01-01T00:00:00+00:00"
    assert svc.list_orchestrations_page(created_from=passado, created_to=futuro)["total"] == 1
    assert svc.list_orchestrations_page(created_from=futuro)["total"] == 0
    assert orch.id


# ------------------------------------------------- filtros caros (demand_brief)


def test_filtro_tipo() -> None:
    svc = OrchestrationService()
    alvo = _orch_com_brief(svc, "bug", tipo="correcao")
    _orch_com_brief(svc, "feature", tipo="funcionalidade")
    resultado = svc.list_orchestrations_page(tipo="correcao")
    assert [o.id for o in resultado["items"]] == [alvo]


def test_filtro_risco_reaproveitado_como_prioridade() -> None:
    """wf §4.2: "Prioridade" não existe como campo de demanda — o filtro real é
    `risco` (ADR-0038)."""
    svc = OrchestrationService()
    alto = _orch_com_brief(svc, "alto risco", risco=RiskLevel.HIGH)
    _orch_com_brief(svc, "baixo risco", risco=RiskLevel.LOW)
    resultado = svc.list_orchestrations_page(risco="high")
    assert [o.id for o in resultado["items"]] == [alto]


def test_filtro_complexidade() -> None:
    svc = OrchestrationService()
    alvo = _orch_com_brief(svc, "complexa", complexidade="complexa")
    _orch_com_brief(svc, "simples", complexidade="simples")
    resultado = svc.list_orchestrations_page(complexidade="complexa")
    assert [o.id for o in resultado["items"]] == [alvo]


def test_filtro_impacto_e_lista() -> None:
    svc = OrchestrationService()
    alvo = _orch_com_brief(svc, "deploy sensível", impactos=["deploy", "security"])
    _orch_com_brief(svc, "sem impacto sensível", impactos=[])
    resultado = svc.list_orchestrations_page(impacto="security")
    assert [o.id for o in resultado["items"]] == [alvo]


def test_filtro_aprovacao_humana_pendente() -> None:
    svc = OrchestrationService()
    com_aprovacao = svc.create_orchestration("com aprovação")
    svc.request_approval(com_aprovacao.id, "ação manual")
    svc.create_orchestration("sem aprovação")
    resultado = svc.list_orchestrations_page(aprovacao_humana=True)
    assert [o.id for o in resultado["items"]] == [com_aprovacao.id]
    resultado_falso = svc.list_orchestrations_page(aprovacao_humana=False)
    assert com_aprovacao.id not in [o.id for o in resultado_falso["items"]]


def test_filtros_combinaveis() -> None:
    svc = OrchestrationService()
    alvo = _orch_com_brief(svc, "bug crítico de frete", tipo="correcao", risco=RiskLevel.CRITICAL)
    _orch_com_brief(svc, "bug simples", tipo="correcao", risco=RiskLevel.LOW)
    resultado = svc.list_orchestrations_page(tipo="correcao", risco="critical", q="frete")
    assert [o.id for o in resultado["items"]] == [alvo]


def test_list_all_tambem_aplica_filtros_caros_sem_paginar() -> None:
    svc = OrchestrationService()
    alvo = _orch_com_brief(svc, "bug", tipo="correcao")
    _orch_com_brief(svc, "feature", tipo="funcionalidade")
    assert [o.id for o in svc.list_all(tipo="correcao")] == [alvo]


def test_paginacao_correta_com_filtro_caro() -> None:
    svc = OrchestrationService()
    for i in range(5):
        _orch_com_brief(svc, f"bug {i}", tipo="correcao")
    pagina1 = svc.list_orchestrations_page(tipo="correcao", page=1, page_size=2)
    pagina2 = svc.list_orchestrations_page(tipo="correcao", page=2, page_size=2)
    assert pagina1["total"] == 5
    assert len(pagina1["items"]) == 2
    assert len(pagina2["items"]) == 2
    assert {o.id for o in pagina1["items"]}.isdisjoint({o.id for o in pagina2["items"]})


# --------------------------------------------------------------------- duplicar


def test_duplicate_orchestration_cria_nova_com_mesmo_user_request() -> None:
    svc = OrchestrationService()
    origem = svc.create_orchestration("implementar cálculo de frete")
    nova = svc.duplicate_orchestration(origem.id)
    assert nova.id != origem.id
    assert nova.user_request == origem.user_request


def test_duplicate_orchestration_nao_copia_cards_nem_historico() -> None:
    svc = OrchestrationService()
    origem = svc.create_orchestration("demanda original")
    origem_card = svc.get_cards(origem.id)[0]
    svc.move_card(origem.id, origem_card.id, "Failed")
    nova = svc.duplicate_orchestration(origem.id)
    novos_cards = svc.get_cards(nova.id)
    assert all(c.status.value != "Failed" for c in novos_cards)


def test_duplicate_orchestration_registra_evento() -> None:
    svc = OrchestrationService()
    origem = svc.create_orchestration("demanda original")
    nova = svc.duplicate_orchestration(origem.id, actor="operador")
    eventos = [e for e in svc.timeline(nova.id) if e.type == "OrchestrationDuplicated"]
    assert eventos
    assert eventos[0].payload["origem_id"] == origem.id
    assert eventos[0].payload["actor"] == "operador"


def test_duplicate_orchestration_inexistente_leva_a_keyerror() -> None:
    svc = OrchestrationService()
    with pytest.raises(KeyError):
        svc.duplicate_orchestration("orch_inexistente")
