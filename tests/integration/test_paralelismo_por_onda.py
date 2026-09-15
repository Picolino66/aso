"""MEL-50 — ondas: independentes em paralelo até o limite, dependência só depois de Done."""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from aso.agents.executor import LocalMockExecutionProvider
from aso.agents.models import AgentOutput, AgentSpec
from aso.application.orchestration_service import OrchestrationService
from aso.control.models import DecisionInput
from aso.shared.types import ExecutionStrategy


class _ProviderMedido:
    """Registra intervalos de execução por card e dorme para expor a concorrência."""

    id = "medido"

    def __init__(self, segundos: float = 0.3) -> None:
        self._segundos = segundos
        self._mock = LocalMockExecutionProvider()
        self._guarda = threading.Lock()
        self.intervalos: dict[str, tuple[float, float]] = {}
        self.chamadas: list[str] = []

    def execute(self, agent: AgentSpec, task: dict[str, Any]) -> AgentOutput:
        inicio = time.monotonic()
        time.sleep(self._segundos)
        with self._guarda:
            card_id = str(task.get("card_id"))
            self.chamadas.append(card_id)
            self.intervalos[card_id] = (inicio, time.monotonic())
        return self._mock.execute(agent, task)


def _orquestracao(svc: OrchestrationService, n_cards: int, estrategia: ExecutionStrategy) -> str:
    oid = svc.create_orchestration("backend").id
    b = svc._bundle(oid)  # noqa: SLF001
    base = svc.get_cards(oid)[0]
    for i in range(1, n_cards):
        b.board_service.add_card(base.model_copy(update={"id": f"card_extra_{i}"}))
    b.plan.strategy = estrategia
    return oid


def _maximo_simultaneo(intervalos: list[tuple[float, float]]) -> int:
    marcos = sorted([(i, 1) for i, _ in intervalos] + [(f, -1) for _, f in intervalos])
    atual = maximo = 0
    for _, delta in marcos:
        atual += delta
        maximo = max(maximo, atual)
    return maximo


def test_cards_independentes_rodam_em_paralelo_ate_o_limite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ASO_MAX_PARALELO_POR_ORQUESTRACAO", "2")
    provider = _ProviderMedido()
    svc = OrchestrationService(provider=provider)
    oid = _orquestracao(svc, 4, ExecutionStrategy.PARALLEL)
    resultado = svc.run_plan(oid)
    assert resultado["count"] == 4 and resultado["paralelismo"] == 2
    assert _maximo_simultaneo(list(provider.intervalos.values())) == 2


def test_estrategia_sequencial_executa_um_card_por_vez() -> None:
    provider = _ProviderMedido(0.1)
    svc = OrchestrationService(provider=provider)
    oid = _orquestracao(svc, 3, ExecutionStrategy.SEQUENTIAL)
    resultado = svc.run_plan(oid)
    assert resultado["count"] == 3 and resultado["paralelismo"] == 1
    assert _maximo_simultaneo(list(provider.intervalos.values())) == 1


def test_run_phase_usa_as_ondas_e_nao_executa_dependente_pendente() -> None:
    provider = _ProviderMedido(0.0)
    svc = OrchestrationService(provider=provider)
    oid = svc.create_orchestration(
        "feature ampla",
        decision_input=DecisionInput(
            user_request="f", domains=["backend", "frontend"], parallelizable=True
        ),
    ).id
    fase = svc.get_cards(oid)[0].phase
    dependente = next(c for c in svc.get_cards(oid) if c.phase == fase)
    b = svc._bundle(oid)  # noqa: SLF001
    extra = dependente.model_copy(update={"id": "card_depois", "dependencies": [dependente.id]})
    b.board_service.add_card(extra)
    svc.run_phase(oid, fase)
    assert "card_depois" not in provider.chamadas
    assert svc.get_cards(oid)[-1].status.value == "Ready"  # não foi bloqueado às cegas
    eventos = [e for e in svc.timeline(oid) if e.type == "CardsAguardandoDependencia"]
    assert eventos and "card_depois" in eventos[-1].payload["cards"]


def test_nenhum_card_executa_duas_vezes_com_coordenadores_concorrentes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ASO_MAX_PARALELO_POR_ORQUESTRACAO", "3")
    provider = _ProviderMedido(0.2)
    svc = OrchestrationService(provider=provider)
    oid = _orquestracao(svc, 3, ExecutionStrategy.PARALLEL)
    threads = [threading.Thread(target=svc.run_plan, args=(oid,)) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    assert sorted(provider.chamadas) == sorted(set(provider.chamadas))
    assert len(provider.chamadas) == 3
