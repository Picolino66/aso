"""PlanningService — planejamento do produto por LLM (M2 do autopilot).

Transforma uma ideia em linguagem natural num plano estruturado e validado
(produto + ADRs + backlog de cards concretos), que o OrchestrationService
materializa no board sob governança. O LlmClient é injetável (offline nos testes).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from aso.control.respostas_estruturadas import (
    TENTATIVAS_DE_CORRECAO,
    RespostaInvalida,
    esquema_de,
    instrucao_de_formato,
    pedido_de_correcao,
    validar,
)
from aso.execution.llm_client import LlmClient, completar
from aso.execution.llm_provider import parse_llm_json

_PLANNING_SYSTEM = (
    "Você é o planejador-chefe (CTO) de um runtime de engenharia autônoma.\n"
    "A partir de uma ideia de produto, produza um plano inicial em português do Brasil.\n"
    "Distribua o backlog por TODA a esteira (fases F1..F7), não só F5:\n"
    "- F1 discovery/requisitos, F2 arquitetura, F3 dados/contratos, F4 UX/planejamento,\n"
    "  F5 desenvolvimento, F6 testes/qualidade/docs, F7 operação/observabilidade.\n"
    "Gere um backlog enxuto e executável (5 a 15 itens), com ao menos um item por fase "
    "relevante à ideia.\n"
    "`depends_on` (fluxo §7/§10) é a ordem de execução: liste os TÍTULOS EXATOS "
    "(não índices) de outros itens deste mesmo backlog que precisam terminar antes — "
    "ex.: um item de F5 que consome um contrato depende do item de F3 que o define. "
    "Deixe vazio quando não houver dependência real; não invente ordem só para "
    "preencher o campo."
)


class ProductSummary(BaseModel):
    name: str = ""
    domain: str = ""
    mvp_hypothesis: str = ""


class PlannedAdr(BaseModel):
    title: str
    decision: str
    rationale: str = ""
    # Caminhos do contexto que a ADR governa (ADR-0061): escrever neles sem referenciá-la
    # em `linked_adrs` é rejeitado pelo ContextBus.
    locked_paths: list[str] = Field(default_factory=list)


class BacklogItem(BaseModel):
    title: str
    phase: str = "F5"
    domain: str = "backend"
    # Tipo do card (req §16.4/§7, ADR-0025) — permite o LLM marcar épicos/features no
    # backlog planejado; "Task" (default) é o único tipo que qualquer caminho de
    # criação produzia até aqui.
    type: str = "Task"
    acceptance_criteria: list[str] = Field(default_factory=list)
    # Títulos de outros itens deste backlog que precisam terminar antes (fluxo §7/§10 do
    # fluxo.md) — resolvidos para ids de card numa segunda passada em
    # `populate_from_plan` (mesmo padrão de `PlannedAgent.depends_on`).
    depends_on: list[str] = Field(default_factory=list)


class ProjectPlan(BaseModel):
    """Plano de produto estruturado produzido pelo LLM (validado)."""

    product: ProductSummary = Field(default_factory=ProductSummary)
    adrs: list[PlannedAdr] = Field(default_factory=list)
    backlog: list[BacklogItem] = Field(default_factory=list)


class PlanningService:
    """Gera um ProjectPlan a partir de uma ideia usando um LlmClient."""

    def __init__(self, client: LlmClient) -> None:
        self._client = client

    def plan(self, idea: str) -> ProjectPlan:
        """Plano validado contra `ProjectPlan` (schema no prompt e saída estruturada nativa,
        ADR-0072); fora do schema, uma única tentativa de correção com os campos que falharam."""
        pedido = f"Ideia do produto:\n{idea}\n\nProduza o plano JSON."
        system = f"{_PLANNING_SYSTEM}\n{instrucao_de_formato(ProjectPlan)}"
        atual = pedido
        for tentativa in range(TENTATIVAS_DE_CORRECAO + 1):
            resposta = completar(
                self._client, system=system, user=atual, esquema=esquema_de(ProjectPlan)
            )
            try:
                return ProjectPlan.model_validate(
                    validar(ProjectPlan, parse_llm_json(resposta.texto))
                )
            except RespostaInvalida as erro:
                if tentativa == TENTATIVAS_DE_CORRECAO:
                    raise
                atual = pedido_de_correcao(pedido, erro)
        raise AssertionError("inalcançável")  # pragma: no cover
