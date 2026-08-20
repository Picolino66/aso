"""Aprendizado da esteira (§24 do fluxo.md, ADR-0025) — `observability/aprendizado.py`.

Puro: cada teste monta `CardSnapshot`/`PullRequestSnapshot` diretamente, sem
depender de `OrchestrationService` (isso é papel do coletor, testado à parte).
"""

from __future__ import annotations

import ast
from pathlib import Path

from aso.observability.aprendizado import (
    RECOMENDACAO_ADICIONAR_TESTE,
    RECOMENDACAO_AJUSTAR_ROTEAMENTO,
    RECOMENDACAO_ALTERAR_LIMITE_TENTATIVAS,
    RECOMENDACAO_AUMENTAR_EFFORT,
    RECOMENDACAO_CRIAR_AGENTE,
    RECOMENDACAO_CRIAR_TEMPLATE,
    RECOMENDACAO_EVITAR_MODELO,
    RECOMENDACAO_MODIFICAR_APROVACAO,
    CardSnapshot,
    PullRequestSnapshot,
    consolidar,
    recomendacoes_estruturadas,
)


def test_orquestracao_sem_historico_devolve_relatorio_vazio() -> None:
    relatorio = consolidar("orch_vazia", [], [])
    assert relatorio.total_cards == 0
    assert relatorio.total_falhas == 0
    assert relatorio.desempenho_por_executor == []
    assert relatorio.recomendacao == ""


def test_consolidar_agrega_por_executor() -> None:
    cards = [
        CardSnapshot(
            id="c1",
            executor="claude-opus",
            failures=[{"categoria": "testes", "etapa": "gate"}],
            tempo_ms=1000.0,
        ),
        CardSnapshot(id="c2", executor="claude-opus", failures=[], tempo_ms=2000.0),
        CardSnapshot(
            id="c3",
            executor="codex-high",
            failures=[
                {"categoria": "lint", "etapa": "gate"},
                {"categoria": "lint", "etapa": "gate"},
            ],
            tempo_ms=500.0,
        ),
    ]
    pulls = [
        PullRequestSnapshot(card_id="c1", review_rounds=2, review_status="approved"),
        PullRequestSnapshot(card_id="c3", review_rounds=1, review_status="changes_requested"),
    ]
    relatorio = consolidar("orch_x", cards, pulls, intervencoes_humanas=1)

    assert relatorio.total_cards == 3
    assert relatorio.total_falhas == 3
    assert relatorio.intervencoes_humanas == 1
    assert relatorio.falhas_por_etapa == {"gate": 3}
    assert relatorio.erros_recorrentes == {"testes": 1, "lint": 2}

    por_nome = {d.executor: d for d in relatorio.desempenho_por_executor}
    assert por_nome["claude-opus"].execucoes == 2
    assert por_nome["claude-opus"].falhas == 1
    assert por_nome["claude-opus"].tempo_medio_ms == 1500.0
    # c2 não tem PR (0 rodadas) — a média é sobre todos os cards do executor, não só
    # os que abriram PR.
    assert por_nome["claude-opus"].rodadas_de_revisao_media == 1.0
    assert por_nome["codex-high"].falhas == 2
    assert por_nome["codex-high"].erros_recorrentes == {"lint": 2}

    assert "codex-high" in relatorio.recomendacao  # pior taxa de falha (2/1... 100%)


def test_card_sem_executor_agrupa_em_bucket_proprio() -> None:
    relatorio = consolidar("orch_y", [CardSnapshot(id="c1", executor="", failures=[])], [])
    assert relatorio.desempenho_por_executor[0].executor == "(sem executor)"


def test_recomendacao_sem_falhas_e_informativa_nao_vazia() -> None:
    cards = [CardSnapshot(id="c1", executor="claude-opus", failures=[])]
    relatorio = consolidar("orch_z", cards, [])
    assert relatorio.recomendacao
    assert "Nenhuma falha" in relatorio.recomendacao


# --------------------------------------- Tela 29: indicadores novos (wf §31.1, ADR-0052)


def test_taxas_sem_denominador_ficam_none() -> None:
    """Sem decisão de aprovação/sem deploy/sem card executado — nunca 0 fabricado."""
    relatorio = consolidar("orch_a", [CardSnapshot(id="c1", executor="x", failures=[])], [])
    assert relatorio.taxa_aprovacao is None
    assert relatorio.taxa_rollback is None
    assert relatorio.taxa_sucesso_primeiro_ciclo is None
    assert relatorio.cobertura_de_testes is None  # SEMPRE None — sem fonte real


