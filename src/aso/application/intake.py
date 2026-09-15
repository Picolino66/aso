"""`IntakeService` — criação da orquestração, triagem e planejamento (ADR-0066).

MEL-32, passo 8: ficha da demanda (ADR-0016/0039), motor de decisão e cards iniciais,
regra de roteamento (ADR-0028), aprovação de estratégia crítica e planejamento LLM — este
último saiu do handler HTTP de criação.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any, cast

from aso.agents.registry import AgentRegistry, fase_padrao
from aso.application.bundles import BundleStore, OrchestrationBundle
from aso.application.preparation import _DOMAIN_AGENTS, _tipo_de_card, prioridade_de
from aso.control.agent_catalog_service import AgentCatalogService
from aso.control.decision_engine import MultiAgentDecisionEngine
from aso.control.execution_planner import ExecutionPlanner
from aso.control.models import (
    TRIAGE_KEY,
    AgentAssignment,
    DecisionInput,
    ExecutionPlan,
    Orchestration,
    PlannedAgent,
)
from aso.control.planning import PlanningService
from aso.control.project_service import ProjectService
from aso.control.routing_rule_service import RoutingRuleService
from aso.control.routing_rules import avaliar_regras, contexto_de_decision_input
from aso.control.triage import DemandBrief, TriageService
from aso.execution.catalog import ExecutorCatalog
from aso.execution.gate_validation import validate_gate_command
from aso.execution.llm_client import LlmClient, LlmError
from aso.governance.adr_registry import ADRRegistry
from aso.governance.context_store import OrchestratorContextStore
from aso.governance.contextbus import ContextBus, PermissionPolicy
from aso.governance.models import HumanApproval
from aso.governance.quality_gate_engine import QualityGateEngine
from aso.governance.snapshot_engine import SnapshotEngine
from aso.kanban.board_service import BoardService
from aso.kanban.models import KanbanCard
from aso.shared.events import EventLog
from aso.shared.ids import now_iso
from aso.shared.types import AssigneeType, CardType, ColumnKey, ExecutionMode, Phase


def _phase_for_agent(agent: str) -> Phase:
    """Fase do card de um agente: tabela declarada no registro de papéis (MEL-20).

    O planejamento LLM (/plan) e a spec continuam podendo fixar fases explícitas.
    """
    return fase_padrao(agent)


def _resumo_da_demanda(brief: DemandBrief, user_request: str, limite: int = 80) -> str:
    """Resumo curto da demanda para título de card e nome de branch (MEL-20)."""
    base = (brief.objetivo or "").strip() or (user_request.strip().splitlines() or [""])[0]
    base = " ".join(base.split())
    if len(base) <= limite:
        return base or "Demanda"
    corte = base[:limite].rsplit(" ", 1)[0]
    return (corte or base[:limite]).rstrip(" ,.;:") + "…"


class IntakeService:
    """Entrada da demanda: triagem, cards iniciais, regra de roteamento e planejamento LLM."""

    def __init__(
        self,
        store: BundleStore,
        *,
        triage: TriageService,
        projects: ProjectService,
        routing_rules: RoutingRuleService,
        agent_catalog: AgentCatalogService,
        orcamento_padrao_usd: float | None,
        catalogo: Callable[[], ExecutorCatalog | None],
        assignment: Callable[..., Any],
        validate_executor: Callable[..., Any],
        replan_if_untouched: Callable[..., Any],
        perguntar_registrando: Callable[..., Any],
    ) -> None:
        self._bundle_store = store
        self._triage = triage
        self._projects = projects
        self._routing_rules = routing_rules
        self._agent_catalog = agent_catalog
        self._orcamento_padrao_usd = orcamento_padrao_usd
        self._catalogo = catalogo
        self._assignment_de = assignment
        self._validar_executor = validate_executor
        self._replanejar = replan_if_untouched
        self._perguntar = perguntar_registrando

    @property
    def _catalog(self) -> ExecutorCatalog | None:
        return self._catalogo()

    @property
    def _bundles(self) -> dict[str, OrchestrationBundle]:
        return self._bundle_store.cache

    def _bundle(self, orchestration_id: str) -> OrchestrationBundle:
        return self._bundle_store.get(orchestration_id)

    def _persist(self, b: OrchestrationBundle) -> None:
        self._bundle_store.persist(b)

    def _lock_for(self, orchestration_id: str) -> threading.RLock:
        return self._bundle_store.lock_for(orchestration_id)

    def _assignment(self, *args: Any, **kwargs: Any) -> Any:
        return self._assignment_de(*args, **kwargs)

    def _validate_executor(self, *args: Any, **kwargs: Any) -> Any:
        return self._validar_executor(*args, **kwargs)

    def _replan_if_untouched(self, *args: Any, **kwargs: Any) -> Any:
        return self._replanejar(*args, **kwargs)

    def _perguntar_registrando[T](
        self, orchestration_id: str, card_id: str | None, chamada: Callable[[], T]
    ) -> T:
        return cast(T, self._perguntar(orchestration_id, card_id, chamada))

    # ------------------------------------------------------------------ criação
    def create_orchestration(
        self,
        user_request: str,
        *,
        project_id: str | None = None,
        target_path: str | None = None,
        execution_mode: ExecutionMode = ExecutionMode.FULL_PIPELINE,
        executor: str | None = None,
        effort: str | None = None,
        validation_command: str | None = None,
        seed_cards: bool = True,
        decision_input: DecisionInput | None = None,
        demand_brief: DemandBrief | None = None,
        orcamento_usd: float | None = None,
    ) -> Orchestration:
        if executor is not None and self._catalog is not None:
            self._validate_executor(executor, effort)
        if validation_command is not None:
            validation_command = validate_gate_command(validation_command)
        if project_id is not None:
            target_path = self._projects.resolve_workspace(project_id, target_path)
        brief = demand_brief or DemandBrief()
        orchestration = Orchestration(
            project_id=project_id,
            target_path=target_path,
            execution_mode=execution_mode,
            user_request=user_request,
            selected_executor=executor,
            selected_effort=effort,
            demand_brief=brief.model_dump(mode="json") if demand_brief is not None else {},
            validation_command=validation_command,
            current_phase=Phase.F5 if execution_mode == ExecutionMode.CODE_EXECUTION else Phase.F1,
            # Tela 03 (§5.2, ADR-0039): orçamento explícito na criação vence o
            # default de ambiente — `None` preserva o comportamento de sempre.
            orcamento_usd=(
                orcamento_usd if orcamento_usd is not None else self._orcamento_padrao_usd
            ),
        )
        oid = orchestration.id
        events = EventLog()

        registry = AgentRegistry()
        registry.seed_from_catalog(self._agent_catalog.list_definitions(only_active=True))

        store = OrchestratorContextStore(oid)
        adr_registry = ADRRegistry(oid)
        bus = ContextBus(
            store,
            permissions=PermissionPolicy(registry.permission_map()),
            adr_registry=adr_registry,
            event_log=events,
        )
        gate_engine = QualityGateEngine(event_log=events)
        snapshot_engine = SnapshotEngine(event_log=events)
        board_service = BoardService(event_log=events)
        board = board_service.create_board(oid, f"Board — {user_request[:40]}", project_id)

        # Plano de execução a partir da decisão multiagente.
        planner = ExecutionPlanner(MultiAgentDecisionEngine())
        din = decision_input or DecisionInput(user_request=user_request, domains=["backend"])
        plan = planner.plan(oid, execution_mode, din)
        self._apply_routing_rule(
            orchestration, din, plan, executor_explicito=executor, effort_explicito=effort
        )
        # Tela 03 (§5.2, ADR-0039): "Aprovação humana obrigatória" força o mesmo
        # efeito que `RoutingRuleAction.aprovacao_humana` (ADR-0028) já tem — só
        # adiciona a exigência, nunca remove o que o motor/regra já decidiram.
        if brief.aprovacao_humana_obrigatoria:
            plan.requires_human_approval = True

        # Registra a decisão de estratégia como ADR (rastreabilidade §21) — cita a
        # regra de roteamento que decidiu, quando uma casou (§33, ADR-0028).
        adr_registry.create(
            title=f"Estratégia de execução: {plan.strategy.value}",
            decision=plan.reason,
            phase=orchestration.current_phase,
            context=f"Demanda: {user_request}",
            rationale=(
                f"Regra de roteamento '{orchestration.routing_rule_applied['regra_nome']}' "
                "(§33, ADR-0028)."
                if orchestration.routing_rule_applied
                else "Decisão do MultiAgentDecisionEngine (§14)."
            ),
        )

        # Cria um card por agente planejado, na fase adequada ao papel do agente
        # (a esteira começa em F1; sem isso, cards de dev cairiam em F1).
        max_tentativas_da_regra = self._max_tentativas_da_regra(orchestration)
        planned_cards: list[tuple[PlannedAgent, KanbanCard]] = []
        # Título e critérios vêm da DEMANDA (MEL-20): "<Papel>: <motivo do motor>" e
        # "Output do agente aplicado via ContextBus" viravam nome de branch e prompt.
        resumo = _resumo_da_demanda(brief, user_request)
        criterios = list(brief.criterios_de_aceite) or [f"A entrega atende à demanda: {resumo}"]
        varios = len(plan.agents) > 1
        for planned in plan.agents:
            if not seed_cards:
                continue
            card = KanbanCard(
                board_id=board.id,
                orchestration_id=oid,
                phase=_phase_for_agent(planned.agent),
                type=CardType.TASK,
                title=f"{resumo} — {planned.agent}" if varios else resumo,
                description=planned.reason,
                priority=prioridade_de(brief),
                assignee_type=AssigneeType.AGENT,
                assignee=planned.agent,
                status=ColumnKey.READY,
                acceptance_criteria=list(criterios),
                max_tentativas=max_tentativas_da_regra,
            )
            planned_cards.append((planned, card))
        # Segunda passada: `dependencies` (§10 do fluxo.md) referencia IDs de cards
        # irmãos, que só existem depois que todos os cards desta onda nasceram.
        # Dependência apontando para um agente fora do plano é ignorada — ele não
        # participou desta estratégia (ex.: descartado pelo MultiAgentDecisionEngine).
        id_por_agente = {planned.agent: card.id for planned, card in planned_cards}
        for planned, card in planned_cards:
            card.dependencies = [
                id_por_agente[dep] for dep in planned.depends_on if dep in id_por_agente
            ]
            board_service.add_card(card)

        events.append(
            "OrchestrationCreated",
            {"orchestration_id": oid, "strategy": plan.strategy.value, "cards": len(plan.agents)},
        )

        bundle = OrchestrationBundle(
            orchestration=orchestration,
            event_log=events,
            agent_registry=registry,
            store=store,
            adr_registry=adr_registry,
            bus=bus,
            gate_engine=gate_engine,
            snapshot_engine=snapshot_engine,
            board_service=board_service,
            board=board,
            plan=plan,
        )
        # Ação crítica: registra aprovação humana pendente (§8.6/§24).
        if plan.requires_human_approval:
            motivo = plan.reason
            if brief.aprovacao_humana_obrigatoria:
                # Honesto sobre a causa real (Tela 03, ADR-0039): sem isto, o motivo
                # exibido seria só o do motor de decisão — que pode nem ter pedido
                # aprovação sozinho (ex. "tarefa de baixo risco") — escondendo que
                # foi o solicitante quem marcou o campo.
                motivo = f"{motivo} (aprovação humana marcada como obrigatória na demanda)"
            bundle.approvals.append(
                HumanApproval(
                    orchestration_id=oid,
                    action=f"Executar estratégia {plan.strategy.value}",
                    tipo="estrategia",
                    risk=plan.risk_level.value,
                    reason=motivo,
                )
            )
            events.append("ApprovalRequested", {"orchestration_id": oid})

        with self._lock_for(oid):
            self._bundles[oid] = bundle
            self._persist(bundle)
        return orchestration

    def _apply_routing_rule(
        self,
        orchestration: Orchestration,
        din: DecisionInput,
        plan: ExecutionPlan,
        *,
        executor_explicito: str | None,
        effort_explicito: str | None,
    ) -> None:
        """Avalia as regras ativas (§33, ADR-0028) e, se uma casar, ajusta o plano.

        Nenhuma regra casando (nenhuma configurada, ou nenhuma condição bateu),
        `plan`/`orchestration` saem exatamente como a heurística
        (`MultiAgentDecisionEngine`/`selecao.py`) os produziu — fallback, nunca
        substituição; mesmo comportamento de toda orquestração anterior a este
        incremento. `executor_explicito`/`effort_explicito` preservam a escolha
        humana explícita: uma regra nunca sobrescreve o que o operador já decidiu.
        """
        regras = self._routing_rules.list_rules(only_active=True)
        if not regras:
            return
        resultado = avaliar_regras(regras, contexto_de_decision_input(din))
        if resultado is None:
            return
        acao = resultado.acao
        if acao.agente and plan.agents:
            plan.agents[0].agent = acao.agente
            plan.agents[0].reason = f"Regra de roteamento '{resultado.regra_nome}' (§33)."
        if acao.aprovacao_humana:
            plan.requires_human_approval = True
        if acao.modelo and executor_explicito is None:
            orchestration.selected_executor = acao.modelo
        if acao.effort and effort_explicito is None:
            orchestration.selected_effort = acao.effort
        orchestration.routing_rule_applied = resultado.model_dump(mode="json")

    @staticmethod
    def _max_tentativas_da_regra(orchestration: Orchestration) -> int | None:
        """§36.4, ADR-0031: limite de tentativas herdado da regra que casou na
        criação/replanejamento (§33, ADR-0028), quando ela declara um.

        A regra decide sobre o perfil de risco da DEMANDA (ex.: "segurança crítica
        → no máximo 3 tentativas"), não sobre um agente específico — por isso o
        limite se aplica a TODOS os cards nascidos nesta leva, não só ao card do
        agente principal (diferente de `acao.agente`/`modelo`, que só tocam
        `plan.agents[0]`/a orquestração). `None` = nenhuma regra casou, ou a que
        casou não declarou limite — cards nascem com `max_tentativas=None` (usa o
        teto global), comportamento idêntico a antes desta ADR.
        """
        aplicada = orchestration.routing_rule_applied
        if not aplicada:
            return None
        limite = aplicada.get("acao", {}).get("limite_tentativas")
        return int(limite) if limite is not None else None

    def planejar(
        self, orchestration_id: str, planning_client: LlmClient, ideia: str
    ) -> dict[str, object]:
        """Planeja com o LLM e materializa cards + ADRs (M2)."""
        plan = PlanningService(planning_client).plan(ideia)
        return self.populate_from_plan(orchestration_id, plan)

    def planejar_na_criacao(
        self, orchestration_id: str, planning_client: LlmClient, user_request: str
    ) -> str | None:
        """Planejamento logo após criar em full-pipeline; devolve aviso se falhou (MEL-20).

        A orquestração já foi persistida: um 500 deixaria uma orquestração sem backlog e sem
        explicação. A falha vira `PlanningFailed` e o próximo passo oferece replanejar.
        """
        try:
            self.planejar(orchestration_id, planning_client, user_request)
        except (LlmError, ValueError) as exc:
            self.registrar_falha_de_planejamento(orchestration_id, str(exc))
            return f"Planejamento LLM falhou: {exc}. Use POST .../plan para replanejar."
        return None

    def registrar_falha_de_planejamento(self, orchestration_id: str, motivo: str) -> None:
        """Planejamento LLM falhou depois de a orquestração existir (MEL-20): evento
        `PlanningFailed` visível na timeline e no próximo passo (replanejar)."""
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            b.event_log.append(
                "PlanningFailed", {"orchestration_id": orchestration_id, "motivo": motivo[:500]}
            )
            self._persist(b)

    def populate_from_plan(self, orchestration_id: str, plan: Any) -> dict[str, object]:
        """Materializa um ProjectPlan (LLM) no board: cards concretos + ADRs (M2).

        Recebe um `ProjectPlan` (control.planning). Cria um card por item do backlog
        e registra as ADRs propostas — sob o lock por orquestração e persistido.
        Não passa pelo ContextBus (espelha create_orchestration, que cria cards/ADRs
        diretamente); os cards nascem em Ready, prontos para execução governada.
        """
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            brief = DemandBrief.model_validate(b.orchestration.demand_brief)
            for adr in plan.adrs:
                b.adr_registry.create(
                    title=adr.title,
                    decision=adr.decision,
                    phase=b.orchestration.current_phase,
                    context=f"Plano LLM para: {b.orchestration.user_request}",
                    rationale=adr.rationale,
                    locked_paths=list(adr.locked_paths),
                )
            created: list[str] = []
            max_tentativas_da_regra = self._max_tentativas_da_regra(b.orchestration)
            planned_cards: list[tuple[Any, KanbanCard]] = []
            for item in plan.backlog:
                try:
                    phase = Phase(item.phase)
                except ValueError:
                    phase = Phase.F5
                assignee = _DOMAIN_AGENTS.get(item.domain, item.domain)
                if b.agent_registry.get(assignee) is None:
                    raise ValueError(f"Domínio/agente desconhecido no plano: {item.domain}")
                card = KanbanCard(
                    board_id=b.board.id,
                    orchestration_id=orchestration_id,
                    phase=phase,
                    type=_tipo_de_card(item.type),
                    title=item.title,
                    priority=prioridade_de(brief),
                    assignee_type=AssigneeType.AGENT,
                    assignee=assignee,
                    status=ColumnKey.READY,
                    acceptance_criteria=list(item.acceptance_criteria),
                    max_tentativas=max_tentativas_da_regra,
                )
                planned_cards.append((item, card))
            # Segunda passada: `depends_on` (§7/§10 do fluxo.md) referencia TÍTULOS de
            # itens irmãos deste mesmo backlog, que só viram ids depois que todos os
            # cards nasceram — mesmo padrão de `PlannedAgent.depends_on` em
            # `create_orchestration`. Título desconhecido é descartado, não quebra.
            id_por_titulo = {item.title: card.id for item, card in planned_cards}
            for item, card in planned_cards:
                card.dependencies = [
                    id_por_titulo[dep] for dep in item.depends_on if dep in id_por_titulo
                ]
                b.board_service.add_card(card)
                created.append(card.id)
            b.event_log.append(
                "PlanPopulated",
                {"cards": len(created), "adrs": len(plan.adrs), "product": plan.product.name},
            )
            self._persist(b)
            return {
                "orchestration_id": orchestration_id,
                "cards_created": created,
                "adrs_created": len(plan.adrs),
                "product": plan.product.model_dump(),
            }

    # -------------------------------------------------------------- ficha da demanda
    def _triage_executor(
        self, explicit: str | None, assignment: AgentAssignment | None
    ) -> str | None:
        """Ordem de resolução do agente de triagem: parâmetro explícito → etapa
        'triagem' configurada → default do catálogo → heurística (`None`)."""
        if explicit:
            return explicit
        if assignment is not None:
            return assignment.executor
        if self._catalog is not None:
            return self._catalog.default_name()
        return None

    def triage_demand(
        self, user_request: str, *, executor: str | None = None, effort: str | None = None
    ) -> DemandBrief:
        """Tria a demanda (§1/§2) antes de criar a orquestração.

        Ainda não existe orquestração, logo não há `agent_assignments["triagem"]`: o
        agente vem do parâmetro explícito ou do default do catálogo, e cai na
        heurística sem nenhum dos dois — a mesma garantia de `TriageService`, triar
        nunca impede a criação.
        """
        nome = self._triage_executor(executor, None)
        assignment = AgentAssignment(executor=nome, effort=effort) if nome else None
        return self._perguntar_registrando(
            "", None, lambda: self._triage.analisar(assignment, user_request=user_request)
        )

    def create_with_triage(
        self,
        /,
        user_request: str,
        *,
        executor: str | None = None,
        effort: str | None = None,
        **kwargs: Any,
    ) -> Orchestration:
        """Tria a demanda e cria a orquestração — o único caminho correto de criação.

        Existe porque a sequência triagem→criação estava duplicada só em `app.py`: a
        CLI nasceu sem ela ([Ponto 1] herdado da avaliação do Incremento A) e criava
        orquestrações com `demand_brief` vazio e `priority` sempre `MEDIUM` fixo — o
        motor de decisão nunca via a demanda real. `create_orchestration` continua
        existindo tal como está (usada em dezenas de testes); este método a envolve.
        """
        brief = self.triage_demand(user_request, executor=executor, effort=effort)
        return self.create_orchestration(
            user_request,
            executor=executor,
            effort=effort,
            decision_input=brief.to_decision_input(user_request),
            demand_brief=brief,
            **kwargs,
        )

    def get_demand_brief(self, orchestration_id: str) -> DemandBrief:
        """Ficha atual da demanda (vazia = orquestração criada antes da ADR-0016)."""
        b = self._bundle(orchestration_id)
        return DemandBrief.model_validate(b.orchestration.demand_brief)

    def set_demand_brief(
        self, orchestration_id: str, brief: DemandBrief, *, actor: str = "system"
    ) -> Orchestration:
        """Persiste a ficha da demanda, com trilha de auditoria (origem/fallback)."""
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            b.orchestration.demand_brief = brief.model_dump(mode="json")
            b.orchestration.updated_at = now_iso()
            b.event_log.append(
                "DemandTriaged",
                {
                    "orchestration_id": orchestration_id,
                    "actor": actor,
                    "origem": brief.origem,
                    "fallback_reason": brief.fallback_reason,
                },
            )
            self._persist(b)
            return b.orchestration

    def retriage_demand(
        self,
        orchestration_id: str,
        *,
        executor: str | None = None,
        effort: str | None = None,
        actor: str = "system",
    ) -> dict[str, object]:
        """Re-tria a demanda (POST .../brief), depois que o operador responder as
        `perguntas_abertas`. O agente roda fora do lock — mesmo motivo de `run_card`:
        não travar a orquestração pelo timeout da triagem; só a persistência do
        resultado é serializada.

        [Ponto 2 herdado da avaliação do Incremento A] Antes, só a ficha era
        atualizada: o operador respondia as `perguntas_abertas`, ganhava uma ficha
        melhor e continuava com a mesma equipe/estratégia da triagem original — o
        mecanismo que o Incremento A existe para ligar ficava desligado no caminho de
        correção. Ver `_replan_if_untouched`.
        """
        b = self._bundle(orchestration_id)
        assignment = self._assignment(b, TRIAGE_KEY)
        nome = self._triage_executor(executor, assignment)
        efetivo_effort = effort or (assignment.effort if assignment else None)
        escolha = AgentAssignment(executor=nome, effort=efetivo_effort) if nome else None
        brief = self._perguntar_registrando(
            b.orchestration.id,
            None,
            lambda: self._triage.analisar(escolha, user_request=b.orchestration.user_request),
        )
        self.set_demand_brief(orchestration_id, brief, actor=actor)
        replanned, motivo = self._replan_if_untouched(orchestration_id, brief, actor=actor)
        return {"demand_brief": brief, "replanned": replanned, "replan_reason": motivo}
