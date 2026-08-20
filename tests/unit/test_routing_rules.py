"""Testes do avaliador puro de regras de roteamento (§33, ADR-0028)."""

from __future__ import annotations

import pytest

from aso.control.models import DecisionInput
from aso.control.routing_rules import (
    RoutingAction,
    RoutingCondition,
    RoutingRule,
    RoutingRuleError,
    avaliar_regras,
    contexto_de_decision_input,
    contexto_de_demand_brief,
    validar_regra,
)
from aso.control.triage import DemandBrief
from aso.shared.types import RiskLevel


def _regra(
    nome: str,
    condicoes: list[RoutingCondition],
    *,
    precedencia: int = 100,
    ativa: bool = True,
    acao: RoutingAction | None = None,
) -> RoutingRule:
    return RoutingRule(
        nome=nome,
        precedencia=precedencia,
        ativa=ativa,
        condicoes=condicoes,
        acao=acao or RoutingAction(modelo="claude-opus"),
    )


def test_regra_sem_condicoes_nunca_casa() -> None:
    regra = RoutingRule(nome="catch-all", condicoes=[], acao=RoutingAction(modelo="x"))
    assert avaliar_regras([regra], {"tipo": "seguranca"}) is None


def test_condicao_igual_bate() -> None:
    regra = _regra("r1", [RoutingCondition(campo="tipo", operador="igual", valor="seguranca")])
    resultado = avaliar_regras([regra], {"tipo": "seguranca"})
    assert resultado is not None
    assert resultado.regra_nome == "r1"
    assert resultado.acao.modelo == "claude-opus"


def test_condicao_igual_nao_bate() -> None:
    regra = _regra("r1", [RoutingCondition(campo="tipo", operador="igual", valor="seguranca")])
    assert avaliar_regras([regra], {"tipo": "funcionalidade"}) is None


def test_condicao_diferente() -> None:
    regra = _regra("r1", [RoutingCondition(campo="tipo", operador="diferente", valor="produto")])
    assert avaliar_regras([regra], {"tipo": "seguranca"}) is not None
    assert avaliar_regras([regra], {"tipo": "produto"}) is None


def test_condicao_em() -> None:
    regra = _regra(
        "r1", [RoutingCondition(campo="tipo", operador="em", valor=["seguranca", "arquitetura"])]
    )
    assert avaliar_regras([regra], {"tipo": "arquitetura"}) is not None
    assert avaliar_regras([regra], {"tipo": "produto"}) is None


def test_condicao_contem_em_campo_lista() -> None:
    regra = _regra("r1", [RoutingCondition(campo="dominios", operador="contem", valor="security")])
    assert avaliar_regras([regra], {"dominios": ["backend", "security"]}) is not None
    assert avaliar_regras([regra], {"dominios": ["backend"]}) is None


def test_condicao_maior_ou_igual_risco() -> None:
    regra = _regra("r1", [RoutingCondition(campo="risco", operador="maior_ou_igual", valor="high")])
    assert avaliar_regras([regra], {"risco": "critical"}) is not None
    assert avaliar_regras([regra], {"risco": "high"}) is not None
    assert avaliar_regras([regra], {"risco": "medium"}) is None


def test_condicao_maior_ou_igual_complexidade() -> None:
    regra = _regra(
        "r1",
        [RoutingCondition(campo="complexidade", operador="maior_ou_igual", valor="complexa")],
    )
    assert avaliar_regras([regra], {"complexidade": "estrategica"}) is not None
    assert avaliar_regras([regra], {"complexidade": "intermediaria"}) is None


def test_condicoes_multiplas_sao_combinadas_por_e() -> None:
    regra = _regra(
        "r1",
        [
            RoutingCondition(campo="tipo", operador="igual", valor="seguranca"),
            RoutingCondition(campo="risco", operador="maior_ou_igual", valor="high"),
        ],
    )
    assert avaliar_regras([regra], {"tipo": "seguranca", "risco": "critical"}) is not None
    assert avaliar_regras([regra], {"tipo": "seguranca", "risco": "low"}) is None
    assert avaliar_regras([regra], {"tipo": "produto", "risco": "critical"}) is None


def test_campo_ausente_no_contexto_nunca_bate() -> None:
    regra = _regra("r1", [RoutingCondition(campo="tipo", operador="igual", valor="seguranca")])
    assert avaliar_regras([regra], {}) is None


