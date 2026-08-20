"""Integração das regras de roteamento (§33, ADR-0028) no OrchestrationService.

Prova as duas garantias centrais da ADR-0028: (1) sem regra ativa configurada, o
comportamento é idêntico ao de antes desta ADR (fallback, nunca substituição);
(2) uma regra casando altera agente/modelo/effort/aprovação sem nunca sobrescrever
uma escolha explícita do operador.
"""

from __future__ import annotations

import pytest

from aso.control.orchestration_service import OrchestrationService
from aso.control.routing_rules import RoutingAction, RoutingCondition, RoutingRuleError
from aso.control.triage import DemandBrief
from aso.shared.types import RiskLevel


def _svc() -> OrchestrationService:
    return OrchestrationService()


def _demanda_seguranca() -> DemandBrief:
    return DemandBrief(
        tipo="seguranca",
        dominios=["security"],
        impactos=["security"],
        risco=RiskLevel.HIGH,
        complexidade="complexa",
    )


def _criar_regra_seguranca(svc: OrchestrationService, **acao_kwargs: object) -> dict[str, object]:
    return svc.create_routing_rule(
        nome="Segurança crítica",
        descricao="SE tipo=seguranca E risco>=high ENTÃO Opus, effort máximo, revisão humana",
        ativa=True,
        precedencia=1,
        condicoes=[
            RoutingCondition(campo="tipo", operador="igual", valor="seguranca"),
            RoutingCondition(campo="risco", operador="maior_ou_igual", valor="high"),
        ],
        acao=RoutingAction(**acao_kwargs),  # type: ignore[arg-type]
        actor="tester",
    )


# --------------------------------------------------------------------------- CRUD


def test_crud_completo_de_regra() -> None:
    svc = _svc()
    criada = _criar_regra_seguranca(svc, modelo="claude-opus", effort="max")
    assert criada["nome"] == "Segurança crítica"
    listadas = svc.list_routing_rules()
    assert len(listadas) == 1

    atualizada = svc.update_routing_rule(
        str(criada["id"]),
        nome="Segurança crítica v2",
        descricao="",
        ativa=True,
        precedencia=1,
        condicoes=[RoutingCondition(campo="tipo", operador="igual", valor="seguranca")],
        acao=RoutingAction(modelo="claude-opus"),
    )
    assert atualizada["nome"] == "Segurança crítica v2"

    svc.delete_routing_rule(str(criada["id"]))
    assert svc.list_routing_rules() == []


def test_criar_regra_sem_condicao_e_recusada() -> None:
    svc = _svc()
    with pytest.raises(RoutingRuleError):
        svc.create_routing_rule(
            nome="vazia",
            descricao="",
            ativa=True,
            precedencia=100,
            condicoes=[],
            acao=RoutingAction(),
            actor="tester",
        )


def test_atualizar_regra_inexistente_lanca_lookup_error() -> None:
    svc = _svc()
    with pytest.raises(LookupError):
        svc.update_routing_rule(
            "route_inexistente",
            nome="x",
            descricao="",
            ativa=True,
            precedencia=100,
            condicoes=[RoutingCondition(campo="tipo", operador="igual", valor="x")],
            acao=RoutingAction(),
        )


def test_deletar_regra_inexistente_lanca_lookup_error() -> None:
    svc = _svc()
    with pytest.raises(LookupError):
        svc.delete_routing_rule("route_inexistente")


def test_list_only_active_filtra_regras_inativas() -> None:
    svc = _svc()
    criada = _criar_regra_seguranca(svc, modelo="claude-opus")
    svc.update_routing_rule(
        str(criada["id"]),
        nome="Segurança crítica",
        descricao="",
        ativa=False,
        precedencia=1,
        condicoes=[RoutingCondition(campo="tipo", operador="igual", valor="seguranca")],
        acao=RoutingAction(modelo="claude-opus"),
    )
    assert svc.list_routing_rules(only_active=True) == []
    assert len(svc.list_routing_rules(only_active=False)) == 1


