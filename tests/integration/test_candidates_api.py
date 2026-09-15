"""(c) Endpoint de corrida de candidatos CLI + comparação no console (§26A.6).

Cobre o `POST .../cards/{cid}/race`: os candidatos são perfis CLI do catálogo (ADR-0076) —
marcados `candidato` ou escolhidos em `executores` —, rodam em paralelo em worktrees isolados e
devolvem a comparação de diffs; e o 409 quando nada está configurado.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.application.orchestration_service import OrchestrationService
from aso.execution.catalog import ExecutorCatalog, ExecutorProfile


def _svc(*candidatos: tuple[str, str], candidato: bool = True) -> OrchestrationService:
    perfis = [
        ExecutorProfile(name=nome, kind="cli", command=comando, candidato=candidato)
        for nome, comando in candidatos
    ]
    return OrchestrationService(catalog=ExecutorCatalog(perfis))


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    run = lambda *a: subprocess.run(["git", *a], cwd=path, check=True, capture_output=True)  # noqa: E731
    run("init", "-q")
    run("config", "user.email", "t@t")
    run("config", "user.name", "t")
    (path / "README.md").write_text("base\n")
    run("add", "-A")
    run("commit", "-q", "-m", "init")


def test_race_endpoint_compares_candidates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "proj"
    _init_repo(repo)
    monkeypatch.setenv("ASO_TARGET_REPO", str(repo))
    svc = _svc(
        ("claude", 'bash -c "echo a > sol_claude.py"'),
        ("codex", "bash -c \"printf 'a\\nb\\nc\\n' > sol_codex.py\""),
    )
    client = TestClient(create_app(svc))
    orch = svc.create_orchestration("implementar no backend")
    card = svc.get_cards(orch.id)[0]

    resp = client.post(f"/v1/orchestrations/{orch.id}/cards/{card.id}/race")
    assert resp.status_code == 200
    comparison = resp.json()
    assert {c["executor"] for c in comparison["candidates"]} == {"claude", "codex"}
    assert comparison["recommended_branch"] in {c["branch"] for c in comparison["candidates"]}
    # candidatos tocam arquivos diferentes, em worktrees isolados
    files = {tuple(c["files"]) for c in comparison["candidates"]}
    assert files == {("sol_claude.py",), ("sol_codex.py",)}
    # o diff de cada candidato acompanha a comparação (para o painel lado a lado)
    claude = next(c for c in comparison["candidates"] if c["executor"] == "claude")
    assert "sol_claude.py" in claude["diff"]


def test_race_endpoint_409_when_unconfigured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ASO_TARGET_REPO", raising=False)
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    orch = svc.create_orchestration("backend")
    card = svc.get_cards(orch.id)[0]

    resp = client.post(f"/v1/orchestrations/{orch.id}/cards/{card.id}/race")
    assert resp.status_code == 409
    assert "candidato" in resp.json()["detail"].lower()


def test_race_is_persisted_and_listed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "proj"
    _init_repo(repo)
    monkeypatch.setenv("ASO_TARGET_REPO", str(repo))
    svc = _svc(
        ("claude", 'bash -c "echo a > s.py"'),
    )
    client = TestClient(create_app(svc))
    orch = svc.create_orchestration("backend")
    oid = orch["id"] if isinstance(orch, dict) else orch.id
    card_id = svc.get_cards(oid)[0].id

    race = client.post(f"/v1/orchestrations/{oid}/cards/{card_id}/race").json()
    assert race["run_id"].startswith("race")

    # sobrevive à reidratação a partir do repositório (não fica só em memória)
    svc._bundles.clear()  # noqa: SLF001
    runs = client.get(f"/v1/orchestrations/{oid}/candidate-runs").json()
    assert len(runs) == 1
    assert runs[0]["id"] == race["run_id"]
    assert runs[0]["card_id"] == card_id
    assert runs[0]["recommended_branch"] == race["recommended_branch"]
    assert runs[0]["candidates"][0]["executor"] == "claude"
    # filtro por card
    by_card = client.get(
        f"/v1/orchestrations/{oid}/candidate-runs", params={"card_id": card_id}
    ).json()
    assert len(by_card) == 1


def test_race_assincrona_devolve_202_e_a_comparacao_fica_no_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MEL-31 (ADR-0067): com a fila ligada, a corrida roda no worker e o resultado é o mesmo."""
    import time

    repo = tmp_path / "proj"
    _init_repo(repo)
    monkeypatch.setenv("ASO_TARGET_REPO", str(repo))
    svc = _svc(
        ("claude", 'bash -c "echo a > sol_claude.py"'),
        ("codex", 'bash -c "echo b > sol_codex.py"'),
    )
    client = TestClient(create_app(svc, execucao_assincrona=True))
    orch = svc.create_orchestration("implementar no backend")
    card = svc.get_cards(orch.id)[0]

    resp = client.post(f"/v1/orchestrations/{orch.id}/cards/{card.id}/race")
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    limite = time.monotonic() + 30
    job = client.get(f"/v1/jobs/{job_id}").json()
    while job["status"] in ("queued", "running") and time.monotonic() < limite:
        time.sleep(0.05)
        job = client.get(f"/v1/jobs/{job_id}").json()
    assert job["status"] == "done"
    assert {c["executor"] for c in job["resultado"]["candidates"]} == {"claude", "codex"}
    assert svc.list_candidate_runs(orch.id)  # corrida persistida como antes
