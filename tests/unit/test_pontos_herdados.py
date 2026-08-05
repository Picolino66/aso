"""Regressões dos dois pontos herdados da avaliação do Incremento A (plano2.md §1).

**Ponto 1** — a CLI criava orquestrações direto por `create_orchestration`, sem
triagem: cards nasciam com `priority=low` fixo e `demand_brief` vazio. A causa raiz
era duplicação (a sequência triagem→criação só existia em `app.py`); a correção é um
único ponto de entrada, `create_with_triage`, usado pela API e pela CLI.

**Ponto 2** — `retriage_demand` atualizava a ficha mas nunca recomputava o
`ExecutionPlan`: o operador respondia as `perguntas_abertas`, ganhava uma ficha
melhor e continuava com a mesma equipe `single_agent` da triagem original.
"""

from __future__ import annotations

import shlex

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.models import TRIAGE_KEY
from aso.control.orchestration_service import OrchestrationService
from aso.execution.catalog import ExecutorCatalog, ExecutorProfile
from aso.shared.types import ColumnKey, ExecutionStrategy, RiskLevel

DEMANDA_MULTIDOMINIO = "Revisar login com token e senha, guardando os dados no banco de dados"


def _cli_triagem(saida: str) -> ExecutorCatalog:
    script = 'cat > /dev/null; printf %s "$1"; exit 0'
    comando = shlex.join(["bash", "-c", script, "_", saida])
    return ExecutorCatalog([ExecutorProfile(name="triador", kind="cli", command=comando)])


# --------------------------------------------------------------------------- Ponto 1


def test_cli_e_api_produzem_a_mesma_ficha_e_prioridade() -> None:
    """`create_with_triage` é o único caminho correto — a CLI usa exatamente o
    mesmo método que a API, então não pode mais nascer com ficha vazia/prioridade
    fixa (o bug relatado: `priority=['low']`, `estrategia=single_agent`,
    `dominios=[]` mesmo para uma demanda multi-domínio e de alto risco)."""
    svc_cli = OrchestrationService()
    orch_cli = svc_cli.create_with_triage(DEMANDA_MULTIDOMINIO)
    brief_cli = svc_cli.get_demand_brief(orch_cli.id)
    cards_cli = svc_cli.get_cards(orch_cli.id)

    svc_api = OrchestrationService()
    client = TestClient(create_app(svc_api))
    oid_api = client.post("/v1/orchestrations", json={"user_request": DEMANDA_MULTIDOMINIO}).json()[
        "id"
    ]
    brief_api = client.get(f"/v1/orchestrations/{oid_api}/brief").json()
    cards_api = client.get(f"/v1/orchestrations/{oid_api}/cards").json()

    assert brief_cli.dominios == brief_api["dominios"]
    assert brief_cli.risco.value == brief_api["risco"]
    assert brief_cli.risco == RiskLevel.HIGH  # não é mais o backend/low fixo do bug
    assert brief_cli.dominios != ["backend"] or len(brief_cli.dominios) > 1
    assert cards_cli and cards_api
    assert cards_cli[0].priority.value == cards_api[0]["priority"] == RiskLevel.HIGH.value


def test_cli_run_cria_com_ficha_e_prioridade_coerente() -> None:
    """A regressão original: `aso run` chamava `create_orchestration` puro e a
    orquestração nascia com `demand_brief` vazio e `priority=low` fixo — mesmo para
    uma demanda multi-domínio e de alto risco."""
    from typer.testing import CliRunner

    from aso.cli.main import _service, app

    resultado = CliRunner().invoke(app, ["run", DEMANDA_MULTIDOMINIO])
    assert resultado.exit_code == 0
    linha = next(ln for ln in resultado.stdout.splitlines() if "Orquestração criada" in ln)
    oid = linha.split(":", 1)[1].strip()

    brief = _service.get_demand_brief(oid)
    assert brief.risco == RiskLevel.HIGH
    cards = _service.get_cards(oid)
    assert cards
    assert all(c.priority == RiskLevel.HIGH for c in cards)


# --------------------------------------------------------------------------- Ponto 2


def test_retriagem_antes_de_executar_replaneja_a_equipe() -> None:
    svc = OrchestrationService(catalog=_cli_triagem("{}"))  # começa sem sinal útil
    orch = svc.create_with_triage("melhorar")
    plano_antes = svc._bundle(orch.id).plan  # noqa: SLF001
    assert plano_antes.strategy == ExecutionStrategy.SINGLE_AGENT
    cards_antes = svc.get_cards(orch.id)
    assert all(c.priority == RiskLevel.LOW for c in cards_antes)

    # O operador configura um agente de triagem melhor e re-tria.
    bruto = (
        '{"objetivo": "Login social seguro", "dominios": ["backend", "security"], '
        '"impactos": ["security"], "risco": "high"}'
    )
    svc.set_agent_assignment(orch.id, TRIAGE_KEY, executor="triador")
    svc._catalog = _cli_triagem(bruto)  # noqa: SLF001 - troca o catálogo pelo agente rico
    svc._triage._catalog = svc._catalog  # noqa: SLF001

    resultado = svc.retriage_demand(orch.id, executor="triador")

    assert resultado["replanned"] is True
    assert resultado["demand_brief"].risco == RiskLevel.HIGH
    plano_depois = svc._bundle(orch.id).plan  # noqa: SLF001
    assert plano_depois.strategy != ExecutionStrategy.SINGLE_AGENT
    assert any(a.agent == "ReviewAgent" for a in plano_depois.agents)
    cards_depois = svc.get_cards(orch.id)
    assert all(c.priority == RiskLevel.HIGH for c in cards_depois)
    eventos = [e.type for e in svc.timeline(orch.id)]
    assert "Replanned" in eventos
    assert "ReplanSkipped" not in eventos


def test_retriagem_depois_de_executar_preserva_o_plano() -> None:
    svc = OrchestrationService()
    orch = svc.create_with_triage("melhorar")
    plano_antes = svc._bundle(orch.id).plan  # noqa: SLF001
    card = svc.get_cards(orch.id)[0]
    # Card saiu de Ready: o trabalho já começou.
    svc._bundle(orch.id).board_service.move_card(card.id, ColumnKey.IN_PROGRESS)  # noqa: SLF001

    resultado = svc.retriage_demand(orch.id)

    assert resultado["replanned"] is False
    assert resultado["replan_reason"]
    plano_depois = svc._bundle(orch.id).plan  # noqa: SLF001
    assert plano_depois.strategy == plano_antes.strategy
    assert plano_depois.id == plano_antes.id  # o mesmo objeto de plano, não recriado
    eventos = [e.type for e in svc.timeline(orch.id)]
    assert "ReplanSkipped" in eventos
    assert "Replanned" not in eventos
