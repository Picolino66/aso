"""compute_next_step — o que falta para a esteira seguir (ADR-0013).

Um caso por bloqueio: as regras de governança que travam o avanço vivem aqui e a UI
só renderiza o resultado, então cada uma precisa de teste próprio.
"""

from __future__ import annotations

from aso.control.deploy import DeployRun
from aso.control.discovery import DiscoveryReport
from aso.control.models import Orchestration
from aso.control.next_step import (
    NextStepInput,
    compute_next_step,
    next_phase_of,
)
from aso.execution.docs_drift import DocsDriftReport
from aso.governance.models import (
    CandidateRun,
    Conflict,
    HumanApproval,
    PullRequest,
    QualityGateResult,
)
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


def test_pr_com_ci_verde_e_sem_veredito_pede_rodar_revisao() -> None:
    """Regressão (ADR-0017): o antigo `pr_review_pendente` de um clique — que oferecia
    `{"status": "approved"}` sem ninguém ter revisado — não existe mais."""
    pr = PullRequest(orchestration_id=ORCH_ID, branch="aso/card-1", ci_status="passed")
    rel = compute_next_step(NextStepInput(orchestration=_orch(), pulls=[pr]))
    assert "pr_review_pendente" not in _codes(rel)
    bloqueio = next(b for b in rel.blockers if b.code == "pr_review_nao_executada")
    assert bloqueio.action is not None
    assert bloqueio.action.path.endswith(f"/pulls/{pr.id}/review/run")
    assert bloqueio.action.body == {}


def test_pr_com_alteracoes_obrigatorias_bloqueia_com_as_acoes() -> None:
    pr = PullRequest(
        orchestration_id=ORCH_ID,
        branch="aso/card-1",
        card_id="card-1",
        ci_status="passed",
        review_verdict={
            "veredito": "alteracoes_obrigatorias",
            "acoes": [{"descricao": "Adicionar teste para o cenário de erro"}],
        },
    )
    rel = compute_next_step(NextStepInput(orchestration=_orch(), pulls=[pr]))
    bloqueio = next(b for b in rel.blockers if b.code == "pr_alteracoes_obrigatorias")
    assert bloqueio.severity == "bloqueia"
    assert "Adicionar teste para o cenário de erro" in bloqueio.detail
    assert bloqueio.action is not None and bloqueio.action.path.endswith("/cards/card-1/run")


def test_pr_aprovada_pelo_agente_mas_pendente_pede_confirmacao_humana() -> None:
    """Veredito aprovado, mas `review_status` continua pending (risco exige humano, §4.3)."""
    pr = PullRequest(
        orchestration_id=ORCH_ID,
        branch="aso/card-1",
        ci_status="passed",
        review_verdict={"veredito": "aprovado"},
        review_status="pending",
    )
    rel = compute_next_step(NextStepInput(orchestration=_orch(), pulls=[pr]))
    bloqueio = next(b for b in rel.blockers if b.code == "pr_review_humana")
    assert bloqueio.severity == "aguardando_humano"
    assert bloqueio.action is not None and bloqueio.action.role == "admin"


