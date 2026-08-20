"""Classificação editável e painel de recomendação (Telas 05/13, wf §7/§15) — ADR-0044."""

from __future__ import annotations

from pathlib import Path

from aso.control.orchestration_service import OrchestrationService, _faixa
from aso.control.routing_rules import RoutingAction, RoutingCondition
from aso.kanban.models import KanbanCard
from aso.shared.types import AssigneeType, CardType, ColumnKey, Phase, RiskLevel


def _svc() -> OrchestrationService:
    return OrchestrationService()


def test_update_classification_altera_so_os_campos_informados() -> None:
    svc = _svc()
    orch = svc.create_orchestration("demanda", demand_brief=None, seed_cards=False)
    svc.update_classification(orch.id, tipo="seguranca", risco=RiskLevel.HIGH)
    brief = svc.get_demand_brief(orch.id)
    assert brief.tipo == "seguranca"
    assert brief.risco == RiskLevel.HIGH


def test_update_classification_registra_evento_com_antes_e_depois() -> None:
    svc = _svc()
    orch = svc.create_orchestration("demanda", seed_cards=False)
    svc.update_classification(orch.id, complexidade="complexa", actor="ana")
    eventos = svc.timeline(orch.id)
    evento = next(e for e in eventos if e.type == "ClassificationUpdated")
    assert evento.payload["actor"] == "ana"
    assert evento.payload["after"]["complexidade"] == "complexa"
    assert "before" in evento.payload


def test_preview_recommendation_usa_regra_quando_bate() -> None:
    svc = _svc()
    svc.create_routing_rule(
        nome="Segurança crítica",
        descricao="",
        ativa=True,
        precedencia=1,
        condicoes=[RoutingCondition(campo="tipo", operador="igual", valor="seguranca")],
        acao=RoutingAction(modelo="claude-opus-high", effort="max", aprovacao_humana=True),
        actor="system",
    )
    orch = svc.create_orchestration(
        "demanda de seguranca",
        demand_brief=None,
        seed_cards=False,
    )
    svc.update_classification(orch.id, tipo="seguranca")

    recomendacao = svc.preview_recommendation(orch.id)
    assert recomendacao["modelo"] == "claude-opus-high"
    assert recomendacao["effort"] == "max"
    assert recomendacao["aprovacao_humana"] is True
    assert recomendacao["confianca"] == "alta"
    assert recomendacao["fonte"].startswith("regra:")
    assert "Segurança crítica" in recomendacao["motivos"][0]


def test_preview_recommendation_cai_na_heuristica_sem_regra() -> None:
    svc = _svc()
    orch = svc.create_orchestration("demanda comum", seed_cards=False)

    recomendacao = svc.preview_recommendation(orch.id)
    assert recomendacao["modelo"] is None
    assert recomendacao["confianca"] == "baixa"
    assert recomendacao["fonte"] == "heuristica"
    assert recomendacao["agente"]
    assert recomendacao["effort"]


def test_preview_recommendation_nao_persiste_nada() -> None:
    svc = _svc()
    orch = svc.create_orchestration("demanda comum", seed_cards=False)
    svc.preview_recommendation(orch.id)
    depois = svc.get(orch.id)
    assert depois.selected_executor is None
    assert depois.selected_effort is None


def test_estimar_custo_e_tempo_sem_modelo_recomendado_e_none() -> None:
    svc = _svc()
    custo, tempo = svc._estimar_custo_e_tempo(None)  # noqa: SLF001
    assert custo is None
    assert tempo is None


# --------------------------------------------- _faixa (wf §15.3, bug real: empate)


def test_faixa_sem_empate_usa_a_posicao_normal() -> None:
    todos = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0]
    assert _faixa(10.0, todos) == "baixo"
    assert _faixa(50.0, todos) == "médio"
    assert _faixa(90.0, todos) == "alto"


