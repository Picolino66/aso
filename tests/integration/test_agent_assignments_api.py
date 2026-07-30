"""Escolha de agente por etapa via API + efeito real na execução (ADR-0014)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.models import NAMING_KEY
from aso.control.orchestration_service import OrchestrationService
from aso.execution.branch_naming import slugify
from aso.execution.catalog import ExecutorCatalog, ExecutorProfile
from aso.execution.workspace import WorkspaceService
from aso.kanban.models import KanbanCard
from aso.shared.types import CardType, ColumnKey, Phase


def _catalogo() -> ExecutorCatalog:
    """Dois executores CLI que marcam por qual deles o card passou."""
    return ExecutorCatalog(
        [
            ExecutorProfile(
                name="barato",
                kind="cli",
                effort="low",
                is_default=True,
                command='bash -c "cat > /dev/null; echo barato > quem-rodou.txt"',
            ),
            ExecutorProfile(
                name="forte",
                kind="cli",
                effort="high",
                command='bash -c "cat > /dev/null; echo forte > quem-rodou.txt"',
            ),
        ]
    )


def _svc_com_pasta(tmp_path: Path) -> tuple[OrchestrationService, str]:
    svc = OrchestrationService(catalog=_catalogo())
    orch = svc.create_orchestration("Calculadora básica", target_path=str(tmp_path))
    WorkspaceService().ensure_git(tmp_path)
    return svc, orch.id


def _diff_da_branch(repo: Path, branch: str) -> str:
    return subprocess.run(
        ["git", "diff", f"HEAD...{branch}"], cwd=repo, capture_output=True, text=True
    ).stdout


def test_put_e_delete_de_assignment(tmp_path: Path) -> None:
    svc, oid = _svc_com_pasta(tmp_path)
    client = TestClient(create_app(svc))

    resposta = client.put(
        f"/v1/orchestrations/{oid}/agents/F5", json={"executor": "forte", "effort": "high"}
    )
    assert resposta.status_code == 200
    assert resposta.json()["agent_assignments"]["F5"] == {"executor": "forte", "effort": "high"}

    assert client.delete(f"/v1/orchestrations/{oid}/agents/F5").status_code == 200
    assert client.get(f"/v1/orchestrations/{oid}").json()["agent_assignments"] == {}


def test_put_do_nomeador(tmp_path: Path) -> None:
    svc, oid = _svc_com_pasta(tmp_path)
    client = TestClient(create_app(svc))
    resposta = client.put(
        f"/v1/orchestrations/{oid}/agents/{NAMING_KEY}", json={"executor": "barato"}
    )
    assert resposta.status_code == 200
    assert resposta.json()["agent_assignments"][NAMING_KEY]["executor"] == "barato"


def test_etapa_invalida_devolve_409(tmp_path: Path) -> None:
    svc, oid = _svc_com_pasta(tmp_path)
    client = TestClient(create_app(svc))
    resposta = client.put(f"/v1/orchestrations/{oid}/agents/F42", json={"executor": "forte"})
    assert resposta.status_code == 409
    assert "Etapa inválida" in resposta.json()["detail"]


def test_executor_inexistente_devolve_409(tmp_path: Path) -> None:
    svc, oid = _svc_com_pasta(tmp_path)
    client = TestClient(create_app(svc))
    resposta = client.put(f"/v1/orchestrations/{oid}/agents/F5", json={"executor": "fantasma"})
    assert resposta.status_code == 409


def test_orquestracao_inexistente_devolve_404(tmp_path: Path) -> None:
    svc, _ = _svc_com_pasta(tmp_path)
    client = TestClient(create_app(svc))
    resposta = client.put(
        "/v1/orchestrations/orch_nao_existe/agents/F5", json={"executor": "forte"}
    )
    assert resposta.status_code == 404


def test_cada_etapa_roda_com_o_seu_executor(tmp_path: Path) -> None:
    """O ponto central da ADR-0014: F1 e F5 na MESMA orquestração, agentes diferentes."""
    svc, oid = _svc_com_pasta(tmp_path)
    client = TestClient(create_app(svc))
    client.put(f"/v1/orchestrations/{oid}/agents/F1", json={"executor": "barato"})
    client.put(f"/v1/orchestrations/{oid}/agents/F5", json={"executor": "forte"})

    b = svc._bundle(oid)  # noqa: SLF001
    card_f1 = b.board_service.get_card(svc.get_cards(oid)[0].id)
    assert card_f1 is not None
    card_f1.phase = Phase.F1
    card_f5 = b.board_service.add_card(
        KanbanCard(
            board_id=b.board.id,
            orchestration_id=oid,
            phase=Phase.F5,
            type=CardType.FEATURE,
            title="Somar dois números",
            status=ColumnKey.READY,
            assignee=card_f1.assignee,
        )
    )

    svc.run_card(oid, card_f1.id)
    svc.run_card(oid, card_f5.id)
    branch_f1 = b.board_service.get_card(card_f1.id).branch
    branch_f5 = b.board_service.get_card(card_f5.id).branch
    assert branch_f1 and branch_f5
    # Mesma orquestração, mesma execução: cada card rodou pelo executor da SUA fase.
    assert "barato" in _diff_da_branch(tmp_path, branch_f1)
    assert "forte" in _diff_da_branch(tmp_path, branch_f5)


def test_branch_do_card_sai_do_titulo(tmp_path: Path) -> None:
    svc, oid = _svc_com_pasta(tmp_path)
    card = svc.get_cards(oid)[0]
    svc.run_card(oid, card.id)
    branch = svc._bundle(oid).board_service.get_card(card.id).branch  # noqa: SLF001
    assert branch is not None
    assert branch.split("/")[0] in {"feat", "fix", "docs", "test", "chore", "refactor"}
    assert slugify(card.title) in branch
    assert "BackendDevelopmentAgent-" not in branch  # o nome antigo, baseado no papel


def test_retry_de_card_gera_branch_nova_sem_colidir(tmp_path: Path) -> None:
    """O mesmo card executado duas vezes não pode colidir em `git worktree add`."""
    svc, oid = _svc_com_pasta(tmp_path)
    card = svc.get_cards(oid)[0]
    svc.run_card(oid, card.id)
    primeira = svc._bundle(oid).board_service.get_card(card.id).branch  # noqa: SLF001
    svc._bundle(oid).board_service.get_card(card.id).status = ColumnKey.READY  # noqa: SLF001
    svc.run_card(oid, card.id)
    segunda = svc._bundle(oid).board_service.get_card(card.id).branch  # noqa: SLF001
    assert primeira and segunda and primeira != segunda
    assert primeira.rsplit("-", 1)[0] == segunda.rsplit("-", 1)[0]  # mesma raiz semântica


def test_card_chega_ao_agente_com_titulo_e_criterios(tmp_path: Path) -> None:
    """Antes o agente só recebia a demanda global — nunca sabia qual card era."""
    svc, oid = _svc_com_pasta(tmp_path)
    card = svc.get_cards(oid)[0]
    board = svc._bundle(oid).board_service  # noqa: SLF001
    alvo = board.get_card(card.id)
    alvo.title = "Exportar relatório em PDF"
    alvo.acceptance_criteria = ["Gera o arquivo", "Abre no leitor"]
    spec = svc._bundle(oid).agent_registry.get(alvo.assignee)  # noqa: SLF001
    task = svc._build_task(svc._bundle(oid), alvo, spec)  # noqa: SLF001

    assert task["content"]["card_title"] == "Exportar relatório em PDF"
    assert task["content"]["acceptance_criteria"] == ["Gera o arquivo", "Abre no leitor"]
    assert task["branch_stem"].endswith("exportar-relatorio-em-pdf")
    assert task["commit_subject"].endswith("Exportar relatório em PDF")
