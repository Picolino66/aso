"""PlanningService — planejamento do produto por LLM (M2 do autopilot).

Transforma uma ideia em linguagem natural num plano estruturado e validado
(produto + ADRs + backlog de cards concretos), que o OrchestrationService
materializa no board sob governança. O LlmClient é injetável (offline nos testes).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from aso.execution.llm_client import LlmClient
from aso.execution.llm_provider import parse_llm_json

_PLANNING_SYSTEM = (
    "Você é o planejador-chefe (CTO) de um runtime de engenharia autônoma.\n"
    "A partir de uma ideia de produto, produza um plano inicial em português do Brasil.\n"
    "Responda SOMENTE com um objeto JSON válido, sem cercas de código, na forma:\n"
    '{"product": {"name": "...", "domain": "...", "mvp_hypothesis": "..."},\n'
    ' "adrs": [{"title": "...", "decision": "...", "rationale": "..."}],\n'
    ' "backlog": [{"title": "...", "phase": "F5", "domain": "backend",'
    ' "acceptance_criteria": ["..."]}]}\n'
    "Use fases válidas (F1..F7). Gere um backlog enxuto e executável (5 a 15 itens)."
)


class ProductSummary(BaseModel):
    name: str = ""
    domain: str = ""
    mvp_hypothesis: str = ""


class PlannedAdr(BaseModel):
    title: str
    decision: str
    rationale: str = ""


class BacklogItem(BaseModel):
    title: str
    phase: str = "F5"
    domain: str = "backend"
    acceptance_criteria: list[str] = Field(default_factory=list)


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
        raw = self._client.complete(
            system=_PLANNING_SYSTEM,
            user=f"Ideia do produto:\n{idea}\n\nProduza o plano JSON.",
        )
        data = parse_llm_json(raw)
        return ProjectPlan.model_validate(data)