def test_precedencia_menor_vence_primeiro() -> None:
    condicao = RoutingCondition(campo="tipo", operador="igual", valor="seguranca")
    alta = _regra("prioritaria", [condicao], precedencia=1, acao=RoutingAction(modelo="a"))
    baixa = _regra("secundaria", [condicao], precedencia=50, acao=RoutingAction(modelo="b"))
    resultado = avaliar_regras([baixa, alta], {"tipo": "seguranca"})
    assert resultado is not None
    assert resultado.regra_nome == "prioritaria"


def test_regra_inativa_e_ignorada() -> None:
    condicao = RoutingCondition(campo="tipo", operador="igual", valor="seguranca")
    regra = _regra("r1", [condicao], ativa=False)
    assert avaliar_regras([regra], {"tipo": "seguranca"}) is None


def test_nenhuma_regra_configurada_devolve_none() -> None:
    assert avaliar_regras([], {"tipo": "seguranca"}) is None


def test_contexto_de_decision_input_le_todos_os_campos() -> None:
    din = DecisionInput(
        user_request="x",
        risk_level=RiskLevel.HIGH,
        domains=["backend", "security"],
        impacts=["deploy"],
        tipo="seguranca",
        complexidade="complexa",
    )
    contexto = contexto_de_decision_input(din)
    assert contexto == {
        "tipo": "seguranca",
        "risco": "high",
        "complexidade": "complexa",
        "dominios": ["backend", "security"],
        "impactos": ["deploy"],
    }


# --------------------------------------------------------------------- validação


def test_validar_regra_aceita_regra_bem_formada() -> None:
    regra = _regra("r1", [RoutingCondition(campo="tipo", operador="igual", valor="seguranca")])
    validar_regra(regra)  # não levanta


def test_validar_regra_recusa_sem_nome() -> None:
    regra = RoutingRule(
        nome="  ", condicoes=[RoutingCondition(campo="tipo", operador="igual", valor="x")]
    )
    with pytest.raises(RoutingRuleError):
        validar_regra(regra)


def test_validar_regra_recusa_sem_condicoes() -> None:
    regra = RoutingRule(nome="r1", condicoes=[])
    with pytest.raises(RoutingRuleError):
        validar_regra(regra)


def test_validar_regra_recusa_campo_invalido() -> None:
    regra = RoutingRule(
        nome="r1", condicoes=[RoutingCondition(campo="inventado", operador="igual", valor="x")]
    )
    with pytest.raises(RoutingRuleError):
        validar_regra(regra)


def test_validar_regra_recusa_operador_invalido() -> None:
    regra = RoutingRule(
        nome="r1", condicoes=[RoutingCondition(campo="tipo", operador="parecido", valor="x")]
    )
    with pytest.raises(RoutingRuleError):
        validar_regra(regra)


def test_validar_regra_recusa_maior_ou_igual_em_campo_nao_ordinal() -> None:
    regra = RoutingRule(
        nome="r1",
        condicoes=[RoutingCondition(campo="tipo", operador="maior_ou_igual", valor="x")],
    )
    with pytest.raises(RoutingRuleError):
        validar_regra(regra)


def test_contexto_de_demand_brief_espelha_contexto_de_decision_input() -> None:
    brief = DemandBrief(
        tipo="seguranca",
        dominios=["security"],
        impactos=["security"],
        risco=RiskLevel.HIGH,
        complexidade="complexa",
    )
    contexto = contexto_de_demand_brief(brief)
    assert contexto == {
        "tipo": "seguranca",
        "risco": "high",
        "complexidade": "complexa",
        "dominios": ["security"],
        "impactos": ["security"],
    }


def test_contexto_de_demand_brief_casa_com_regra_via_avaliar_regras() -> None:
    regra = RoutingRule(
        nome="Segurança crítica",
        condicoes=[
            RoutingCondition(campo="tipo", operador="igual", valor="seguranca"),
            RoutingCondition(campo="risco", operador="maior_ou_igual", valor="high"),
        ],
        acao=RoutingAction(modelo="claude-opus"),
    )
    brief = DemandBrief(tipo="seguranca", risco=RiskLevel.CRITICAL)
    resultado = avaliar_regras([regra], contexto_de_demand_brief(brief))
    assert resultado is not None
    assert resultado.regra_nome == "Segurança crítica"
