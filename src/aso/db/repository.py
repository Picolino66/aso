"""SqlAlchemyOrchestrationRepository — adapter relacional NORMALIZADO (§29, ADR-0006).

Coleções de valor são persistidas em tabelas de junção (card_links, adr_links,
board_columns, planned_agents). Escrita transacional (delete-and-reinsert dos filhos
+ merge do pai); leitura reconstrói o `OrchestrationState`. Inclui consultas indexadas.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import Engine, create_engine, delete, event, func, inspect, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from aso.agents.models import AgentDefinition
from aso.control.models import ExecutionPlan, Orchestration, PlannedAgent, Project, ProjectEvent
from aso.control.routing_rules import RoutingRule
from aso.db.gravacao import (
    ENTIDADE,
    TABELAS,
    MetaDaUnidade,
    impressao,
    prefixo_comum,
    sequencias_do_estado,
    unidades_do_estado,
)
from aso.db.models import (
    AdrLinkRow,
    AdrOptionRow,
    AdrRow,
    AgentDefinitionRow,
    AgentRunRow,
    Base,
    BoardColumnRow,
    BoardRow,
    BugReportRow,
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
    IncidentRow,
    JobRow,
    OrchestrationRow,
    PlannedAgentRow,
    ProjectEventRow,
    ProjectRow,
    PullRequestRow,
    QualityGateResultRow,
    ReviewCommentRow,
    RoutingRuleRow,
    SloEvaluationRow,
    SnapshotRow,
    ValueItemRow,
)
from aso.execution.jobs import Job
from aso.governance.models import (
    ADR,
    BugReport,
    CandidateRun,
    Conflict,
    ContextPatch,
    GateCriterionResult,
    HumanApproval,
    Incident,
    PullRequest,
    QualityGateResult,
    ReviewComment,
    SloEvaluation,
    Snapshot,
)
from aso.kanban.models import Board, BoardColumn, CardEvent, KanbanCard
from aso.observability.agent_runs import KIND_ASK, AgentRun
from aso.persistence.ports import ConcurrentModificationError
from aso.persistence.state import OrchestrationState
from aso.shared.types import ColumnKey, GateStatus


@dataclass
class _Impressoes:
    """O que foi gravado numa versão: base da comparação da próxima gravação (ADR-0068)."""

    versao: int
    unidades: dict[tuple[str, tuple[Any, ...]], MetaDaUnidade]
    sequencias: dict[str, list[str]]


def _cols(row: object, exclude: tuple[str, ...] = ()) -> dict[str, Any]:
    mapper = inspect(row).mapper  # type: ignore[union-attr]
    return {c.key: getattr(row, c.key) for c in mapper.column_attrs if c.key not in exclude}


def _scalar(dump: dict[str, Any], row_cls: type) -> dict[str, Any]:
    """Mantém apenas as chaves que são colunas escalares da tabela."""
    cols = set(row_cls.__table__.columns.keys())  # type: ignore[attr-defined]
    return {k: v for k, v in dump.items() if k in cols}


def _engine(url: str) -> Engine:
    """Cria engine e aproxima o SQLite das restrições aplicadas pelo Postgres."""
    engine = create_engine(url, future=True)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def enable_foreign_keys(dbapi_connection: Any, _connection_record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def _build_card(row: CardRow, links: dict[str, list[str]]) -> KanbanCard:
    data: dict[str, Any] = {**_cols(row), **links}
    return KanbanCard(**data)


def _build_adr(row: AdrRow, links: dict[str, list[str]], options: list[dict[str, Any]]) -> ADR:
    data: dict[str, Any] = {**_cols(row), **links, "options_considered": options}
    return ADR(**data)


class SqlAlchemyOrchestrationRepository:
    """Persiste o aggregate em tabelas relacionais normalizadas, com índices."""

    def __init__(self, url: str = "sqlite:///aso.db", *, create_schema: bool = True) -> None:
        self.engine = _engine(url)
        if create_schema:
            # Conveniência dev/testes; em produção use Alembic (migrations/).
            Base.metadata.create_all(self.engine)
        self._session_factory = sessionmaker(bind=self.engine, class_=Session)
        self._impressoes: dict[str, _Impressoes] = {}

    # --------------------------------------------------------------------- save
    def save(self, state: OrchestrationState) -> int:
        """Gravação incremental com versão otimista (ADR-0068).

        Só o que mudou desde a versão lida é escrito: entidades alteradas viram `UPDATE`,
        grupos de junção alterados são reescritos só naquele dono, sequências (`events`,
        `context_history`) recebem apenas a cauda nova. A orquestração é atualizada com
        `WHERE versao = esperada`; se outro processo gravou antes, nada é escrito.
        """
        oid = state.orchestration.id
        esperada = state.versao
        anteriores = self._impressoes_da_versao(oid, esperada)
        unidades = unidades_do_estado(state)
        sequencias = sequencias_do_estado(state)
        orch = state.orchestration.model_dump(mode="json")
        with self._session_factory() as session:
            if esperada == 0:
                if session.get(OrchestrationRow, oid) is not None:
                    raise self._conflito(oid, esperada)
                session.add(OrchestrationRow(**orch, versao=1))
            else:
                valores = {k: v for k, v in orch.items() if k != "id"}
                resultado = cast(
                    CursorResult[Any],
                    session.execute(
                        update(OrchestrationRow)
                        .where(OrchestrationRow.id == oid, OrchestrationRow.versao == esperada)
                        .values(**valores, versao=esperada + 1)
                    ),
                )
                if resultado.rowcount != 1:
                    session.rollback()
                    raise self._conflito(oid, esperada)
            session.flush()

            atuais = {un.id: un for un in unidades}
            impressoes = {un.id: un.impressao for un in unidades}
            removidas = sorted(
                (chave for chave in anteriores.unidades if chave not in atuais),
                key=lambda chave: -anteriores.unidades[chave].nivel,
            )
            # Remoções primeiro, das folhas para os pais (FK-safe no Postgres).
            for tabela, chave in removidas:
                meta = anteriores.unidades[(tabela, chave)]
                self._apagar(session, tabela, meta.filtro)
            session.flush()
            for nivel in (1, 2, 3):
                for un in unidades:
                    if un.nivel != nivel:
                        continue
                    antes = anteriores.unidades.get(un.id)
                    if antes is not None and antes.impressao == impressoes[un.id]:
                        continue
                    row_cls = TABELAS[un.tabela]
                    if un.tipo == ENTIDADE and antes is not None:
                        session.merge(row_cls(**un.linhas[0]))
                        continue
                    if antes is not None:  # grupo alterado: reescreve só este dono
                        self._apagar(session, un.tabela, un.filtro)
                    for linha in un.linhas:
                        session.add(row_cls(**linha))
                session.flush()
            impressoes_seq = self._gravar_sequencias(session, oid, sequencias, anteriores)
            session.commit()

        self._impressoes[oid] = _Impressoes(
            versao=esperada + 1,
            unidades={
                un.id: MetaDaUnidade(un.tipo, un.nivel, un.filtro, un.impressao) for un in unidades
            },
            sequencias=impressoes_seq,
        )
        return esperada + 1

    def versao_atual(self, orchestration_id: str) -> int | None:
        with self._session_factory() as session:
            return session.scalar(
                select(OrchestrationRow.versao).where(OrchestrationRow.id == orchestration_id)
            )

    @staticmethod
    def _conflito(oid: str, esperada: int) -> ConcurrentModificationError:
        return ConcurrentModificationError(
            f"A orquestração {oid} foi alterada por outra gravação depois da versão "
            f"{esperada} — recarregue e tente de novo."
        )

    @staticmethod
    def _apagar(session: Session, tabela: str, filtro: tuple[tuple[str, Any], ...]) -> None:
        row_cls: Any = TABELAS[tabela]
        condicoes = [getattr(row_cls, col) == valor for col, valor in filtro]
        session.execute(delete(row_cls).where(*condicoes))

    def _impressoes_da_versao(self, oid: str, versao: int) -> _Impressoes:
        """Impressões do que está gravado na versão `versao` (cache do `load`/`save`).

        Sem cache compatível (outra instância gravou/leu), recalcula a partir do banco; se o
        banco já não está nessa versão, a gravação nem começa."""
        if versao == 0:
            return _Impressoes(versao=0, unidades={}, sequencias={})
        cache = self._impressoes.get(oid)
        if cache is not None and cache.versao == versao:
            return cache
        gravado = self.load(oid)
        if gravado is None or gravado.versao != versao:
            raise self._conflito(oid, versao)
        return self._impressoes[oid]

    def _registrar_impressoes(self, state: OrchestrationState) -> None:
        sequencias = sequencias_do_estado(state)
        self._impressoes[state.orchestration.id] = _Impressoes(
            versao=state.versao,
            unidades={
                un.id: MetaDaUnidade(un.tipo, un.nivel, un.filtro, un.impressao)
                for un in unidades_do_estado(state)
            },
            sequencias={
                nome: [impressao(x) for x in linhas] for nome, linhas in sequencias.items()
            },
        )

    @staticmethod
    def _gravar_sequencias(
        session: Session,
        oid: str,
        sequencias: dict[str, list[dict[str, Any]]],
        anteriores: _Impressoes,
    ) -> dict[str, list[str]]:
        resultado: dict[str, list[str]] = {}
        for nome, linhas in sequencias.items():
            atuais = [impressao(linha) for linha in linhas]
            antes = anteriores.sequencias.get(nome, [])
            comum = prefixo_comum(antes, atuais)
            row_cls: Any = TABELAS[nome]
            if comum < len(antes):
                # Prefixo divergente (ex.: histórico restaurado): remove só o sufixo gravado.
                ids = list(
                    session.scalars(
                        select(row_cls.id)
                        .where(row_cls.orchestration_id == oid)
                        .order_by(row_cls.id)
                        .offset(comum)
                    )
                )
                if ids:
                    session.execute(delete(row_cls).where(row_cls.id.in_(ids)))
            for linha in linhas[comum:]:
                session.add(row_cls(**linha))
            resultado[nome] = atuais
        session.flush()
        return resultado

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
                session.scalars(
                    select(CardRow).where(CardRow.orchestration_id == oid).order_by(CardRow.posicao)
                )
            )
            card_links = self._group_links(
                session.scalars(select(CardLinkRow).where(CardLinkRow.orchestration_id == oid)),
                key=lambda r: r.card_id,
            )
            card_event_rows = list(
                session.scalars(
                    select(CardEventRow)
                    .where(CardEventRow.orchestration_id == oid)
                    .order_by(CardEventRow.posicao, CardEventRow.created_at)
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
                    .order_by(SnapshotRow.posicao, SnapshotRow.snapshot_version)
                )
            )
            conflict_rows = list(
                session.scalars(
                    select(ConflictRow)
                    .where(ConflictRow.orchestration_id == oid)
                    .order_by(ConflictRow.posicao)
                )
            )
            gate_rows = list(
                session.scalars(
                    select(QualityGateResultRow)
                    .where(QualityGateResultRow.orchestration_id == oid)
                    .order_by(QualityGateResultRow.posicao, QualityGateResultRow.created_at)
                )
            )
            approval_rows = list(
                session.scalars(
                    select(HumanApprovalRow)
                    .where(HumanApprovalRow.orchestration_id == oid)
                    .order_by(HumanApprovalRow.posicao)
                )
            )
            patch_rows = list(
                session.scalars(
                    select(ContextPatchRow)
                    .where(ContextPatchRow.orchestration_id == oid)
                    .order_by(ContextPatchRow.posicao, ContextPatchRow.created_at)
                )
            )
            pr_rows = list(
                session.scalars(
                    select(PullRequestRow)
                    .where(PullRequestRow.orchestration_id == oid)
                    .order_by(PullRequestRow.posicao, PullRequestRow.created_at)
                )
            )
            run_rows = list(
                session.scalars(
                    select(CandidateRunRow)
                    .where(CandidateRunRow.orchestration_id == oid)
                    .order_by(CandidateRunRow.posicao, CandidateRunRow.created_at)
                )
            )
            slo_rows = list(
                session.scalars(
                    select(SloEvaluationRow)
                    .where(SloEvaluationRow.orchestration_id == oid)
                    .order_by(SloEvaluationRow.posicao, SloEvaluationRow.created_at)
                )
            )
            incident_rows = list(
                session.scalars(
                    select(IncidentRow)
                    .where(IncidentRow.orchestration_id == oid)
                    .order_by(IncidentRow.posicao, IncidentRow.created_at)
                )
            )
            bug_report_rows = list(
                session.scalars(
                    select(BugReportRow)
                    .where(BugReportRow.orchestration_id == oid)
                    .order_by(BugReportRow.posicao, BugReportRow.created_at)
                )
            )
            review_comment_rows = list(
                session.scalars(
                    select(ReviewCommentRow)
                    .where(ReviewCommentRow.orchestration_id == oid)
                    .order_by(ReviewCommentRow.posicao, ReviewCommentRow.created_at)
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
                        duration_ms=crit.duration_ms,
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

            estado = OrchestrationState(
                orchestration=Orchestration(**_cols(orch_row)),
                versao=orch_row.versao,
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
                incidents=[Incident(**_cols(r)) for r in incident_rows],
                bug_reports=[BugReport(**_cols(r)) for r in bug_report_rows],
                review_comments=[ReviewComment(**_cols(r)) for r in review_comment_rows],
                events=[
                    {"type": r.type, "payload": r.payload, "created_at": r.created_at}
                    for r in event_rows
                ],
            )
        self._registrar_impressoes(estado)
        return estado

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
        self,
        *,
        limit: int | None = None,
        offset: int = 0,
        project_id: str | None = None,
        status: str | None = None,
        q: str | None = None,
        executor: str | None = None,
        created_from: str | None = None,
        created_to: str | None = None,
    ) -> tuple[list[Orchestration], int]:
        """Filtros baratos (Tela 02 §4.2, ADR-0038) — todos sobre colunas reais e
        indexadas (`project_id`, `status`, `created_at`) ou um `LIKE` simples
        (`user_request`). Os filtros que exigem ler `demand_brief` (JSON sem
        índice) ou aprovação pendente ficam no serviço, sobre o resultado desta
        consulta — ver `OrchestrationService.list_orchestrations_page`."""
        with self._session_factory() as session:
            count_stmt = select(func.count()).select_from(OrchestrationRow)
            stmt = select(OrchestrationRow)
            if project_id is not None:
                count_stmt = count_stmt.where(OrchestrationRow.project_id == project_id)
                stmt = stmt.where(OrchestrationRow.project_id == project_id)
            if status is not None:
                count_stmt = count_stmt.where(OrchestrationRow.status == status)
                stmt = stmt.where(OrchestrationRow.status == status)
            if q:
                padrao = f"%{q}%"
                count_stmt = count_stmt.where(OrchestrationRow.user_request.ilike(padrao))
                stmt = stmt.where(OrchestrationRow.user_request.ilike(padrao))
            if executor is not None:
                count_stmt = count_stmt.where(OrchestrationRow.selected_executor == executor)
                stmt = stmt.where(OrchestrationRow.selected_executor == executor)
            if created_from is not None:
                count_stmt = count_stmt.where(OrchestrationRow.created_at >= created_from)
                stmt = stmt.where(OrchestrationRow.created_at >= created_from)
            if created_to is not None:
                count_stmt = count_stmt.where(OrchestrationRow.created_at <= created_to)
                stmt = stmt.where(OrchestrationRow.created_at <= created_to)
            total = session.scalar(count_stmt) or 0
            stmt = stmt.order_by(OrchestrationRow.created_at).offset(offset)
            if limit is not None:
                stmt = stmt.limit(limit)
            rows = list(session.scalars(stmt))
            return [Orchestration(**_cols(r)) for r in rows], int(total)

    def orchestration_ids_with_pending_approval(self) -> set[str]:
        """Filtro "aprovação humana" (Tela 02 §4.2, ADR-0038) — uma query direta
        na tabela indexada (`ix_approvals_orch_status`), sem hidratar nenhum
        bundle. Deliberadamente NÃO reaproveita `list_all_approvals` (que
        hidrata o bundle de toda orquestração do sistema a cada chamada — bom
        para um agregado global chamado uma vez, ruim como filtro de tabela
        paginada, que colidiria com "pagina sem travar com muitas demandas")."""
        with self._session_factory() as session:
            stmt = (
                select(HumanApprovalRow.orchestration_id)
                .where(HumanApprovalRow.status == "pending")
                .distinct()
            )
            return set(session.scalars(stmt))

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
            # Última amostra de SLO por orquestração (ADR-0057) — subquery do MAX, sem
            # hidratar agregados; `/metrics` expõe só o que já foi avaliado e persistido.
            ultimo = (
                select(
                    SloEvaluationRow.orchestration_id,
                    func.max(SloEvaluationRow.created_at).label("created_at"),
                )
                .group_by(SloEvaluationRow.orchestration_id)
                .subquery()
            )
            slo_rows = session.execute(
                select(
                    SloEvaluationRow.orchestration_id,
                    SloEvaluationRow.burn_rate,
                    SloEvaluationRow.consumed_pct,
                ).join(
                    ultimo,
                    (SloEvaluationRow.orchestration_id == ultimo.c.orchestration_id)
                    & (SloEvaluationRow.created_at == ultimo.c.created_at),
                )
            ).all()
            return {
                "orchestrations_total": int(orch_total),
                "cards_by_status": {status: int(count) for status, count in cards},
                "adrs_total": int(adrs),
                "snapshots_total": int(snaps),
                "open_conflicts": int(conflicts),
                "agent_retries": ev.get("AgentRetry", 0),
                "agent_failures": ev.get("AgentFailed", 0),
                "slo_latest": {
                    oid: {"burn_rate": float(burn), "consumed_pct": float(pct)}
                    for oid, burn, pct in slo_rows
                },
            }

    def events_page(
        self, orchestration_id: str, *, limit: int, offset: int, newest_first: bool = False
    ) -> tuple[list[dict[str, Any]], int]:
        """Página da timeline. `newest_first` inverte a ordem no BANCO, não na página.

        Sem isso, um painel que quisesse "as últimas N atividades" recebia as N **mais
        antigas** da orquestração: `ORDER BY seq` com `offset=0` devolve o começo da
        história, e reordenar depois só embaralha a mesma fatia errada.
        """
        with self._session_factory() as session:
            total = (
                session.scalar(
                    select(func.count())
                    .select_from(EventRow)
                    .where(EventRow.orchestration_id == orchestration_id)
                )
                or 0
            )
            ordem = EventRow.seq.desc() if newest_first else EventRow.seq
            rows = list(
                session.scalars(
                    select(EventRow)
                    .where(EventRow.orchestration_id == orchestration_id)
                    .order_by(ordem)
                    .offset(offset)
                    .limit(limit)
                )
            )
            items = [
                {"type": r.type, "payload": r.payload, "created_at": r.created_at} for r in rows
            ]
            return items, int(total)

    def recent_events(self, *, limit: int) -> list[dict[str, Any]]:
        """Atividade recente GLOBAL (Dashboard §3.3, ADR-0037) — uma única query
        `ORDER BY created_at DESC LIMIT N` sem filtro de orquestração, ao contrário
        de `events_page`. `created_at` é ISO 8601 (`now_iso`), ordena
        lexicograficamente igual a cronologicamente."""
        with self._session_factory() as session:
            rows = list(
                session.scalars(select(EventRow).order_by(EventRow.created_at.desc()).limit(limit))
            )
            return [
                {
                    "orchestration_id": r.orchestration_id,
                    "type": r.type,
                    "payload": r.payload,
                    "created_at": r.created_at,
                }
                for r in rows
            ]

    def audit_page(
        self,
        *,
        limit: int,
        offset: int,
        project_id: str | None = None,
        orchestration_id: str | None = None,
        agente: str | None = None,
        etapa: str | None = None,
        resultado: str | None = None,
        data_de: str | None = None,
        data_ate: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Auditoria cross-demanda (Tela 28, wf §30, ADR-0051) — `CardEventRow`
        como fonte primária (append-only, nunca truncado, ao contrário dos
        rings `tentativas`/`failures`/`qa_checks`), joinada com
        `OrchestrationRow` para "Projeto"/"Demanda". 6 filtros do wf §30.3
        sobre colunas reais: `data`/`agente`/`etapa` são igualdade/faixa
        indexada; `resultado` é `ILIKE` (texto livre, não um enum)."""
        with self._session_factory() as session:
            base = select(CardEventRow).join(
                OrchestrationRow, OrchestrationRow.id == CardEventRow.orchestration_id
            )
            count_stmt = (
                select(func.count())
                .select_from(CardEventRow)
                .join(OrchestrationRow, OrchestrationRow.id == CardEventRow.orchestration_id)
            )
            if project_id is not None:
                base = base.where(OrchestrationRow.project_id == project_id)
                count_stmt = count_stmt.where(OrchestrationRow.project_id == project_id)
            if orchestration_id is not None:
                base = base.where(CardEventRow.orchestration_id == orchestration_id)
                count_stmt = count_stmt.where(CardEventRow.orchestration_id == orchestration_id)
            if agente is not None:
                base = base.where(CardEventRow.actor == agente)
                count_stmt = count_stmt.where(CardEventRow.actor == agente)
            if etapa is not None:
                base = base.where(CardEventRow.phase == etapa)
                count_stmt = count_stmt.where(CardEventRow.phase == etapa)
            if resultado:
                padrao = f"%{resultado}%"
                base = base.where(CardEventRow.result.ilike(padrao))
                count_stmt = count_stmt.where(CardEventRow.result.ilike(padrao))
            if data_de is not None:
                base = base.where(CardEventRow.created_at >= data_de)
                count_stmt = count_stmt.where(CardEventRow.created_at >= data_de)
            if data_ate is not None:
                base = base.where(CardEventRow.created_at <= data_ate)
                count_stmt = count_stmt.where(CardEventRow.created_at <= data_ate)
            total = session.scalar(count_stmt) or 0
            rows = list(
                session.scalars(
                    base.order_by(CardEventRow.created_at.desc()).offset(offset).limit(limit)
                )
            )
            orch_ids = {r.orchestration_id for r in rows}
            orch_rows = (
                list(
                    session.scalars(
                        select(OrchestrationRow).where(OrchestrationRow.id.in_(orch_ids))
                    )
                )
                if orch_ids
                else []
            )
            projeto_e_demanda = {o.id: (o.project_id, o.user_request) for o in orch_rows}
            card_ids = {r.card_id for r in rows}
            titulos: dict[str, str] = {}
            if card_ids:
                for card_id, titulo in session.execute(
                    select(CardRow.id, CardRow.title).where(CardRow.id.in_(card_ids))
                ).all():
                    titulos[card_id] = titulo
            itens = []
            for r in rows:
                projeto_id, demanda = projeto_e_demanda.get(r.orchestration_id, (None, ""))
                itens.append(
                    {
                        **_cols(r),
                        "project_id": projeto_id,
                        "demanda": demanda,
                        "card_titulo": titulos.get(r.card_id, r.card_id),
                    }
                )
            return itens, int(total)

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