# ------------------------------------------------------------- criação com regra


def test_sem_regra_ativa_comportamento_identico_ao_de_antes_da_adr() -> None:
    """Regressão central da ADR-0028: nenhuma regra configurada não muda nada."""
    svc = _svc()
    brief = _demanda_seguranca()
    orch = svc.create_orchestration(
        "revisar autenticação",
        decision_input=brief.to_decision_input("revisar autenticação"),
        demand_brief=brief,
    )
    assert orch.routing_rule_applied is None
    assert orch.selected_executor is None
    assert orch.selected_effort is None


def test_regra_casando_sobrescreve_agente_modelo_effort_e_aprovacao() -> None:
    svc = _svc()
    _criar_regra_seguranca(
        svc, agente="SecurityAgent", modelo="claude-opus", effort="max", aprovacao_humana=True
    )
    brief = _demanda_seguranca()
    orch = svc.create_orchestration(
        "revisar autenticação",
        decision_input=brief.to_decision_input("revisar autenticação"),
        demand_brief=brief,
    )
    assert orch.routing_rule_applied is not None
    assert orch.routing_rule_applied["regra_nome"] == "Segurança crítica"
    assert orch.selected_executor == "claude-opus"
    assert orch.selected_effort == "max"
    plano = svc._bundle(orch.id).plan  # noqa: SLF001
    assert plano.agents[0].agent == "SecurityAgent"
    assert plano.requires_human_approval is True


def test_regra_com_limite_de_tentativas_e_herdado_por_todos_os_cards() -> None:
    """§36.4, ADR-0031: RoutingRule.acao.limite_tentativas se aplica à leva
    inteira de cards nascidos com a orquestração, não só ao card principal."""
    svc = _svc()
    _criar_regra_seguranca(svc, modelo="claude-opus", limite_tentativas=3)
    brief = _demanda_seguranca()
    orch = svc.create_orchestration(
        "revisar autenticação",
        decision_input=brief.to_decision_input("revisar autenticação"),
        demand_brief=brief,
    )
    cards = svc.get_cards(orch.id)
    assert cards
    assert all(c.max_tentativas == 3 for c in cards)


def test_sem_limite_na_regra_cards_usam_o_teto_global() -> None:
    svc = _svc()
    _criar_regra_seguranca(svc, modelo="claude-opus")  # sem limite_tentativas
    brief = _demanda_seguranca()
    orch = svc.create_orchestration(
        "revisar autenticação",
        decision_input=brief.to_decision_input("revisar autenticação"),
        demand_brief=brief,
    )
    cards = svc.get_cards(orch.id)
    assert cards
    assert all(c.max_tentativas is None for c in cards)


def test_regra_nunca_sobrescreve_executor_explicito_do_operador() -> None:
    svc = _svc()
    _criar_regra_seguranca(svc, modelo="claude-opus", effort="max")
    brief = _demanda_seguranca()
    orch = svc.create_orchestration(
        "revisar autenticação",
        executor="escolha-humana",
        effort="alto",
        decision_input=brief.to_decision_input("revisar autenticação"),
        demand_brief=brief,
    )
    # A regra ainda "casa" (routing_rule_applied preenchido), mas não sobrescreve
    # a escolha explícita do operador.
    assert orch.routing_rule_applied is not None
    assert orch.selected_executor == "escolha-humana"
    assert orch.selected_effort == "alto"


def test_regra_nunca_rebaixa_aprovacao_humana_ja_exigida_pela_heuristica() -> None:
    svc = _svc()
    _criar_regra_seguranca(svc, modelo="claude-opus", aprovacao_humana=False)
    brief = DemandBrief(
        tipo="seguranca", risco=RiskLevel.CRITICAL, dominios=["security"], impactos=["security"]
    )
    orch = svc.create_orchestration(
        "revisar autenticação crítica",
        decision_input=brief.to_decision_input("revisar autenticação crítica"),
        demand_brief=brief,
    )
    plano = svc._bundle(orch.id).plan  # noqa: SLF001
    # risk_level CRITICAL já exige aprovação pela heurística (decision_engine.py);
    # aprovacao_humana=False da regra não pode rebaixar isso.
    assert plano.requires_human_approval is True


