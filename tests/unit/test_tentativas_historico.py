"""Histórico completo de tentativas no card — sucesso e falha (§36.4, ADR-0031)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from aso.control.attempts import RESULTADO_FALHOU, RESULTADO_SUCESSO
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


def test_tentativa_com_sucesso_registra_resultado_sucesso(tmp_path: Path) -> None:
    repo = tmp_path / "sucesso-proj"
    _init_repo(repo)
    provider = CliAgentExecutionProvider(["bash", "-c", "echo 'gerado' > feature.py"], str(repo))
    svc = OrchestrationService(provider=provider)
    orch = svc.create_orchestration("implementar no backend")
    card = svc.get_cards(orch.id)[0]

    svc.run_card(orch.id, card.id)

    atualizado = svc.get_cards(orch.id)[0]
    assert atualizado.tentativa_atual == 1
    assert len(atualizado.tentativas) == 1
    assert atualizado.tentativas[0]["resultado"] == RESULTADO_SUCESSO
    assert atualizado.tentativas[0]["numero"] == 1


def test_tentativa_com_falha_registra_resultado_falhou_e_diagnostico(tmp_path: Path) -> None:
    repo = tmp_path / "falha-proj"
    _init_repo(repo)
    comando = ["bash", "-c", 'echo "AssertionError: sample failure" >&2; exit 1']
    provider = CliAgentExecutionProvider(comando, str(repo))
    svc = OrchestrationService(provider=provider, max_escalonamentos=1)
    orch = svc.create_orchestration("ajustar backend")
    card = svc.get_cards(orch.id)[0]

    svc.run_card(orch.id, card.id)

    atualizado = svc.get_cards(orch.id)[0]
    assert atualizado.tentativa_atual >= 1
    resultados = {t["resultado"] for t in atualizado.tentativas}
    assert resultados == {RESULTADO_FALHOU}
    assert all(t["diagnostico"] for t in atualizado.tentativas)


def test_max_tentativas_do_card_vence_o_teto_global(tmp_path: Path) -> None:
    """§36.4, ADR-0031: `card.max_tentativas` (herdado de uma RoutingRule, por
    exemplo) sobrepõe `self._max_escalonamentos` quando definido. `teste_falhou`
    (4 passos na tabela) só convergiria para escalar_humano na 4ª tentativa por
    conta própria — com `max_tentativas=1`, o teto força a escalada na 2ª (o
    teto `tentativa > limite` só passa a valer a partir da 2ª: `1 > 1` é falso)."""
    repo = tmp_path / "override-proj"
    _init_repo(repo)
    comando = ["bash", "-c", 'echo "AssertionError: sample failure" >&2; exit 1']
    provider = CliAgentExecutionProvider(comando, str(repo))
    svc = OrchestrationService(provider=provider, max_escalonamentos=5)
    orch = svc.create_orchestration("ajustar backend")
    card_id = svc.get_cards(orch.id)[0].id

    b = svc._bundle(orch.id)  # noqa: SLF001
    card = b.board_service.get_card(card_id)
    assert card is not None
    card.max_tentativas = 1
    svc._persist(b)  # noqa: SLF001

    svc.run_card(orch.id, card_id)

    atualizado = svc.get_cards(orch.id)[0]
    assert atualizado.status.value == "Failed"
    assert atualizado.tentativa_atual == 2  # escalou na 2ª, não esperou a tabela convergir na 4ª


def test_falha_apos_sucessos_anteriores_nao_escala_prematuramente(tmp_path: Path) -> None:
    """Bug real encontrado pelo code-review ultra: `decidir()` recebia
    `card.tentativa_atual` (soma sucesso + falha) em vez de um contador só de
    falha consecutiva — 2 sucessos anteriores inflavam o contador, batendo o
    teto `max_escalonamentos=3` já na 1ª falha real e escalando direto para
    humano em 1 tentativa, em vez de percorrer `mesmo_agente` → `aumentar_effort`
    → `escalar_humano` (§13, ADR-0019). O comando sempre falha (`AgentSupervisor`
    consome 2 tentativas internas por falha de card, ADR-0019 nota
    `max_attempts=2`), então a política precisa de 3 falhas REAIS de card para
    escalar — corrigido, é exatamente isso que acontece."""
    repo = tmp_path / "sucesso-depois-falha-proj"
    _init_repo(repo)
    comando = ["bash", "-c", 'echo "algo inesperado aconteceu" >&2; exit 1']
    provider = CliAgentExecutionProvider(comando, str(repo))
    svc = OrchestrationService(provider=provider, max_escalonamentos=3)
    orch = svc.create_orchestration("ajustar backend")
    card_id = svc.get_cards(orch.id)[0].id

    b = svc._bundle(orch.id)  # noqa: SLF001
    card = b.board_service.get_card(card_id)
    assert card is not None
    card.tentativa_atual = 2  # simula 2 tentativas bem-sucedidas anteriores
    svc._persist(b)  # noqa: SLF001

    svc.run_card(orch.id, card_id)

    atualizado = svc.get_cards(orch.id)[0]
    # Sob o bug, a 1ª falha real já via tentativa=3 (2 sucessos + 1 falha) e
    # escalava de imediato — só 1 tentativa real registrada. Corrigido, leva
    # exatamente as 3 falhas reais consecutivas que `max_escalonamentos=3` pede.
    assert atualizado.status.value == "Failed"
    assert len(atualizado.tentativas) == 3
    assert atualizado.tentativa_falha_atual == 3
    assert atualizado.tentativa_atual == 5  # 2 pré-existentes + 3 falhas reais


def test_sucesso_zera_a_sequencia_de_falhas_consecutivas(tmp_path: Path) -> None:
    """Uma falha real de card seguida de sucesso (retry automático dentro do
    mesmo `run_card`, ACAO_MESMO_AGENTE) deve zerar `tentativa_falha_atual` — só
    `tentativa_atual` (histórico total) continua somando os dois. O contador do
    script precisa sobreviver às 2 tentativas internas do `AgentSupervisor`
    (ADR-0019, `max_attempts=2`) antes de a 3ª invocação (já no retry de card)
    ter sucesso."""
    repo = tmp_path / "falha-depois-sucesso-proj"
    _init_repo(repo)
    contador = tmp_path / "invocacoes"
    comando = [
        "bash",
        "-c",
        f'n=$(( $(cat "{contador}" 2>/dev/null || echo 0) + 1 )); echo "$n" > "{contador}"; '
        'if [ "$n" -le 2 ]; then echo "algo inesperado aconteceu" >&2; exit 1; '
        "else echo gerado > feature.py; fi",
    ]
    provider = CliAgentExecutionProvider(comando, str(repo))
    svc = OrchestrationService(provider=provider, max_escalonamentos=3)
    orch = svc.create_orchestration("ajustar backend")
    card_id = svc.get_cards(orch.id)[0].id

    svc.run_card(orch.id, card_id)

    atualizado = svc.get_cards(orch.id)[0]
    assert atualizado.status.value != "Failed"
    assert atualizado.tentativa_atual == 2  # 1 falha real + 1 sucesso, nunca truncado
    assert atualizado.tentativa_falha_atual == 0  # sucesso zerou a sequência de falha


def test_tentativa_atual_sobrevive_a_recarregar_o_bundle(tmp_path: Path) -> None:
    from aso.db.repository import SqlAlchemyOrchestrationRepository

    repo_git = tmp_path / "persist-tentativas-proj"
    _init_repo(repo_git)
    db_url = f"sqlite:///{tmp_path / 'aso_tentativas.db'}"
    comando = ["bash", "-c", 'echo "AssertionError: sample failure" >&2; exit 1']

    repository = SqlAlchemyOrchestrationRepository(db_url)
    svc = OrchestrationService(
        provider=CliAgentExecutionProvider(comando, str(repo_git)),
        repository=repository,
        max_escalonamentos=1,
    )
    orch = svc.create_orchestration("ajustar backend")
    card_id = svc.get_cards(orch.id)[0].id
    svc.run_card(orch.id, card_id)
    tentativa_antes = svc.get_cards(orch.id)[0].tentativa_atual
    assert tentativa_antes >= 1

    outro_svc = OrchestrationService(
        provider=CliAgentExecutionProvider(comando, str(repo_git)),
        repository=SqlAlchemyOrchestrationRepository(db_url),
        max_escalonamentos=1,
    )
    card_recarregado = outro_svc.get_cards(orch.id)[0]
    assert card_recarregado.tentativa_atual == tentativa_antes
    assert card_recarregado.tentativas