class SqlAlchemyProjectRepository:
    """Adapter relacional do catálogo de projetos e de seus eventos."""

    def __init__(self, url: str = "sqlite:///aso.db", *, create_schema: bool = True) -> None:
        self.engine = _engine(url)
        if create_schema:
            Base.metadata.create_all(self.engine)
        self._session_factory = sessionmaker(bind=self.engine, class_=Session)

    def save_project(self, project: Project, event: ProjectEvent) -> None:
        try:
            with self._session_factory() as session:
                values = project.model_dump(mode="json")
                if event.before:
                    result = cast(
                        CursorResult[Any],
                        session.execute(
                            update(ProjectRow)
                            .where(
                                ProjectRow.id == project.id,
                                ProjectRow.updated_at == event.before.get("updated_at"),
                                ProjectRow.name == event.before.get("name"),
                                ProjectRow.description == event.before.get("description"),
                                ProjectRow.target_path == event.before.get("target_path"),
                                ProjectRow.status == event.before.get("status"),
                                ProjectRow.archived_at == event.before.get("archived_at"),
                            )
                            .values(**values)
                        ),
                    )
                    if result.rowcount != 1:
                        raise ValueError("Projeto foi alterado por outra operação; recarregue-o.")
                else:
                    session.add(ProjectRow(**values))
                session.flush()
                session.add(ProjectEventRow(**event.model_dump(mode="json")))
                session.commit()
        except IntegrityError as exc:
            raise ValueError("A pasta já pertence a outro projeto.") from exc

    def get_project(self, project_id: str) -> Project | None:
        with self._session_factory() as session:
            row = session.get(ProjectRow, project_id)
            return Project(**_cols(row)) if row is not None else None

    def get_project_by_path(self, target_path: str) -> Project | None:
        with self._session_factory() as session:
            row = session.scalar(select(ProjectRow).where(ProjectRow.target_path == target_path))
            return Project(**_cols(row)) if row is not None else None

    def list_projects(self, *, include_archived: bool = False) -> list[Project]:
        with self._session_factory() as session:
            stmt = select(ProjectRow)
            if not include_archived:
                stmt = stmt.where(ProjectRow.status == "active")
            stmt = stmt.order_by(ProjectRow.name, ProjectRow.created_at)
            return [Project(**_cols(row)) for row in session.scalars(stmt)]

    def list_project_events(self, project_id: str) -> list[ProjectEvent]:
        with self._session_factory() as session:
            stmt = (
                select(ProjectEventRow)
                .where(ProjectEventRow.project_id == project_id)
                .order_by(ProjectEventRow.created_at, ProjectEventRow.id)
            )
            return [ProjectEvent(**_cols(row)) for row in session.scalars(stmt)]


