"""compute_next_step — o que falta para a esteira seguir (ADR-0013).

Um caso por bloqueio: as regras de governança que travam o avanço vivem aqui e a UI
só renderiza o resultado, então cada uma precisa de teste próprio.
"""

from __future__ import annotations

from aso.control.models import Orchestration
from aso.control.next_step import (
    NextStepInput,
    compute_next_step,
    next_phase_of,
)
from aso.execution.docs_drift import DocsDriftReport
from aso.governance.models import Conflict, HumanApproval, PullRequest, QualityGateResult
from aso.kanban.models import KanbanCard
from aso.shared.types import (
    CardType,
    ColumnKey,
    ConflictType,
    ExecutionMode,
    GateStatus,
    Phase,
)

ORCH_ID = "orch_next"
BOARD_ID = "board_next"


def _orch(**kwargs: object) -> Orchestration:
    """Orquestração já configurada (pasta + docs + validação): o caminho feliz."""
    base: dict[str, object] = {
        "id": ORCH_ID,
        "target_path": "/tmp/projeto",
        "workspace_prepared": True,
        "validation_command": "npm run build",
        "execution_mode": ExecutionMode.CODE_EXECUTION,
        "current_phase": Phase.F5,
        "status": "running",
        "user_request": "Criar calculadora",
    }
    base.update(kwargs)
    return Orchestration(**base)  # type: ignore[arg-type]


def _card(status: ColumnKey, *, phase: Phase = Phase.F5, **kwargs: object) -> KanbanCard:
    base: dict[str, object] = {
        "board_id": BOARD_ID,
        "orchestration_id": ORCH_ID,
        "phase": phase,
        "type": CardType.TASK,
        "title": "BackendDevelopmentAgent: domínio de baixo risco",
        "status": status,
        "assignee": "BackendDevelopmentAgent",
    }
    base.update(kwargs)
    return KanbanCard(**base)  # type: ignore[arg-type]


def _gate(status: GateStatus, *, phase: Phase = Phase.F5, **kwargs: object) -> QualityGateResult:
    base: dict[str, object] = {"orchestration_id": ORCH_ID, "phase": phase, "status": status}
    base.update(kwargs)
    return QualityGateResult(**base)  # type: ignore[arg-type]


def _codes(report: object) -> list[str]:
    return [b.code for b in report.blockers]  # type: ignore[attr-defined]


# ------------------------------------------------------------------ configuração


def test_sem_pasta_de_trabalho_bloqueia() -> None:
    rel = compute_next_step(NextStepInput(orchestration=_orch(target_path=None)))
    assert "workspace_ausente" in _codes(rel)
    assert rel.headline == "Sem pasta de trabalho"


def test_execucao_direta_sem_validacao_manda_configurar() -> None:
    rel = compute_next_step(NextStepInput(orchestration=_orch(validation_command=None)))
    assert _codes(rel)[0] == "validacao_ausente"
    assert rel.primary_action is not None
    assert rel.primary_action.method == "PATCH"
    assert rel.primary_action.path.endswith("/execution-settings")


def test_pipeline_completo_nao_exige_comando_de_validacao() -> None:
    rel = compute_next_step(
        NextStepInput(
            orchestration=_orch(validation_command=None, execution_mode=ExecutionMode.FULL_PIPELINE)
        )
    )
    assert "validacao_ausente" not in _codes(rel)


def test_docs_first_pendente_oferece_geracao() -> None:
    rel = compute_next_step(NextStepInput(orchestration=_orch(workspace_prepared=False)))
    bloqueio = next(b for b in rel.blockers if b.code == "docs_first_pendente")
    assert bloqueio.action is not None
    assert bloqueio.action.path.endswith("/analyze-folder")


def test_executor_indisponivel_bloqueia_com_motivo() -> None:
    rel = compute_next_step(
        NextStepInput(
            orchestration=_orch(selected_executor="codex-default"),
            executor_available=False,
            executor_reason="binário do Codex não encontrado",
        )
    )
    bloqueio = next(b for b in rel.blockers if b.code == "executor_indisponivel")
    assert "codex-default" in bloqueio.title
    assert bloqueio.detail == "binário do Codex não encontrado"
    assert bloqueio.action is not None and bloqueio.action.role == "admin"