def test_regra_inativa_nao_e_avaliada() -> None:
    svc = _svc()
    criada = _criar_regra_seguranca(svc, modelo="claude-opus")
    svc.update_routing_rule(
        str(criada["id"]),
        nome="Segurança crítica",
        descricao="",
        ativa=False,
        precedencia=1,
        condicoes=[RoutingCondition(campo="tipo", operador="igual", valor="seguranca")],
        acao=RoutingAction(modelo="claude-opus"),
    )
    brief = _demanda_seguranca()
    orch = svc.create_orchestration(
        "revisar autenticação",
        decision_input=brief.to_decision_input("revisar autenticação"),
        demand_brief=brief,
    )
    assert orch.routing_rule_applied is None


def test_adr_de_estrategia_cita_a_regra_quando_uma_casa() -> None:
    svc = _svc()
    _criar_regra_seguranca(svc, modelo="claude-opus")
    brief = _demanda_seguranca()
    orch = svc.create_orchestration(
        "revisar autenticação",
        decision_input=brief.to_decision_input("revisar autenticação"),
        demand_brief=brief,
    )
    adrs = svc._bundle(orch.id).adr_registry.list_all()  # noqa: SLF001
    estrategia = next(a for a in adrs if a.title.startswith("Estratégia de execução"))
    assert "Segurança crítica" in estrategia.rationale


# ------------------------------------------------------------------------ replan


def test_replan_aplica_regra_recem_ativada_sem_perder_executor_ja_escolhido() -> None:
    svc = _svc()
    brief_inicial = DemandBrief(tipo="funcionalidade", risco=RiskLevel.LOW)
    orch = svc.create_orchestration(
        "ajuste simples",
        executor="executor-humano",
        decision_input=brief_inicial.to_decision_input("ajuste simples"),
        demand_brief=brief_inicial,
    )
    assert orch.selected_executor == "executor-humano"

    _criar_regra_seguranca(svc, modelo="claude-opus", effort="max")
    svc.retriage_demand(orch.id, executor=None)
    # A ficha padrão de retriagem (heurística) não vira "seguranca" sem sinal no
    # texto — então a regra continua não casando; o teste prova que o executor
    # explícito da criação sobrevive ao replan mesmo com a regra ativa.
    atualizado = svc.get(orch.id)
    assert atualizado.selected_executor == "executor-humano"


def test_replan_aplica_regra_quando_a_nova_ficha_casa() -> None:
    """A triagem sem agente configurado usa a heurística (`triage.py::_heuristica`),
    que nunca classifica `tipo="seguranca"` por palavra-chave — só `_sanear` (agente)
    faz isso. Por isso a regra deste teste casa por `dominios`/`risco`, os dois
    sinais que a heurística de fato eleva para um texto com "login"/"senha"/"token".
    """
    svc = _svc()
    texto = "revisar login com senha e token de autenticação"
    brief_inicial = DemandBrief(tipo="funcionalidade", risco=RiskLevel.LOW)
    orch = svc.create_orchestration(
        texto,
        decision_input=brief_inicial.to_decision_input(texto),
        demand_brief=brief_inicial,
    )
    svc.create_routing_rule(
        nome="Domínio de segurança",
        descricao="SE dominios contem security E risco>=high ENTÃO Opus",
        ativa=True,
        precedencia=1,
        condicoes=[
            RoutingCondition(campo="dominios", operador="contem", valor="security"),
            RoutingCondition(campo="risco", operador="maior_ou_igual", valor="high"),
        ],
        acao=RoutingAction(modelo="claude-opus", effort="max"),
        actor="tester",
    )
    svc.retriage_demand(orch.id, executor=None)
    atualizado = svc.get(orch.id)
    assert atualizado.selected_executor == "claude-opus"
    assert atualizado.selected_effort == "max"
    assert atualizado.routing_rule_applied is not None
