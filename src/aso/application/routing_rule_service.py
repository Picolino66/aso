"""Casos de uso das regras de roteamento (§33, ADR-0028).

Regras de roteamento são configuração do runtime, não estado de uma orquestração
específica — mesmo raciocínio de `ProjectService`: persistidas por porta própria
(`RoutingRuleRepository`), fora do `ContextBus`. A avaliação em si
(`avaliar_regras`) é pura e vive em `control/routing_rules.py`; este serviço só
cuida do CRUD (validação + concorrência otimista), o I/O que o módulo puro não
pode ter.
"""

from __future__ import annotations

import threading

from aso.control.routing_rules import RoutingAction, RoutingCondition, RoutingRule, validar_regra
from aso.persistence.ports import RoutingRuleRepository
from aso.shared.ids import now_iso


class RoutingRuleService:
    """Coordena validação, persistência e concorrência das regras de roteamento."""

    def __init__(self, repository: RoutingRuleRepository) -> None:
        self._repo = repository
        self._lock = threading.RLock()

    def _get(self, rule_id: str) -> RoutingRule:
        rule = self._repo.get_rule(rule_id)
        if rule is None:
            raise LookupError("Regra de roteamento inexistente.")
        return rule

    def list_rules(self, *, only_active: bool = False) -> list[RoutingRule]:
        return self._repo.list_rules(only_active=only_active)

    def get(self, rule_id: str) -> RoutingRule:
        return self._get(rule_id)

    def create(
        self,
        *,
        nome: str,
        descricao: str = "",
        ativa: bool = True,
        precedencia: int = 100,
        condicoes: list[RoutingCondition],
        acao: RoutingAction,
        actor: str,
    ) -> RoutingRule:
        with self._lock:
            rule = RoutingRule(
                nome=nome,
                descricao=descricao,
                ativa=ativa,
                precedencia=precedencia,
                condicoes=condicoes,
                acao=acao,
                created_by=actor,
            )
            validar_regra(rule)
            self._repo.save_rule(rule)
            return rule

    def update(
        self,
        rule_id: str,
        *,
        nome: str,
        descricao: str = "",
        ativa: bool = True,
        precedencia: int = 100,
        condicoes: list[RoutingCondition],
        acao: RoutingAction,
    ) -> RoutingRule:
        with self._lock:
            atual = self._get(rule_id)
            atualizada = atual.model_copy(
                update={
                    "nome": nome,
                    "descricao": descricao,
                    "ativa": ativa,
                    "precedencia": precedencia,
                    "condicoes": condicoes,
                    "acao": acao,
                    "updated_at": now_iso(),
                }
            )
            validar_regra(atualizada)
            self._repo.save_rule(atualizada, before_updated_at=atual.updated_at)
            return atualizada

    def delete(self, rule_id: str) -> None:
        with self._lock:
            self._get(rule_id)
            self._repo.delete_rule(rule_id)

    def reorder(self, ordem: list[str]) -> list[RoutingRule]:
        """Reatribui `precedencia` a partir da ordem visual arrastada na Tela 31
        (wf §33, ADR-0042) — passo de 10 (10, 20, 30...) para deixar espaço a
        ajustes futuros sem precisar renumerar tudo de novo. `ordem` com um id
        inexistente levanta `LookupError`, mesma checagem de `update`/`delete`."""
        with self._lock:
            atualizadas = []
            for indice, rule_id in enumerate(ordem):
                atual = self._get(rule_id)
                nova = atual.model_copy(
                    update={"precedencia": (indice + 1) * 10, "updated_at": now_iso()}
                )
                self._repo.save_rule(nova, before_updated_at=atual.updated_at)
                atualizadas.append(nova)
            return atualizadas