# ------------------------------------------------------------------ cards da fase


def test_card_em_ready_pede_rodar_a_fase() -> None:
    """Caso da tela: 1 card em Ready, nenhuma execução — o clique é 'Executar fase'."""
    rel = compute_next_step(NextStepInput(orchestration=_orch(), cards=[_card(ColumnKey.READY)]))
    assert "cards_prontos" in _codes(rel)
    assert rel.primary_action is not None
    assert rel.primary_action.path.endswith("/run-phase")
    assert rel.cards_total == 1 and rel.cards_done == 0


def test_card_no_backlog_pede_mover_para_ready() -> None:
    card = _card(ColumnKey.BACKLOG)
    rel = compute_next_step(NextStepInput(orchestration=_orch(), cards=[card]))
    bloqueio = next(b for b in rel.blockers if b.code == "cards_em_backlog")
    assert bloqueio.action is not None
    assert bloqueio.action.path.endswith(f"/cards/{card.id}/move")
    assert bloqueio.action.body == {"to_column": "Ready"}


def test_card_bloqueado_vence_card_pronto_na_ordem() -> None:
    rel = compute_next_step(
        NextStepInput(
            orchestration=_orch(),
            cards=[_card(ColumnKey.READY), _card(ColumnKey.BLOCKED, block_reason="conflito")],
        )
    )
    assert _codes(rel)[0] == "cards_bloqueados"
    assert rel.explanation == "conflito"


def test_diff_vazio_vira_dica_de_permissao_do_executor() -> None:
    """O agente rodou e não escreveu nada: a causa quase sempre é permissão, não o card."""
    rel = compute_next_step(
        NextStepInput(
            orchestration=_orch(),
            cards=[
                _card(
                    ColumnKey.FAILED,
                    block_reason=(
                        "BackendDevelopmentAgent falhou após 2 tentativas: Executor CLI não "
                        "produziu alterações no worktree (diff vazio)."
                    ),
                )
            ],
        )
    )
    assert _codes(rel)[0] == "executor_sem_permissao"
    assert "--permission-mode" in rel.blockers[0].detail
    assert "--sandbox workspace-write" in rel.blockers[0].detail
    assert "cards_falhos" in _codes(rel)  # o retry continua disponível


def test_falha_comum_nao_vira_dica_de_permissao() -> None:
    rel = compute_next_step(
        NextStepInput(
            orchestration=_orch(),
            cards=[_card(ColumnKey.FAILED, block_reason="Executor CLI terminou com exit=1")],
        )
    )
    assert "executor_sem_permissao" not in _codes(rel)


def test_card_falho_oferece_retry() -> None:
    rel = compute_next_step(
        NextStepInput(orchestration=_orch(), cards=[_card(ColumnKey.FAILED, block_reason="boom")])
    )
    bloqueio = next(b for b in rel.blockers if b.code == "cards_falhos")
    assert bloqueio.action is not None and bloqueio.action.path.endswith("/retry")


def test_fase_sem_cards_sugere_rodar_a_fase() -> None:
    rel = compute_next_step(
        NextStepInput(orchestration=_orch(), cards=[_card(ColumnKey.READY, phase=Phase.F2)])
    )
    assert "sem_cards_na_fase" in _codes(rel)
    assert rel.cards_total == 0


def test_card_executado_sem_pr_pede_abrir_pr() -> None:
    card = _card(ColumnKey.TESTING)
    rel = compute_next_step(NextStepInput(orchestration=_orch(), cards=[card]))
    bloqueio = next(b for b in rel.blockers if b.code == "entrega_pendente")
    assert bloqueio.action is not None
    assert bloqueio.action.path.endswith(f"/cards/{card.id}/open-pr")


def test_cards_entregues_pedem_o_gate() -> None:
    rel = compute_next_step(NextStepInput(orchestration=_orch(), cards=[_card(ColumnKey.DONE)]))
    assert "gate_pendente" in _codes(rel)
    assert rel.cards_done == 1 and rel.cards_total == 1


