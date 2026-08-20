"""Regras de roteamento SE/ENTÃO (wiframe-fluxo.md §33, fluxo.md §9) — ADR-0028.

Hoje o `MultiAgentDecisionEngine` (§14) decide agente/effort/aprovação só por
heurística compilada — o operador não tem como declarar uma política como
"SE tipo=Segurança E risco≥Alto ENTÃO Opus, effort máximo, revisão humana". Este
módulo fecha essa lacuna com uma camada que é avaliada **antes** da heurística, não
no lugar dela: nenhuma regra casando, o comportamento de toda orquestração
existente permanece idêntico (fallback, nunca substituição).

Tudo aqui é **puro e determinístico** (mesmo princípio de
`control/failure.py`/`control/selecao.py`): dado o mesmo conjunto de regras e o
mesmo contexto, o resultado é sempre o mesmo. Nenhum LLM decide roteamento —
decisão de governança é regra declarada pelo operador, não palpite. Quem tem I/O
(persistir regras, aplicar o resultado à orquestração) é
`control/routing_rule_service.py` e `OrchestrationService`.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from aso.control.models import DecisionInput
from aso.control.triage import DemandBrief
from aso.shared.ids import gen_id, now_iso

# --------------------------------------------------------------- vocabulário fechado

# Campos avaliáveis de uma condição — mesmo espírito de `triage.py::_TIPOS_VALIDOS`:
# rótulo fora daqui é rejeitado na validação, nunca avaliado silenciosamente errado.
CAMPO_TIPO = "tipo"
CAMPO_RISCO = "risco"
CAMPO_COMPLEXIDADE = "complexidade"
CAMPO_DOMINIOS = "dominios"
CAMPO_IMPACTOS = "impactos"
CAMPOS_VALIDOS = frozenset(
    {CAMPO_TIPO, CAMPO_RISCO, CAMPO_COMPLEXIDADE, CAMPO_DOMINIOS, CAMPO_IMPACTOS}
)

OP_IGUAL = "igual"
OP_DIFERENTE = "diferente"
OP_EM = "em"  # contexto[campo] está na lista `valor`
OP_CONTEM = "contem"  # `valor` está na lista contexto[campo] (dominios/impactos)
OP_MAIOR_OU_IGUAL = "maior_ou_igual"  # ordinal, só para risco/complexidade
OPERADORES_VALIDOS = frozenset({OP_IGUAL, OP_DIFERENTE, OP_EM, OP_CONTEM, OP_MAIOR_OU_IGUAL})

# Ordem ordinal para "maior_ou_igual" — mesmos vocabulários de RiskLevel (shared/types.py)
# e de `_COMPLEXIDADES_VALIDAS` (triage.py), copiados aqui pelo mesmo motivo que
# `triage.py` copia `_DOMAIN_AGENT`: um valor fora do vocabulário nunca deve
# silenciosamente comparar como "menor que tudo".
_ORDEM_RISCO = {"low": 0, "medium": 1, "high": 2, "critical": 3}
_ORDEM_COMPLEXIDADE = {"simples": 0, "intermediaria": 1, "complexa": 2, "estrategica": 3}
_ORDINAIS: dict[str, dict[str, int]] = {
    CAMPO_RISCO: _ORDEM_RISCO,
    CAMPO_COMPLEXIDADE: _ORDEM_COMPLEXIDADE,
}


class RoutingRuleError(ValueError):
    """Regra inválida: campo/operador fora do vocabulário, ou sem condições."""


# ------------------------------------------------------------------------- modelos


class RoutingCondition(BaseModel):
    """Um termo do "SE" — `campo` `operador` `valor` (wiframe §33.2)."""

    campo: str
    operador: str
    valor: object


class RoutingAction(BaseModel):
    """O "ENTÃO" — cada campo `None`/vazio significa "sem opinião, não sobrescreve".

    `limite_tentativas` e `quality_gates` ficam registrados no resultado para o
    operador/UI e para a FID-04 (limite de tentativas por card, que depende deste
    card) consumirem — este incremento não os aplica ao card, só os transporta.
    """

    agente: str | None = None
    modelo: str | None = None
    effort: str | None = None
    aprovacao_humana: bool | None = None
    quality_gates: list[str] = Field(default_factory=list)
    limite_tentativas: int | None = None


class RoutingRule(BaseModel):
    """Uma regra de roteamento declarada pelo operador (§33 do wireframe)."""

    id: str = Field(default_factory=lambda: gen_id("route"))
    nome: str
    descricao: str = ""
    ativa: bool = True
    # Menor valor = avaliada primeiro. Duas regras com a mesma precedência mantêm a
    # ordem de entrada (sort estável) — não há empate silencioso resolvido ao acaso.
    precedencia: int = 100
    condicoes: list[RoutingCondition] = Field(default_factory=list)
    acao: RoutingAction = Field(default_factory=RoutingAction)
    created_by: str = ""
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class RoutingRuleResult(BaseModel):
    """O que uma regra decidiu — inclui o rastro de qual regra decidiu (auditoria)."""

    regra_id: str
    regra_nome: str
    acao: RoutingAction


# -------------------------------------------------------------------------- validação


def validar_regra(regra: RoutingRule) -> None:
    """Recusa regra sem condições ou com campo/operador fora do vocabulário.

    Sem condições, uma regra "ativa" casaria com tudo (ver `_regra_bate`) — recusada
    aqui, antes de persistir, em vez de silenciosamente nunca casar em runtime.
    """
    if not regra.nome.strip():
        raise RoutingRuleError("Informe um nome para a regra.")
    if not regra.condicoes:
        raise RoutingRuleError("A regra precisa de ao menos uma condição no SE.")
    for i, condicao in enumerate(regra.condicoes):
        if condicao.campo not in CAMPOS_VALIDOS:
            raise RoutingRuleError(
                f"Condição {i}: campo {condicao.campo!r} inválido "
                f"(esperado um de {sorted(CAMPOS_VALIDOS)})."
            )
        if condicao.operador not in OPERADORES_VALIDOS:
            raise RoutingRuleError(
                f"Condição {i}: operador {condicao.operador!r} inválido "
                f"(esperado um de {sorted(OPERADORES_VALIDOS)})."
            )
        if condicao.operador == OP_MAIOR_OU_IGUAL and condicao.campo not in _ORDINAIS:
            raise RoutingRuleError(
                f"Condição {i}: operador 'maior_ou_igual' só vale para "
                f"{sorted(_ORDINAIS)}, não para {condicao.campo!r}."
            )


# -------------------------------------------------------------------------- avaliação


def _condicao_bate(condicao: RoutingCondition, contexto: dict[str, object]) -> bool:
    if condicao.campo not in contexto:
        return False
    atual = contexto[condicao.campo]
    valor = condicao.valor
    if condicao.operador == OP_IGUAL:
        return atual == valor
    if condicao.operador == OP_DIFERENTE:
        return atual != valor
    if condicao.operador == OP_EM:
        return isinstance(valor, list) and atual in valor
    if condicao.operador == OP_CONTEM:
        return isinstance(atual, list) and valor in atual
    if condicao.operador == OP_MAIOR_OU_IGUAL:
        ordem = _ORDINAIS.get(condicao.campo)
        if ordem is None:
            return False
        rank_atual = ordem.get(str(atual))
        rank_minimo = ordem.get(str(valor))
        return rank_atual is not None and rank_minimo is not None and rank_atual >= rank_minimo
    return False  # operador desconhecido nunca casa (defesa; validar_regra já barra na entrada)


def _regra_bate(regra: RoutingRule, contexto: dict[str, object]) -> bool:
    # Sem condições, a regra nunca casa (não é um catch-all silencioso) — mesma
    # postura defensiva de `validar_regra`, para o caso de dado legado/corrompido
    # que tenha escapado da validação de escrita.
    if not regra.condicoes:
        return False
    return all(_condicao_bate(c, contexto) for c in regra.condicoes)


def avaliar_regras(
    regras: list[RoutingRule], contexto: dict[str, object]
) -> RoutingRuleResult | None:
    """Primeira regra ativa, em ordem de precedência, cujas condições batem (E).

    `None` = nenhuma regra casou → quem chama cai na heurística existente
    (`MultiAgentDecisionEngine`/`selecao.py`), sem exceção, sem regressão.
    """
    ativas = [r for r in regras if r.ativa]
    for regra in sorted(ativas, key=lambda r: r.precedencia):
        if _regra_bate(regra, contexto):
            return RoutingRuleResult(regra_id=regra.id, regra_nome=regra.nome, acao=regra.acao)
    return None


def contexto_de_decision_input(din: DecisionInput) -> dict[str, object]:
    """Contexto de avaliação a partir do que já alimenta o motor de decisão (§14)."""
    return {
        CAMPO_TIPO: din.tipo,
        CAMPO_RISCO: din.risk_level.value,
        CAMPO_COMPLEXIDADE: din.complexidade,
        CAMPO_DOMINIOS: din.domains,
        CAMPO_IMPACTOS: din.impacts,
    }


def contexto_de_demand_brief(brief: DemandBrief) -> dict[str, object]:
    """Contexto de avaliação a partir da ficha de uma demanda já existente (Tela 31,
    wf §33.2, ADR-0042) — usado pela pré-visualização "quais demandas casariam com
    a regra", que roda contra o `demand_brief` já persistido de cada orquestração."""
    return {
        CAMPO_TIPO: brief.tipo,
        CAMPO_RISCO: brief.risco.value,
        CAMPO_COMPLEXIDADE: brief.complexidade,
        CAMPO_DOMINIOS: brief.dominios,
        CAMPO_IMPACTOS: brief.impactos,
    }
