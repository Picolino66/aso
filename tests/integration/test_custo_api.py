"""Custo real capturado ponta a ponta (§1.1 do plano7.md) — ADR-0026.

Mesmo padrão de `tests/unit/test_ficha_de_encerramento.py`: `CliAgentExecutionProvider`
com um comando `bash -c` fake — aqui o comando também escreve, no stdout, um envelope
`result` com `usage`/`total_cost_usd`, exercitando a extração real via
`_bombear`/`_extrair_uso_da_saida` sem depender de um CLI de agente instalado.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.api.auth import AuthService, Principal
from aso.control.orchestration_service import OrchestrationService
from aso.execution.cli_provider import CliAgentExecutionProvider

_ENVELOPE = (
    '{"type":"result","subtype":"success","result":"ok",'
    '"total_cost_usd":0.05,"model":"claude-sonnet-5",'
    '"usage":{"input_tokens":10,"output_tokens":5}}'
)


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    run = lambda *a: subprocess.run(["git", *a], cwd=path, check=True, capture_output=True)  # noqa: E731
    run("init", "-q")
    run("config", "user.email", "t@t")
    run("config", "user.name", "t")
    (path / "README.md").write_text("base\n")
    run("add", "-A")
    run("commit", "-q", "-m", "init")


def test_execucao_com_usage_reflete_custo_no_card_closure_e_aprendizado(tmp_path: Path) -> None:
    repo = tmp_path / "proj"
    _init_repo(repo)
    comando = f"echo 'gerado' > feature.py; echo '{_ENVELOPE}'"
    provider = CliAgentExecutionProvider(["bash", "-c", comando], str(repo))
    svc = OrchestrationService(provider=provider)
    orch = svc.create_orchestration("implementar no backend")
    card_id = svc.get_cards(orch.id)[0].id

    svc.run_card(orch.id, card_id)

    card = svc.get_cards(orch.id)[0]
    assert card.uso["custo_usd"] == 0.05
    assert card.uso["tokens_entrada"] == 10
    assert card.uso["execucoes_sem_custo"] == 0

    pr = svc.list_pulls(orch.id)[0]
    svc.report_ci(orch.id, pr.id, "passed")
    svc.report_review(orch.id, pr.id, "approved", justificativa="revisão manual do teste")
    svc.merge_pr(orch.id, pr.id)
    card_final = svc.get_cards(orch.id)[0]
    assert card_final.closure["custo_usd"] == 0.05

    relatorio = svc.get_learning_report(orch.id)
    executor = next(d for d in relatorio.desempenho_por_executor if d.execucoes)
    assert executor.custo_total_usd == 0.05


def test_agente_sem_usage_marca_origem_indisponivel(tmp_path: Path) -> None:
    repo = tmp_path / "proj"
    _init_repo(repo)
    provider = CliAgentExecutionProvider(["bash", "-c", "echo 'gerado' > feature.py"], str(repo))
    svc = OrchestrationService(provider=provider)
    orch = svc.create_orchestration("implementar no backend")
    card_id = svc.get_cards(orch.id)[0].id

    svc.run_card(orch.id, card_id)

    card = svc.get_cards(orch.id)[0]
    assert card.uso["custo_usd"] == 0.0
    assert card.uso["execucoes_sem_custo"] == 1
    assert card.uso["execucoes"] == 1

    relatorio = svc.get_learning_report(orch.id)
    executor = next(d for d in relatorio.desempenho_por_executor if d.execucoes)
    assert executor.execucoes_sem_custo == 1


def test_prune_worktrees_exige_admin(tmp_path: Path) -> None:
    repo = tmp_path / "proj"
    _init_repo(repo)
    provider = CliAgentExecutionProvider(["bash", "-c", "echo x"], str(repo))
    svc = OrchestrationService(provider=provider)
    orch = svc.create_orchestration("demanda qualquer", target_path=str(repo))
    auth = AuthService(
        {
            "v": Principal(actor="view", role="viewer"),
            "a": Principal(actor="adm", role="admin"),
        },
        dev_mode=False,
    )
    client = TestClient(create_app(svc, auth=auth))

    negado = client.post(
        f"/v1/orchestrations/{orch.id}/worktrees/prune", headers={"Authorization": "Bearer v"}
    )
    assert negado.status_code == 403

    liberado = client.get(
        f"/v1/orchestrations/{orch.id}/worktrees", headers={"Authorization": "Bearer v"}
    )
    assert liberado.status_code == 200

    permitido = client.post(
        f"/v1/orchestrations/{orch.id}/worktrees/prune", headers={"Authorization": "Bearer a"}
    )
    assert permitido.status_code == 200
