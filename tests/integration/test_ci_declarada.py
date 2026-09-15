"""MEL-12 — CI executada × CI declarada (ADR-0056, regra inviolável 6).

Tentativas explícitas de satisfazer "merge só com CI passed" por declaração: operator
declarando `passed`, admin sem justificativa, e a origem da CI na ficha de encerramento.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.api.auth import AuthService, Principal
from aso.control.orchestration_service import OrchestrationService
from aso.execution.cli_provider import CliAgentExecutionProvider


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    run = lambda *a: subprocess.run(["git", *a], cwd=path, check=True, capture_output=True)  # noqa: E731
    run("init", "-q")
    run("config", "user.email", "t@t")
    run("config", "user.name", "t")
    (path / "README.md").write_text("base\n")
    run("add", "-A")
    run("commit", "-q", "-m", "init")


def _pr_aberta(tmp_path: Path, **kwargs: str) -> tuple[OrchestrationService, str, str]:
    repo = tmp_path / "proj"
    _init_repo(repo)
    provider = CliAgentExecutionProvider(["bash", "-c", "echo 'gerado' > feature.py"], str(repo))
    svc = OrchestrationService(provider=provider)
    orch = svc.create_orchestration("implementar no backend", **kwargs)
    card = svc.get_cards(orch.id)[0]
    svc.run_card(orch.id, card.id)  # abre a PR sozinho
    return svc, orch.id, svc.list_pulls(orch.id)[0].id


def test_servico_recusa_passed_declarado_sem_justificativa(tmp_path: Path) -> None:
    svc, oid, pr_id = _pr_aberta(tmp_path)
    with pytest.raises(ValueError, match="justificativa"):
        svc.report_ci(oid, pr_id, "passed")
    with pytest.raises(ValueError, match="justificativa"):
        svc.report_ci(oid, pr_id, "passed", justificativa="   ")
    pr = svc.list_pulls(oid)[0]
    assert (pr.ci_status, pr.ci_origem) == ("pending", "")
    # Sem CI passed o merge continua bloqueado.
    svc.report_review(oid, pr_id, "approved", justificativa="revisão manual do teste")
    with pytest.raises(ValueError, match="CI 'passed'"):
        svc.merge_pr(oid, pr_id)


def test_passed_declarado_com_justificativa_fica_rastreado(tmp_path: Path) -> None:
    svc, oid, pr_id = _pr_aberta(tmp_path)
    pr = svc.report_ci(oid, pr_id, "passed", actor="alice", justificativa="CI do GitLab ok")
    assert (pr.ci_status, pr.ci_origem) == ("passed", "declarada")
    declarados = [e.payload for e in svc.timeline(oid) if e.type == "CIDeclared"]
    assert declarados == [
        {"pr_id": pr_id, "status": "passed", "actor": "alice", "justificativa": "CI do GitLab ok"}
    ]


def test_failed_declarado_segue_livre_e_marca_origem(tmp_path: Path) -> None:
    svc, oid, pr_id = _pr_aberta(tmp_path)
    pr = svc.report_ci(oid, pr_id, "failed")
    assert (pr.ci_status, pr.ci_origem) == ("failed", "declarada")


def test_ci_executada_grava_origem_executada(tmp_path: Path) -> None:
    svc, oid, pr_id = _pr_aberta(tmp_path, validation_command="true")
    pr = svc.run_pr_ci(oid, pr_id)
    assert (pr.ci_status, pr.ci_origem) == ("passed", "executada")


@pytest.mark.parametrize(
    ("declarar", "origem_esperada"), [(True, "declarada"), (False, "executada")]
)
def test_ficha_de_encerramento_mostra_origem_da_ci(
    tmp_path: Path, declarar: bool, origem_esperada: str
) -> None:
    svc, oid, pr_id = _pr_aberta(tmp_path, validation_command="true")
    if declarar:
        svc.report_ci(oid, pr_id, "passed", justificativa="CI externa verificada")
    else:
        svc.run_pr_ci(oid, pr_id)
    svc.report_review(oid, pr_id, "approved", justificativa="revisão manual do teste")
    svc.merge_pr(oid, pr_id)
    ficha = svc.get_cards(oid)[0].closure
    assert ficha["ci_origem"] == origem_esperada
    assert f"CI: passed ({origem_esperada})" in ficha["evidencias"]


def test_api_operator_403_admin_sem_justificativa_409_com_justificativa_200(
    tmp_path: Path,
) -> None:
    svc, oid, pr_id = _pr_aberta(tmp_path)
    auth = AuthService(
        {
            "o": Principal(actor="op", role="operator"),
            "a": Principal(actor="adm", role="admin"),
        },
        dev_mode=False,
    )
    client = TestClient(create_app(svc, auth=auth))
    rota = f"/v1/orchestrations/{oid}/pulls/{pr_id}/ci"
    op = {"Authorization": "Bearer o"}
    adm = {"Authorization": "Bearer a"}

    burla = {"status": "passed", "justificativa": "confia"}
    assert client.post(rota, json=burla, headers=op).status_code == 403
    assert client.post(rota, json={"status": "passed"}, headers=adm).status_code == 409
    assert svc.list_pulls(oid)[0].ci_status == "pending"

    ok = client.post(rota, json={"status": "passed", "justificativa": "CI externa"}, headers=adm)
    assert ok.status_code == 200
    assert (ok.json()["ci_status"], ok.json()["ci_origem"]) == ("passed", "declarada")
    assert [e.payload["actor"] for e in svc.timeline(oid) if e.type == "CIDeclared"] == ["adm"]

    # Reprovar é seguro: operator continua podendo declarar `failed`.
    assert client.post(rota, json={"status": "failed"}, headers=op).status_code == 200


def test_ci_origem_persiste_no_repositorio_sql(tmp_path: Path) -> None:
    from aso.db.repository import SqlAlchemyOrchestrationRepository

    repo = tmp_path / "proj"
    _init_repo(repo)
    url = f"sqlite:///{tmp_path / 'ci.db'}"
    provider = CliAgentExecutionProvider(["bash", "-c", "echo x > f.py"], str(repo))
    svc = OrchestrationService(provider=provider, repository=SqlAlchemyOrchestrationRepository(url))
    orch = svc.create_orchestration("implementar no backend")
    svc.run_card(orch.id, svc.get_cards(orch.id)[0].id)
    pr_id = svc.list_pulls(orch.id)[0].id
    svc.report_ci(orch.id, pr_id, "passed", justificativa="CI externa verificada")

    recarregado = OrchestrationService(repository=SqlAlchemyOrchestrationRepository(url))
    assert recarregado.list_pulls(orch.id)[0].ci_origem == "declarada"