def test_taxas_calculadas_a_partir_de_contagens_brutas() -> None:
    relatorio = consolidar(
        "orch_b",
        [CardSnapshot(id="c1", executor="x", failures=[])],
        [],
        aprovados=3,
        decisoes_de_aprovacao=4,
        rollbacks=1,
        deploys=5,
        sucesso_primeiro_ciclo=2,
        cards_com_tentativa=4,
    )
    assert relatorio.taxa_aprovacao == 0.75
    assert relatorio.taxa_rollback == 0.2
    assert relatorio.taxa_sucesso_primeiro_ciclo == 0.5


def test_falhas_por_agente_agrupa_por_assignee_nao_por_modelo() -> None:
    cards = [
        CardSnapshot(
            id="c1",
            executor="opus",
            agente="BackendDevelopmentAgent",
            failures=[{"categoria": "lint", "etapa": "gate"}],
        ),
        CardSnapshot(
            id="c2",
            executor="sonnet",
            agente="BackendDevelopmentAgent",
            failures=[{"categoria": "lint", "etapa": "gate"}],
        ),
    ]
    relatorio = consolidar("orch_m", cards, [])
    assert relatorio.falhas_por_agente == {"BackendDevelopmentAgent": 2}
    # "por modelo" continua sendo um agrupamento DIFERENTE (por executor).
    executores = {d.executor for d in relatorio.desempenho_por_executor}
    assert executores == {"opus", "sonnet"}


def test_numero_medio_tentativas_a_partir_de_contagem_bruta() -> None:
    relatorio = consolidar(
        "orch_n",
        [CardSnapshot(id="c1", executor="x", failures=[])],
        [],
        soma_tentativas=9,
        cards_com_tentativa=3,
    )
    assert relatorio.numero_medio_tentativas == 3.0


def test_tempo_e_custo_medio_por_demanda_dividem_pelo_total_de_orquestracoes() -> None:
    cards = [
        CardSnapshot(id="c1", executor="x", failures=[], tempo_ms=1000.0, custo_usd=2.0),
        CardSnapshot(id="c2", executor="x", failures=[], tempo_ms=1000.0, custo_usd=2.0),
    ]
    relatorio = consolidar("orch_o", cards, [], total_orchestrations=2)
    assert relatorio.tempo_medio_por_demanda_ms == 1000.0  # 2000ms / 2 demandas
    assert relatorio.custo_medio_por_demanda_usd == 2.0  # 4.0 usd / 2 demandas


def test_tempo_medio_por_etapa_calcula_media() -> None:
    relatorio = consolidar(
        "orch_c",
        [CardSnapshot(id="c1", executor="x", failures=[])],
        [],
        tempo_por_etapa_ms={"F5": [1000.0, 2000.0], "F6": [500.0]},
    )
    assert relatorio.tempo_medio_por_etapa_ms == {"F5": 1500.0, "F6": 500.0}


# ------------------------------------ Tela 29: recomendações estruturadas (wf §31.3)


def test_recomendacoes_estruturadas_tem_oito_categorias_na_ordem_do_wireframe() -> None:
    relatorio = consolidar("orch_d", [], [])
    recomendacoes = recomendacoes_estruturadas(relatorio)
    assert len(recomendacoes) == 8
    tipos = [r["tipo"] for r in recomendacoes]
    assert tipos == [
        RECOMENDACAO_AUMENTAR_EFFORT,
        RECOMENDACAO_EVITAR_MODELO,
        RECOMENDACAO_CRIAR_AGENTE,
        RECOMENDACAO_ADICIONAR_TESTE,
        RECOMENDACAO_MODIFICAR_APROVACAO,
        RECOMENDACAO_ALTERAR_LIMITE_TENTATIVAS,
        RECOMENDACAO_CRIAR_TEMPLATE,
        RECOMENDACAO_AJUSTAR_ROTEAMENTO,
    ]


def test_duas_recomendacoes_ficam_permanentemente_desabilitadas() -> None:
    relatorio = consolidar("orch_e", [], [])
    recomendacoes = recomendacoes_estruturadas(relatorio)
    por_tipo = {r["tipo"]: r for r in recomendacoes}
    assert por_tipo[RECOMENDACAO_CRIAR_AGENTE]["disponivel"] is False
    assert por_tipo[RECOMENDACAO_CRIAR_TEMPLATE]["disponivel"] is False
    assert por_tipo[RECOMENDACAO_AUMENTAR_EFFORT]["disponivel"] is True


def test_sem_sinal_nenhuma_recomendacao_dispara() -> None:
    relatorio = consolidar("orch_f", [CardSnapshot(id="c1", executor="x", failures=[])], [])
    recomendacoes = recomendacoes_estruturadas(relatorio)
    assert not any(r["disparada"] for r in recomendacoes)


