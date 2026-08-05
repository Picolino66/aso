"""Aprendizado da esteira (§24 do fluxo.md, ADR-0025) — `observability/aprendizado.py`.

Puro: cada teste monta `CardSnapshot`/`PullRequestSnapshot` diretamente, sem
depender de `OrchestrationService` (isso é papel do coletor, testado à parte).
"""

from __future__ import annotations

import ast
from pathlib import Path

from aso.observability.aprendizado import CardSnapshot, PullRequestSnapshot, consolidar


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