class SqlAlchemyRoutingRuleRepository:
    """Adapter relacional das regras de roteamento (§33, ADR-0028)."""

    def __init__(self, url: str = "sqlite:///aso.db", *, create_schema: bool = True) -> None:
        self.engine = _engine(url)
        if create_schema:
            Base.metadata.create_all(self.engine)
        self._session_factory = sessionmaker(bind=self.engine, class_=Session)

    def save_rule(self, rule: RoutingRule, *, before_updated_at: str | None = None) -> None:
        values = rule.model_dump(mode="json")
        with self._session_factory() as session:
            if before_updated_at is not None:
                result = cast(
                    CursorResult[Any],
                    session.execute(
                        update(RoutingRuleRow)
                        .where(
                            RoutingRuleRow.id == rule.id,
                            RoutingRuleRow.updated_at == before_updated_at,
                        )
                        .values(**values)
                    ),
                )
                if result.rowcount != 1:
                    raise ValueError("Regra foi alterada por outra operação; recarregue-a.")
            else:
                session.add(RoutingRuleRow(**values))
            session.commit()

    def get_rule(self, rule_id: str) -> RoutingRule | None:
        with self._session_factory() as session:
            row = session.get(RoutingRuleRow, rule_id)
            return RoutingRule(**_cols(row)) if row is not None else None

    def list_rules(self, *, only_active: bool = False) -> list[RoutingRule]:
        with self._session_factory() as session:
            stmt = select(RoutingRuleRow)
            if only_active:
                stmt = stmt.where(RoutingRuleRow.ativa.is_(True))
            stmt = stmt.order_by(RoutingRuleRow.precedencia, RoutingRuleRow.created_at)
            return [RoutingRule(**_cols(row)) for row in session.scalars(stmt)]

    def delete_rule(self, rule_id: str) -> None:
        with self._session_factory() as session:
            session.execute(delete(RoutingRuleRow).where(RoutingRuleRow.id == rule_id))
            session.commit()


