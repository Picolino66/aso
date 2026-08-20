"""Teste de integração da persistência (SQLAlchemy/SQLite) — estado sobrevive.

Prova que o estado de uma orquestração persiste entre instâncias diferentes do
OrchestrationService apontando para o mesmo banco (o objetivo da persistência).
"""

from __future__ import annotations

from pathlib import Path

from aso.control.orchestration_service import OrchestrationService
from aso.db.repository import SqlAlchemyOrchestrationRepository
from aso.execution.catalog import ExecutorCatalog, ExecutorProfile
from aso.persistence.memory import InMemoryOrchestrationRepository
from aso.shared.types import Phase


def test_state_survives_new_service_instance(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'aso.db'}"

    # Instância 1: cria, executa e roda o gate.
    svc1 = OrchestrationService(repository=SqlAlchemyOrchestrationRepository(url))
    orch = svc1.create_orchestration("Implementar módulo X no backend")
    card = svc1.get_cards(orch.id)[0]
    svc1.run_card(orch.id, card.id)
    svc1.run_quality_gate(orch.id, Phase.F5)

    # Instância 2: novo service + novo repositório sobre o MESMO banco.
    svc2 = OrchestrationService(repository=SqlAlchemyOrchestrationRepository(url))

    assert svc2.get(orch.id).id == orch.id
    assert svc2.get(orch.id).snapshot_version == "O5"
    assert svc2.get_context(orch.id)["version"] == 1
    assert len(svc2.get_cards(orch.id)) == 1
    assert svc2.get_cards(orch.id)[0].status.value == "Testing"
    assert len(svc2.list_snapshots(orch.id)) == 1
    assert len(svc2.list_adrs(orch.id)) >= 1
    assert orch.id in [o.id for o in svc2.list_all()]

    # Timeline e histórico do contexto preservados.
    event_types = {e.type for e in svc2.timeline(orch.id)}
    assert {"OrchestrationCreated", "ContextPatchApplied", "SnapshotCreated"} <= event_types


def test_sql_repository_roundtrip(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'rt.db'}"
    svc = OrchestrationService(repository=SqlAlchemyOrchestrationRepository(url))
    orch = svc.create_orchestration("demo")
    assert svc.list_all()[0].id == orch.id


def test_aprovacao_tipo_sobrevive_a_recarregar_o_bundle(tmp_path: Path) -> None:
    """Dashboard §3.3, ADR-0037: `HumanApproval.tipo` persiste via
    `SqlAlchemyOrchestrationRepository`."""
    url = f"sqlite:///{tmp_path / 'approval_tipo.db'}"
    svc1 = OrchestrationService(repository=SqlAlchemyOrchestrationRepository(url))
    orch = svc1.create_orchestration("demanda com aprovação")
    svc1.request_approval(orch.id, "ação manual via API")

    svc2 = OrchestrationService(repository=SqlAlchemyOrchestrationRepository(url))
    aprovacao = svc2.list_all_approvals()[0]
    assert aprovacao.tipo == "manual"


def test_execution_settings_survive_restart(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'settings.db'}"
    catalog = ExecutorCatalog([ExecutorProfile(name="mock", kind="mock", is_default=True)])
    first = OrchestrationService(repository=SqlAlchemyOrchestrationRepository(url), catalog=catalog)
    orchestration = first.create_orchestration("demo")
    first.update_execution_settings(
        orchestration.id,
        executor="mock",
        effort="medium",
        validation_command="npm test",
        actor="operador",
    )
    second = OrchestrationService(
        repository=SqlAlchemyOrchestrationRepository(url), catalog=catalog
    )
    loaded = second.get(orchestration.id)
    assert loaded.selected_executor == "mock"
    assert loaded.selected_effort == "medium"
    assert loaded.validation_command == "npm test"
    assert any(event.type == "ExecutionSettingsUpdated" for event in second.timeline(loaded.id))


