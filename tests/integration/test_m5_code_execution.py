"""(M5) Execução de código real: gate rodando testes.

O `RoutingExecutionProvider` (planner/coder por fase) saiu na ADR-0076: a escolha por etapa é
do catálogo (`agent_assignments` + perfil padrão), coberta em `test_catalogo_unico_executores`.
"""

from __future__ import annotations

import pytest

from aso.application.orchestration_service import OrchestrationService
from aso.shared.types import Phase


def test_code_gate_blocks_on_failing_tests(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("ASO_TARGET_REPO", str(tmp_path))
    monkeypatch.setenv("ASO_GATE_TEST_COMMAND", "bash -c 'exit 1'")  # suíte vermelha
    svc = OrchestrationService()
    orch = svc.create_orchestration("backend")
    card = svc.get_cards(orch.id)[0]
    svc.run_card(orch.id, card.id)

    result = svc.run_phase(orch.id, Phase.F5)  # gate de código roda em F5
    assert result["gate_status"] == "FAILED"
    assert result["approval_id"] is None
    assert result["snapshot"] is None


def test_code_gate_passes_on_green_tests(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("ASO_TARGET_REPO", str(tmp_path))
    monkeypatch.setenv("ASO_GATE_TEST_COMMAND", "bash -c 'exit 0'")  # suíte verde
    svc = OrchestrationService()
    orch = svc.create_orchestration("backend")
    card = svc.get_cards(orch.id)[0]
    svc.run_card(orch.id, card.id)

    result = svc.run_phase(orch.id, Phase.F5)
    assert result["gate_status"] == "PASSED"
    assert result["approval_id"]
