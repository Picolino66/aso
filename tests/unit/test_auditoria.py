"""Auditoria cross-demanda (Tela 28, wf §30, ADR-0051)."""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from aso.control.orchestration_service import OrchestrationService
from aso.execution.catalog import ExecutorCatalog, ExecutorProfile
from aso.shared.types import ColumnKey


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    run = lambda *a: subprocess.run(["git", *a], cwd=path, check=True, capture_output=True)  # noqa: E731
    run("init", "-q")
    run("config", "user.email", "t@t")
    run("config", "user.name", "t")
    (path / "README.md").write_text("base\n")
    run("add", "-A")
    run("commit", "-q", "-m", "init")


def _catalogo() -> ExecutorCatalog:
    script = 'cat > /dev/null; echo "x = 1" > feature.py; git add -A && git commit -q -m feat'
    comando = shlex.join(["bash", "-c", script])
    return ExecutorCatalog([ExecutorProfile(name="implementador", kind="cli", command=comando)])


def _mover(
    svc: OrchestrationService,
    orchestration_id: str,
    card_id: str,
    destino: ColumnKey,
    **kwargs: object,
) -> None:
    """Movimentação manual com metadados extras (actor/reason/result) — o wrapper
    `svc.move_card` só aceita `to_column`; testes que precisam de mais usam o
    bundle diretamente, mesmo padrão já usado em `test_ficha_do_card.py`."""
    b = svc._bundle(orchestration_id)  # noqa: SLF001
    b.board_service.move_card(card_id, destino, **kwargs)  # type: ignore[arg-type]
    svc._persist(b)  # noqa: SLF001


def test_move_card_manual_deixa_campos_novos_em_branco() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("demanda qualquer")
    card = svc.get_cards(orch.id)[0]
    svc.move_card(orch.id, card.id, "InProgress")
    pagina = svc.audit_page()
    assert pagina["total"] == 1
    item = pagina["items"][0]
    assert item["model"] is None
    assert item["effort"] is None
    assert item["phase"] is None
    assert item["execution_id"] is None


def test_run_card_preenche_effort_fase_e_execution_id(tmp_path: Path) -> None:
    repo = tmp_path / "proj"
    _init_repo(repo)
    svc = OrchestrationService(catalog=_catalogo())
    orch = svc.create_orchestration(
        "ajustar módulo", executor="implementador", effort="medium", target_path=str(repo)
    )
    card = svc.get_cards(orch.id)[0]
    svc.run_card(orch.id, card.id)

    pagina = svc.audit_page()
    eventos_da_execucao = [i for i in pagina["items"] if i["execution_id"] is not None]
    assert eventos_da_execucao
    ids_de_execucao = {i["execution_id"] for i in eventos_da_execucao}
    assert len(ids_de_execucao) == 1  # mesma execução, mesmo id em todos os eventos dela
    for item in eventos_da_execucao:
        assert item["effort"]
        assert item["phase"] == "F5"


def test_audit_page_filtra_por_agente_etapa_e_resultado() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("demanda qualquer")
    card = svc.get_cards(orch.id)[0]
    _mover(svc, orch.id, card.id, ColumnKey.IN_PROGRESS, actor="humano-x", result="ok manual")
    _mover(svc, orch.id, card.id, ColumnKey.TESTING, actor="automation", result="rodou testes")

    por_agente = svc.audit_page(agente="humano-x")
    assert por_agente["total"] == 1
    assert por_agente["items"][0]["actor"] == "humano-x"

    por_resultado = svc.audit_page(resultado="manual")
    assert por_resultado["total"] == 1
    assert por_resultado["items"][0]["result"] == "ok manual"

    por_etapa_inexistente = svc.audit_page(etapa="F9")
    assert por_etapa_inexistente["total"] == 0


def test_audit_page_filtra_por_demanda_e_e_cross_orquestracao() -> None:
    svc = OrchestrationService()
    orch1 = svc.create_orchestration("demanda um")
    orch2 = svc.create_orchestration("demanda dois")
    card1 = svc.get_cards(orch1.id)[0]
    card2 = svc.get_cards(orch2.id)[0]
    svc.move_card(orch1.id, card1.id, "InProgress")
    svc.move_card(orch2.id, card2.id, "InProgress")

    tudo = svc.audit_page()
    assert tudo["total"] == 2

    so_orch1 = svc.audit_page(orchestration_id=orch1.id)
    assert so_orch1["total"] == 1
    assert so_orch1["items"][0]["orchestration_id"] == orch1.id


def test_audit_page_pagina_corretamente() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("demanda qualquer")
    card = svc.get_cards(orch.id)[0]
    for status in ("Planning", "WaitingHuman", "Ready", "InProgress"):
        svc.move_card(orch.id, card.id, status)

    pagina1 = svc.audit_page(page=1, page_size=2)
    assert pagina1["total"] == 4
    assert len(pagina1["items"]) == 2
    pagina2 = svc.audit_page(page=2, page_size=2)
    assert len(pagina2["items"]) == 2
    ids_pagina1 = {i["id"] for i in pagina1["items"]}
    ids_pagina2 = {i["id"] for i in pagina2["items"]}
    assert not ids_pagina1 & ids_pagina2


def test_export_audit_devolve_csv_com_os_quatorze_campos() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("demanda para exportar")
    card = svc.get_cards(orch.id)[0]
    _mover(svc, orch.id, card.id, ColumnKey.IN_PROGRESS, reason="motivo x", result="resultado y")

    csv_text = svc.export_audit()
    linhas = csv_text.strip().splitlines()
    assert len(linhas) == 2  # cabeçalho + 1 registro
    cabecalho = linhas[0]
    for rotulo in [
        "Data e hora",
        "Projeto",
        "Demanda",
        "Card",
        "Etapa",
        "Agente",
        "Modelo",
        "Effort",
        "Ação",
        "Motivo",
        "Resultado",
        "Evidências",
        "Próxima ação",
        "Identificador da execução",
    ]:
        assert rotulo in cabecalho
    assert "motivo x" in linhas[1]
    assert "resultado y" in linhas[1]