def _card_entregue(
    svc: OrchestrationService, orch_id: str, *, executor: str, custo_usd: float
) -> None:
    b = svc._bundle(orch_id)  # noqa: SLF001
    board = b.board_service.get_board(b.board.id)  # noqa: SLF001
    card = KanbanCard(
        board_id=board.id,
        orchestration_id=orch_id,
        phase=Phase.F5,
        type=CardType.TASK,
        title=f"card de {executor}",
        assignee_type=AssigneeType.AGENT,
        assignee="BackendDevelopmentAgent",
        status=ColumnKey.DONE,
        executor=executor,
        uso={"custo_usd": custo_usd},
    )
    b.board_service.add_card(card)
    svc._persist(b)  # noqa: SLF001


def test_estimar_custo_e_tempo_com_project_id_nao_hidrata_o_sistema_inteiro(
    tmp_path: Path,
) -> None:
    """Bug real (code-review ultra): `_estimar_custo_e_tempo` chamava
    `get_learning_report_global()` SEM filtro nenhum — um endpoint só-leitura
    (Tela 13, `preview_recommendation`) hidratando toda orquestração do sistema a
    cada chamada. Recortando por `project_id`, o resultado passa a refletir só o
    histórico do PROJETO da orquestração — aqui, um valor "alto" dentro do projeto
    (3 amostras) vira "baixo" quando 10 orquestrações bem mais caras de FORA do
    projeto entram na conta (13 amostras)."""
    svc = _svc()
    pasta_projeto = tmp_path / "a"
    pasta_projeto.mkdir()
    projeto = svc.create_project(
        name="Projeto A", description="", target_path=str(pasta_projeto), actor="op"
    )
    orch = svc.create_orchestration("demanda do projeto", project_id=projeto.id, seed_cards=False)
    _card_entregue(svc, orch.id, executor="claude-barato", custo_usd=1.0)
    _card_entregue(svc, orch.id, executor="claude-medio", custo_usd=500.0)
    _card_entregue(svc, orch.id, executor="claude-x", custo_usd=1000.0)

    # Isolado no projeto: "claude-x" é o mais caro das 3 amostras -> "alto".
    custo_escopado, _ = svc._estimar_custo_e_tempo(  # noqa: SLF001
        "claude-x", project_id=projeto.id
    )
    assert custo_escopado == "alto"

    # 10 orquestrações FORA do projeto, todas mais caras que "claude-x".
    for i in range(10):
        outra = svc.create_orchestration(f"demanda externa {i}", seed_cards=False)
        _card_entregue(svc, outra.id, executor=f"executor-caro-{i}", custo_usd=2000.0 + i)

    # Sem recorte (comportamento antigo, bug): "claude-x" cai para "baixo" entre
    # as 13 amostras globais — o histórico do projeto vira ruído.
    custo_global, _ = svc._estimar_custo_e_tempo("claude-x")  # noqa: SLF001
    assert custo_global == "baixo"

    # Com o recorte corrigido, o resultado do projeto continua estável.
    custo_escopado_de_novo, _ = svc._estimar_custo_e_tempo(  # noqa: SLF001
        "claude-x", project_id=projeto.id
    )
    assert custo_escopado_de_novo == "alto"


def test_faixa_com_empate_usa_o_rank_medio_do_grupo_nao_o_mais_baixo() -> None:
    """Bug real (code-review ultra): `sorted(todos).index(valor)` sempre devolve a
    1ª ocorrência — um grupo de 3 valores empatados na 3ª/4ª/5ª posição de 5 caía
    todo no rank 0 (`index` acha só o primeiro `10.0`), classificando "baixo" para
    os três, mesmo eles sendo o topo do custo. Com rank médio do grupo empatado
    (posição 2 de 0-4), o grupo cai em "alto" — correto, é o valor mais caro."""
    todos = [10.0, 10.0, 10.0, 5.0, 1.0]
    # grupo empatado em 10.0 ocupa os ranks 2,3,4 (os 3 maiores) — rank médio 3.
    assert _faixa(10.0, todos) == "alto"
    assert _faixa(1.0, todos) == "baixo"