# ------------------------------------------------------------------ governança


def test_aprovacao_pendente_ranqueia_acima_do_trabalho_de_card() -> None:
    aprovacao = HumanApproval(
        orchestration_id=ORCH_ID,
        action="Aprovar avanço da fase F5",
        reason="Fase F5 concluída (gate PASSED).",
        payload={"kind": "phase_gate", "phase": "F5"},
    )
    rel = compute_next_step(
        NextStepInput(orchestration=_orch(), cards=[_card(ColumnKey.READY)], approvals=[aprovacao])
    )
    assert _codes(rel)[0] == "aprovacao_pendente"
    assert rel.primary_action is not None
    assert rel.primary_action.path == f"/v1/approvals/{aprovacao.id}/approve"
    assert rel.primary_action.role == "admin"


def test_pr_sem_ci_pede_rodar_ci() -> None:
    pr = PullRequest(orchestration_id=ORCH_ID, branch="aso/card-1")
    rel = compute_next_step(NextStepInput(orchestration=_orch(), pulls=[pr]))
    bloqueio = next(b for b in rel.blockers if b.code == "pr_ci_pendente")
    assert bloqueio.action is not None and bloqueio.action.path.endswith(f"/pulls/{pr.id}/ci/run")


def test_pr_com_ci_verde_pede_revisao() -> None:
    pr = PullRequest(orchestration_id=ORCH_ID, branch="aso/card-1", ci_status="passed")
    rel = compute_next_step(NextStepInput(orchestration=_orch(), pulls=[pr]))
    bloqueio = next(b for b in rel.blockers if b.code == "pr_review_pendente")
    assert bloqueio.action is not None and bloqueio.action.body == {"status": "approved"}


def test_pr_com_ci_e_revisao_libera_merge_admin() -> None:
    pr = PullRequest(
        orchestration_id=ORCH_ID,
        branch="aso/card-1",
        ci_status="passed",
        review_status="approved",
    )
    rel = compute_next_step(NextStepInput(orchestration=_orch(), pulls=[pr]))
    bloqueio = next(b for b in rel.blockers if b.code == "pr_pronto_merge")
    assert bloqueio.action is not None
    assert bloqueio.action.role == "admin"
    assert bloqueio.action.path.endswith(f"/pulls/{pr.id}/merge")


def test_pr_com_ci_reprovada_bloqueia() -> None:
    pr = PullRequest(orchestration_id=ORCH_ID, branch="aso/card-1", ci_status="failed")
    rel = compute_next_step(NextStepInput(orchestration=_orch(), pulls=[pr]))
    bloqueio = next(b for b in rel.blockers if b.code == "pr_ci_pendente")
    assert bloqueio.severity == "bloqueia"


def test_conflito_aberto_oferece_resolucao() -> None:
    conflito = Conflict(
        orchestration_id=ORCH_ID,
        type=ConflictType.ARCHITECTURE,
        description="patch contraria ADR aceita",
    )
    rel = compute_next_step(NextStepInput(orchestration=_orch(), conflicts=[conflito]))
    bloqueio = next(b for b in rel.blockers if b.code == "conflitos_abertos")
    assert bloqueio.detail == "patch contraria ADR aceita"
    assert bloqueio.action is not None
    assert bloqueio.action.path.endswith(f"/conflicts/{conflito.id}/resolve")


def test_gate_reprovado_mostra_acoes_requeridas() -> None:
    gate = _gate(
        GateStatus.FAILED,
        blocking_issues=["tests_pass"],
        required_actions=["Corrigir a suíte de testes"],
    )
    rel = compute_next_step(NextStepInput(orchestration=_orch(), gate_results=[gate]))
    bloqueio = next(b for b in rel.blockers if b.code == "gate_reprovado")
    assert bloqueio.detail == "Corrigir a suíte de testes"
    assert bloqueio.severity == "bloqueia"


# ------------------------------------------------------------------ sinais não-bloqueantes


