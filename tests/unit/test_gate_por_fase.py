"""MEL-16 — quality gate escopado por fase, sem aprovação vazia (ADR-0060).

Tenta explicitamente as duas aprovações indevidas do critério antigo
(`store.version > 0 or not has_work`): patch de outra fase aprovando a fase, e fase
vazia virando `PASSED` com aprovação humana.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aso.application.orchestration_service import OrchestrationService
from aso.control.models import DecisionInput
from aso.governance.gate_definitions import tabela_markdown
from aso.governance.quality_gate_engine import Criterion, QualityGateEngine
from aso.shared.types import ColumnKey, GateStatus, Phase

RAIZ = Path(__file__).resolve().parents[2]


def _multifase() -> tuple[OrchestrationService, str]:
    """Cards em F2 (arquitetura), F5 (backend) e F6 (revisão)."""
    svc = OrchestrationService()
    oid = svc.create_orchestration(
        "arquitetura e backend",
        decision_input=DecisionInput(user_request="x", domains=["architecture", "backend"]),
    ).id
    return svc, oid


def _card_da_fase(svc: OrchestrationService, oid: str, fase: Phase) -> str:
    return next(c.id for c in svc.get_cards(oid) if c.phase == fase)


def _evidencias(resultado: object) -> str:
    return " ".join(e for c in resultado.criteria for e in c.evidence)  # type: ignore[attr-defined]


@pytest.mark.parametrize("fase", list(Phase))
def test_fase_sem_cards_e_skipped_sem_snapshot(fase: Phase) -> None:
    svc = OrchestrationService()
    oid = svc.create_orchestration("backend", seed_cards=False).id
    resultado = svc.run_quality_gate(oid, fase)
    assert resultado.status == GateStatus.SKIPPED
    assert resultado.approved_by is None
    assert svc.list_snapshots(oid) == []


def test_patch_de_outra_fase_nao_aprova_a_fase() -> None:
    svc, oid = _multifase()
    svc.run_card(oid, _card_da_fase(svc, oid, Phase.F5))  # patch aplicado em F5
    # Tentativa de burla: o card de F2 "parece" entregue, mas nada foi aplicado em F2.
    b = svc._bundle(oid)  # noqa: SLF001 - força a coluna sem executar o agente
    b.board_service.move_card(_card_da_fase(svc, oid, Phase.F2), ColumnKey.TESTING)
    resultado = svc.run_quality_gate(oid, Phase.F2)
    assert resultado.status == GateStatus.FAILED
    assert resultado.blocking_issues == ["output_da_fase_aplicado"]
    assert "patches de outras fases não contam" in _evidencias(resultado)


def test_card_pendente_reprova_listando_o_card() -> None:
    svc, oid = _multifase()
    card_f2 = next(c for c in svc.get_cards(oid) if c.phase == Phase.F2)
    resultado = svc.run_quality_gate(oid, Phase.F2)
    assert resultado.status == GateStatus.FAILED
    assert "cards_da_fase_entregues" in resultado.blocking_issues
    assert card_f2.id in _evidencias(resultado)
    assert "(Ready)" in _evidencias(resultado)


def test_fase_entregue_com_output_proprio_passa_e_gera_snapshot() -> None:
    svc, oid = _multifase()
    svc.run_card(oid, _card_da_fase(svc, oid, Phase.F2))
    resultado = svc.run_quality_gate(oid, Phase.F2)
    assert resultado.status == GateStatus.PASSED
    assert [s.snapshot_version for s in svc.list_snapshots(oid)] == ["O2"]


def test_cards_cancelados_nao_contam_como_trabalho() -> None:
    svc, oid = _multifase()
    b = svc._bundle(oid)  # noqa: SLF001
    b.board_service.move_card(_card_da_fase(svc, oid, Phase.F2), ColumnKey.CANCELLED)
    assert svc.run_quality_gate(oid, Phase.F2).status == GateStatus.SKIPPED


def test_card_testing_com_branch_ainda_espera_o_merge() -> None:
    svc, oid = _multifase()
    card_id = _card_da_fase(svc, oid, Phase.F2)
    svc.run_card(oid, card_id)
    svc._bundle(oid).board_service.get_card(card_id).branch = "feat/x"  # type: ignore[union-attr]  # noqa: SLF001
    resultado = svc.run_quality_gate(oid, Phase.F2)
    assert resultado.status == GateStatus.FAILED
    assert "cards_da_fase_entregues" in resultado.blocking_issues


def test_run_phase_de_fase_vazia_registra_phase_skipped_sem_aprovacao() -> None:
    svc, oid = _multifase()
    resultado = svc.run_phase(oid, Phase.F3)
    assert resultado["gate_status"] == "SKIPPED"
    assert resultado["approval_id"] is None
    assert not [a for a in svc.list_approvals(oid) if a.payload.get("kind") == "phase_gate"]
    assert [e.payload["phase"] for e in svc.timeline(oid) if e.type == "PhaseSkipped"] == ["F3"]


def test_autopilot_pula_fases_vazias_e_para_no_gate_reprovado() -> None:
    svc, oid = _multifase()
    svc.start_autopilot(oid)
    aprovacoes: list[str] = []
    for _ in range(len(list(Phase))):
        pendente = next(
            (
                a
                for a in svc.list_approvals(oid)
                if a.status == "pending" and a.payload.get("kind") == "phase_gate"
            ),
            None,
        )
        if pendente is None:
            break
        aprovacoes.append(str(pendente.payload["phase"]))
        svc.decide_approval(pendente.id, approved=True)
    # Só as fases com trabalho pediram aprovação humana; F3/F4 vazias foram puladas.
    assert aprovacoes == ["F2", "F5"]
    puladas = [e.payload["phase"] for e in svc.timeline(oid) if e.type == "PhaseSkipped"]
    assert puladas == ["F1", "F3", "F4"]
    # F6: o card de revisão depende do card de F5 ainda não mesclado → gate FAILED, e o
    # autopilot para ali em vez de pular (fase com trabalho nunca vira SKIPPED).
    assert svc.get(oid).current_phase == Phase.F6
    assert svc.list_gate_results(oid)[-1].status == GateStatus.FAILED


# ----------------------------------------------------- critérios condicionais mantidos
def test_discovery_reprovado_reprova_f1_mesmo_sem_cards() -> None:
    svc = OrchestrationService()
    oid = svc.create_orchestration("backend", seed_cards=False).id
    svc._bundle(oid).orchestration.discovery_reports = [{"status": "reprovado"}]  # noqa: SLF001
    resultado = svc.run_quality_gate(oid, Phase.F1)
    assert resultado.status == GateStatus.FAILED
    assert resultado.blocking_issues == ["discovery_aprovado"]


def test_deploy_nao_aceito_reprova_f6_mesmo_sem_cards() -> None:
    svc = OrchestrationService()
    oid = svc.create_orchestration("backend", seed_cards=False).id
    svc._bundle(oid).orchestration.deploy_runs = [{"aceite_status": "reprovado"}]  # noqa: SLF001
    resultado = svc.run_quality_gate(oid, Phase.F6)
    assert resultado.status == GateStatus.FAILED
    assert resultado.blocking_issues == ["deploy_aprovado"]


def test_so_criterio_nao_bloqueante_fica_skipped_com_aviso() -> None:
    engine = QualityGateEngine()
    engine.register(
        Phase.F5, [Criterion("docs_in_sync", lambda _c: (False, "drift"), blocking=False)]
    )
    resultado = engine.run(Phase.F5, "orch", {})
    assert resultado.status == GateStatus.SKIPPED
    assert resultado.warnings == ["docs_in_sync"]


def test_gate_sem_criterios_e_skipped() -> None:
    engine = QualityGateEngine()
    engine.register(Phase.F3, [])
    assert engine.run(Phase.F3, "orch", {}).status == GateStatus.SKIPPED


def test_tabela_de_gates_da_documentacao_e_gerada_das_definicoes() -> None:
    doc = (RAIZ / "docs/quality-gates.md").read_text(encoding="utf-8")
    inicio = doc.index("<!-- gate-definitions:inicio -->") + len("<!-- gate-definitions:inicio -->")
    fim = doc.index("<!-- gate-definitions:fim -->")
    assert doc[inicio:fim].strip() == tabela_markdown().strip()
