"""Revisão independente de código pela API (§14/§15 do fluxo.md, ADR-0017)."""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.models import REVIEW_KEY
from aso.control.orchestration_service import OrchestrationService
from aso.execution.catalog import ExecutorCatalog, ExecutorProfile


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    run = lambda *a: subprocess.run(["git", *a], cwd=path, check=True, capture_output=True)  # noqa: E731
    run("init", "-q")
    run("config", "user.email", "t@t")
    run("config", "user.name", "t")
    (path / "README.md").write_text("base\n")
    run("add", "-A")
    run("commit", "-q", "-m", "init")


def _cli_perfil(
    nome: str, saida_ou_script: str, *, escreve_arquivo: bool = False
) -> ExecutorProfile:
    """Perfil CLI fake: `escreve_arquivo` simula um implementador; senão, cospe a saída."""
    if escreve_arquivo:
        comando = shlex.join(["bash", "-c", saida_ou_script])
    else:
        script = 'cat > /dev/null; printf %s "$1"; exit 0'
        comando = shlex.join(["bash", "-c", script, "_", saida_ou_script])
    return ExecutorProfile(name=nome, kind="cli", command=comando)


def _catalogo(veredito_revisor: str) -> ExecutorCatalog:
    return ExecutorCatalog(
        [
            _cli_perfil("implementador", "echo 'x = 1' > feature.py", escreve_arquivo=True),
            _cli_perfil("revisor", veredito_revisor),
        ]
    )


def _preparar(
    tmp_path: Path, catalog: ExecutorCatalog, user_request: str
) -> tuple[TestClient, str, str]:
    """Cria a orquestração, executa o único card e devolve (client, oid, pr_id)."""
    repo = tmp_path / "proj"
    _init_repo(repo)
    client = TestClient(create_app(OrchestrationService(catalog=catalog)))
    oid = client.post(
        "/v1/orchestrations",
        json={"user_request": user_request, "executor": "implementador", "target_path": str(repo)},
    ).json()["id"]
    card_id = client.get(f"/v1/orchestrations/{oid}/cards").json()[0]["id"]
    assert client.post(f"/v1/orchestrations/{oid}/cards/{card_id}/run").status_code == 200
    pulls = client.get(f"/v1/orchestrations/{oid}/pulls").json()
    return client, oid, pulls[0]["id"]


def test_review_run_persiste_veredito_recuperavel_por_get(tmp_path: Path) -> None:
    catalog = _catalogo('{"veredito": "aprovado_com_sugestoes", "resumo": "bem escrito"}')
    client, oid, pr_id = _preparar(tmp_path, catalog, "ajustar módulo qualquer")

    resposta = client.post(
        f"/v1/orchestrations/{oid}/pulls/{pr_id}/review/run", json={"executor": "revisor"}
    )
    assert resposta.status_code == 200
    assert resposta.json()["review_verdict"]["veredito"] == "aprovado_com_sugestoes"
    assert resposta.json()["review_rounds"] == 1

    veredito = client.get(f"/v1/orchestrations/{oid}/pulls/{pr_id}/review").json()
    assert veredito["veredito"] == "aprovado_com_sugestoes"
    assert veredito["resumo"] == "bem escrito"
    assert veredito["revisor"] == "revisor"
    assert veredito["origem"] == "agente"


def test_risco_baixo_com_veredito_aprovado_libera_merge(tmp_path: Path) -> None:
    catalog = _catalogo('{"veredito": "aprovado", "resumo": "ok, sem ressalvas"}')
    client, oid, pr_id = _preparar(tmp_path, catalog, "ajustar relatorio mensal de vendas")
    client.post(f"/v1/orchestrations/{oid}/pulls/{pr_id}/ci", json={"status": "passed"})

    resposta = client.post(
        f"/v1/orchestrations/{oid}/pulls/{pr_id}/review/run", json={"executor": "revisor"}
    )
    assert resposta.status_code == 200
    assert resposta.json()["review_verdict"]["veredito"] == "aprovado"
    assert resposta.json()["review_status"] == "approved"  # risco baixo fecha sozinho

    veredito = client.get(f"/v1/orchestrations/{oid}/pulls/{pr_id}/review").json()
    assert veredito["veredito"] == "aprovado"
    assert veredito["revisor"] == "revisor"

    step = client.get(f"/v1/orchestrations/{oid}/next-step").json()
    codigos = {b["code"] for b in step["blockers"]}
    assert "pr_pronto_merge" in codigos
    assert "pr_review_pendente" not in codigos  # regressão: o clique sem revisão não existe mais

    merge = client.post(f"/v1/orchestrations/{oid}/pulls/{pr_id}/merge")
    assert merge.status_code == 200