def test_incidente_sobrevive_a_recarregar_o_bundle(tmp_path: Path) -> None:
    """§21, ADR-0032: `Incident` (gravidade, snapshot do deploy, timeline) persiste
    via `SqlAlchemyOrchestrationRepository`, mesmo padrão de `pull_requests`/
    `candidate_runs`/`slo_evaluations`."""
    from aso.control.triage import DemandBrief
    from aso.shared.types import RiskLevel

    url = f"sqlite:///{tmp_path / 'incidents.db'}"
    svc1 = OrchestrationService(repository=SqlAlchemyOrchestrationRepository(url))
    orch = svc1.create_orchestration(
        "ajustar cálculo de frete",
        target_path=str(tmp_path),
        seed_cards=False,
        demand_brief=DemandBrief(risco=RiskLevel.HIGH),
    )
    svc1.run_quality_gate(orch.id, Phase.F5)
    svc1.set_deploy_config(orch.id, command="bash -c 'exit 0'")
    svc1.run_deploy(orch.id)
    svc1.rollback_deploy(orch.id, reason="erro grave em produção")
    incidente_antes = svc1.list_incidents(orch.id)[0]
    svc1.investigate_incident(orch.id, incidente_antes.id, detalhe="checando", actor="op")

    svc2 = OrchestrationService(repository=SqlAlchemyOrchestrationRepository(url))
    incidentes_depois = svc2.list_incidents(orch.id)
    assert len(incidentes_depois) == 1
    incidente_depois = incidentes_depois[0]
    assert incidente_depois.id == incidente_antes.id
    assert incidente_depois.gravidade == "alta"
    assert incidente_depois.status == "investigando"
    assert incidente_depois.deploy_ambiente == "producao"
    assert [e["evento"] for e in incidente_depois.timeline] == ["aberto", "investigando"]


def test_review_comment_sobrevive_a_recarregar_o_bundle(tmp_path: Path) -> None:
    """wf §20.3, ADR-0033: `ReviewComment` (arquivo/linha/categoria/severidade/status)
    persiste via `SqlAlchemyOrchestrationRepository`, mesmo padrão de `incidents`."""
    from aso.control.review import ReviewCommentDraft, ReviewVerdict

    url = f"sqlite:///{tmp_path / 'review_comments.db'}"
    svc1 = OrchestrationService(repository=SqlAlchemyOrchestrationRepository(url))
    orch = svc1.create_orchestration("ajustar cálculo de frete")
    card = svc1.get_cards(orch.id)[0]
    pr = svc1.open_pr(orch.id, card.id, branch="feat/frete-abc123")
    b = svc1._bundle(orch.id)  # noqa: SLF001
    verdito = ReviewVerdict(
        veredito="alteracoes_obrigatorias",
        comentarios=[
            ReviewCommentDraft(
                arquivo="src/frete.py",
                linha=10,
                categoria="seguranca",
                severidade="alta",
                descricao="Validar entrada do usuário",
                obrigatorio=True,
            )
        ],
    )
    svc1._apply_review_verdict(b, pr, card, verdito, actor="teste")  # noqa: SLF001
    comentario_antes = svc1.list_review_comments(orch.id, pr.id)[0]
    svc1.resolve_review_comment(orch.id, pr.id, comentario_antes.id, actor="operador")

    svc2 = OrchestrationService(repository=SqlAlchemyOrchestrationRepository(url))
    comentarios_depois = svc2.list_review_comments(orch.id, pr.id)
    assert len(comentarios_depois) == 1
    comentario_depois = comentarios_depois[0]
    assert comentario_depois.id == comentario_antes.id
    assert comentario_depois.arquivo == "src/frete.py"
    assert comentario_depois.linha == 10
    assert comentario_depois.categoria == "seguranca"
    assert comentario_depois.severidade == "alta"
    assert comentario_depois.status == "resolvido"
    assert comentario_depois.resolved_by == "operador"


def test_two_orchestrations_share_adr_id_no_collision(tmp_path: Path) -> None:
    # Regressão: ADR-0001 é sequencial por orquestração; PK composta evita colisão.
    url = f"sqlite:///{tmp_path / 'multi.db'}"
    svc = OrchestrationService(repository=SqlAlchemyOrchestrationRepository(url))
    o1 = svc.create_orchestration("primeira")
    o2 = svc.create_orchestration("segunda")
    assert o1.id != o2.id
    assert svc.list_adrs(o1.id)[0].id == "ADR-0001"
    assert svc.list_adrs(o2.id)[0].id == "ADR-0001"
    assert len(svc.list_all()) == 2

    # Recarrega em instância nova: ambas as ADR-0001 coexistem.
    svc2 = OrchestrationService(repository=SqlAlchemyOrchestrationRepository(url))
    assert {a.id for a in svc2.list_adrs(o1.id)} == {"ADR-0001"}
    assert {a.id for a in svc2.list_adrs(o2.id)} == {"ADR-0001"}


def test_inmemory_repository_roundtrip() -> None:
    svc = OrchestrationService(repository=InMemoryOrchestrationRepository())
    orch = svc.create_orchestration("demo")
    # Limpa o cache para forçar carga a partir do repositório.
    svc._bundles.clear()  # noqa: SLF001
    assert svc.get(orch.id).id == orch.id
    assert svc.get_context(orch.id)["version"] == 0