class SqlAlchemyAgentDefinitionRepository:
    """Adapter relacional do catálogo de agentes (Tela 30, wf §32, ADR-0053) —
    mesmo desenho de `SqlAlchemyRoutingRuleRepository`."""

    def __init__(self, url: str = "sqlite:///aso.db", *, create_schema: bool = True) -> None:
        self.engine = _engine(url)
        if create_schema:
            Base.metadata.create_all(self.engine)
        self._session_factory = sessionmaker(bind=self.engine, class_=Session)

    def save_definition(
        self, definition: AgentDefinition, *, before_updated_at: str | None = None
    ) -> None:
        values = definition.model_dump(mode="json")
        with self._session_factory() as session:
            if before_updated_at is not None:
                result = cast(
                    CursorResult[Any],
                    session.execute(
                        update(AgentDefinitionRow)
                        .where(
                            AgentDefinitionRow.id == definition.id,
                            AgentDefinitionRow.updated_at == before_updated_at,
                        )
                        .values(**values)
                    ),
                )
                if result.rowcount != 1:
                    raise ValueError("Definição foi alterada por outra operação; recarregue-a.")
            else:
                session.add(AgentDefinitionRow(**values))
            session.commit()

    def get_definition(self, definition_id: str) -> AgentDefinition | None:
        with self._session_factory() as session:
            row = session.get(AgentDefinitionRow, definition_id)
            return AgentDefinition(**_cols(row)) if row is not None else None

    def list_definitions(self, *, only_active: bool = False) -> list[AgentDefinition]:
        with self._session_factory() as session:
            stmt = select(AgentDefinitionRow)
            if only_active:
                stmt = stmt.where(AgentDefinitionRow.ativo.is_(True))
            stmt = stmt.order_by(AgentDefinitionRow.nome)
            return [AgentDefinition(**_cols(row)) for row in session.scalars(stmt)]

    def delete_definition(self, definition_id: str) -> None:
        with self._session_factory() as session:
            session.execute(
                delete(AgentDefinitionRow).where(AgentDefinitionRow.id == definition_id)
            )
            session.commit()