def test_pr_com_ci_e_revisao_libera_merge_admin() -> None:
    pr = PullRequest(
        orchestration_id=ORCH_ID,
        branch="aso/card-1",
        ci_status="passed",
        review_status="approved",
        review_verdict={"veredito": "aprovado"},
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


# ------------------------------------------------------------------------ discovery


def test_discovery_nunca_rodado_nao_bloqueia_nem_aparece_no_checklist() -> None:
    rel = compute_next_step(NextStepInput(orchestration=_orch(current_phase=Phase.F1)))
    assert "discovery_reprovado" not in _codes(rel)
    assert "discovery_aguardando_aprovacao" not in _codes(rel)
    assert all(item.code != "discovery" for item in rel.checklist)


def test_discovery_reprovado_bloqueia_com_acao_de_operador() -> None:
    rel = compute_next_step(
        NextStepInput(
            orchestration=_orch(current_phase=Phase.F1),
            discovery_report=DiscoveryReport(status="reprovado", revisao_comentarios="ajustar X"),
        )
    )
    bloqueio = next(b for b in rel.blockers if b.code == "discovery_reprovado")
    assert bloqueio.severity == "acao_do_operador"
    assert bloqueio.detail == "ajustar X"
    assert bloqueio.action is not None and bloqueio.action.path.endswith("/discovery/run")
    estados = {item.code: item.state for item in rel.checklist}
    assert estados["discovery"] == "pendente"


def test_discovery_aguardando_aprovacao_exige_humano() -> None:
    rel = compute_next_step(
        NextStepInput(
            orchestration=_orch(current_phase=Phase.F1),
            discovery_report=DiscoveryReport(status="aguardando_aprovacao"),
        )
    )
    bloqueio = next(b for b in rel.blockers if b.code == "discovery_aguardando_aprovacao")
    assert bloqueio.severity == "aguardando_humano"
    assert bloqueio.action is not None and bloqueio.action.role == "admin"
    assert bloqueio.action.path.endswith("/discovery/decide")


def test_discovery_aprovado_nao_bloqueia_e_marca_checklist_ok() -> None:
    rel = compute_next_step(
        NextStepInput(
            orchestration=_orch(current_phase=Phase.F1),
            discovery_report=DiscoveryReport(status="aprovado"),
        )
    )
    assert "discovery_reprovado" not in _codes(rel)
    assert "discovery_aguardando_aprovacao" not in _codes(rel)
    estados = {item.code: item.state for item in rel.checklist}
    assert estados["discovery"] == "ok"


def test_discovery_fora_da_fase_f1_nao_bloqueia() -> None:
    """O relatório persiste na orquestração mesmo depois de avançar de fase — o
    bloqueio só faz sentido enquanto a esteira ainda está em F1."""
    rel = compute_next_step(
        NextStepInput(
            orchestration=_orch(current_phase=Phase.F2),
            discovery_report=DiscoveryReport(status="aguardando_aprovacao"),
        )
    )
    assert "discovery_aguardando_aprovacao" not in _codes(rel)


# ------------------------------------------------------------- implantação (§18-22)


def test_deploy_nunca_rodado_nao_bloqueia() -> None:
    """`status` pendente (default) = nunca implantou — não-regressivo."""
    rel = compute_next_step(
        NextStepInput(orchestration=_orch(current_phase=Phase.F6), deploy=DeployRun())
    )
    assert "deploy_falhou" not in _codes(rel)
    assert "deploy_aguardando_aceite" not in _codes(rel)
    assert "deploy_reprovada" not in _codes(rel)


def test_deploy_falhou_oferece_rodar_de_novo() -> None:
    rel = compute_next_step(
        NextStepInput(
            orchestration=_orch(current_phase=Phase.F6),
            deploy=DeployRun(status="falhou", aceite_status="reprovado", resultado="exit=1"),
        )
    )
    bloqueio = next(b for b in rel.blockers if b.code == "deploy_falhou")
    assert bloqueio.severity == "acao_do_operador"
    assert bloqueio.action is not None and bloqueio.action.path.endswith("/deploy/run")


def test_deploy_aguardando_aceite_exige_humano() -> None:
    rel = compute_next_step(
        NextStepInput(
            orchestration=_orch(current_phase=Phase.F6),
            deploy=DeployRun(status="sucesso", aceite_status="aguardando_aprovacao"),
        )
    )
    bloqueio = next(b for b in rel.blockers if b.code == "deploy_aguardando_aceite")
    assert bloqueio.severity == "aguardando_humano"
    assert bloqueio.action is not None and bloqueio.action.role == "admin"
    assert bloqueio.action.path.endswith("/deploy/approve")


def test_deploy_reprovado_no_aceite_oferece_rodar_de_novo() -> None:
    rel = compute_next_step(
        NextStepInput(
            orchestration=_orch(current_phase=Phase.F6),
            deploy=DeployRun(status="sucesso", aceite_status="reprovado"),
        )
    )
    bloqueio = next(b for b in rel.blockers if b.code == "deploy_reprovada")
    assert bloqueio.severity == "acao_do_operador"


def test_deploy_aprovado_nao_bloqueia_e_marca_checklist_ok() -> None:
    rel = compute_next_step(
        NextStepInput(
            orchestration=_orch(current_phase=Phase.F6),
            deploy=DeployRun(status="sucesso", aceite_status="aprovado"),
        )
    )
    assert "deploy_aguardando_aceite" not in _codes(rel)
    assert "deploy_reprovada" not in _codes(rel)
    estados = {item.code: item.state for item in rel.checklist}
    assert estados["implantacao"] == "ok"


def test_deploy_fora_da_fase_f6_nao_bloqueia() -> None:
    rel = compute_next_step(
        NextStepInput(
            orchestration=_orch(current_phase=Phase.F5),
            deploy=DeployRun(status="sucesso", aceite_status="aguardando_aprovacao"),
        )
    )
    assert "deploy_aguardando_aceite" not in _codes(rel)


# ------------------------------------------------------- corrida de candidatos (plano6 §0)


def _race(*, card_id: str, falhou: bool) -> CandidateRun:
    candidates: list[dict[str, object]] = [
        {"executor": "a", "branch": "aso/a", "diff_lines": 3, "files": ["a.py"], "error": None},
    ]
    if falhou:
        candidates.append(
            {"executor": "b", "branch": "", "diff_lines": 0, "files": [], "error": "broken pipe"}
        )
    return CandidateRun(
        orchestration_id=ORCH_ID, card_id=card_id, recommended_branch="aso/a", candidates=candidates
    )


def test_corrida_sem_falha_nao_bloqueia() -> None:
    rel = compute_next_step(
        NextStepInput(
            orchestration=_orch(current_phase=Phase.F5),
            cards=[_card(ColumnKey.IN_PROGRESS, board_id=BOARD_ID, id="c1")],
            candidate_runs=[_race(card_id="c1", falhou=False)],
        )
    )
    assert "corrida_degradada" not in _codes(rel)


def test_corrida_degradada_bloqueia_com_acao_de_operador() -> None:
    rel = compute_next_step(
        NextStepInput(
            orchestration=_orch(current_phase=Phase.F5),
            cards=[_card(ColumnKey.IN_PROGRESS, board_id=BOARD_ID, id="c1")],
            candidate_runs=[_race(card_id="c1", falhou=True)],
        )
    )
    bloqueio = next(b for b in rel.blockers if b.code == "corrida_degradada")
    assert bloqueio.severity == "acao_do_operador"
    assert bloqueio.title == "Corrida de candidatos concluiu 1 de 2"
    assert bloqueio.action is not None and bloqueio.action.path.endswith("/cards/c1/race")


def test_corrida_degradada_em_card_ja_done_nao_bloqueia() -> None:
    """Corrida degradada num card mesclado é histórico, não bloqueio (plano6 §0)."""
    rel = compute_next_step(
        NextStepInput(
            orchestration=_orch(current_phase=Phase.F5),
            cards=[_card(ColumnKey.DONE, board_id=BOARD_ID, id="c1")],
            candidate_runs=[_race(card_id="c1", falhou=True)],
        )
    )
    assert "corrida_degradada" not in _codes(rel)


# ------------------------------------------------------------------- QA (§16/§17)


def test_qa_pendente_quando_card_exige_qa_e_ninguem_registrou() -> None:
    rel = compute_next_step(
        NextStepInput(
            orchestration=_orch(current_phase=Phase.F5),
            cards=[_card(ColumnKey.TESTING, board_id=BOARD_ID, id="c1", type=CardType.FEATURE)],
        )
    )
    bloqueio = next(b for b in rel.blockers if b.code == "qa_pendente")
    assert bloqueio.severity == "aguardando_humano"
    assert bloqueio.action is not None and bloqueio.action.path.endswith("/cards/c1/qa")


def test_qa_pendente_nao_aparece_para_card_que_nao_exige_qa() -> None:
    rel = compute_next_step(
        NextStepInput(
            orchestration=_orch(current_phase=Phase.F5),
            cards=[_card(ColumnKey.TESTING, board_id=BOARD_ID, id="c1", type=CardType.TASK)],
        )
    )
    assert "qa_pendente" not in _codes(rel)


def test_qa_pendente_nao_aparece_antes_do_card_chegar_em_testing() -> None:
    rel = compute_next_step(
        NextStepInput(
            orchestration=_orch(current_phase=Phase.F5),
            cards=[_card(ColumnKey.IN_PROGRESS, board_id=BOARD_ID, id="c1", type=CardType.FEATURE)],
        )
    )
    assert "qa_pendente" not in _codes(rel)


def test_qa_reprovado_bloqueia() -> None:
    check = {"cenario": "login", "status": "falhou"}
    rel = compute_next_step(
        NextStepInput(
            orchestration=_orch(current_phase=Phase.F5),
            cards=[
                _card(
                    ColumnKey.TESTING, board_id=BOARD_ID, id="c1", title="login", qa_checks=[check]
                )
            ],
        )
    )
    bloqueio = next(b for b in rel.blockers if b.code == "qa_reprovado")
    assert bloqueio.severity == "bloqueia"
    assert "login" in bloqueio.title


def test_qa_check_mais_recente_aprovado_libera_o_bloqueio() -> None:
    checks = [{"cenario": "login", "status": "falhou"}, {"cenario": "login", "status": "passou"}]
    rel = compute_next_step(
        NextStepInput(
            orchestration=_orch(current_phase=Phase.F5),
            cards=[_card(ColumnKey.TESTING, board_id=BOARD_ID, id="c1", qa_checks=checks)],
        )
    )
    assert "qa_reprovado" not in _codes(rel)
    assert "qa_pendente" not in _codes(rel)


# --------------------------------------------------------- orçamento (§1.2/§3.2, ADR-0026)


def test_sem_teto_configurado_nao_gera_bloqueio_de_orcamento() -> None:
    rel = compute_next_step(NextStepInput(orchestration=_orch(orcamento_usd=None), gasto_usd=999.0))
    assert "orcamento_estourado" not in _codes(rel)
    assert "orcamento_em_alerta" not in _codes(rel)


def test_orcamento_estourado_bloqueia_com_acao_admin() -> None:
    rel = compute_next_step(NextStepInput(orchestration=_orch(orcamento_usd=10.0), gasto_usd=15.0))
    bloqueio = next(b for b in rel.blockers if b.code == "orcamento_estourado")
    assert bloqueio.severity == "bloqueia"
    assert bloqueio.action is not None
    assert bloqueio.action.role == "admin"


def test_orcamento_em_alerta_e_informativo_nao_bloqueia() -> None:
    rel = compute_next_step(NextStepInput(orchestration=_orch(orcamento_usd=10.0), gasto_usd=8.5))
    bloqueio = next(b for b in rel.blockers if b.code == "orcamento_em_alerta")
    assert bloqueio.severity == "informativo"


def test_orcamento_dentro_do_teto_nao_gera_bloqueio() -> None:
    rel = compute_next_step(NextStepInput(orchestration=_orch(orcamento_usd=10.0), gasto_usd=1.0))
    assert "orcamento_estourado" not in _codes(rel)
    assert "orcamento_em_alerta" not in _codes(rel)


# ---------------------------------------------------------- card órfão (§1.4/§3.3, ADR-0027)


def test_card_in_progress_alem_do_timeout_vira_card_orfao() -> None:
    from datetime import UTC, datetime, timedelta

    parado_ha_1h = (datetime.now(UTC) - timedelta(seconds=3700)).isoformat()
    rel = compute_next_step(
        NextStepInput(
            orchestration=_orch(current_phase=Phase.F5),
            cards=[
                _card(
                    ColumnKey.IN_PROGRESS,
                    board_id=BOARD_ID,
                    id="c1",
                    updated_at=parado_ha_1h,
                )
            ],
            agent_timeout_seconds=1800.0,
        )
    )
    bloqueio = next(b for b in rel.blockers if b.code == "card_orfao")
    assert bloqueio.severity == "acao_do_operador"
    assert bloqueio.action is not None
    assert bloqueio.action.path.endswith("/cards/c1/route")


def test_card_in_progress_dentro_do_timeout_nao_acusa() -> None:
    from datetime import UTC, datetime

    rel = compute_next_step(
        NextStepInput(
            orchestration=_orch(current_phase=Phase.F5),
            cards=[
                _card(
                    ColumnKey.IN_PROGRESS,
                    board_id=BOARD_ID,
                    id="c1",
                    updated_at=datetime.now(UTC).isoformat(),
                )
            ],
            agent_timeout_seconds=1800.0,
        )
    )
    assert "card_orfao" not in _codes(rel)


def test_card_fora_de_in_progress_nunca_vira_orfao() -> None:
    from datetime import UTC, datetime, timedelta

    parado_ha_1h = (datetime.now(UTC) - timedelta(seconds=3700)).isoformat()
    rel = compute_next_step(
        NextStepInput(
            orchestration=_orch(current_phase=Phase.F5),
            cards=[_card(ColumnKey.BLOCKED, board_id=BOARD_ID, id="c1", updated_at=parado_ha_1h)],
            agent_timeout_seconds=1800.0,
        )
    )
    assert "card_orfao" not in _codes(rel)
