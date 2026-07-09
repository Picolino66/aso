"""(M1+M2) Cérebro LLM: provider de execução + planejamento do produto (offline)."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from aso.agents.models import AgentSpec
from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService
from aso.control.planning import PlanningService
from aso.execution.llm_client import FakeLlmClient
from aso.execution.llm_provider import LlmExecutionProvider, parse_llm_json

_PLAN_JSON = {
    "product": {
        "name": "TarefasApp",
        "domain": "produtividade",
        "mvp_hypothesis": "listas simples",
    },
    "adrs": [{"title": "Stack", "decision": "FastAPI + Postgres", "rationale": "familiaridade"}],
    "backlog": [
        {
            "title": "CRUD de tarefas",
            "phase": "F5",
            "domain": "backend",
            "acceptance_criteria": ["cria", "lista"],
        },
        {
            "title": "Tela de listas",
            "phase": "F5",
            "domain": "frontend",
            "acceptance_criteria": ["render"],
        },
        {"title": "Testes e2e", "phase": "F6", "domain": "qa", "acceptance_criteria": ["verde"]},
    ],
}


def test_parse_llm_json_tolerates_code_fences() -> None:
    assert parse_llm_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_llm_json('lixo antes {"b": 2} lixo depois')["b"] == 2


def test_llm_execution_provider_produces_patch() -> None:
    client = FakeLlmClient(lambda s, u: json.dumps({"summary": "ok", "content": {"x": 1}}))
    provider = LlmExecutionProvider(client)
    agent = AgentSpec(role="BackendDevelopmentAgent", context_sections=["engineering"])
    out = provider.execute(
        agent,
        {
            "orchestration_id": "o1",
            "phase": "F5",
            "target_path": "engineering.api",
            "content": {"request": "faça"},
        },
    )
    assert out.summary == "ok"
    assert out.patches[0].target_path == "engineering.api"
    assert out.patches[0].content == {"x": 1}
    assert client.calls  # o prompt foi montado e enviado


def test_planning_service_returns_structured_plan() -> None:
    client = FakeLlmClient(lambda s, u: json.dumps(_PLAN_JSON))
    plan = PlanningService(client).plan("um app de tarefas")
    assert plan.product.name == "TarefasApp"
    assert len(plan.backlog) == 3
    assert plan.backlog[0].phase == "F5"


def test_plan_endpoint_creates_cards_and_adrs() -> None:
    client = FakeLlmClient(lambda s, u: json.dumps(_PLAN_JSON))
    svc = OrchestrationService()
    app_client = TestClient(create_app(svc, llm_client=client))

    oid = app_client.post("/v1/orchestrations", json={"user_request": "app de tarefas"}).json()[
        "id"
    ]
    before = len(app_client.get(f"/v1/orchestrations/{oid}/cards").json())

    res = app_client.post(f"/v1/orchestrations/{oid}/plan", json={"idea": "um app de tarefas"})
    assert res.status_code == 201
    body = res.json()
    assert len(body["cards_created"]) == 3
    assert body["adrs_created"] == 1
    assert body["product"]["name"] == "TarefasApp"

    cards = app_client.get(f"/v1/orchestrations/{oid}/cards").json()
    assert len(cards) == before + 3
    titles = {c["title"] for c in cards}
    assert "CRUD de tarefas" in titles
    # sobrevive à reidratação (persistido)
    svc._bundles.clear()  # noqa: SLF001
    assert len(svc.get_cards(oid)) == before + 3


def test_plan_endpoint_409_without_llm() -> None:
    app_client = TestClient(create_app(OrchestrationService()))  # sem llm_client
    oid = app_client.post("/v1/orchestrations", json={"user_request": "x"}).json()["id"]
    res = app_client.post(f"/v1/orchestrations/{oid}/plan", json={"idea": "algo"})
    assert res.status_code == 409
