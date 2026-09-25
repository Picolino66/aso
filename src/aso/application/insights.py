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
from aso.control.similaridade import (
    LIMITE_DE_CANDIDATAS,
    MINIMO_DE_HISTORICO,
    DemandaIndexada,
    ranquear,
    texto_da_demanda,
)
from aso.control.spec import SpecDocument
from aso.control.triage import DemandBrief
from aso.execution.cli_provider import TIMEOUT_PADRAO as CLI_AGENT_TIMEOUT_PADRAO
from aso.execution.docs_drift import DocsDriftReport, check_drift
from aso.execution.workspace import WorkspaceError
from aso.observability.aprendizado import (
    AmostraDeAprendizado,
    CardSnapshot,
    PullRequestSnapshot,
    RelatorioDeAprendizado,
    consolidar,
    indicadores_da_amostra,
    snapshots_da_amostra,
)
from aso.persistence.ports import OrchestrationRepository
from aso.shared.events import DomainEvent


def _ultima_falha_de_planejamento(b: OrchestrationBundle) -> str:
    """Motivo da última `PlanningFailed` ainda não superada por um plano com cards."""
    if b.board_service.cards_of(b.board.id):
        return ""
    falhas = [e for e in b.event_log.all() if e.type == "PlanningFailed"]
    return str(falhas[-1].payload.get("motivo", "")) if falhas else ""


