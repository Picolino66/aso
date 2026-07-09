"""Clareza + esteira F1→F7: início em F1, gate de fase vazia, erro visível, filtro de log."""

from __future__ import annotations

import logging
from typing import Any

from aso.agents.models import AgentOutput, AgentSpec
from aso.control.orchestration_service import OrchestrationService
from aso.observability.logging import _QuietAccessFilter
from aso.shared.types import Phase


def test_orchestration_starts_at_f1() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("Criar uma calculadora")
    assert orch.current_phase == Phase.F1  # esteira começa no discovery


def test_empty_phase_gate_passes_vacuously_and_opens_approval() -> None:
    # "backend" gera 1 card de dev (F5); F1 não tem cards → não deve travar.
    svc = OrchestrationService()
    orch = svc.create_orchestration("backend")
    assert not any(c.phase == Phase.F1 for c in svc.get_cards(orch.id))

    result = svc.run_phase(orch.id)  # fase corrente = F1 (vazia)
    assert result["phase"] == "F1"
    assert result["gate_status"] == "PASSED"  # vacuamente aprovado
    assert result["approval_id"]  # abre aprovação p/ avançar


def test_agent_role_maps_to_phase() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("implementar no backend")
    # o card de desenvolvimento nasce em F5, não na fase inicial F1
    assert svc.get_cards(orch.id)[0].phase == Phase.F5


class _FailProvider:
    id = "fail"

    def execute(self, agent: AgentSpec, task: dict[str, Any]) -> AgentOutput:
        raise RuntimeError("comando 'claude' não encontrado")


def test_failed_card_records_reason() -> None:
    svc = OrchestrationService(provider=_FailProvider())
    orch = svc.create_orchestration("backend")
    card = svc.get_cards(orch.id)[0]
    svc.run_card(orch.id, card.id)

    failed = next(c for c in svc.get_cards(orch.id) if c.id == card.id)
    assert failed.status.value == "Failed"
    assert failed.block_reason and "claude" in failed.block_reason  # motivo visível


def _record(path: str) -> logging.LogRecord:
    # Espelha o formato do uvicorn.access: (client, method, path, http_version, status).
    r = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, "%s", None, None)
    r.args = ("127.0.0.1:1", "GET", path, "1.1", 200)
    return r


def test_quiet_access_filter_drops_health_and_metrics() -> None:
    f = _QuietAccessFilter()
    assert f.filter(_record("/health")) is False
    assert f.filter(_record("/metrics")) is False
    assert f.filter(_record("/v1/orchestrations")) is True
