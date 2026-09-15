"""MEL-13 — claim atômico do card antes de executar (ADR-0058).

Concorrência determinística: o provider bloqueia num `threading.Event` enquanto o
teste tenta, de outra thread, executar/mover o mesmo card — sem `sleep` nem corrida
de sorte.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from aso.agents.executor import LocalMockExecutionProvider
from aso.agents.models import AgentOutput, AgentSpec
from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService
from aso.db.repository import SqlAlchemyOrchestrationRepository
from aso.shared.ids import gen_id
from aso.shared.types import ColumnKey


class _ProviderBloqueante(LocalMockExecutionProvider):
    """Conta chamadas e segura a execução até o teste liberar."""

    def __init__(self) -> None:
        self.chamadas = 0
        self.entrou = threading.Event()
        self.liberar = threading.Event()

    def execute(self, agent: AgentSpec, task: dict[str, Any]) -> AgentOutput:
        self.chamadas += 1
        self.entrou.set()
        assert self.liberar.wait(timeout=10), "teste não liberou o provider"
        return super().execute(agent, task)


def _cenario(
    repository: Any = None,
) -> tuple[OrchestrationService, _ProviderBloqueante, str, str]:
    provider = _ProviderBloqueante()
    svc = OrchestrationService(provider=provider, repository=repository)
    orch = svc.create_orchestration("backend")
    card = next(c for c in svc.get_cards(orch.id) if c.status == ColumnKey.READY)
    return svc, provider, orch.id, card.id


def _em_background(fn: Any) -> tuple[threading.Thread, list[BaseException]]:
    erros: list[BaseException] = []

    def alvo() -> None:
        try:
            fn()
        except BaseException as exc:  # noqa: BLE001 - repassado ao teste
            erros.append(exc)

    thread = threading.Thread(target=alvo)
    thread.start()
    return thread, erros


def _card(svc: OrchestrationService, oid: str, card_id: str) -> Any:
    return next(c for c in svc.get_cards(oid) if c.id == card_id)


def test_duas_execucoes_concorrentes_rodam_o_agente_uma_vez() -> None:
    svc, provider, oid, card_id = _cenario()
    thread, erros = _em_background(lambda: svc.run_card(oid, card_id))
    assert provider.entrou.wait(timeout=10)

    with pytest.raises(ValueError, match="já em execução"):
        svc.run_card(oid, card_id)

    provider.liberar.set()
    thread.join(timeout=10)
    assert not erros
    assert provider.chamadas == 1


def test_durante_a_execucao_o_card_esta_in_progress_e_o_claim_persistido(
    tmp_path: Path,
) -> None:
    url = f"sqlite:///{tmp_path / 'claim.db'}"
    svc, provider, oid, card_id = _cenario(SqlAlchemyOrchestrationRepository(url))
    thread, erros = _em_background(lambda: svc.run_card(oid, card_id))
    assert provider.entrou.wait(timeout=10)

    em_voo = _card(svc, oid, card_id)
    assert em_voo.status == ColumnKey.IN_PROGRESS
    assert em_voo.em_execucao_desde and em_voo.execution_id
    # O estado "rodando" já está no banco antes do agente terminar (sobrevive a crash).
    persistido = SqlAlchemyOrchestrationRepository(url).load(oid)
    assert persistido is not None
    card_no_banco = next(c for c in persistido.cards if c.id == card_id)
    assert card_no_banco.status == ColumnKey.IN_PROGRESS
    assert card_no_banco.em_execucao_desde == em_voo.em_execucao_desde

    provider.liberar.set()
    thread.join(timeout=10)
    assert not erros
    final = _card(svc, oid, card_id)
    assert final.em_execucao_desde is None and final.execution_id is None
    assert final.status != ColumnKey.IN_PROGRESS


def test_evento_agent_started_e_resultado_compartilham_execution_id() -> None:
    svc, provider, oid, card_id = _cenario()
    provider.liberar.set()
    svc.run_card(oid, card_id)
    eventos = [e for e in svc.get_card_events(oid, card_id) if e.execution_id]
    inicio = next(e for e in eventos if e.to_status == ColumnKey.IN_PROGRESS)
    assert {e.execution_id for e in eventos} == {inicio.execution_id}


def test_falha_do_provider_libera_o_claim() -> None:
    class _Quebra(LocalMockExecutionProvider):
        def execute(self, agent: AgentSpec, task: dict[str, Any]) -> AgentOutput:
            raise RuntimeError("agente explodiu")

    svc = OrchestrationService(provider=_Quebra())
    oid = svc.create_orchestration("backend").id
    card_id = next(c.id for c in svc.get_cards(oid) if c.status == ColumnKey.READY)
    svc.run_card(oid, card_id)
    assert _card(svc, oid, card_id).em_execucao_desde is None


def test_excecao_inesperada_fora_do_provider_libera_o_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc, provider, oid, card_id = _cenario()
    provider.liberar.set()

    def _explode(*_a: object, **_k: object) -> object:
        raise RuntimeError("bug ao aplicar resultado")

    # A execução vive no ExecutionService (MEL-32): o patch vai onde o método é chamado.
    monkeypatch.setattr(svc._execution, "_apply_execution", _explode)  # noqa: SLF001
    with pytest.raises(RuntimeError, match="bug ao aplicar"):
        svc.run_card(oid, card_id)
    monkeypatch.undo()
    assert _card(svc, oid, card_id).em_execucao_desde is None
    # E o card continua executável depois.
    svc.run_card(oid, card_id)
    assert provider.chamadas == 2


def test_reidratacao_com_claim_de_outra_instancia_marca_failed(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'crash.db'}"
    svc = OrchestrationService(repository=SqlAlchemyOrchestrationRepository(url))
    oid = svc.create_orchestration("backend").id
    card_id = next(c.id for c in svc.get_cards(oid) if c.status == ColumnKey.READY)
    # Simula o processo morrendo com o agente em voo: claim persistido, nunca liberado.
    b = svc._bundle(oid)  # noqa: SLF001 - reproduz o crash no meio da execução
    with svc._lock_for(oid):  # noqa: SLF001
        svc._reivindicar_card(  # noqa: SLF001
            b, b.board_service.get_card(card_id), execution_id=gen_id("exec")
        )

    reiniciado = OrchestrationService(repository=SqlAlchemyOrchestrationRepository(url))
    card = _card(reiniciado, oid, card_id)
    assert card.status == ColumnKey.FAILED
    assert card.em_execucao_desde is None
    motivo = [e.reason for e in reiniciado.get_card_events(oid, card_id)][-1]
    assert motivo == "execução interrompida (reinício do runtime)"
    assert any(e.type == "ExecutionInterrupted" for e in reiniciado.timeline(oid))
    # A recuperação foi persistida: uma terceira instância não vê claim nem repete o evento.
    terceira = OrchestrationService(repository=SqlAlchemyOrchestrationRepository(url))
    assert [e.type for e in terceira.timeline(oid)].count("ExecutionInterrupted") == 1


def test_claim_da_propria_instancia_nao_e_tratado_como_interrompido() -> None:
    svc, provider, oid, card_id = _cenario()
    thread, _erros = _em_background(lambda: svc.run_card(oid, card_id))
    assert provider.entrou.wait(timeout=10)
    svc._recuperar_execucoes_interrompidas(svc._bundle(oid))  # noqa: SLF001
    assert _card(svc, oid, card_id).status == ColumnKey.IN_PROGRESS
    provider.liberar.set()
    thread.join(timeout=10)


def test_run_plan_pula_card_ja_reivindicado_e_libera_os_seus() -> None:
    svc, provider, oid, card_id = _cenario()
    thread, erros = _em_background(lambda: svc.run_card(oid, card_id))
    assert provider.entrou.wait(timeout=10)
    chamadas_antes = provider.chamadas

    plano, erros_plano = _em_background(lambda: svc.run_plan(oid, concurrent=False))
    # O card em voo não entra na onda; os demais cards Ready rodam normalmente.
    provider.liberar.set()
    plano.join(timeout=10)
    thread.join(timeout=10)
    assert not erros and not erros_plano
    assert provider.chamadas >= chamadas_antes
    assert all(c.em_execucao_desde is None for c in svc.get_cards(oid))
    inicios = [e for e in svc.get_card_events(oid, card_id) if e.to_status == ColumnKey.IN_PROGRESS]
    assert len(inicios) == 1  # só a execução do run_card


def test_race_card_recusa_card_em_execucao() -> None:
    svc, provider, oid, card_id = _cenario()
    thread, _erros = _em_background(lambda: svc.run_card(oid, card_id))
    assert provider.entrou.wait(timeout=10)
    with pytest.raises(ValueError, match="já em execução"):
        svc.race_card(oid, card_id, [LocalMockExecutionProvider()])
    provider.liberar.set()
    thread.join(timeout=10)


def test_race_card_libera_o_lease_sem_mudar_a_coluna() -> None:
    svc = OrchestrationService()
    oid = svc.create_orchestration("backend").id
    card = next(c for c in svc.get_cards(oid) if c.status == ColumnKey.READY)
    svc.race_card(oid, card.id, [LocalMockExecutionProvider()])
    depois = _card(svc, oid, card.id)
    assert depois.em_execucao_desde is None
    assert depois.status == ColumnKey.READY


def test_mover_manual_recusa_card_em_execucao() -> None:
    svc, provider, oid, card_id = _cenario()
    thread, _erros = _em_background(lambda: svc.run_card(oid, card_id))
    assert provider.entrou.wait(timeout=10)
    with pytest.raises(ValueError, match="já em execução"):
        svc.move_card_validado(oid, card_id, ColumnKey.TESTING.value)
    provider.liberar.set()
    thread.join(timeout=10)


def test_api_devolve_409_para_execucao_concorrente() -> None:
    svc, provider, oid, card_id = _cenario()
    client = TestClient(create_app(svc))
    thread, _erros = _em_background(lambda: svc.run_card(oid, card_id))
    assert provider.entrou.wait(timeout=10)
    resposta = client.post(f"/v1/orchestrations/{oid}/cards/{card_id}/run")
    assert resposta.status_code == 409
    assert "já em execução" in resposta.json()["detail"]
    assert client.get(f"/v1/orchestrations/{oid}/cards").json()
    provider.liberar.set()
    thread.join(timeout=10)
    assert provider.chamadas == 1