def test_risco_alto_com_veredito_aprovado_fica_pendente_de_humano(tmp_path: Path) -> None:
    catalog = _catalogo('{"veredito": "aprovado", "resumo": "ok"}')
    client, oid, pr_id = _preparar(
        tmp_path, catalog, "Ajustar login com token e senha de autenticacao"
    )
    client.post(f"/v1/orchestrations/{oid}/pulls/{pr_id}/ci", json={"status": "passed"})

    resposta = client.post(
        f"/v1/orchestrations/{oid}/pulls/{pr_id}/review/run", json={"executor": "revisor"}
    )
    assert resposta.json()["review_verdict"]["veredito"] == "aprovado"
    assert resposta.json()["review_status"] == "pending"  # risco alto não fecha sozinho

    step = client.get(f"/v1/orchestrations/{oid}/next-step").json()
    bloqueio = next(b for b in step["blockers"] if b["code"] == "pr_review_humana")
    assert bloqueio["action"]["role"] == "admin"

    # Risco alto não fecha com o veredito do agente sozinho, mesmo aprovado — a
    # confirmação humana precisa ser uma decisão registrada (justificativa), não um
    # clique (ADR-0019, pendência da ADR-0017 corrigida aqui).
    sem_justificativa = client.post(
        f"/v1/orchestrations/{oid}/pulls/{pr_id}/review", json={"status": "approved"}
    )
    assert sem_justificativa.status_code == 409

    confirmado = client.post(
        f"/v1/orchestrations/{oid}/pulls/{pr_id}/review",
        json={"status": "approved", "justificativa": "risco alto avaliado manualmente"},
    )
    assert confirmado.status_code == 200
    assert confirmado.json()["review_status"] == "approved"


def test_aprovar_sem_veredito_aprovado_exige_justificativa(tmp_path: Path) -> None:
    catalog = _catalogo('{"veredito": "necessita_humano", "resumo": "área sensível"}')
    client, oid, pr_id = _preparar(tmp_path, catalog, "ajustar módulo qualquer")
    client.post(f"/v1/orchestrations/{oid}/pulls/{pr_id}/ci", json={"status": "passed"})
    client.post(f"/v1/orchestrations/{oid}/pulls/{pr_id}/review/run", json={"executor": "revisor"})

    recusado = client.post(
        f"/v1/orchestrations/{oid}/pulls/{pr_id}/review", json={"status": "approved"}
    )
    assert recusado.status_code == 409

    aceito = client.post(
        f"/v1/orchestrations/{oid}/pulls/{pr_id}/review",
        json={"status": "approved", "justificativa": "risco avaliado manualmente"},
    )
    assert aceito.status_code == 200
    assert aceito.json()["review_status"] == "approved"


def test_put_e_delete_do_agente_de_revisao() -> None:
    client = TestClient(create_app(OrchestrationService(catalog=ExecutorCatalog())))
    oid = client.post("/v1/orchestrations", json={"user_request": "demanda qualquer"}).json()["id"]

    resposta = client.put(
        f"/v1/orchestrations/{oid}/agents/{REVIEW_KEY}", json={"executor": "mock"}
    )
    assert resposta.status_code == 200
    assert resposta.json()["agent_assignments"][REVIEW_KEY]["executor"] == "mock"
    assert client.delete(f"/v1/orchestrations/{oid}/agents/{REVIEW_KEY}").status_code == 200


def test_review_run_sem_pr_devolve_404() -> None:
    client = TestClient(create_app(OrchestrationService()))
    oid = client.post("/v1/orchestrations", json={"user_request": "demanda qualquer"}).json()["id"]
    resposta = client.post(f"/v1/orchestrations/{oid}/pulls/pr-inexistente/review/run", json={})
    assert resposta.status_code == 404
