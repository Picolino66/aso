"""MEL-30 — registro persistido de execuções de agente (`AgentRun`, ADR-0065)."""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from aso.agents.executor import LocalMockExecutionProvider
from aso.agents.models import AgentOutput, AgentSpec
from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService
from aso.db.repository import SqlAlchemyAgentRunRepository
from aso.execution.catalog import ExecutorCatalog, ExecutorProfile
from aso.execution.cli_provider import CliAgentExecutionProvider
from aso.observability.agent_runs import (
    MASCARA,
    AgentRun,
    InMemoryAgentRunRepository,
    mascarar_segredos,
)
from aso.shared.types import ColumnKey

SEGREDO = "sk-proj-abcdefghijklmnop123456"


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=path, check=True, capture_output=True)
    (path / "README.md").write_text("base\n")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True, capture_output=True)


# ------------------------------------------------------------------ filtro de segredos
def test_mascara_padroes_e_valores_do_ambiente(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEU_API_KEY", "valor-muito-secreto-42")
    texto = f"chave {SEGREDO} · Bearer abcdefghijklmnopqrst · env valor-muito-secreto-42"
    mascarado = mascarar_segredos(texto)
    assert SEGREDO not in mascarado
    assert "abcdefghijklmnopqrst" not in mascarado
    assert "valor-muito-secreto-42" not in mascarado
    assert mascarado.count(MASCARA) == 3


# ------------------------------------------------------------------ repositórios
@pytest.mark.parametrize("sql", [False, True])
def test_repositorio_salva_atualiza_lista_e_expurga(sql: bool, tmp_path: Path) -> None:
    banco = tmp_path / "runs.db"
    repo = (
        SqlAlchemyAgentRunRepository(f"sqlite:///{banco}") if sql else InMemoryAgentRunRepository()
    )
    antigo = AgentRun(
        orchestration_id="o1", prompt=f"usa {SEGREDO}", inicio="2020-01-01T00:00:00+00:00"
    )
    novo = AgentRun(orchestration_id="o1", card_id="c1", prompt="recente")
    repo.salvar(antigo)
    repo.salvar(novo)
    repo.salvar(novo.model_copy(update={"status": "sucesso", "duracao_ms": 12.5}))
    assert [r.id for r in repo.listar("o1")] == [antigo.id, novo.id]
    assert [r.id for r in repo.listar("o1", card_id="c1")] == [novo.id]
    assert repo.obter(novo.id).status == "sucesso"  # type: ignore[union-attr]
    assert SEGREDO not in repo.obter(antigo.id).prompt  # type: ignore[union-attr]
    assert repo.expurgar_textos("2021-01-01T00:00:00+00:00") == 1
    assert repo.obter(antigo.id).prompt == ""  # type: ignore[union-attr]
    assert repo.obter(novo.id).prompt == "recente"  # type: ignore[union-attr]
    if sql:
        assert SEGREDO.encode() not in banco.read_bytes()


# ------------------------------------------------------------------ execução de card
def test_run_card_com_cli_gera_registro_completo_e_propaga_run_id(tmp_path: Path) -> None:
    repo_git = tmp_path / "proj"
    _init_repo(repo_git)
    marca = tmp_path / "run_id.txt"
    comando = ["bash", "-c", f'echo "$ASO_RUN_ID" > {shlex.quote(str(marca))}; echo x > f.py']
    svc = OrchestrationService(provider=CliAgentExecutionProvider(comando, str(repo_git)))
    oid = svc.create_orchestration("implementar no backend").id
    card = svc.get_cards(oid)[0]
    svc.run_card(oid, card.id)

    runs = svc.list_agent_runs(oid)
    assert len(runs) == 1
    run = runs[0]
    assert run.kind == "execute" and run.card_id == card.id and run.status == "sucesso"
    assert run.prompt and "Implemente" in run.prompt
    assert run.envelope["task_type"] == "card"
    assert run.duracao_ms is not None and run.fim is not None
    assert run.branch and run.exit_code == 0 and (run.diff_lines or 0) > 0
    # run_id no ambiente do processo do agente e no CardEvent da tentativa.
    assert marca.read_text().strip() == run.id
    assert run.id in {e.execution_id for e in svc.get_card_events(oid, card.id)}
    evento = next(e for e in svc.timeline(oid) if e.type == "AgentExecuted")
    assert evento.payload["run_id"] == run.id


def test_falha_roteada_registra_a_decisao_no_mesmo_run() -> None:
    class _Quebra(LocalMockExecutionProvider):
        def execute(self, agent: AgentSpec, task: dict[str, Any]) -> AgentOutput:
            raise RuntimeError("compilação falhou")

    svc = OrchestrationService(provider=_Quebra(), max_escalonamentos=1)
    oid = svc.create_orchestration("backend").id
    card = next(c for c in svc.get_cards(oid) if c.status == ColumnKey.READY)
    svc.run_card(oid, card.id)
    falhos = [r for r in svc.list_agent_runs(oid) if r.status == "falha"]
    assert falhos
    assert falhos[-1].decisao.get("acao")
    assert "compilação falhou" in falhos[-1].erro
    roteado = next(e for e in svc.timeline(oid) if e.type == "FailureRouted")
    assert roteado.payload["run_id"] in {r.id for r in falhos}


def test_pergunta_de_triagem_gera_registro_ask() -> None:
    resposta = '{"objetivo": "Login social", "dominios": ["backend"]}'
    comando = shlex.join(["bash", "-c", 'cat > /dev/null; printf %s "$1"', "_", resposta])
    catalogo = ExecutorCatalog([ExecutorProfile(name="triador", kind="cli", command=comando)])
    svc = OrchestrationService(catalog=catalogo)
    oid = svc.create_orchestration("login social", seed_cards=False).id
    svc.retriage_demand(oid, executor="triador")
    ask = [r for r in svc.list_agent_runs(oid) if r.kind == "ask"]
    assert len(ask) == 1
    assert ask[0].task_type == "triagem" and ask[0].status == "sucesso"
    assert ask[0].executor == "triador"
    assert "Login social" in ask[0].saida_resumo
    assert "triagem" in ask[0].prompt.lower()


def test_registro_sobrevive_a_reinicio_e_nao_persiste_segredo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "chave-real-do-ambiente-123")
    banco = tmp_path / "aso.db"
    url = f"sqlite:///{banco}"
    svc = OrchestrationService(agent_run_repository=SqlAlchemyAgentRunRepository(url))
    oid = svc.create_orchestration(f"backend usando {SEGREDO} e chave-real-do-ambiente-123").id
    svc.run_card(oid, svc.get_cards(oid)[0].id)
    run_id = svc.list_agent_runs(oid)[0].id

    reiniciado = SqlAlchemyAgentRunRepository(url)
    run = reiniciado.obter(run_id)
    assert run is not None and run.status == "sucesso"
    assert SEGREDO not in run.prompt and MASCARA in run.prompt
    assert SEGREDO.encode() not in banco.read_bytes()
    assert b"chave-real-do-ambiente-123" not in banco.read_bytes()


def test_retencao_limpa_textos_antigos(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = InMemoryAgentRunRepository()
    repo.salvar(AgentRun(orchestration_id="o", prompt="velho", inicio="2000-01-01T00:00:00+00:00"))
    monkeypatch.setenv("ASO_RUN_RETENCAO_DIAS", "30")
    svc = OrchestrationService(agent_run_repository=repo)
    oid = svc.create_orchestration("backend").id
    svc.run_card(oid, svc.get_cards(oid)[0].id)
    assert repo.listar("o")[0].prompt == ""
    assert svc.list_agent_runs(oid)[0].prompt  # o recente fica


def test_endpoints_de_runs() -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid = svc.create_orchestration("backend").id
    card = svc.get_cards(oid)[0]
    svc.run_card(oid, card.id)
    lista = client.get(f"/v1/orchestrations/{oid}/runs", params={"card_id": card.id}).json()
    assert len(lista) == 1
    assert client.get(f"/v1/runs/{lista[0]['id']}").json()["card_id"] == card.id
    assert client.get("/v1/runs/run_inexistente").status_code == 404