def test_drift_de_docs_avisa_sem_virar_manchete() -> None:
    drift = DocsDriftReport(
        path="/tmp/projeto",
        has_docs=True,
        has_drift=True,
        undocumented_modules=["api"],
        orphan_module_docs=[],
        broken_links=[],
        unfilled_features=["docs/modules/api/api.md"],
    )
    rel = compute_next_step(
        NextStepInput(orchestration=_orch(), cards=[_card(ColumnKey.READY)], drift=drift)
    )
    bloqueio = next(b for b in rel.blockers if b.code == "drift_docs")
    assert bloqueio.severity == "informativo"
    assert "1 módulo(s) sem doc" in bloqueio.detail
    assert rel.headline != bloqueio.title  # aviso não sequestra o próximo passo


def test_slo_em_risco_entra_como_aviso() -> None:
    rel = compute_next_step(
        NextStepInput(orchestration=_orch(), slo_breaches=["sem_conflitos_abertos"])
    )
    bloqueio = next(b for b in rel.blockers if b.code == "slo_em_risco")
    assert bloqueio.severity == "informativo"


# ------------------------------------------------------------------ ciclo completo


def test_fase_pronta_oferece_avanco() -> None:
    gate = _gate(GateStatus.PASSED)
    aprovacao = HumanApproval(
        orchestration_id=ORCH_ID,
        action="Aprovar avanço da fase F5",
        status="approved",
        payload={"kind": "phase_gate", "phase": "F5"},
    )
    rel = compute_next_step(
        NextStepInput(
            orchestration=_orch(),
            cards=[_card(ColumnKey.DONE)],
            gate_results=[gate],
            approvals=[aprovacao],
        )
    )
    assert rel.blockers == []
    assert rel.primary_action is not None
    assert rel.primary_action.path.endswith("/advance-phase")
    assert rel.next_phase == Phase.F6


def test_cancelada_so_oferece_retomar() -> None:
    rel = compute_next_step(
        NextStepInput(orchestration=_orch(status="cancelled"), cards=[_card(ColumnKey.READY)])
    )
    assert _codes(rel) == ["cancelada"]
    assert rel.primary_action is not None and rel.primary_action.path.endswith("/resume")


def test_concluida_nao_tem_bloqueios() -> None:
    rel = compute_next_step(NextStepInput(orchestration=_orch(status="completed")))
    assert rel.blockers == []
    assert rel.headline == "Esteira concluída"


# ------------------------------------------------------------------ checklist


def test_checklist_marca_onde_voce_esta() -> None:
    rel = compute_next_step(NextStepInput(orchestration=_orch(), cards=[_card(ColumnKey.READY)]))
    estados = {item.code: item.state for item in rel.checklist}
    assert estados["workspace"] == "ok"
    assert estados["docs_first"] == "ok"
    assert estados["validacao"] == "ok"
    assert estados["cards_executados"] == "atual"  # primeiro pendente
    assert estados["gate"] == "pendente"
    assert estados["aprovacao"] == "pendente"


def test_checklist_de_entrega_so_existe_nas_fases_de_codigo() -> None:
    codigo = compute_next_step(NextStepInput(orchestration=_orch(), cards=[_card(ColumnKey.READY)]))
    planejamento = compute_next_step(
        NextStepInput(
            orchestration=_orch(current_phase=Phase.F2),
            cards=[_card(ColumnKey.READY, phase=Phase.F2)],
        )
    )
    assert any(item.code == "entrega" for item in codigo.checklist)
    assert all(item.code != "entrega" for item in planejamento.checklist)


def test_checklist_marca_gate_reprovado_como_falha() -> None:
    rel = compute_next_step(
        NextStepInput(
            orchestration=_orch(),
            cards=[_card(ColumnKey.DONE)],
            gate_results=[_gate(GateStatus.FAILED)],
        )
    )
    estados = {item.code: item.state for item in rel.checklist}
    assert estados["gate"] == "falha"


def test_rotulo_e_proxima_fase_acompanham_a_esteira() -> None:
    rel = compute_next_step(NextStepInput(orchestration=_orch(current_phase=Phase.F7)))
    assert rel.phase_label == "Operate & Evolve"
    assert rel.next_phase is None
    assert next_phase_of(Phase.F1) == Phase.F2
    assert next_phase_of(Phase.F7) is None
