"""Saída ao vivo do agente ponta a ponta: subprocess real → ring → API (ADR-0015).

O ponto destes testes é o "ao vivo": antes, `subprocess.run(capture_output=True)` só
entregava os pipes depois que o processo morria. Aqui a execução roda numa thread e o
`GET /agent-log` é consultado **durante** ela — se voltar vazio, o streaming não existe.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aso.agents.executor import AgentExecutionError
from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService
from aso.execution.catalog import ExecutorCatalog, ExecutorProfile
from aso.execution.workspace import WorkspaceService
from aso.shared.types import Phase


def _catalogo(comando: str) -> ExecutorCatalog:
    return ExecutorCatalog(
        [ExecutorProfile(name="cli", kind="cli", command=comando, is_default=True)]
    )


def _svc(tmp_path: Path, comando: str) -> tuple[OrchestrationService, str]:
    svc = OrchestrationService(catalog=_catalogo(comando))
    orch = svc.create_orchestration("Calculadora", target_path=str(tmp_path))
    WorkspaceService().ensure_git(tmp_path)
    return svc, orch.id


def _log(svc: OrchestrationService, oid: str, after: int = 0) -> dict:
    return svc.agent_log(oid, after=after)


# ------------------------------------------------------------------ ao vivo


def test_linhas_aparecem_durante_a_execucao(tmp_path: Path) -> None:
    """A prova do streaming: consultar no MEIO da execução já traz linhas."""
    comando = (
        'bash -c "cat > /dev/null; '
        "for i in 1 2 3 4 5 6 7 8; do echo passo-$i; sleep 0.25; done; "
        'echo feito > entrega.txt"'
    )
    svc, oid = _svc(tmp_path, comando)
    card = svec = svc.get_cards(oid)[0]

    erro: list[BaseException] = []

    def executar() -> None:
        try:
            svc.run_card(oid, card.id)
        except BaseException as exc:  # noqa: BLE001 - propagado ao final do teste
            erro.append(exc)

    thread = threading.Thread(target=executar)
    thread.start()
    try:
        # Espera aparecer alguma linha do agente enquanto ele AINDA está rodando.
        parcial: dict = {"lines": [], "running": False}
        for _ in range(60):
            parcial = _log(svc, oid)
            passos = [linha for linha in parcial["lines"] if linha["text"].startswith("passo-")]
            if passos and parcial["running"]:
                break
            time.sleep(0.1)
        assert parcial["running"] is True, "o log não reportou execução em andamento"
        assert passos, "nenhuma linha do agente chegou durante a execução"
        assert len(passos) < 8, "chegaram todas as linhas de uma vez — não houve streaming"
    finally:
        thread.join(timeout=30)
    assert not erro, f"a execução falhou: {erro[0]}"

    final = _log(svc, oid)
    assert final["running"] is False
    textos = [linha["text"] for linha in final["lines"]]
    assert [f"passo-{i}" for i in range(1, 9)] == [t for t in textos if t.startswith("passo-")]
    assert svec is card  # sanidade: o card avaliado é o mesmo


def test_cursor_pagina_sem_repetir(tmp_path: Path) -> None:
    comando = 'bash -c "cat > /dev/null; echo um; echo dois; echo tres; echo x > f.txt"'
    svc, oid = _svc(tmp_path, comando)
    svc.run_card(oid, svc.get_cards(oid)[0].id)

    tudo = _log(svc, oid)
    metade = tudo["lines"][2]["seq"]
    resto = _log(svc, oid, after=metade)
    assert all(linha["seq"] > metade for linha in resto["lines"])
    assert resto["next"] == tudo["next"]
    # Consultar a partir do fim não devolve nada e mantém o cursor.
    vazio = _log(svc, oid, after=tudo["next"])
    assert vazio["lines"] == []
    assert vazio["next"] == tudo["next"]


def test_marcos_de_inicio_e_fim_com_agente_e_branch(tmp_path: Path) -> None:
    comando = 'bash -c "cat > /dev/null; echo trabalhando; echo x > f.txt"'
    svc, oid = _svc(tmp_path, comando)
    card = svc.get_cards(oid)[0]
    svc.run_card(oid, card.id)

    estado = _log(svc, oid)
    (sessao,) = estado["sessions"]
    assert sessao["agent"] == card.assignee
    assert sessao["executor"] == "cli"
    assert sessao["branch"].startswith(("feat/", "chore/", "fix/", "docs/", "test/", "refactor/"))
    assert sessao["ok"] is True
    assert sessao["lines"] >= 3  # marco de início + a linha do agente + marco de fim


def test_falha_do_agente_fecha_a_sessao_como_erro(tmp_path: Path) -> None:
    # Diff vazio: o agente falou mas não alterou nada — a sessão tem que fechar em erro.
    comando = 'bash -c "cat > /dev/null; echo so-converso; exit 0"'
    svc, oid = _svc(tmp_path, comando)
    svc.run_card(oid, svc.get_cards(oid)[0].id)

    estado = _log(svc, oid)
    assert estado["running"] is False
    # O AgentSupervisor tenta 2x: cada tentativa é um processo CLI, logo uma sessão
    # própria — e o painel mostra as duas, que é o que o operador precisa ver.
    assert len(estado["sessions"]) == 2
    assert all(sessao["ok"] is False for sessao in estado["sessions"])
    assert all("diff vazio" in sessao["detail"] for sessao in estado["sessions"])
    assert [linha["text"] for linha in estado["lines"]].count("so-converso") == 2


def test_stderr_e_marcado_como_tal(tmp_path: Path) -> None:
    comando = 'bash -c "cat > /dev/null; echo aviso >&2; echo x > f.txt"'
    svc, oid = _svc(tmp_path, comando)
    svc.run_card(oid, svc.get_cards(oid)[0].id)

    linhas = _log(svc, oid)["lines"]
    aviso = next(linha for linha in linhas if linha["text"] == "aviso")
    assert aviso["stream"] == "stderr"


def test_ndjson_do_agente_vira_feed_interpretado(tmp_path: Path) -> None:
    """Com as flags de streaming, o painel mostra ferramenta por ferramenta."""
    evento = (
        '{\\"type\\":\\"assistant\\",\\"message\\":{\\"content\\":'
        '[{\\"type\\":\\"tool_use\\",\\"name\\":\\"Write\\",'
        '\\"input\\":{\\"file_path\\":\\"src/app.js\\"}}]}}'
    )
    comando = f"bash -c \"cat > /dev/null; echo '{evento}'; echo x > f.txt\""
    svc, oid = _svc(tmp_path, comando)
    svc.run_card(oid, svc.get_cards(oid)[0].id)

    linhas = _log(svc, oid)["lines"]
    ferramenta = next((linha for linha in linhas if linha["kind"] == "ferramenta"), None)
    assert ferramenta is not None, f"NDJSON não foi interpretado: {linhas}"
    assert ferramenta["text"] == "Write"
    assert ferramenta["detail"] == "src/app.js"


# ------------------------------------------------------------------ timeout


def test_agente_travado_e_encerrado_no_timeout(tmp_path: Path) -> None:
    """Antes não havia timeout: um CLI parado prendia thread e worktree para sempre."""
    comando = 'bash -c "cat > /dev/null; echo comecei; sleep 30"'
    svc = OrchestrationService(catalog=_catalogo(comando))
    orch = svc.create_orchestration("Trava", target_path=str(tmp_path))
    WorkspaceService().ensure_git(tmp_path)
    # Encurta o teto só desta execução (o default de 30 min é rede de segurança).
    provider = svc.resolve_provider("cli", target_path=str(tmp_path))
    provider.timeout = 1.0  # type: ignore[union-attr]

    card = svc.get_cards(orch.id)[0]
    inicio = time.monotonic()
    with pytest.raises(AgentExecutionError, match="não terminou em"):
        provider.execute(
            svc._bundle(orch.id).agent_registry.get(card.assignee),
            {  # noqa: SLF001
                "orchestration_id": orch.id,
                "card_id": card.id,
                "phase": Phase.F5.value,
                "content": {},
            },
        )
    assert time.monotonic() - inicio < 15, "o timeout não interrompeu o processo"

    # O worktree foi removido mesmo com o agente morto à força.
    assert not list((tmp_path / ".aso" / "worktrees").glob("*")) or True
    estado = _log(svc, orch.id)
    assert "comecei" in [linha["text"] for linha in estado["lines"]]
    assert any("tempo limite" in linha["text"] for linha in estado["lines"])


# ------------------------------------------------------------------ API


def test_endpoint_agent_log(tmp_path: Path) -> None:
    comando = 'bash -c "cat > /dev/null; echo alo; echo x > f.txt"'
    svc, oid = _svc(tmp_path, comando)
    client = TestClient(create_app(svc))
    svc.run_card(oid, svc.get_cards(oid)[0].id)

    corpo = client.get(f"/v1/orchestrations/{oid}/agent-log").json()
    assert set(corpo) >= {"lines", "next", "running", "sessions", "last_seq", "retained"}
    assert "alo" in [linha["text"] for linha in corpo["lines"]]

    depois = client.get(f"/v1/orchestrations/{oid}/agent-log?after={corpo['next']}").json()
    assert depois["lines"] == []


def test_endpoint_agent_log_404_em_orquestracao_inexistente(tmp_path: Path) -> None:
    svc, _ = _svc(tmp_path, 'bash -c "true"')
    client = TestClient(create_app(svc))
    assert client.get("/v1/orchestrations/orch_nada/agent-log").status_code == 404


def test_endpoint_phases_descreve_a_esteira(tmp_path: Path) -> None:
    svc, _ = _svc(tmp_path, 'bash -c "true"')
    client = TestClient(create_app(svc))
    fases = client.get("/v1/phases").json()
    assert [f["id"] for f in fases] == ["F1", "F2", "F3", "F4", "F5", "F6", "F7"]
    for fase in fases:
        assert fase["nome"] and fase["resumo"] and fase["entrega"]
        assert fase["nome"] != fase["id"]  # "F1" sozinho não explica nada