def test_falha_recorrente_dispara_aumentar_effort_com_justificativa() -> None:
    cards = [
        CardSnapshot(id="c1", executor="x", failures=[{"categoria": "lint", "etapa": "gate"}]),
        CardSnapshot(id="c2", executor="x", failures=[{"categoria": "lint", "etapa": "gate"}]),
    ]
    relatorio = consolidar("orch_g", cards, [])
    recomendacoes = recomendacoes_estruturadas(relatorio)
    por_tipo = {r["tipo"]: r for r in recomendacoes}
    assert por_tipo[RECOMENDACAO_AUMENTAR_EFFORT]["disparada"] is True
    assert "lint" in por_tipo[RECOMENDACAO_AUMENTAR_EFFORT]["justificativa"]


def test_falha_de_categoria_teste_dispara_adicionar_teste() -> None:
    cards = [
        CardSnapshot(id="c1", executor="x", failures=[{"categoria": "testes", "etapa": "gate"}]),
        CardSnapshot(id="c2", executor="x", failures=[{"categoria": "testes", "etapa": "gate"}]),
    ]
    relatorio = consolidar("orch_h", cards, [])
    recomendacoes = recomendacoes_estruturadas(relatorio)
    por_tipo = {r["tipo"]: r for r in recomendacoes}
    assert por_tipo[RECOMENDACAO_ADICIONAR_TESTE]["disparada"] is True


def test_modelo_com_metade_das_execucoes_falhas_dispara_evitar_modelo() -> None:
    cards = [
        CardSnapshot(id="c1", executor="ruim", failures=[{"categoria": "x", "etapa": "y"}]),
        CardSnapshot(id="c2", executor="ruim", failures=[]),
    ]
    relatorio = consolidar("orch_i", cards, [])
    recomendacoes = recomendacoes_estruturadas(relatorio)
    por_tipo = {r["tipo"]: r for r in recomendacoes}
    assert por_tipo[RECOMENDACAO_EVITAR_MODELO]["disparada"] is True
    assert "ruim" in por_tipo[RECOMENDACAO_EVITAR_MODELO]["justificativa"]


def test_taxa_aprovacao_baixa_dispara_modificar_criterios() -> None:
    relatorio = consolidar(
        "orch_j",
        [CardSnapshot(id="c1", executor="x", failures=[])],
        [],
        aprovados=1,
        decisoes_de_aprovacao=4,
    )
    recomendacoes = recomendacoes_estruturadas(relatorio)
    por_tipo = {r["tipo"]: r for r in recomendacoes}
    assert por_tipo[RECOMENDACAO_MODIFICAR_APROVACAO]["disparada"] is True


def test_intervencao_humana_alta_dispara_alterar_limite_tentativas() -> None:
    cards = [CardSnapshot(id=f"c{i}", executor="x", failures=[]) for i in range(3)]
    relatorio = consolidar("orch_k", cards, [], intervencoes_humanas=2)
    recomendacoes = recomendacoes_estruturadas(relatorio)
    por_tipo = {r["tipo"]: r for r in recomendacoes}
    assert por_tipo[RECOMENDACAO_ALTERAR_LIMITE_TENTATIVAS]["disparada"] is True


def test_retrabalho_alto_dispara_ajustar_roteamento() -> None:
    cards = [
        CardSnapshot(id="c1", executor="x", failures=[{"categoria": "y", "etapa": "z"}]),
        CardSnapshot(id="c2", executor="x", failures=[{"categoria": "y", "etapa": "z"}]),
        CardSnapshot(id="c3", executor="x", failures=[]),
    ]
    relatorio = consolidar("orch_l", cards, [])
    recomendacoes = recomendacoes_estruturadas(relatorio)
    por_tipo = {r["tipo"]: r for r in recomendacoes}
    assert por_tipo[RECOMENDACAO_AJUSTAR_ROTEAMENTO]["disparada"] is True


def test_aprendizado_nao_importa_control() -> None:
    """Regra de módulo (plano6 §3.4): `observability` importa só `shared` — o
    agregador não pode importar `control`, mesmo transitivamente via outro nome."""
    raiz = Path(__file__).resolve().parents[2]
    caminho = raiz / "src" / "aso" / "observability" / "aprendizado.py"
    arvore = ast.parse(caminho.read_text())
    modulos_importados: set[str] = set()
    for node in ast.walk(arvore):
        if isinstance(node, ast.ImportFrom) and node.module:
            modulos_importados.add(node.module)
        elif isinstance(node, ast.Import):
            modulos_importados.update(alias.name for alias in node.names)
    proibidos = {m for m in modulos_importados if m.startswith("aso.control")}
    assert not proibidos, f"aprendizado.py importa control: {proibidos}"
