"""Workspace por orquestração: bootstrap git, docs-first e execução na pasta."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from aso.application.orchestration_service import OrchestrationService
from aso.execution.branch_naming import slugify
from aso.execution.catalog import ExecutorCatalog, ExecutorProfile
from aso.execution.workspace import WorkspaceAnalyzer, WorkspaceError, WorkspaceService


def _git_out(path: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=path, capture_output=True, text=True).stdout.strip()


def test_ensure_git_cria_repo_com_head(tmp_path: Path) -> None:
    ws = WorkspaceService()
    initialized = ws.ensure_git(tmp_path)
    assert initialized is True
    assert (tmp_path / ".git").exists()
    # HEAD válido (worktrees exigem) e .gitignore com .aso/worktrees/
    assert _git_out(tmp_path, "rev-parse", "--verify", "HEAD")
    assert ".aso/worktrees/" in (tmp_path / ".gitignore").read_text(encoding="utf-8")
    # idempotente
    assert ws.ensure_git(tmp_path) is False


def _mock_catalog() -> ExecutorCatalog:
    return ExecutorCatalog([ExecutorProfile(name="mock", kind="mock", is_default=True)])


def test_analyze_folder_pasta_sem_git_exige_confirmacao(tmp_path: Path) -> None:
    svc = OrchestrationService(catalog=_mock_catalog())
    orch = svc.create_orchestration("um projeto novo", target_path=str(tmp_path))
    with pytest.raises(WorkspaceError, match="inicializar_git"):
        svc.analyze_folder(orch.id)
    assert not (tmp_path / ".git").exists()  # nada foi inicializado sem confirmação


def test_analyze_folder_pasta_vazia_gera_scaffold(tmp_path: Path) -> None:
    svc = OrchestrationService(catalog=_mock_catalog())
    orch = svc.create_orchestration("um projeto novo", target_path=str(tmp_path))
    out = svc.analyze_folder(orch.id, inicializar_git=True)
    assert out["mode"] == "scaffold"
    # Repo recém-criado pelo ASO numa pasta vazia: único caso de commit direto (ADR-0062).
    assert out["entrega"] == "commit_direto"
    assert out["git_initialized"] is True
    assert any(e.type == "WorkspaceGitInitialized" for e in svc.timeline(orch.id))
    assert (tmp_path / "docs" / "index.md").is_file()
    assert (tmp_path / "docs" / "modules").is_dir()
    assert (tmp_path / "docs" / "modules" / "projeto" / "projeto.md").is_file()
    # commit determinístico do scaffold aconteceu
    assert "docs/index.md" in _git_out(tmp_path, "ls-files")
    rep = WorkspaceAnalyzer().analyze(tmp_path)
    assert rep.has_aso_docs is True
    assert svc.get(orch.id).workspace_prepared is True


def test_retry_com_apenas_scaffold_de_seguranca_permanece_deterministico(tmp_path: Path) -> None:
    ws = WorkspaceService()
    ws.ensure_git(tmp_path)
    modules = tmp_path / "docs" / "modules"
    modules.mkdir(parents=True)
    (modules / ".gitkeep").write_text("", encoding="utf-8")
    (tmp_path / "docs" / "index.md").write_text(
        "# Projeto — Documentação (docs-first)\n\n"
        "> Fonte de verdade para IA\n\n"
        "_Nenhum módulo ainda. Adicione um em `modules/<módulo>/index.md`._\n",
        encoding="utf-8",
    )
    ws.commit_all(tmp_path, "aso: docs-first (scaffold de segurança)")
    svc = OrchestrationService(catalog=_mock_catalog())
    orch = svc.create_orchestration("um projeto novo", target_path=str(tmp_path))

    base_antes = _git_out(tmp_path, "rev-parse", "HEAD")

    out = svc.analyze_folder(orch.id)

    assert out["mode"] == "scaffold"
    # Repo com histórico: o scaffold vai por PR, a base não muda (ADR-0062).
    assert out["entrega"] == "pr"
    assert _git_out(tmp_path, "rev-parse", "HEAD") == base_antes
    pr = next(p for p in svc.list_pulls(orch.id) if p.id == out["pr_id"])
    feature = _git_out(tmp_path, "show", f"{pr.branch}:docs/modules/projeto/projeto.md")
    assert feature.count("## ") == 8
    assert svc.get(orch.id).workspace_prepared is True


def test_analyze_folder_projeto_existente_com_agente_cli(tmp_path: Path) -> None:
    # Projeto existente (não vazio) já em git.
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('oi')\n", encoding="utf-8")
    WorkspaceService().ensure_git(tmp_path)
    # Executor CLI fake que escreve docs/ no worktree (simula o agente documentando).
    cmd = (
        "mkdir -p docs/modules/src && "
        "printf '# docs\\n' > docs/index.md && "
        "printf '# src\\n' > docs/modules/src/src.md"
    )
    prof = ExecutorProfile(name="doccli", kind="cli", command=f'bash -c "{cmd}"', is_default=True)
    svc = OrchestrationService(catalog=ExecutorCatalog([prof]))
    orch = svc.create_orchestration("documente", target_path=str(tmp_path))
    base_antes = _git_out(tmp_path, "rev-parse", "HEAD")
    out = svc.analyze_folder(orch.id, executor="doccli")
    assert out["mode"] == "agent"
    # Regra 5/6 (ADR-0062): o diff do agente virou card Documentation + PR, sem tocar a base.
    assert out["entrega"] == "pr"
    assert _git_out(tmp_path, "rev-parse", "HEAD") == base_antes
    assert not (tmp_path / "docs" / "index.md").exists()
    card = next(c for c in svc.get_cards(orch.id) if c.id == out["card_id"])
    assert card.type.value == "Documentation"
    assert svc.get(orch.id).workspace_prepared is True

    # O merge da documentação exige as mesmas condições de qualquer PR.
    with pytest.raises(ValueError, match="CI 'passed'"):
        svc.merge_pr(orch.id, str(out["pr_id"]))
    svc.report_ci(orch.id, str(out["pr_id"]), "passed", justificativa="docs sem bateria")
    svc.report_review(orch.id, str(out["pr_id"]), "approved", justificativa="docs revisadas")
    svc.merge_pr(orch.id, str(out["pr_id"]))
    assert (tmp_path / "docs" / "index.md").is_file()
    assert WorkspaceAnalyzer().analyze(tmp_path).has_aso_docs is True


def test_falha_docs_preserva_orquestracao_para_retry(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("print('x')\n", encoding="utf-8")
    WorkspaceService().ensure_git(tmp_path)
    profile = ExecutorProfile(
        name="falha", kind="cli", command='bash -c "echo erro >&2; exit 1"', is_default=True
    )
    svc = OrchestrationService(catalog=ExecutorCatalog([profile]))
    orch = svc.create_orchestration("documente", target_path=str(tmp_path), executor="falha")
    with pytest.raises(WorkspaceError, match="Falha ao documentar"):
        svc.analyze_folder(orch.id, executor="falha")
    assert svc.get(orch.id).workspace_prepared is False
    assert any(
        event.type == "WorkspaceDocumentationFailed"
        for event in svc._bundle(orch.id).event_log.all()  # noqa: SLF001
    )


def test_run_card_roda_na_pasta_da_orquestracao(tmp_path: Path) -> None:
    # Executor CLI fake (default) que cria um arquivo; sem provider explícito, run_card
    # deve resolver o provider atrelado à pasta desta orquestração (não um repo global).
    prof = ExecutorProfile(
        name="cli",
        kind="cli",
        command='bash -c "echo gerado > gerado.py"',
        is_default=True,
    )
    svc = OrchestrationService(catalog=ExecutorCatalog([prof]))
    orch = svc.create_orchestration("backend", target_path=str(tmp_path))
    WorkspaceService().ensure_git(tmp_path)
    card = svc.get_cards(orch.id)[0]
    results = svc.run_card(orch.id, card.id)  # provider=None → _provider_for(pasta)
    assert results and results[0].status.value == "applied"
    # o worktree/branch foi criado na pasta da orquestração, batizado pelo card (ADR-0014)
    branches = _git_out(tmp_path, "branch")
    assert f"{slugify(card.title)}-" in branches


def test_run_card_default_para_repo_global_sem_pasta(tmp_path: Path) -> None:
    # Sem target_path: cai no provider global do bootstrap (comportamento legado).
    from aso.execution.cli_provider import CliAgentExecutionProvider

    repo = tmp_path / "global"
    repo.mkdir()
    WorkspaceService().ensure_git(repo)
    provider = CliAgentExecutionProvider(["bash", "-c", "echo x > f.txt"], str(repo))
    svc = OrchestrationService(provider=provider, catalog=_mock_catalog())
    orch = svc.create_orchestration("backend")  # sem pasta
    card = svc.get_cards(orch.id)[0]
    results = svc.run_card(orch.id, card.id)
    assert results and results[0].status.value == "applied"
    assert f"{slugify(card.title)}-" in _git_out(repo, "branch")


def test_conflito_no_merge_da_documentacao_registra_falha_e_mantem_card(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("print('x')\n", encoding="utf-8")
    WorkspaceService().ensure_git(tmp_path)
    (tmp_path / "LEIA.md").write_text("x\n", encoding="utf-8")
    WorkspaceService().commit_all(tmp_path, "historico do usuario")
    svc = OrchestrationService(catalog=_mock_catalog())
    orch = svc.create_orchestration("documente", target_path=str(tmp_path))
    out = svc.analyze_folder(orch.id)  # scaffold por PR
    pr_id = str(out["pr_id"])
    # A base diverge no mesmo arquivo que a PR cria → conflito real no merge.
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "index.md").write_text("conteúdo divergente\n", encoding="utf-8")
    WorkspaceService().commit_all(tmp_path, "docs manuais")
    svc.report_ci(orch.id, pr_id, "passed", justificativa="docs sem bateria")
    svc.report_review(orch.id, pr_id, "approved", justificativa="docs revisadas")

    with pytest.raises(ValueError, match="falhou"):
        svc.merge_pr(orch.id, pr_id)

    assert any(e.type == "DocsMergeFailed" for e in svc.timeline(orch.id))
    card = next(c for c in svc.get_cards(orch.id) if c.id == out["card_id"])
    assert card.status.value != "Done"  # não marcado como entregue
    assert next(p for p in svc.list_pulls(orch.id) if p.id == pr_id).status == "open"
    # O merge com conflito foi abortado: a base não ficou em estado de merge pela metade.
    assert not (tmp_path / ".git" / "MERGE_HEAD").exists()
    assert _git_out(tmp_path, "status", "--porcelain") == ""


def test_heal_docs_com_agente_nao_altera_a_base(tmp_path: Path) -> None:
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "a.py").write_text("x=1\n", encoding="utf-8")
    from aso.execution.docs_scaffold import write_scaffold

    write_scaffold(tmp_path, [])  # docs sem o módulo core → drift
    WorkspaceService().ensure_git(tmp_path)
    cmd = "mkdir -p docs/modules/core && printf '# core\\n' > docs/modules/core/core.md"
    prof = ExecutorProfile(name="doccli", kind="cli", command=f'bash -c "{cmd}"', is_default=True)
    svc = OrchestrationService(catalog=ExecutorCatalog([prof]))
    orch = svc.create_orchestration("documente", target_path=str(tmp_path))
    base_antes = _git_out(tmp_path, "rev-parse", "HEAD")
    out = svc.heal_docs(orch.id, executor="doccli")
    assert (out["mode"], out["entrega"]) == ("agent", "pr")
    assert _git_out(tmp_path, "rev-parse", "HEAD") == base_antes
    assert not (tmp_path / "docs" / "modules" / "core" / "core.md").exists()


def test_autopilot_em_pasta_sem_git_exige_confirmacao_pela_api(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from aso.api.app import create_app

    svc = OrchestrationService(catalog=_mock_catalog())
    client = TestClient(create_app(svc))
    oid = client.post(
        "/v1/orchestrations", json={"user_request": "x", "target_path": str(tmp_path)}
    ).json()["id"]
    recusa = client.post(f"/v1/orchestrations/{oid}/autopilot", json={})
    assert recusa.status_code == 409
    assert "inicializar_git" in recusa.json()["detail"]
    assert not (tmp_path / ".git").exists()
    ok = client.post(f"/v1/orchestrations/{oid}/autopilot", json={"inicializar_git": True})
    assert ok.status_code == 200
