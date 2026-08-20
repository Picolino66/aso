"""Roteamento de falha ponta a ponta — execução real em worktree (§13, ADR-0019)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService
from aso.db.repository import SqlAlchemyOrchestrationRepository
from aso.execution.cli_provider import CliAgentExecutionProvider
from aso.governance.models import QualityGateResult
from aso.shared.types import ColumnKey, GateStatus, Phase


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    run = lambda *a: subprocess.run(["git", *a], cwd=path, check=True, capture_output=True)  # noqa: E731
    run("init", "-q")
    run("config", "user.email", "t@t")
    run("config", "user.name", "t")
    (path / "README.md").write_text("base\n")
    run("add", "-A")
    run("commit", "-q", "-m", "init")


# ------------------------------------------------------------ segunda tentativa: effort


def test_timeout_sobe_effort_na_segunda_tentativa(tmp_path: Path) -> None:
    """`teste_falhou` (1ª tentativa) e `timeout` compartilham o passo `aumentar_effort` —
    aqui provocamos timeout de propósito e conferimos o `effort` no task efetivamente
    montado para a 2ª chamada ao agente, não só o campo devolvido pela política."""
    repo = tmp_path / "timeout-proj"
    _init_repo(repo)
    tarefas_dir = tmp_path / "tarefas"
    tarefas_dir.mkdir()
    # Grava a task (JSON via stdin) antes de dormir além do timeout do provider.
    comando = ["bash", "-c", f'cat > "{tarefas_dir}"/tentativa-$$.json; sleep 5']
    provider = CliAgentExecutionProvider(comando, str(repo), timeout=0.3)
    svc = OrchestrationService(provider=provider)
    orch = svc.create_orchestration("ajustar backend")
    card_id = svc.get_cards(orch.id)[0].id

    svc.run_card(orch.id, card_id)

    arquivos = sorted(tarefas_dir.glob("tentativa-*.json"), key=lambda p: p.stat().st_mtime)
    # AgentSupervisor tenta 2x por rodada externa; o roteamento (ADR-0019) manda subir
    # o effort na 2ª rodada externa (timeout → aumentar_effort) — 2 rodadas × 2
    # tentativas internas = 4 arquivos, o effort muda entre a 1ª e a última rodada.
    assert len(arquivos) == 4
    tarefas = [json.loads(a.read_text()) for a in arquivos]
    # 1ª rodada: sem effort configurado, a task nem carrega o campo. 2ª rodada: a
    # política subiu para o primeiro degrau da escada ('low').
    assert tarefas[0].get("effort") is None
    assert tarefas[-1].get("effort") == "low"

    card = svc.get_cards(orch.id)[0]
    assert [f["etapa"] for f in card.failures]
    diagnosticos = {f["mensagem"] for f in card.failures}
    assert any("terminou" in d or "tempo limite" in d.lower() for d in diagnosticos)


# --------------------------------------------------------- três falhas, escala e para


def test_tres_falhas_escala_para_humano_e_para_de_reexecutar(tmp_path: Path) -> None:
    repo = tmp_path / "assert-proj"
    _init_repo(repo)
    comando = ["bash", "-c", 'echo "AssertionError: sample failure" >&2; exit 1']
    provider = CliAgentExecutionProvider(comando, str(repo))
    svc = OrchestrationService(provider=provider, max_escalonamentos=3)
    orch = svc.create_orchestration("ajustar backend")
    card_id = svc.get_cards(orch.id)[0].id

    svc.run_card(orch.id, card_id)

    card = svc.get_cards(orch.id)[0]
    assert card.status.value == "Failed"
    # teste_falhou: mesmo_agente, aumentar_effort, trocar_executor(sem catálogo, cai
    # para escalar_humano) — 3 falhas registradas antes de parar.
    assert len(card.failures) == 3

    # Uma nova chamada manual (ex.: via /route) já esgotou o limite — escala de novo
    # sem sequer tentar rodar o agente uma 4ª vez desnecessariamente.
    svc.run_card(orch.id, card_id)
    card_depois = svc.get_cards(orch.id)[0]
    assert card_depois.status.value == "Failed"
    assert len(card_depois.failures) == 4


# ------------------------------------------------------------------- roteiro de gate


def test_gate_reprovado_roteia_so_os_cards_pendentes_da_fase() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("demanda qualquer")
    b = svc._bundle(orch.id)  # noqa: SLF001
    cards = svc.get_cards(orch.id)
    assert len(cards) == 1
    pendente = cards[0]
    entregue = b.board_service.add_card(
        pendente.model_copy(
            update={
                "id": "card_extra",
                "status": ColumnKey.DONE,
                "title": "outro card já entregue",
            }
        )
    )
    b.gate_results.append(
        QualityGateResult(orchestration_id=orch.id, phase=Phase.F5, status=GateStatus.FAILED)
    )
    svc._persist(b)  # noqa: SLF001

    roteados = svc.retry(orch.id)

    assert roteados == [pendente.id]
    assert entregue.id not in roteados
    card_roteado = svc.get_cards(orch.id)[0]
    assert card_roteado.failures and card_roteado.failures[-1]["etapa"] == "gate"


# ------------------------------------------------------------------------- API: rotas


def test_get_failures_e_post_route_pela_api(tmp_path: Path) -> None:
    repo = tmp_path / "route-proj"
    _init_repo(repo)
    comando = ["bash", "-c", 'echo "AssertionError: sample failure" >&2; exit 1']
    provider = CliAgentExecutionProvider(comando, str(repo), timeout=5)
    svc = OrchestrationService(provider=provider, max_escalonamentos=1)
    client = TestClient(create_app(svc))
    oid = svc.create_orchestration("ajustar backend").id
    card_id = svc.get_cards(oid)[0].id

    client.post(f"/v1/orchestrations/{oid}/cards/{card_id}/run")

    falhas = client.get(f"/v1/orchestrations/{oid}/cards/{card_id}/failures")
    assert falhas.status_code == 200
    # max_escalonamentos=1: a 1ª falha ainda segue a tabela (teste_falhou → mesmo
    # agente), a 2ª já ultrapassa o limite e força escalar_humano.
    assert len(falhas.json()) == 2

    card = client.get(f"/v1/orchestrations/{oid}/cards").json()[0]
    assert card["status"] == "Failed"

    roteado = client.post(f"/v1/orchestrations/{oid}/cards/{card_id}/route")
    assert roteado.status_code == 200
    falhas_depois = client.get(f"/v1/orchestrations/{oid}/cards/{card_id}/failures").json()
    assert len(falhas_depois) == 3


def test_reroteamento_repetido_nao_trava_o_contador_no_tamanho_do_ring(
    tmp_path: Path,
) -> None:
    """§36.4, ADR-0031: `card.tentativa_atual` é o contador autoritativo — reroteamento
    manual repetido (`/route`) sobre um card já `Failed` precisa continuar contando de
    verdade depois da 5ª falha, não travar porque `card.failures` é um ring de 5.
    Antes desta ADR, `next_step` usava `len(card.failures)` e o rótulo "tentativa N"
    ficava preso em 5 para sempre."""
    repo = tmp_path / "route-repetido-proj"
    _init_repo(repo)
    comando = ["bash", "-c", 'echo "AssertionError: sample failure" >&2; exit 1']
    provider = CliAgentExecutionProvider(comando, str(repo), timeout=5)
    svc = OrchestrationService(provider=provider, max_escalonamentos=1)
    client = TestClient(create_app(svc))
    oid = svc.create_orchestration("ajustar backend").id
    card_id = svc.get_cards(oid)[0].id

    client.post(f"/v1/orchestrations/{oid}/cards/{card_id}/run")  # 2 falhas (limite=1)
    for _ in range(5):  # mais 5 reroteamentos manuais → 7 falhas no total
        resposta = client.post(f"/v1/orchestrations/{oid}/cards/{card_id}/route")
        assert resposta.status_code == 200

    card = client.get(f"/v1/orchestrations/{oid}/cards").json()[0]
    assert card["status"] == "Failed"
    assert card["tentativa_atual"] == 7
    # O ring de auditoria (`failures`) continua travado em 5 — isso é o esperado
    # (histórico das ÚLTIMAS falhas, não um contador) — o bug era usar o TAMANHO
    # dele como se fosse o contador.
    falhas = client.get(f"/v1/orchestrations/{oid}/cards/{card_id}/failures").json()
    assert len(falhas) == 5

    # `_card_blockers` só considera cards da FASE CORRENTE da orquestração (F1 por
    # padrão); o card em si nasce em F5 — alinha as duas para o bloqueio aparecer,
    # mesmo padrão já usado nos testes de pipeline de implantação (F6).
    b = svc._bundle(oid)  # noqa: SLF001
    b.orchestration.current_phase = Phase.F5
    svc._persist(b)  # noqa: SLF001

    next_step = client.get(f"/v1/orchestrations/{oid}/next-step").json()
    blocker = next(b for b in next_step["blockers"] if b["code"] == "cards_falhos")
    assert "tentativa 7" in blocker["detail"]


# ---------------------------------------------------------------- persistência (Postgres/SQLite)


def test_contador_de_falhas_sobrevive_a_recarregar_o_bundle(tmp_path: Path) -> None:
    """`len(card.failures)` — a base do limite duro — precisa sobreviver a um restart
    da API: persiste via `SqlAlchemyOrchestrationRepository`, não só em memória."""
    repo_git = tmp_path / "persist-proj"
    _init_repo(repo_git)
    db_url = f"sqlite:///{tmp_path / 'aso_test.db'}"
    comando = ["bash", "-c", 'echo "AssertionError: sample failure" >&2; exit 1']

    repository = SqlAlchemyOrchestrationRepository(db_url)
    svc = OrchestrationService(
        provider=CliAgentExecutionProvider(comando, str(repo_git)),
        repository=repository,
        max_escalonamentos=5,
    )
    orch = svc.create_orchestration("ajustar backend")
    card_id = svc.get_cards(orch.id)[0].id
    svc.run_card(orch.id, card_id)
    falhas_antes = len(svc.get_cards(orch.id)[0].failures)
    assert falhas_antes >= 1

    # Novo serviço, mesma base — força hidratação do zero (nenhum cache em memória).
    outro_repository = SqlAlchemyOrchestrationRepository(db_url)
    outro_svc = OrchestrationService(
        provider=CliAgentExecutionProvider(comando, str(repo_git)),
        repository=outro_repository,
        max_escalonamentos=5,
    )
    card_recarregado = outro_svc.get_cards(orch.id)[0]
    assert len(card_recarregado.failures) == falhas_antes
    assert card_recarregado.failures[-1]["etapa"] == "execucao"

    # A auditoria de movimentação (§8) também sobrevive: o último CardEvent do card
    # tem reason/next_action preenchidos.
    b = outro_svc._bundle(orch.id)  # noqa: SLF001
    eventos_do_card = [e for e in b.board_service.card_events if e.card_id == card_id]
    assert eventos_do_card[-1].reason
    assert eventos_do_card[-1].next_action