class SqlAlchemyAgentRunRepository:
    """Adapter relacional dos registros de execução (ADR-0065) — upsert por `id`."""

    def __init__(self, url: str = "sqlite:///aso.db", *, create_schema: bool = True) -> None:
        self.engine = _engine(url)
        if create_schema:
            Base.metadata.create_all(self.engine)
        self._session_factory = sessionmaker(bind=self.engine, class_=Session)

    def salvar(self, run: AgentRun) -> None:
        with self._session_factory() as session:
            session.merge(AgentRunRow(**run.mascarado().model_dump(mode="json")))
            session.commit()

    def obter(self, run_id: str) -> AgentRun | None:
        with self._session_factory() as session:
            row = session.get(AgentRunRow, run_id)
            return AgentRun(**_cols(row)) if row is not None else None

    def listar(self, orchestration_id: str, *, card_id: str | None = None) -> list[AgentRun]:
        with self._session_factory() as session:
            stmt = select(AgentRunRow).where(AgentRunRow.orchestration_id == orchestration_id)
            if card_id is not None:
                stmt = stmt.where(AgentRunRow.card_id == card_id)
            rows = session.scalars(stmt.order_by(AgentRunRow.inicio)).all()
            return [AgentRun(**_cols(r)) for r in rows]

    def custo_de_perguntas(self, orchestration_id: str) -> float:
        with self._session_factory() as session:
            total = session.scalar(
                select(func.coalesce(func.sum(AgentRunRow.custo_usd), 0.0)).where(
                    AgentRunRow.orchestration_id == orchestration_id,
                    AgentRunRow.kind == KIND_ASK,
                )
            )
            return round(float(total or 0.0), 6)

    def expurgar_textos(self, antes_de: str) -> int:
        with self._session_factory() as session:
            result = cast(
                CursorResult[Any],
                session.execute(
                    update(AgentRunRow)
                    .where(AgentRunRow.inicio < antes_de)
                    .values(prompt="", stdout_cauda="", envelope={})
                ),
            )
            session.commit()
            return int(result.rowcount or 0)


class SqlAlchemyJobRepository:
    """Adapter relacional da fila de jobs (ADR-0067) — upsert por `id`."""

    def __init__(self, url: str = "sqlite:///aso.db", *, create_schema: bool = True) -> None:
        self.engine = _engine(url)
        if create_schema:
            Base.metadata.create_all(self.engine)
        self._session_factory = sessionmaker(bind=self.engine, class_=Session)

    def salvar(self, job: Job) -> None:
        with self._session_factory() as session:
            session.merge(JobRow(**job.model_dump(mode="json")))
            session.commit()

    def obter(self, job_id: str) -> Job | None:
        with self._session_factory() as session:
            row = session.get(JobRow, job_id)
            return Job(**_cols(row)) if row is not None else None

    def listar(
        self, *, orchestration_id: str | None = None, status: str | None = None
    ) -> list[Job]:
        with self._session_factory() as session:
            stmt = select(JobRow)
            if orchestration_id is not None:
                stmt = stmt.where(JobRow.orchestration_id == orchestration_id)
            if status is not None:
                stmt = stmt.where(JobRow.status == status)
            rows = session.scalars(stmt.order_by(JobRow.criado_em)).all()
            return [Job(**_cols(r)) for r in rows]