def _faixa(valor: float, todos: list[float]) -> str:
    """Posição categórica (baixo/médio/alto) de `valor` dentro de `todos` (wf
    wf §15.3, `_estimar_custo_e_tempo`).

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
    """Soma `AgentExecuted.ms` por card — insumo de "tempo gasto" do fluxo §24."""
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
        """Checklist de preparação do card (fluxo §10, ADR-0030) — só leitura: a escrita é
        100% automática pelo runtime, nunca manual (um checklist editável mentiria
        sobre o que de fato foi verificado)."""
        b = self._bundle(orchestration_id)
        card = b.board_service.get_card(card_id)
        if card is None:
            raise KeyError(f"Card inexistente: {card_id}")
        return card.preparation_checklist

    def _amostra_do_bundle(self, b: OrchestrationBundle) -> AmostraDeAprendizado:
        """Achata o agregado hidratado na mesma `AmostraDeAprendizado` que as consultas
        produzem (MEL-52) — daqui para frente o relatório de uma demanda e o global passam
        pela mesma aritmética de `observability/aprendizado.py` (o único ponto que pode ligar
        `control` a `observability`, mesmo arranjo de `next_step`/`Service.next_step`)."""
        return AmostraDeAprendizado(
            orchestration_id=b.orchestration.id,
            cards=[
                {
                    "id": c.id,
                    "status": c.status.value,
                    "executor": c.executor,
                    "assignee": c.assignee,
                    "phase": c.phase.value,
                    "failures": list(c.failures),
                    "uso": dict(c.uso),
                    "tentativa_atual": c.tentativa_atual,
                    "qa_checks": list(c.qa_checks),
                }
                for c in b.board_service.cards_of(b.board.id)
            ],
            pulls=[
                {
                    "card_id": pr.card_id,
                    "review_rounds": pr.review_rounds,
                    "review_status": pr.review_status,
                }
                for pr in b.pull_requests
            ],
            approvals=[a.status for a in b.approvals],
            deploy_runs=list(b.orchestration.deploy_runs),
            tempo_ms_por_card=_tempo_ms_por_card(b.event_log.all()),
        )

    def _coletar_aprendizado(
        self, b: OrchestrationBundle
    ) -> tuple[list[CardSnapshot], list[PullRequestSnapshot], int]:
        return snapshots_da_amostra(self._amostra_do_bundle(b))

    def _coletar_indicadores_extra(self, b: OrchestrationBundle) -> dict[str, Any]:
        """Contagens brutas dos indicadores da Tela 29 — ver `indicadores_da_amostra`."""
        return indicadores_da_amostra(self._amostra_do_bundle(b), status_revertido=STATUS_REVERTIDO)

    def get_learning_report(self, orchestration_id: str) -> RelatorioDeAprendizado:
        """Relatório de aprendizado de UMA demanda (fluxo §24) — retrabalho, falhas por
        etapa, desempenho por executor, intervenções humanas. Informativo: não
        altera nenhuma decisão automaticamente (ADR-0052)."""
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
        ADR-0052) — "recorte por projeto e período" reaproveita o filtro SQL real já
        indexado de `list_orchestrations` (ADR-0038) e, desde a MEL-52, os insumos vêm de
        `amostras_de_aprendizado` (só as colunas usadas) em vez de hidratar o agregado
        inteiro de cada orquestração do recorte."""
        orchestrations, _ = self._repo.list_orchestrations(
            project_id=project_id, created_from=data_de, created_to=data_ate
        )
        cards: list[CardSnapshot] = []
        pulls: list[PullRequestSnapshot] = []
        intervencoes = 0
        aprovados = decisoes_de_aprovacao = rollbacks = deploys = 0
        sucesso_primeiro_ciclo = cards_com_tentativa = soma_tentativas = 0
        tempo_por_etapa_ms: dict[str, list[float]] = {}
        amostras = [
            AmostraDeAprendizado(**bruta)
            for bruta in self._repo.amostras_de_aprendizado([o.id for o in orchestrations])
        ]
        for amostra in amostras:
            c, p, i = snapshots_da_amostra(amostra)
            cards.extend(c)
            pulls.extend(p)
            intervencoes += i
            extra = indicadores_da_amostra(amostra, status_revertido=STATUS_REVERTIDO)
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
            total_orchestrations=len(amostras),
            soma_tentativas=soma_tentativas,
            cards_com_tentativa=cards_com_tentativa,
            tempo_por_etapa_ms=tempo_por_etapa_ms,
        )

    # ------------------------------------------------- demandas parecidas (MEL-45, ADR-0079)
    def demandas_similares(
        self, orchestration_id: str, *, limite: int = 5, do_projeto: bool = False
    ) -> dict[str, object]:
        """Demandas parecidas com esta e o que aconteceu com elas (ADR-0079).

        Responde "parecidas com esta falharam onde, com qual executor e a que custo?" com
        **evidência citável**: cada linha traz o id e o título da demanda de onde o número veio.
        Sem histórico suficiente, diz isso — o painel nunca inventa recomendação.

        `do_projeto` restringe ao projeto da demanda (o histórico do mesmo repositório é mais
        relevante); sem projeto definido, o recorte não se aplica e a janela é global."""
        b = self._bundle(orchestration_id)
        ficha = dict(b.orchestration.demand_brief or {})
        consulta = texto_da_demanda(b.orchestration.user_request, ficha)
        projeto = b.orchestration.project_id if do_projeto else None
        brutas = self._repo.textos_de_demandas(
            limite=LIMITE_DE_CANDIDATAS, project_id=projeto, excluir=orchestration_id
        )
        candidatas = [
            DemandaIndexada(
                orchestration_id=str(item["id"]),
                titulo=str(item["user_request"])[:120],
                texto=texto_da_demanda(
                    str(item["user_request"]), dict(item.get("demand_brief") or {})
                ),
                criada_em=str(item.get("created_at") or ""),
                status=str(item.get("status") or ""),
            )
            for item in brutas
        ]
        parecidas = ranquear(consulta, candidatas, limite=limite)
        if not parecidas:
            return {
                "consulta": consulta[:200],
                "candidatas_avaliadas": len(candidatas),
                "similares": [],
                "recomendacoes": [],
                "fonte": "sem demanda parecida no histórico",
            }
        # Desfecho só das vencedoras: uma amostra por demanda, com as colunas que já existem.
        amostras = {
            str(amostra["orchestration_id"]): amostra
            for amostra in self._repo.amostras_de_aprendizado(
                [p.orchestration_id for p in parecidas]
            )
        }
        similares: list[dict[str, Any]] = []
        for parecida in parecidas:
            similares.append(
                {
                    "orchestration_id": parecida.orchestration_id,
                    "titulo": parecida.titulo,
                    "score": parecida.score,
                    "termos_em_comum": parecida.termos_em_comum[:8],
                    "criada_em": parecida.criada_em,
                    "status": parecida.status,
                    **_desfecho_da_amostra(amostras.get(parecida.orchestration_id, {})),
                }
            )
        com_execucao = [s for s in similares if int(s.get("cards_executados") or 0) > 0]
        return {
            "consulta": consulta[:200],
            "candidatas_avaliadas": len(candidatas),
            "similares": similares,
            "recomendacoes": _recomendacoes_dos_similares(com_execucao),
            "fonte": (
                f"baseado em {len(com_execucao)} demanda(s) parecida(s) com execução registrada"
                if len(com_execucao) >= MINIMO_DE_HISTORICO
                else (
                    f"{len(similares)} demanda(s) parecida(s), mas só {len(com_execucao)} com "
                    "execução registrada — histórico insuficiente para recomendar"
                )
            ),
        }

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

    def get_agent_reserved_roles(self) -> list[str]:
        """Papéis reservados (MEL-53, ADR-0075): existem no registro, mas nenhum card os usa."""
        registry = AgentRegistry()
        registry.seed_defaults()
        return [spec.role for spec in registry.list_all() if spec.reservado]

    # ------------------------------------------------------------- próximo passo
    def next_step(
        self, orchestration_id: str, *, slo_breaches: list[str] | None = None
    ) -> NextStepReport:
        """Diz o que falta para a esteira seguir (ADR-0013).

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


def _desfecho_da_amostra(amostra: dict[str, Any]) -> dict[str, Any]:
    """O que a demanda parecida ensina: executor mais usado, tentativas, custo e falhas.

    Tudo vem das colunas que o runtime já grava (cards e PRs). Custo ausente é `None`, nunca
    zero: "ninguém informou" e "custou zero" são coisas diferentes (ADR-0026)."""
    cards = list(amostra.get("cards") or [])
    if not cards:
        return {
            "cards_executados": 0,
            "executor": None,
            "tentativas": None,
            "custo_usd": None,
            "entregues": 0,
            "review": None,
            "falhas": [],
        }
    executados = [c for c in cards if int(c.get("tentativa_atual") or 0) >= 1]
    por_executor: dict[str, int] = {}
    for card in executados:
        nome = str(card.get("executor") or "")
        if nome:
            por_executor[nome] = por_executor.get(nome, 0) + 1
    custos = [
        float((card.get("uso") or {}).get("custo_usd", 0.0) or 0.0)
        for card in executados
        if (card.get("uso") or {}).get("custo_usd")
    ]
    tentativas = [int(card.get("tentativa_atual") or 0) for card in executados]
    diagnosticos: dict[str, int] = {}
    for card in cards:
        for falha in card.get("failures") or []:
            chave = str(falha.get("diagnostico") or falha.get("categoria") or "").strip()
            if chave:
                diagnosticos[chave] = diagnosticos.get(chave, 0) + 1
    vereditos = [
        str(pr.get("review_status") or "")
        for pr in (amostra.get("pulls") or [])
        if pr.get("review_status")
    ]
    return {
        "cards_executados": len(executados),
        "executor": max(por_executor, key=lambda k: por_executor[k]) if por_executor else None,
        "tentativas": round(sum(tentativas) / len(tentativas), 2) if tentativas else None,
        "custo_usd": round(sum(custos), 6) if custos else None,
        "entregues": sum(1 for c in cards if c.get("status") == "Done"),
        "review": vereditos[-1] if vereditos else None,
        "falhas": sorted(diagnosticos, key=lambda k: -diagnosticos[k])[:3],
    }


def _recomendacoes_dos_similares(similares: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Frases com fonte a partir das demandas parecidas — nunca uma decisão automática.

    Só afirma o que os dados sustentam: o executor que mais apareceu, o diagnóstico de falha
    recorrente e o custo observado. Abaixo de `MINIMO_DE_HISTORICO` demandas, devolve vazio."""
    if len(similares) < MINIMO_DE_HISTORICO:
        return []
    recomendacoes: list[dict[str, Any]] = []
    executores: dict[str, list[str]] = {}
    for similar in similares:
        nome = similar.get("executor")
        if isinstance(nome, str) and nome:
            executores.setdefault(nome, []).append(str(similar["orchestration_id"]))
    if executores:
        melhor = max(executores, key=lambda k: len(executores[k]))
        recomendacoes.append(
            {
                "tipo": "executor",
                "texto": f"Demandas parecidas rodaram com `{melhor}`.",
                "fonte": executores[melhor],
            }
        )
    falhas: dict[str, list[str]] = {}
    for similar in similares:
        for falha in similar.get("falhas") or []:
            falhas.setdefault(str(falha), []).append(str(similar["orchestration_id"]))
    for falha, fontes in sorted(falhas.items(), key=lambda par: -len(par[1]))[:2]:
        if len(fontes) >= MINIMO_DE_HISTORICO:
            recomendacoes.append(
                {
                    "tipo": "falha",
                    "texto": f"Demandas parecidas falharam por `{falha}` — vale prevenir.",
                    "fonte": fontes,
                }
            )
    custos = [
        (str(s["orchestration_id"]), float(s["custo_usd"]))
        for s in similares
        if isinstance(s.get("custo_usd"), (int, float)) and s.get("custo_usd")
    ]
    if len(custos) >= MINIMO_DE_HISTORICO:
        media = sum(valor for _, valor in custos) / len(custos)
        recomendacoes.append(
            {
                "tipo": "custo",
                "texto": f"Custo observado em demandas parecidas: US$ {media:.4f} em média.",
                "fonte": [oid for oid, _ in custos],
            }
        )
    tentativas = [
        (str(s["orchestration_id"]), float(s["tentativas"]))
        for s in similares
        if isinstance(s.get("tentativas"), (int, float)) and s.get("tentativas")
    ]
    if len(tentativas) >= MINIMO_DE_HISTORICO:
        media = sum(valor for _, valor in tentativas) / len(tentativas)
        if media > 1.5:
            recomendacoes.append(
                {
                    "tipo": "tentativas",
                    "texto": (
                        f"Demandas parecidas precisaram de {media:.1f} tentativas por card em "
                        "média — considere esforço maior desde o início."
                    ),
                    "fonte": [oid for oid, _ in tentativas],
                }
            )
    return recomendacoes
