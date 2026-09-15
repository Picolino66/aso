"""`InsightService` — aprendizado, estimativas e próximo passo (ADR-0066).

MEL-32, passo 11d: leituras derivadas (relatório de aprendizado por orquestração e global,
faixas de custo/tempo, prévia de recomendação, checklist de preparação e `next_step`) saem da
façade. Nada aqui muta estado de governança.
"""

from __future__ import annotations

import threading
from typing import Any

from aso.agents.registry import AgentRegistry
from aso.application.bundles import BundleStore, OrchestrationBundle
from aso.application.execution import ExecutionService
from aso.application.routing_rule_service import RoutingRuleService
from aso.application.settings import ExecutionSettingsService
from aso.control.decision_engine import MultiAgentDecisionEngine
from aso.control.deploy import STATUS_REVERTIDO, DeployRun
from aso.control.discovery import DiscoveryReport
from aso.control.documentos import versao_atual
from aso.control.next_step import NextStepInput, NextStepReport, compute_next_step
from aso.control.routing_rules import avaliar_regras, contexto_de_demand_brief
from aso.control.selecao import sugerir_effort
from aso.control.spec import SpecDocument
from aso.control.triage import DemandBrief
from aso.execution.cli_provider import TIMEOUT_PADRAO as CLI_AGENT_TIMEOUT_PADRAO
from aso.execution.docs_drift import DocsDriftReport, check_drift
from aso.execution.workspace import WorkspaceError
from aso.observability.aprendizado import (
    CardSnapshot,
    PullRequestSnapshot,
    RelatorioDeAprendizado,
    consolidar,
)
from aso.persistence.ports import OrchestrationRepository
from aso.shared.events import DomainEvent
from aso.shared.types import ColumnKey


def _ultima_falha_de_planejamento(b: OrchestrationBundle) -> str:
    """Motivo da última `PlanningFailed` ainda não superada por um plano com cards."""
    if b.board_service.cards_of(b.board.id):
        return ""
    falhas = [e for e in b.event_log.all() if e.type == "PlanningFailed"]
    return str(falhas[-1].payload.get("motivo", "")) if falhas else ""


