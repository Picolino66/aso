"""SqlAlchemyOrchestrationRepository — adapter relacional NORMALIZADO (§29, ADR-0006).

Coleções de valor são persistidas em tabelas de junção (card_links, adr_links,
board_columns, planned_agents). Escrita transacional (delete-and-reinsert dos filhos
+ merge do pai); leitura reconstrói o `OrchestrationState`. Inclui consultas indexadas.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import create_engine, delete, func, inspect, select
from sqlalchemy.orm import Session, sessionmaker

from aso.control.models import ExecutionPlan, Orchestration, PlannedAgent
from aso.db.models import (
    AdrLinkRow,
    AdrOptionRow,
    AdrRow,
    Base,
    BoardColumnRow,
    BoardRow,
    CandidateRunRow,
    CardEventRow,
    CardLinkRow,
    CardRow,
    ConflictRow,
    ContextHistoryRow,
    ContextPatchRow,
    ContextRow,
    EventRow,
    ExecutionPlanRow,
    GateCriterionRow,
    HumanApprovalRow,
    OrchestrationRow,
    PlannedAgentRow,
    PullRequestRow,
    QualityGateResultRow,
    SloEvaluationRow,
    SnapshotRow,
    ValueItemRow,
)
from aso.governance.models import (
    ADR,
    CandidateRun,
    Conflict,
    ContextPatch,
    GateCriterionResult,
    HumanApproval,
    PullRequest,
    QualityGateResult,
    SloEvaluation,
    Snapshot,
)
from aso.kanban.models import Board, BoardColumn, CardEvent, KanbanCard
from aso.persistence.state import OrchestrationState
from aso.shared.types import ColumnKey, GateStatus

# Coleções de valor por entidade (nome do campo = rel na tabela de junção).
_CARD_RELS = (
    "agents",
    "dependencies",
    "blocked_by",
    "acceptance_criteria",
    "linked_requirements",
    "linked_adrs",
    "linked_contracts",
    "linked_files",
    "linked_prs",
)
_ADR_RELS = ("tradeoffs", "consequences", "linked_cards", "linked_requirements", "locked_paths")

# Ordem de deleção segura (folhas antes dos pais).
_CHILD_TABLES = (
    EventRow,
    ContextHistoryRow,
    ContextPatchRow,
    PullRequestRow,
    CandidateRunRow,
    SloEvaluationRow,
    ValueItemRow,
    GateCriterionRow,
    AdrOptionRow,
    CardLinkRow,
    CardEventRow,
    CardRow,
    PlannedAgentRow,
    ExecutionPlanRow,
    AdrLinkRow,
    AdrRow,
    SnapshotRow,
    ConflictRow,
    QualityGateResultRow,
    HumanApprovalRow,
    BoardColumnRow,
    ContextRow,
    BoardRow,
)


def _cols(row: object, exclude: tuple[str, ...] = ()) -> dict[str, Any]:
    mapper = inspect(row).mapper  # type: ignore[union-attr]
    return {c.key: getattr(row, c.key) for c in mapper.column_attrs if c.key not in exclude}


def _scalar(dump: dict[str, Any], row_cls: type) -> dict[str, Any]:
    """Mantém apenas as chaves que são colunas escalares da tabela."""
    cols = set(row_cls.__table__.columns.keys())  # type: ignore[attr-defined]
    return {k: v for k, v in dump.items() if k in cols}


def _build_card(row: CardRow, links: dict[str, list[str]]) -> KanbanCard:
    data: dict[str, Any] = {**_cols(row), **links}
    return KanbanCard(**data)


def _build_adr(row: AdrRow, links: dict[str, list[str]], options: list[dict[str, Any]]) -> ADR:
    data: dict[str, Any] = {**_cols(row), **links, "options_considered": options}
    return ADR(**data)


class SqlAlchemyOrchestrationRepository:
    """Persiste o aggregate em tabelas relacionais normalizadas, com índices."""

    def __init__(self, url: str = "sqlite:///aso.db", *, create_schema: bool = True) -> None:
        self.engine = create_engine(url, future=True)
        if create_schema:
            # Conveniência dev/testes; em produção use Alembic (migrations/).
            Base.metadata.create_all(self.engine)
        self._session_factory = sessionmaker(bind=self.engine, class_=Session)

    # --------------------------------------------------------------------- save
    def save(self, state: OrchestrationState) -> None:
        oid = state.orchestration.id
        with self._session_factory() as session:
            for table in _CHILD_TABLES:
                session.execute(delete(table).where(table.orchestration_id == oid))

            # Flush por nível de dependência de FK (o Postgres enforce FKs e o
            # unit-of-work não ordena sem relationship()).
            # Nível 0 — orquestração (pai de tudo).
            session.merge(OrchestrationRow(**state.orchestration.model_dump(mode="json")))
            session.flush()

            # Nível 1 — board e plano (pais de cards e de tabelas de junção).
            session.add(BoardRow(**_scalar(state.board.model_dump(mode="json"), BoardRow)))
            session.add(
                ExecutionPlanRow(**_scalar(state.plan.model_dump(mode="json"), ExecutionPlanRow))
            )
            session.flush()

            # Nível 2 — entidades que dependem de orquestração/board/plano.
            session.add(
                ContextRow(
                    orchestration_id=oid,
                    version=state.context_version,
                    context_hash="",
                    payload=state.context_payload,
                )
            )
            for col in state.board.columns:
                session.add(
                    BoardColumnRow(
                        board_id=state.board.id,
                        orchestration_id=oid,
                        key=col.key.value,
                        position=col.order,
                        wip_limit=col.wip_limit,
                    )
                )
            for pos, planned in enumerate(state.plan.agents):
                session.add(
                    PlannedAgentRow(
                        plan_id=state.plan.id,
                        orchestration_id=oid,
                        position=pos,
                        agent=planned.agent,
                        role=planned.role,
                        reason=planned.reason,
                        parallel_group=planned.parallel_group,
                        allowed_tools=list(planned.allowed_tools),
                        depends_on=list(planned.depends_on),
                    )
                )
            for entry in state.context_history:
                session.add(ContextHistoryRow(orchestration_id=oid, **entry))
            for card in state.cards:
                session.add(CardRow(**_scalar(card.model_dump(mode="json"), CardRow)))
            for evt in state.card_events:
                session.add(CardEventRow(orchestration_id=oid, **evt.model_dump(mode="json")))
            for adr in state.adrs:
                session.add(AdrRow(**_scalar(adr.model_dump(mode="json"), AdrRow)))
            for snap in state.snapshots:
                session.add(SnapshotRow(**_scalar(snap.model_dump(mode="json"), SnapshotRow)))
            for conflict in state.conflicts:
                session.add(ConflictRow(**_scalar(conflict.model_dump(mode="json"), ConflictRow)))
            for gate in state.gate_results:
                session.add(
                    QualityGateResultRow(
                        **_scalar(gate.model_dump(mode="json"), QualityGateResultRow)
                    )
                )
            for approval in state.approvals:
                session.add(HumanApprovalRow(**approval.model_dump(mode="json")))
            for patch in state.patches:
                session.add(
                    ContextPatchRow(**_scalar(patch.model_dump(mode="json"), ContextPatchRow))
                )
            for pr in state.pull_requests:
                session.add(PullRequestRow(**pr.model_dump(mode="json")))
            for run in state.candidate_runs:
                session.add(CandidateRunRow(**run.model_dump(mode="json")))
            for ev in state.slo_evaluations:
                session.add(SloEvaluationRow(**ev.model_dump(mode="json")))
            for seq, event in enumerate(state.events):
                session.add(
                    EventRow(
                        orchestration_id=oid,
                        seq=seq,
                        type=event["type"],
                        payload=event.get("payload", {}),
                        created_at=event["created_at"],
                    )
                )
            session.flush()

            # Nível 3 — tabelas de junção que dependem de cards/adrs.
            for card in state.cards:
                for rel in _CARD_RELS:
                    for pos, value in enumerate(getattr(card, rel)):
                        session.add(
                            CardLinkRow(
                                card_id=card.id,
                                orchestration_id=oid,
                                rel=rel,
                                value=value,
                                position=pos,
                            )
                        )
            for adr in state.adrs:
                for rel in _ADR_RELS:
                    for pos, value in enumerate(getattr(adr, rel)):
                        session.add(
                            AdrLinkRow(
                                adr_id=adr.id,
                                orchestration_id=oid,
                                rel=rel,
                                value=value,
                                position=pos,
                            )
                        )
                for pos, opt in enumerate(adr.options_considered):
                    session.add(
                        AdrOptionRow(
                            adr_id=adr.id,
                            orchestration_id=oid,
                            position=pos,
                            name=str(opt.get("name", "")),
                            pros=list(opt.get("pros", [])),
                            cons=list(opt.get("cons", [])),
                        )
                    )
            for gate in state.gate_results:
                for pos, crit in enumerate(gate.criteria):
                    session.add(
                        GateCriterionRow(
                            gate_id=gate.id,
                            orchestration_id=oid,
                            position=pos,
                            name=crit.name,
                            status=crit.status.value,
                            failure_reason=crit.failure_reason,
                            evidence=list(crit.evidence),
                        )
                    )

            def _values(owner_type: str, owner_id: str, rel: str, values: list[str]) -> None:
                for pos, value in enumerate(values):
                    session.add(
                        ValueItemRow(
                            orchestration_id=oid,
                            owner_type=owner_type,
                            owner_id=owner_id,
                            rel=rel,
                            value=value,
                            position=pos,
                        )
                    )

            _values("plan", state.plan.id, "success_criteria", list(state.plan.success_criteria))
            _values("context", oid, "frozen_sections", list(state.context_frozen))
            for snap in state.snapshots:
                _values("snapshot", snap.id, "frozen_sections", list(snap.frozen_sections))
                _values("snapshot", snap.id, "adrs", list(snap.adrs))
                _values("snapshot", snap.id, "cards", list(snap.cards))
            for conflict in state.conflicts:
                _values(
                    "conflict", conflict.id, "source_patch_ids", list(conflict.source_patch_ids)
                )
            for gate in state.gate_results:
                _values("gate", gate.id, "blocking_issues", list(gate.blocking_issues))
                _values("gate", gate.id, "warnings", list(gate.warnings))
                _values("gate", gate.id, "required_actions", list(gate.required_actions))
            session.commit()

    # -------------------------------------------------------------------- delete
    def delete(self, orchestration_id: str) -> None:
        """Remove o aggregate em ordem FK-safe (filhos → pai)."""
        oid = orchestration_id
        with self._session_factory() as session:
            for table in reversed(_CHILD_TABLES):
                session.execute(delete(table).where(table.orchestration_id == oid))  # type: ignore[attr-defined]
            session.execute(delete(OrchestrationRow).where(OrchestrationRow.id == oid))
            session.commit()

    # --------------------------------------------------------------------- load
    def load(self, orchestration_id: str) -> OrchestrationState | None:
        oid = orchestration_id
        with self._session_factory() as session:
            orch_row = session.get(OrchestrationRow, oid)
            if orch_row is None:
                return None

            plan_row = session.scalar(
                select(ExecutionPlanRow).where(ExecutionPlanRow.orchestration_id == oid)
            )
            board_row = session.scalar(select(BoardRow).where(BoardRow.orchestration_id == oid))
            if plan_row is None or board_row is None:
                raise ValueError(f"Aggregate corrompido: {oid} sem plan/board")

            context_row = session.get(ContextRow, oid)
            board_cols = list(
                session.scalars(
                    select(BoardColumnRow)
                    .where(BoardColumnRow.board_id == board_row.id)
                    .order_by(BoardColumnRow.position)
                )
            )
            planned = list(
                session.scalars(
                    select(PlannedAgentRow)
                    .where(PlannedAgentRow.plan_id == plan_row.id)
                    .order_by(PlannedAgentRow.position)
                )
            )
            history_rows = list(
                session.scalars(
                    select(ContextHistoryRow)
                    .where(ContextHistoryRow.orchestration_id == oid)
                    .order_by(ContextHistoryRow.version)
                )
            )
            card_rows = list(
                session.scalars(select(CardRow).where(CardRow.orchestration_id == oid))
            )
            card_links = self._group_links(
                session.scalars(select(CardLinkRow).where(CardLinkRow.orchestration_id == oid)),
                key=lambda r: r.card_id,
            )
            card_event_rows = list(
                session.scalars(
                    select(CardEventRow)
                    .where(CardEventRow.orchestration_id == oid)
                    .order_by(CardEventRow.created_at)
                )
            )
            adr_rows = list(
                session.scalars(
                    select(AdrRow).where(AdrRow.orchestration_id == oid).order_by(AdrRow.id)
                )
            )
            adr_links = self._group_links(
                session.scalars(select(AdrLinkRow).where(AdrLinkRow.orchestration_id == oid)),
                key=lambda r: r.adr_id,
            )
            snapshot_rows = list(
                session.scalars(
                    select(SnapshotRow)
                    .where(SnapshotRow.orchestration_id == oid)
                    .order_by(SnapshotRow.snapshot_version)
                )
            )
            conflict_rows = list(
                session.scalars(select(ConflictRow).where(ConflictRow.orchestration_id == oid))
            )
            gate_rows = list(
                session.scalars(
                    select(QualityGateResultRow)
                    .where(QualityGateResultRow.orchestration_id == oid)
                    .order_by(QualityGateResultRow.created_at)
                )
            )
            approval_rows = list(
                session.scalars(
                    select(HumanApprovalRow).where(HumanApprovalRow.orchestration_id == oid)
                )
            )
            patch_rows = list(
                session.scalars(
                    select(ContextPatchRow)
                    .where(ContextPatchRow.orchestration_id == oid)
                    .order_by(ContextPatchRow.created_at)
                )
            )
            pr_rows = list(
                session.scalars(
                    select(PullRequestRow)
                    .where(PullRequestRow.orchestration_id == oid)
                    .order_by(PullRequestRow.created_at)
                )
            )
            run_rows = list(
                session.scalars(
                    select(CandidateRunRow)
                    .where(CandidateRunRow.orchestration_id == oid)
                    .order_by(CandidateRunRow.created_at)
                )
            )
            slo_rows = list(
                session.scalars(
                    select(SloEvaluationRow)
                    .where(SloEvaluationRow.orchestration_id == oid)
                    .order_by(SloEvaluationRow.created_at)
                )
            )
            event_rows = list(
                session.scalars(
                    select(EventRow).where(EventRow.orchestration_id == oid).order_by(EventRow.seq)
                )
            )
            option_rows = list(
                session.scalars(
                    select(AdrOptionRow)
                    .where(AdrOptionRow.orchestration_id == oid)
                    .order_by(AdrOptionRow.position)
                )
            )
            criterion_rows = list(
                session.scalars(
                    select(GateCriterionRow)
                    .where(GateCriterionRow.orchestration_id == oid)
                    .order_by(GateCriterionRow.position)
                )
            )
            value_rows = list(
                session.scalars(select(ValueItemRow).where(ValueItemRow.orchestration_id == oid))
            )

            # Agrupa coleções de valor por (owner_type, owner_id) -> {rel: [valores]}.
            _tmp: dict[tuple[str, str], dict[str, list[tuple[int, str]]]] = defaultdict(
                lambda: defaultdict(list)
            )
            for v in value_rows:
                _tmp[(v.owner_type, v.owner_id)][v.rel].append((v.position, v.value))
            vi: dict[tuple[str, str], dict[str, list[str]]] = {
                key: {rel: [x for _, x in sorted(pairs)] for rel, pairs in rels.items()}
                for key, rels in _tmp.items()
            }

            def _vi(owner_type: str, owner_id: str, rel: str) -> list[str]:
                return vi.get((owner_type, owner_id), {}).get(rel, [])

            options_by_adr: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for opt in option_rows:
                options_by_adr[opt.adr_id].append(
                    {"name": opt.name, "pros": list(opt.pros), "cons": list(opt.cons)}
                )
            criteria_by_gate: dict[str, list[GateCriterionResult]] = defaultdict(list)
            for crit in criterion_rows:
                criteria_by_gate[crit.gate_id].append(
                    GateCriterionResult(
                        name=crit.name,
                        status=GateStatus(crit.status),
                        evidence=list(crit.evidence),
                        failure_reason=crit.failure_reason,
                    )
                )

            columns = [
                BoardColumn(key=ColumnKey(c.key), order=c.position, wip_limit=c.wip_limit)
                for c in board_cols
            ]
            board = Board(**_cols(board_row), columns=columns)
            agents = [
                PlannedAgent(
                    agent=p.agent,
                    role=p.role,
                    reason=p.reason,
                    allowed_tools=list(p.allowed_tools),
                    depends_on=list(p.depends_on),
                    parallel_group=p.parallel_group,
                )
                for p in planned
            ]
            plan = ExecutionPlan(
                **_cols(plan_row),
                agents=agents,
                success_criteria=_vi("plan", plan_row.id, "success_criteria"),
            )

            return OrchestrationState(
                orchestration=Orchestration(**_cols(orch_row)),
                plan=plan,
                board=board,
                context_payload=context_row.payload if context_row else {},
                context_version=context_row.version if context_row else 0,
                context_frozen=_vi("context", oid, "frozen_sections"),
                context_history=[
                    _cols(r, exclude=("id", "orchestration_id")) for r in history_rows
                ],
                cards=[_build_card(r, card_links.get(r.id, {})) for r in card_rows],
                card_events=[
                    CardEvent(**_cols(r, exclude=("orchestration_id",))) for r in card_event_rows
                ],
                adrs=[
                    _build_adr(r, adr_links.get(r.id, {}), options_by_adr.get(r.id, []))
                    for r in adr_rows
                ],
                snapshots=[
                    Snapshot(
                        **_cols(r),
                        frozen_sections=_vi("snapshot", r.id, "frozen_sections"),
                        adrs=_vi("snapshot", r.id, "adrs"),
                        cards=_vi("snapshot", r.id, "cards"),
                    )
                    for r in snapshot_rows
                ],
                conflicts=[
                    Conflict(**_cols(r), source_patch_ids=_vi("conflict", r.id, "source_patch_ids"))
                    for r in conflict_rows
                ],
                gate_results=[
                    QualityGateResult(
                        **_cols(r),
                        criteria=criteria_by_gate.get(r.id, []),
                        blocking_issues=_vi("gate", r.id, "blocking_issues"),
                        warnings=_vi("gate", r.id, "warnings"),
                        required_actions=_vi("gate", r.id, "required_actions"),
                    )
                    for r in gate_rows
                ],
                approvals=[HumanApproval(**_cols(r)) for r in approval_rows],
                patches=[ContextPatch(**_cols(r)) for r in patch_rows],
                pull_requests=[PullRequest(**_cols(r)) for r in pr_rows],
                candidate_runs=[CandidateRun(**_cols(r)) for r in run_rows],
                slo_evaluations=[SloEvaluation(**_cols(r)) for r in slo_rows],
                events=[
                    {"type": r.type, "payload": r.payload, "created_at": r.created_at}
                    for r in event_rows
                ],
            )

    @staticmethod
    def _group_links(rows: Any, key: Any) -> dict[str, dict[str, list[str]]]:
        """Agrupa linhas de junção em {parent_id: {rel: [valores ordenados]}}."""
        grouped: dict[str, dict[str, list[tuple[int, str]]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for row in rows:
            grouped[key(row)][row.rel].append((row.position, row.value))
        result: dict[str, dict[str, list[str]]] = {}
        for parent_id, rels in grouped.items():
            result[parent_id] = {rel: [v for _, v in sorted(pairs)] for rel, pairs in rels.items()}
        return result

    # ------------------------------------------------------------------ listagem
    def list_ids(self) -> list[str]:
        with self._session_factory() as session:
            return list(session.scalars(select(OrchestrationRow.id)))

    def list_orchestrations(
        self, *, limit: int | None = None, offset: int = 0
    ) -> tuple[list[Orchestration], int]:
        with self._session_factory() as session:
            total = session.scalar(select(func.count()).select_from(OrchestrationRow)) or 0
            stmt = select(OrchestrationRow).order_by(OrchestrationRow.created_at).offset(offset)
            if limit is not None:
                stmt = stmt.limit(limit)
            rows = list(session.scalars(stmt))
            return [Orchestration(**_cols(r)) for r in rows], int(total)

    def aggregate_metrics(self) -> dict[str, Any]:
        with self._session_factory() as session:
            orch_total = session.scalar(select(func.count()).select_from(OrchestrationRow)) or 0
            cards = session.execute(
                select(CardRow.status, func.count()).group_by(CardRow.status)
            ).all()
            adrs = session.scalar(select(func.count()).select_from(AdrRow)) or 0
            snaps = session.scalar(select(func.count()).select_from(SnapshotRow)) or 0
            conflicts = (
                session.scalar(
                    select(func.count())
                    .select_from(ConflictRow)
                    .where(ConflictRow.status == "open")
                )
                or 0
            )
            events = session.execute(
                select(EventRow.type, func.count())
                .where(EventRow.type.in_(["AgentRetry", "AgentFailed"]))
                .group_by(EventRow.type)
            ).all()
            ev = {etype: int(count) for etype, count in events}
            return {
                "orchestrations_total": int(orch_total),
                "cards_by_status": {status: int(count) for status, count in cards},
                "adrs_total": int(adrs),
                "snapshots_total": int(snaps),
                "open_conflicts": int(conflicts),
                "agent_retries": ev.get("AgentRetry", 0),
                "agent_failures": ev.get("AgentFailed", 0),
            }

    def events_page(
        self, orchestration_id: str, *, limit: int, offset: int
    ) -> tuple[list[dict[str, Any]], int]:
        with self._session_factory() as session:
            total = (
                session.scalar(
                    select(func.count())
                    .select_from(EventRow)
                    .where(EventRow.orchestration_id == orchestration_id)
                )
                or 0
            )
            rows = list(
                session.scalars(
                    select(EventRow)
                    .where(EventRow.orchestration_id == orchestration_id)
                    .order_by(EventRow.seq)
                    .offset(offset)
                    .limit(limit)
                )
            )
            items = [
                {"type": r.type, "payload": r.payload, "created_at": r.created_at} for r in rows
            ]
            return items, int(total)

    # -------------------------------------------------------------- consultas
    def cards_by_status(self, orchestration_id: str, status: str) -> list[str]:
        """IDs dos cards de uma orquestração num dado status (usa índice)."""
        with self._session_factory() as session:
            stmt = select(CardRow.id).where(
                CardRow.orchestration_id == orchestration_id, CardRow.status == status
            )
            return list(session.scalars(stmt))

    def count_cards_by_status(self, orchestration_id: str) -> dict[str, int]:
        """Contagem de cards por status (agregação indexada)."""
        with self._session_factory() as session:
            stmt = (
                select(CardRow.status, func.count())
                .where(CardRow.orchestration_id == orchestration_id)
                .group_by(CardRow.status)
            )
            return {status: count for status, count in session.execute(stmt)}

    def adrs_by_status(self, orchestration_id: str, status: str) -> list[str]:
        """IDs das ADRs num dado status (usa índice orch+status)."""
        with self._session_factory() as session:
            stmt = select(AdrRow.id).where(
                AdrRow.orchestration_id == orchestration_id, AdrRow.status == status
            )
            return list(session.scalars(stmt))

    def cards_linked_to_adr(self, orchestration_id: str, adr_id: str) -> list[str]:
        """IDs de cards que referenciam uma ADR (consulta reversa via card_links)."""
        with self._session_factory() as session:
            stmt = select(CardLinkRow.card_id).where(
                CardLinkRow.orchestration_id == orchestration_id,
                CardLinkRow.rel == "linked_adrs",
                CardLinkRow.value == adr_id,
            )
            return list(session.scalars(stmt))
