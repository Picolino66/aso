"""Persistência relacional das regras de roteamento (§33, ADR-0028)."""

from __future__ import annotations

from pathlib import Path

import pytest

from aso.control.orchestration_service import OrchestrationService
from aso.control.routing_rules import RoutingAction, RoutingCondition
from aso.db.repository import SqlAlchemyRoutingRuleRepository


def _service(url: str) -> OrchestrationService:
    return OrchestrationService(routing_rule_repository=SqlAlchemyRoutingRuleRepository(url))


def test_regra_sobrevive_ao_reinicio(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'routing.db'}"
    first = _service(url)
    criada = first.create_routing_rule(
        nome="Segurança crítica",
        descricao="",
        ativa=True,
        precedencia=1,
        condicoes=[RoutingCondition(campo="tipo", operador="igual", valor="seguranca")],
        acao=RoutingAction(modelo="claude-opus"),
        actor="op",
    )

    restarted = _service(url)
    listadas = restarted.list_routing_rules()
    assert len(listadas) == 1
    assert listadas[0]["id"] == criada["id"]
    assert listadas[0]["nome"] == "Segurança crítica"


def test_escrita_otimista_rejeita_update_obsoleto(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'routing-optimistic.db'}"
    repository = SqlAlchemyRoutingRuleRepository(url)
    svc = _service(url)
    criada = svc.create_routing_rule(
        nome="Regra",
        descricao="",
        ativa=True,
        precedencia=10,
        condicoes=[RoutingCondition(campo="tipo", operador="igual", valor="x")],
        acao=RoutingAction(modelo="a"),
        actor="op",
    )
    rule_id = str(criada["id"])

    first = repository.get_rule(rule_id)
    stale = repository.get_rule(rule_id)
    assert first is not None and stale is not None

    first_atualizada = first.model_copy(
        update={"nome": "primeiro escritor", "updated_at": "2030-01-01T00:00:00+00:00"}
    )
    repository.save_rule(first_atualizada, before_updated_at=first.updated_at)

    stale_atualizada = stale.model_copy(
        update={"nome": "escrita obsoleta", "updated_at": "2030-01-02T00:00:00+00:00"}
    )
    with pytest.raises(ValueError, match="outra operação"):
        repository.save_rule(stale_atualizada, before_updated_at=stale.updated_at)

    atual = repository.get_rule(rule_id)
    assert atual is not None
    assert atual.nome == "primeiro escritor"


def test_delete_e_list_only_active_via_sql(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'routing-crud.db'}"
    svc = _service(url)
    ativa = svc.create_routing_rule(
        nome="Ativa",
        descricao="",
        ativa=True,
        precedencia=1,
        condicoes=[RoutingCondition(campo="tipo", operador="igual", valor="x")],
        acao=RoutingAction(modelo="a"),
        actor="op",
    )
    inativa = svc.create_routing_rule(
        nome="Inativa",
        descricao="",
        ativa=False,
        precedencia=2,
        condicoes=[RoutingCondition(campo="tipo", operador="igual", valor="y")],
        acao=RoutingAction(modelo="b"),
        actor="op",
    )

    assert {r["id"] for r in svc.list_routing_rules(only_active=True)} == {ativa["id"]}
    assert {r["id"] for r in svc.list_routing_rules()} == {ativa["id"], inativa["id"]}

    svc.delete_routing_rule(str(inativa["id"]))
    assert {r["id"] for r in svc.list_routing_rules()} == {ativa["id"]}