def _faixa(valor: float, todos: list[float]) -> str:
    """Posição categórica (baixo/médio/alto) de `valor` dentro de `todos` (wf
    §15.3, `_estimar_custo_e_tempo`).

    Bug real (code-review ultra): a versão anterior usava `sorted(todos).index(valor)`
    — `list.index` devolve sempre a primeira ocorrência, então todo grupo empatado
    colapsava no rank mais baixo do grupo (ex.: 3 executores empatados em 3º/4º/5º
    lugar de 5 todos apareciam como 3º, todos "baixo"). Aqui o rank de um valor
    empatado é a MÉDIA das posições que o grupo ocupa (convenção estatística padrão
    de "fractional ranking") — nenhum valor empatado fica sub ou super-representado.
    """
    ordenados = sorted(todos)
    menores = sum(1 for x in ordenados if x < valor)
    empatados = sum(1 for x in ordenados if x == valor)
    posicao = menores + (empatados - 1) / 2
    terco = max(len(ordenados) // 3, 1)
    if posicao < terco:
        return "baixo"
    if posicao < 2 * terco:
        return "médio"
    return "alto"


def _tempo_ms_por_card(events: list[DomainEvent]) -> dict[str, float]:
    """Soma `AgentExecuted.ms` por card — insumo de "tempo gasto" do §24."""
    tempos: dict[str, float] = {}
    for e in events:
        if e.type != "AgentExecuted":
            continue
        card_id = e.payload.get("card_id")
        ms = e.payload.get("ms")
        if isinstance(card_id, str) and isinstance(ms, int | float):
            tempos[card_id] = tempos.get(card_id, 0.0) + float(ms)
    return tempos


class InsightService:
    """Relatórios de aprendizado, estimativas, recomendação de estratégia e próximo passo."""

    def __init__(
        self,
        store: BundleStore,
        *,
        repository: OrchestrationRepository,
        routing_rules: RoutingRuleService,
        execution: ExecutionService,
        settings: ExecutionSettingsService,
    ) -> None:
        self._bundle_store = store
        self._repo = repository
        self._routing_rules = routing_rules
        self._execution = execution
        self._settings = settings

    def _bundle(self, orchestration_id: str) -> OrchestrationBundle:
        return self._bundle_store.get(orchestration_id)

    def _persist(self, b: OrchestrationBundle) -> None:
        self._bundle_store.persist(b)

    def _lock_for(self, orchestration_id: str) -> threading.RLock:
        return self._bundle_store.lock_for(orchestration_id)

    def _gasto_usd(self, b: OrchestrationBundle) -> float:
        return self._execution._gasto_usd(b)

    def _executor_availability(self, name: str | None) -> tuple[bool | None, str]:
        return self._settings._executor_availability(name)

    def get_preparation_checklist(
        self, orchestration_id: str, card_id: str
    ) -> list[dict[str, object]]:
        """Checklist de preparação do card (§10, ADR-0030) — só leitura: a escrita é
        100% automática pelo runtime, nunca manual (um checklist editável mentiria
        sobre o que de fato foi verificado)."""
        b = self._bundle(orchestration_id)
        card = b.board_service.get_card(card_id)
        if card is None:
            raise KeyError(f"Card inexistente: {card_id}")
        return card.preparation_checklist

    def _coletar_aprendizado(
        self, b: OrchestrationBundle
    ) -> tuple[list[CardSnapshot], list[PullRequestSnapshot], int]:
        """Coleta o estado já persistido do bundle e o achata para o agregador puro
        de `observability/aprendizado.py` — o único ponto que pode ligar `control`
        a `observability` (mesmo arranjo de `next_step`/`Service.next_step`)."""
        cards_do_board = b.board_service.cards_of(b.board.id)
        tempo_por_card = _tempo_ms_por_card(b.event_log.all())
        cards = [
            CardSnapshot(
                id=c.id,
                executor=c.executor or "",
                failures=list(c.failures),
                tempo_ms=tempo_por_card.get(c.id, 0.0),
                custo_usd=float(c.uso.get("custo_usd", 0.0)),
                # Nenhuma execução informou uso ainda (inclui card nunca executado,
                # 0 >= 0) — nunca "custou zero" por omissão (§1.1, ADR-0026).
                uso_indisponivel=int(c.uso.get("execucoes_sem_custo", 0))
                >= int(c.uso.get("execucoes", 0)),
                entregue=c.status == ColumnKey.DONE,
                agente=c.assignee or "",
            )
            for c in cards_do_board
        ]
        pulls = [
            PullRequestSnapshot(
                card_id=pr.card_id, review_rounds=pr.review_rounds, review_status=pr.review_status
            )
            for pr in b.pull_requests
        ]
        intervencoes = sum(1 for a in b.approvals if a.status in ("approved", "rejected"))
        intervencoes += sum(
            1
            for c in cards_do_board
            for check in c.qa_checks
            if check.get("tipo_responsavel") == "humano"
            and check.get("status") in ("passou", "falhou")
        )
        return cards, pulls, intervencoes

    def _coletar_indicadores_extra(self, b: OrchestrationBundle) -> dict[str, Any]:
        """Contagens brutas dos indicadores novos da Tela 29 (wf §31.1,
        ADR-0052) — taxa de aprovação/rollback/sucesso-no-primeiro-ciclo e
        tempo por etapa. Devolve CONTAGENS, não taxas: quem soma através de
        várias orquestrações (`get_learning_report_global`) precisa dos
        brutos antes de dividir, senão a taxa global vira média-de-médias
        (errada quando as amostras têm tamanhos diferentes).
        """
        aprovados = sum(1 for a in b.approvals if a.status == "approved")
        decisoes_de_aprovacao = sum(1 for a in b.approvals if a.status in ("approved", "rejected"))
        deploys = len(b.orchestration.deploy_runs)
        rollbacks = sum(
            1 for d in b.orchestration.deploy_runs if d.get("status") == STATUS_REVERTIDO
        )
        cards_do_board = b.board_service.cards_of(b.board.id)
        # `tentativa_atual` é o contador AUTORITATIVO e sem limite de ring
        # (§36.4, ADR-0031) — "primeiro ciclo" com base no ring de tentativas
        # (capado em 10) mentiria para cards com histórico de retry mais longo.
        cards_com_tentativa = sum(1 for c in cards_do_board if c.tentativa_atual >= 1)
        soma_tentativas = sum(c.tentativa_atual for c in cards_do_board if c.tentativa_atual >= 1)
        sucesso_primeiro_ciclo = sum(
            1 for c in cards_do_board if c.tentativa_atual == 1 and c.status == ColumnKey.DONE
        )
        tempo_por_card = _tempo_ms_por_card(b.event_log.all())
        tempo_por_etapa_ms: dict[str, list[float]] = {}
        for c in cards_do_board:
            tempo = tempo_por_card.get(c.id)
            if tempo:
                tempo_por_etapa_ms.setdefault(c.phase.value, []).append(tempo)
        return {
            "aprovados": aprovados,
            "decisoes_de_aprovacao": decisoes_de_aprovacao,
            "rollbacks": rollbacks,
            "deploys": deploys,
            "sucesso_primeiro_ciclo": sucesso_primeiro_ciclo,
            "cards_com_tentativa": cards_com_tentativa,
            "soma_tentativas": soma_tentativas,
            "tempo_por_etapa_ms": tempo_por_etapa_ms,
        }

    def get_learning_report(self, orchestration_id: str) -> RelatorioDeAprendizado:
        """Relatório de aprendizado de UMA demanda (§24) — retrabalho, falhas por
        etapa, desempenho por executor, intervenções humanas. Informativo: não
        altera nenhuma decisão automaticamente (§3.4 do plano6)."""
        b = self._bundle(orchestration_id)
        cards, pulls, intervencoes = self._coletar_aprendizado(b)
        extra = self._coletar_indicadores_extra(b)
        return consolidar(
            orchestration_id, cards, pulls, intervencoes_humanas=intervencoes, **extra
        )

    def get_learning_report_global(
        self,
        *,
        project_id: str | None = None,
        data_de: str | None = None,
        data_ate: str | None = None,
    ) -> RelatorioDeAprendizado:
        """Mesmo relatório, consolidado entre orquestrações (Tela 29, wf §31,
        ADR-0052) — "recorte por projeto e período" reaproveita o filtro SQL
        real já indexado de `list_orchestrations` (ADR-0038) para restringir
        QUAIS orquestrações hidratar, em vez de hidratar todo o sistema e
        filtrar em memória (mesmo cuidado de escala já aplicado em
        `audit_page`, ADR-0051)."""
        orchestrations, _ = self._repo.list_orchestrations(
            project_id=project_id, created_from=data_de, created_to=data_ate
        )
        cards: list[CardSnapshot] = []
        pulls: list[PullRequestSnapshot] = []
        intervencoes = 0
        aprovados = decisoes_de_aprovacao = rollbacks = deploys = 0
        sucesso_primeiro_ciclo = cards_com_tentativa = soma_tentativas = 0
        tempo_por_etapa_ms: dict[str, list[float]] = {}
        for orch in orchestrations:
            b = self._bundle(orch.id)
            c, p, i = self._coletar_aprendizado(b)
            cards.extend(c)
            pulls.extend(p)
            intervencoes += i
            extra = self._coletar_indicadores_extra(b)
            aprovados += extra["aprovados"]
            decisoes_de_aprovacao += extra["decisoes_de_aprovacao"]
            rollbacks += extra["rollbacks"]
            deploys += extra["deploys"]
            sucesso_primeiro_ciclo += extra["sucesso_primeiro_ciclo"]
            cards_com_tentativa += extra["cards_com_tentativa"]
            soma_tentativas += extra["soma_tentativas"]
            for etapa, valores in extra["tempo_por_etapa_ms"].items():
                tempo_por_etapa_ms.setdefault(etapa, []).extend(valores)
        return consolidar(
            "todas",
            cards,
            pulls,
            intervencoes_humanas=intervencoes,
            aprovados=aprovados,
            decisoes_de_aprovacao=decisoes_de_aprovacao,
            rollbacks=rollbacks,
            deploys=deploys,
            sucesso_primeiro_ciclo=sucesso_primeiro_ciclo,
            total_orchestrations=len(orchestrations),
            soma_tentativas=soma_tentativas,
            cards_com_tentativa=cards_com_tentativa,
            tempo_por_etapa_ms=tempo_por_etapa_ms,
        )

    def preview_recommendation(self, orchestration_id: str) -> dict[str, object]:
        """Painel de recomendação (Tela 13, wf §15, ADR-0044) — o que o motor
        decidiria HOJE para esta demanda, sem persistir nada (equivalente, em
        espírito, ao `POST /v1/routing-rules/preview` do FID-15, só que na direção
        oposta: aqui é UMA demanda contra TODAS as regras, lá era UMA regra contra
        TODAS as demandas). Reaproveita as mesmas funções puras do caminho real de
        criação (`avaliar_regras`, `MultiAgentDecisionEngine.decide`,
        `sugerir_effort`) montadas num método só-leitura novo — não toca
        `create_orchestration`/`_apply_routing_rule`, caminho crítico já em
        produção, para não introduzir risco de regressão por uma tela nova de UI."""
        b = self._bundle(orchestration_id)
        brief = DemandBrief.model_validate(b.orchestration.demand_brief)
        din = brief.to_decision_input(b.orchestration.user_request)
        contexto = contexto_de_demand_brief(brief)
        regras_ativas = self._routing_rules.list_rules(only_active=True)
        resultado_regra = avaliar_regras(regras_ativas, contexto)

        if resultado_regra is not None:
            acao = resultado_regra.acao
            recomendacao: dict[str, object] = {
                "agente": acao.agente,
                "modelo": acao.modelo,
                "effort": acao.effort,
                "aprovacao_humana": acao.aprovacao_humana,
                "quality_gates": list(acao.quality_gates),
                "motivos": [f"Regra de roteamento '{resultado_regra.regra_nome}' bateu."],
                "confianca": "alta",
                "fonte": "regra:" + resultado_regra.regra_id,
            }
        else:
            decisao = MultiAgentDecisionEngine().decide(din)
            effort_sugerido = sugerir_effort(brief.complexidade, brief.risco)
            lider = decisao.agents[0] if decisao.agents else None
            motivos = [decisao.reason]
            if lider is not None and lider.reason != decisao.reason:
                motivos.append(lider.reason)
            recomendacao = {
                "agente": lider.agent if lider is not None else None,
                # Sem regra casando, não há recomendação automática de modelo/
                # plataforma — heurística decide estratégia/agente/effort/aprovação,
                # não modelo (fato do motor, não lacuna a esconder com um palpite).
                "modelo": None,
                "effort": effort_sugerido,
                "aprovacao_humana": decisao.requires_human_approval,
                "quality_gates": [],
                "motivos": motivos,
                "confianca": "baixa",
                "fonte": "heuristica",
            }

        custo_estimado, tempo_estimado = self._estimar_custo_e_tempo(
            recomendacao.get("modelo"), project_id=b.orchestration.project_id
        )
        recomendacao["custo_estimado"] = custo_estimado
        recomendacao["tempo_estimado"] = tempo_estimado
        return recomendacao

    def _estimar_custo_e_tempo(
        self, modelo: object, *, project_id: str | None = None
    ) -> tuple[str | None, str | None]:
        """Custo/tempo estimados (wf §15.3) categóricos (baixo/médio/alto), derivados
        da posição relativa do executor recomendado no histórico de desempenho
        (`observability/aprendizado.py`) — nunca um número inventado. `None`/`None`
        quando não há recomendação de modelo (fallback heurístico) ou nenhum
        histórico de execução real para compará-lo.

        `project_id` (bug real, code-review ultra): `preview_recommendation` é um
        endpoint só-leitura (Tela 13) chamado a cada edição de classificação — sem
        recorte, `get_learning_report_global()` hidratava TODA orquestração do
        sistema (o próprio docstring dele existe para evitar isso, ADR-0052).
        Recortar pelo projeto da orquestração atual reaproveita o filtro SQL já
        indexado e, de quebra, compara contra o histórico do MESMO projeto — mais
        relevante do que o sistema inteiro."""
        if not modelo:
            return None, None
        relatorio = self.get_learning_report_global(project_id=project_id)
        amostras = [e for e in relatorio.desempenho_por_executor if e.execucoes > 0]
        alvo = next((e for e in amostras if e.executor == modelo), None)
        if alvo is None or len(amostras) < 1:
            return None, None
        custos = [e.custo_por_entrega for e in amostras]
        tempos = [e.tempo_medio_ms for e in amostras]
        return _faixa(alvo.custo_por_entrega, custos), _faixa(alvo.tempo_medio_ms, tempos)

    def get_agent_real_roles(self) -> list[str]:
        """Papéis reais do `AgentRegistry` (Tela 30, wf §32) — para o operador
        vincular uma definição só a um `role` que de fato existe, nunca um
        inventado na hora de preencher o formulário."""
        registry = AgentRegistry()
        registry.seed_defaults()
        return [spec.role for spec in registry.list_all()]

    # ------------------------------------------------------------- próximo passo
    def next_step(
        self, orchestration_id: str, *, slo_breaches: list[str] | None = None
    ) -> NextStepReport:
        """Diz o que falta para a esteira seguir (§14 · ADR-0013).

        Coleta o retrato do estado governado e delega o cálculo ao motor puro em
        `control/next_step.py` — assim a UI não reimplementa regra de governança.
        Sinais externos que não vivem no bundle (drift de docs, SLO) entram como
        entrada opcional e nunca derrubam a leitura.
        """
        b = self._bundle(orchestration_id)
        drift: DocsDriftReport | None = None
        if b.orchestration.target_path:
            try:
                drift = check_drift(b.orchestration.target_path)
            except (OSError, WorkspaceError):  # pasta sumiu/sem permissão: segue sem o sinal
                drift = None
        available, reason = self._executor_availability(b.orchestration.selected_executor)
        return compute_next_step(
            NextStepInput(
                orchestration=b.orchestration,
                demand_brief=DemandBrief.model_validate(b.orchestration.demand_brief),
                discovery_report=versao_atual(b.orchestration.discovery_reports, DiscoveryReport),
                spec=versao_atual(b.orchestration.spec_documents, SpecDocument),
                deploy=versao_atual(b.orchestration.deploy_runs, DeployRun),
                candidate_runs=list(b.candidate_runs),
                cards=b.board_service.cards_of(b.board.id),
                approvals=list(b.approvals),
                pulls=list(b.pull_requests),
                review_comments=list(b.review_comments),
                conflicts=list(b.bus.conflicts),
                gate_results=list(b.gate_results),
                drift=drift,
                executor_available=available,
                executor_reason=reason,
                slo_breaches=list(slo_breaches or []),
                gasto_usd=self._gasto_usd(b),
                agent_timeout_seconds=CLI_AGENT_TIMEOUT_PADRAO,
                planejamento_falhou=_ultima_falha_de_planejamento(b),
            )
        )
