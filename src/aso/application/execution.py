"""`ExecutionService` — execução de cards extraída do `OrchestrationService` (ADR-0066).

MEL-32, passo 4b: claim atômico (ADR-0058), execução supervisionada, aplicação do resultado
via ContextBus, roteamento de falha (ADR-0019), freios de estratégia/orçamento/limite e
corrida de candidatos.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from typing import Any

from aso.agents.executor import AgentExecutionError, ExecutionProvider
from aso.agents.models import AgentDefinition, AgentOutput, AgentSpec
from aso.agents.supervisor import AgentSupervisor
from aso.application.agent_catalog_service import AgentCatalogService
from aso.application.agent_task import AgentTaskService, _metricas_de_contexto, _uso_do_output
from aso.application.bundles import BundleStore, OrchestrationBundle
from aso.application.delivery import DeliveryService
from aso.control.attempts import (
    RESULTADO_FALHOU,
    RESULTADO_SUCESSO,
    TentativaRegistro,
    registrar_tentativa,
)
from aso.control.failure import (
    ACAO_AUMENTAR_EFFORT,
    ACAO_BLOQUEAR,
    ACAO_ESCALAR_HUMANO,
    ACAO_MESMO_AGENTE,
    ACAO_TROCAR_EXECUTOR,
    ETAPA_EXECUCAO,
    DecisaoDeFalha,
    FailureRecord,
    decidir,
    diagnosticar,
    registrar,
)
from aso.control.orcamento import SITUACAO_ESTOURADO, avaliar_orcamento
from aso.control.preparation import (
    ITEM_BRANCH_CRIADA,
    ITEM_CARD_DESBLOQUEADO,
    ITEM_DEPENDENCIAS_VERIFICADAS,
    marcar_item,
)
from aso.execution.catalog import ExecutorCatalog
from aso.execution.jobs import verificar_cancelamento
from aso.governance.contextbus import BusResult
from aso.kanban.models import KanbanCard
from aso.shared.agent_usage import acumular_uso
from aso.shared.events import DomainEvent, EventLog
from aso.shared.ids import gen_id, now_iso
from aso.shared.types import CardType, ColumnKey, PatchStatus


def _catalog_name_of(provider: ExecutionProvider | None) -> str:
    """Nome do perfil no catálogo a partir de `provider.id` (ADR-0019).

    `CliAgentExecutionProvider.id` já é o nome do perfil; `LlmExecutionProvider` usa
    `llm:<nome>` — sem remover o prefixo, `ExecutorCatalog.get()` nunca encontraria o
    perfil ao decidir `trocar_executor`/`aumentar_effort`.
    """
    if provider is None:
        return ""
    return str(getattr(provider, "id", "") or "").removeprefix("llm:")


class ExecutionService:
    """Execução de cards: claim, agente, aplicação do resultado, roteamento de falha e freios."""

    def __init__(
        self,
        store: BundleStore,
        *,
        agent_task: AgentTaskService,
        delivery: DeliveryService,
        agent_catalog: AgentCatalogService,
        log: Any,
        instancia_id: str,
        max_escalonamentos: int,
        catalogo: Callable[[], ExecutorCatalog | None],
        provider: Callable[[], ExecutionProvider | None],
        effective_effort: Callable[..., str | None],
        effective_executor: Callable[..., str | None],
        provider_for: Callable[..., ExecutionProvider | None],
        resolve_provider: Callable[..., ExecutionProvider | None],
        submit_with_approval: Callable[..., BusResult],
    ) -> None:
        self._bundle_store = store
        self._agent_task = agent_task
        self._delivery = delivery
        self._agent_catalog = agent_catalog
        self._log = log
        self._instancia_id = instancia_id
        self._max_escalonamentos = max_escalonamentos
        self._catalogo = catalogo
        self._provider_atual = provider
        self._effort_de = effective_effort
        self._executor_de = effective_executor
        self._provider_de = provider_for
        self._resolver_provider = resolve_provider
        self._submeter = submit_with_approval

    # Colaboradores lidos a cada uso (a façade pode trocar catálogo/provider em runtime).
    @property
    def _catalog(self) -> ExecutorCatalog | None:
        return self._catalogo()

    @property
    def _provider(self) -> ExecutionProvider | None:
        return self._provider_atual()

    def _bundle(self, orchestration_id: str) -> OrchestrationBundle:
        return self._bundle_store.get(orchestration_id)

    def _persist(self, b: OrchestrationBundle) -> None:
        self._bundle_store.persist(b)

    def _lock_for(self, orchestration_id: str) -> threading.RLock:
        return self._bundle_store.lock_for(orchestration_id)

    def _build_task(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self._agent_task._build_task(*args, **kwargs)

    def _abrir_run(self, *args: Any, **kwargs: Any) -> Any:
        return self._agent_task._abrir_run(*args, **kwargs)

    def _fechar_run(self, *args: Any, **kwargs: Any) -> None:
        self._agent_task._fechar_run(*args, **kwargs)

    def _registrar_decisao_no_run(self, *args: Any, **kwargs: Any) -> None:
        self._agent_task._registrar_decisao_no_run(*args, **kwargs)

    def _effective_effort(self, *args: Any, **kwargs: Any) -> str | None:
        return self._effort_de(*args, **kwargs)

    def _effective_executor(self, *args: Any, **kwargs: Any) -> str | None:
        return self._executor_de(*args, **kwargs)

    def _provider_for(self, *args: Any, **kwargs: Any) -> ExecutionProvider | None:
        return self._provider_de(*args, **kwargs)

    def resolve_provider(self, *args: Any, **kwargs: Any) -> ExecutionProvider | None:
        return self._resolver_provider(*args, **kwargs)

    def _submit_with_approval(self, *args: Any, **kwargs: Any) -> BusResult:
        return self._submeter(*args, **kwargs)

    def open_pr(self, *args: Any, **kwargs: Any) -> Any:
        return self._delivery.open_pr(*args, **kwargs)

    def _recuperar_execucoes_interrompidas(self, b: OrchestrationBundle) -> None:
        """Claim de outra instância na reidratação = execução interrompida (ADR-0058).

        O runtime é single-process: quem reivindicou o card não está mais vivo, e o
        agente que rodava morreu junto. Deixar o card "em execução" travaria o card
        para sempre (o claim recusa nova execução); marcá-lo `Failed` com o motivo
        devolve a decisão ao operador (roteamento/retry), sem inventar um resultado.
        Execuções da PRÓPRIA instância nunca são tocadas — o claim continua válido.
        """
        interrompidos = [
            c
            for c in b.board_service.cards_of(b.board.id)
            if c.em_execucao_desde and c.execucao_dono != self._instancia_id
        ]
        for card in interrompidos:
            execution_id = card.execution_id
            desde = card.em_execucao_desde
            self._liberar_claim(card)
            b.board_service.move_card(
                card.id,
                ColumnKey.FAILED,
                reason="execução interrompida (reinício do runtime)",
                execution_id=execution_id,
            )
            b.event_log.append(
                "ExecutionInterrupted",
                {"card_id": card.id, "execution_id": execution_id, "desde": desde},
            )
        if interrompidos:
            self._persist(b)

    @staticmethod
    def _liberar_claim(card: KanbanCard) -> None:
        card.em_execucao_desde = None
        card.execution_id = None
        card.execucao_dono = None

    @staticmethod
    def _recusar_se_em_execucao(card: KanbanCard) -> None:
        if card.em_execucao_desde:
            raise ValueError(
                f"Card {card.id} já em execução desde {card.em_execucao_desde} "
                f"(execução {card.execution_id}) — aguarde terminar."
            )

    def _reivindicar_card(
        self,
        b: OrchestrationBundle,
        card: KanbanCard,
        *,
        execution_id: str,
        effort: str | None = None,
        mover: bool = True,
    ) -> None:
        """Claim atômico (ADR-0058). O chamador DEVE deter `_lock_for`: check-then-act.

        `mover=False` só reserva o lease sem mudar a coluna (corrida de candidatos não
        é a execução do card). Persiste na hora: o estado "rodando" precisa existir no
        banco antes do agente começar, senão um crash o apaga.
        """
        self._recusar_se_em_execucao(card)
        card.em_execucao_desde = now_iso()
        card.execution_id = execution_id
        card.execucao_dono = self._instancia_id
        if mover:
            b.board_service.apply_event(
                card.id,
                "AgentStarted",
                effort=effort,
                phase=card.phase.value,
                execution_id=execution_id,
            )
        self._persist(b)

    @staticmethod
    def _pending_dependencies(b: OrchestrationBundle, card: KanbanCard) -> list[KanbanCard]:
        """Dependências (§10 do fluxo.md) que ainda não chegaram a `Done`.

        Só usado no caminho manual de execução (`run_card`): o `run_plan` já ordena
        agentes por `depends_on` nas suas próprias ondas e não precisa deste guard.
        """
        pendentes = []
        for dep_id in card.dependencies:
            dep = b.board_service.get_card(dep_id)
            if dep is not None and dep.status != ColumnKey.DONE:
                pendentes.append(dep)
        return pendentes

    @staticmethod
    def _criar_tarefa_vinculada(
        b: OrchestrationBundle, card: KanbanCard, titulos_pendentes: str
    ) -> KanbanCard:
        """§10, ADR-0030: tarefa de acompanhamento criada na primeira vez que `card`
        bloqueia por dependência — dá ao operador um ponto de triagem próprio, distinto
        da(s) dependência(s) em si (que já são cards, possivelmente grandes/em curso).
        Idempotente por chamador: só é chamada quando `card.dependency_task_id is None`.
        """
        tarefa = KanbanCard(
            board_id=b.board.id,
            orchestration_id=b.orchestration.id,
            phase=card.phase,
            type=CardType.TASK,
            title=f"Resolver dependência(s) de '{card.title}'",
            description=f"O card '{card.title}' está bloqueado aguardando: {titulos_pendentes}.",
            status=ColumnKey.BACKLOG,
            linked_requirements=["§10"],
        )
        b.board_service.add_card(tarefa)
        return tarefa

    def _execute_isolated(
        self,
        agent: AgentSpec,
        task: dict[str, Any],
        provider: ExecutionProvider | None = None,
    ) -> tuple[AgentOutput | None, list[DomainEvent], Exception | None]:
        """Executa o agente com supervisão (retry/nudge) em EventLog isolado (thread-safe)."""
        local = EventLog()
        efetivo = provider or self._provider
        supervisor = AgentSupervisor(efetivo, event_log=local)
        start = time.perf_counter()
        card_id = task.get("card_id")
        run = self._abrir_run(agent, task, efetivo)
        try:
            output = supervisor.run(agent, task)
            ms = round((time.perf_counter() - start) * 1000, 1)
            uso = _uso_do_output(output)
            self._fechar_run(run, output=output, ms=ms)
            local.append(
                "AgentExecuted",
                {
                    "agent": agent.role,
                    "card_id": card_id,
                    "ms": ms,
                    "ok": True,
                    "tokens": uso.tokens_entrada + uso.tokens_saida,
                    "custo_usd": uso.custo_usd,
                    "modelo": uso.modelo,
                    "uso_origem": uso.origem,
                    "run_id": task.get("run_id"),
                    **_metricas_de_contexto(task),
                },
            )
            return output, local.all(), None
        except AgentExecutionError as exc:
            ms = round((time.perf_counter() - start) * 1000, 1)
            self._fechar_run(run, erro=exc, ms=ms)
            local.append(
                "AgentExecuted",
                {
                    "agent": agent.role,
                    "card_id": card_id,
                    "ms": ms,
                    "ok": False,
                    "run_id": task.get("run_id"),
                    **_metricas_de_contexto(task),
                },
            )
            return None, local.all(), exc

    def _execute_wave(
        self,
        jobs: list[tuple[AgentSpec, dict[str, Any], ExecutionProvider | None]],
        concurrent: bool,
    ) -> list[tuple[AgentOutput | None, list[DomainEvent], Exception | None]]:
        """Executa uma onda; cada job traz o **seu** provider (a etapa do card decide qual)."""
        if concurrent and len(jobs) > 1:
            with ThreadPoolExecutor(max_workers=min(8, len(jobs))) as pool:
                # Um contexto copiado por tarefa: leva o job atual (cancelamento, ADR-0067)
                # e o request_id do log para as threads do pool.
                futuros = [
                    pool.submit(copy_context().run, self._execute_isolated, agent, task, provider)
                    for agent, task, provider in jobs
                ]
                return [futuro.result() for futuro in futuros]
        return [self._execute_isolated(agent, task, provider) for agent, task, provider in jobs]

    def _gasto_usd(self, b: OrchestrationBundle) -> float:
        """Custo real acumulado (§1.1, ADR-0026): execuções de card (`card.uso.custo_usd`)
        **e** perguntas a agentes — triagem, discovery, spec, revisão, nomeação (ADR-0070),
        lidas do registro `agent_runs`, que é a fonte única delas."""
        cards = sum(
            float(c.uso.get("custo_usd", 0.0)) for c in b.board_service.cards_of(b.board.id)
        )
        return cards + self._agent_task._agent_runs.custo_de_perguntas(b.orchestration.id)

    @staticmethod
    def _recusar_se_estrategia_pendente(b: OrchestrationBundle) -> None:
        """Regra inviolável 4: estratégia crítica só executa depois da decisão humana.

        `create_orchestration` abre a aprovação `tipo="estrategia"` quando o plano exige
        humano; sem este guard ela era só informativa e os agentes rodavam mesmo assim.
        Estratégia REJEITADA também recusa — `resume` volta o status para `running`, e
        sem esta checagem bastaria retomar para executar a estratégia que o humano negou.
        """
        estrategias = [a for a in b.approvals if a.tipo == "estrategia"]
        if any(a.status == "pending" for a in estrategias):
            raise ValueError(
                "Estratégia aguardando aprovação humana: decida a aprovação pendente "
                "(papel admin) antes de executar."
            )
        if estrategias and estrategias[-1].status == "rejected":
            raise ValueError("Estratégia rejeitada pelo humano: execução bloqueada.")

    def _recusar_se_orcamento_estourado(self, b: OrchestrationBundle) -> None:
        """§3.2 do plano7: orçamento estourado recusa **execução nova**, nunca mata a
        que já está rodando — o freio vive na entrada de `run_card`/`race_card`, não
        num kill no meio da chamada."""
        situacao, motivo = avaliar_orcamento(self._gasto_usd(b), b.orchestration.orcamento_usd)
        if situacao == SITUACAO_ESTOURADO:
            raise ValueError(f"Orçamento estourado: {motivo}. Eleve o teto para continuar.")

    def _agent_definition_for_role(self, role: str) -> AgentDefinition | None:
        return next(
            (d for d in self._agent_catalog.list_definitions(only_active=True) if d.role == role),
            None,
        )

    def _gasto_usd_por_agente(self, b: OrchestrationBundle, role: str) -> float:
        """Custo real acumulado por um AGENTE (papel) dentro desta orquestração
        (Tela 30, wf §32, ADR-0053) — mesmo cálculo de `_gasto_usd`, só
        filtrado por `card.assignee == role`."""
        return sum(
            float(c.uso.get("custo_usd", 0.0))
            for c in b.board_service.cards_of(b.board.id)
            if c.assignee == role
        )

    def _recusar_se_limite_do_agente_estourado(
        self, b: OrchestrationBundle, card: KanbanCard
    ) -> None:
        """Limite de custo/tentativas POR AGENTE (Tela 30, wf §32, ADR-0053) —
        freio independente do orçamento da orquestração (ADR-0026) e do
        limite de tentativas do CARD (ADR-0031), que continuam valendo sem
        nenhuma mudança; `None` (sem definição vinculada ao papel, ou campo
        não configurado) nunca bloqueia — mesmo comportamento de antes desta
        ADR para todo agente ainda sem catálogo customizado."""
        role = card.assignee
        if role is None:
            return
        definicao = self._agent_definition_for_role(role)
        if definicao is None:
            return
        if (
            definicao.limite_tentativas is not None
            and card.tentativa_atual >= definicao.limite_tentativas
        ):
            raise ValueError(
                f"Agente '{role}' atingiu o limite de {definicao.limite_tentativas} "
                "tentativa(s) configurado no catálogo de agentes (Tela 30)."
            )
        if definicao.limite_custo_usd is not None:
            gasto = self._gasto_usd_por_agente(b, role)
            if gasto >= definicao.limite_custo_usd:
                raise ValueError(
                    f"Agente '{role}' atingiu o limite de custo de "
                    f"${definicao.limite_custo_usd:.2f} configurado no catálogo de "
                    "agentes (Tela 30)."
                )

    def _route_failure(
        self,
        b: OrchestrationBundle,
        card: KanbanCard,
        error: Exception | None,
        *,
        executor_atual: str,
        effort_atual: str | None,
        execution_id: str | None = None,
    ) -> DecisaoDeFalha:
        """Registra a falha (§13), diagnostica e decide o roteamento (ADR-0019).

        Chamada de dentro do laço de `run_card`: a decisão pode mandar re-tentar (mesmo
        agente, effort maior, outro executor — o laço continua) ou parar (bloquear ou
        escalar humano). `run_plan` chama isto uma vez por card e ignora a decisão: a
        próxima onda simplesmente segue com o que sobrou.
        """
        mensagem = str(error) if error is not None else "execução não produziu saída"
        card.tentativa_atual += 1  # §36.4, ADR-0031: contador autoritativo, não o ring
        card.tentativa_falha_atual += 1  # §13, ADR-0019: só falha consecutiva, decidir() usa este
        record = FailureRecord(
            etapa=ETAPA_EXECUCAO,
            tentativa=card.tentativa_atual,
            comando=executor_atual,
            mensagem=mensagem,
            saida=mensagem,
            executor=executor_atual,
            effort=effort_atual or "",
        )
        card.failures = registrar(card.failures, record)
        diagnostico = diagnosticar(record)
        decisao = decidir(
            diagnostico,
            card.tentativa_falha_atual,
            executor_atual=executor_atual,
            effort_atual=effort_atual or "",
            catalogo=self._catalog,
            max_escalonamentos=(
                card.max_tentativas if card.max_tentativas is not None else self._max_escalonamentos
            ),
        )
        card.tentativas = registrar_tentativa(
            card.tentativas,
            TentativaRegistro(
                numero=card.tentativa_atual,
                executor=executor_atual,
                effort=effort_atual or "",
                resultado=RESULTADO_FALHOU,
                diagnostico=diagnostico,
            ),
        )
        # Freio de orçamento (§1.2/§3.2, ADR-0026): antes de gastar mais (effort maior
        # ou outro executor), confere o teto. Estourado vira `escalar_humano` — é
        # justamente quando as coisas já estão dando errado que a política, sem isto,
        # escalaria para o modelo mais caro sem ninguém olhar.
        if decisao.acao in (ACAO_AUMENTAR_EFFORT, ACAO_TROCAR_EXECUTOR):
            situacao, motivo_orcamento = avaliar_orcamento(
                self._gasto_usd(b), b.orchestration.orcamento_usd
            )
            if situacao == SITUACAO_ESTOURADO:
                decisao = DecisaoDeFalha(
                    acao=ACAO_ESCALAR_HUMANO, motivo=f"orçamento esgotado — {motivo_orcamento}"
                )
        # O motivo técnico (mensagem crua) continua visível no card — a política só
        # acrescenta o "por quê" da decisão, não substitui o erro real do agente.
        detalhe = f"{mensagem} — {decisao.motivo}"
        card.block_reason = detalhe
        # Nudge da política reaproveita o canal que `_build_task` já encaminha ao
        # agente (ADR-0017, `correction_actions`) — instrução concreta para a próxima
        # tentativa, seja ela dentro do mesmo `run_card` ou um retry manual depois.
        card.correction_actions = [decisao.nudge] if decisao.nudge else []
        b.event_log.append(
            "FailureRouted",
            {
                "card_id": card.id,
                "run_id": execution_id,
                "etapa": record.etapa,
                "diagnostico": diagnostico,
                "acao": decisao.acao,
                "tentativa": record.tentativa,
            },
        )
        # Mantido por compatibilidade: `aggregate_metrics` (db/repository.py) já conta
        # "AgentFailed" para a métrica `agent_failures` — `FailureRouted` acima é o
        # evento novo e mais rico, não uma substituição.
        b.event_log.append("AgentFailed", {"card_id": card.id, "error": mensagem})
        if decisao.acao == ACAO_BLOQUEAR:
            b.board_service.move_card(
                card.id,
                ColumnKey.BLOCKED,
                reason=detalhe,
                result="falhou",
                next_action=decisao.acao,
                effort=effort_atual,
                phase=card.phase.value,
                execution_id=execution_id,
            )
        elif decisao.acao == ACAO_ESCALAR_HUMANO:
            b.board_service.move_card(
                card.id,
                ColumnKey.FAILED,
                reason=detalhe,
                result="falhou",
                next_action=decisao.acao,
            )
        else:
            b.board_service.move_card(
                card.id,
                card.status,
                reason=detalhe,
                result="falhou, nova tentativa automática",
                next_action=decisao.acao,
            )
        self._log.warning(
            "agent_failed",
            card_id=card.id,
            error=mensagem,
            diagnostico=diagnostico,
            acao=decisao.acao,
        )
        return decisao

    def _apply_execution(
        self,
        b: OrchestrationBundle,
        card_id: str,
        output: AgentOutput | None,
        events: list[DomainEvent],
        error: Exception | None,
        *,
        executor_name: str | None = None,
        catalog_executor: str | None = None,
        effort: str | None = None,
        execution_id: str | None = None,
    ) -> tuple[list[BusResult], DecisaoDeFalha | None]:
        """Aplica serialmente (single-writer) o resultado de uma execução e move o card.

        Em falha, delega ao roteamento (ADR-0019): a `DecisaoDeFalha` devolvida diz a
        `run_card` se vale a pena tentar de novo dentro do mesmo laço (None = sucesso).
        `catalog_executor` é o nome do perfil no catálogo (distinto de `executor_name`,
        que é `provider.id` e pode vir prefixado `llm:` — ver `_catalog_name_of`); sem
        ele, cai em `executor_name`.

        `execution_id` (Tela 28, wf §30, ADR-0051) identifica esta execução na
        auditoria — gerado pelo chamador (`run_card`/`run_plan`), uma vez por
        tentativa, e propagado a todo `CardEvent` que nasce dela.
        """
        # `AgentStarted` (→ InProgress) NÃO é aplicado aqui: o chamador o aplica no
        # claim, antes de chamar o provider (ADR-0058) — aplicá-lo só depois deixava o
        # card `Ready` durante toda a execução.
        b.event_log.extend(events)
        card = b.board_service.get_card(card_id)
        if card is None:
            return [], None
        if error is not None or output is None:
            decisao = self._route_failure(
                b,
                card,
                error,
                executor_atual=catalog_executor or executor_name or "",
                effort_atual=effort,
                execution_id=execution_id,
            )
            return [], decisao
        # Perfil de executor que de fato rodou (ADR-0017): distinto do papel
        # (`assignee`) — sem isto não há como exigir revisor diferente do card.
        if executor_name:
            card.executor = executor_name
        card.uso = acumular_uso(card.uso, _uso_do_output(output))
        modelo = str(card.uso.get("modelo") or "") or None
        # §36.4, ADR-0031: sucesso também é uma tentativa — conta para o histórico
        # (não para o limite de escalação, que só olha falhas consecutivas).
        card.tentativa_atual += 1
        card.tentativa_falha_atual = 0  # §13, ADR-0019: sucesso zera a sequência de falhas
        card.tentativas = registrar_tentativa(
            card.tentativas,
            TentativaRegistro(
                numero=card.tentativa_atual,
                executor=catalog_executor or executor_name or "",
                effort=effort or "",
                resultado=RESULTADO_SUCESSO,
            ),
        )
        branch = output.artifacts.get("branch")
        if branch:
            card.branch = str(branch)
            # §10, ADR-0030: a branch existe de fato (nome gravado acima) — fato
            # estrutural, não uma etapa separada a inferir.
            card.preparation_checklist = marcar_item(card.preparation_checklist, ITEM_BRANCH_CRIADA)
        card.correction_actions = []  # sucesso: nudge/correções pendentes não se aplicam mais
        results = [self._submit_with_approval(b, p, card_id=card_id) for p in output.patches]
        fase_atual = card.phase.value
        if any(r.status == PatchStatus.REJECTED for r in results):
            b.board_service.move_card(
                card_id,
                ColumnKey.BLOCKED,
                reason="conflito detectado",
                model=modelo,
                effort=effort,
                phase=fase_atual,
                execution_id=execution_id,
            )
        elif any(r.status == PatchStatus.PENDING for r in results):
            b.board_service.apply_event(  # → Waiting Human
                card_id,
                "AgentNeedsInput",
                model=modelo,
                effort=effort,
                phase=fase_atual,
                execution_id=execution_id,
            )
        else:
            b.board_service.apply_event(  # → Testing
                card_id,
                "TestsPassed",
                model=modelo,
                effort=effort,
                phase=fase_atual,
                execution_id=execution_id,
            )
        return results, None

    def run_card(
        self,
        orchestration_id: str,
        card_id: str,
        *,
        provider: ExecutionProvider | None = None,
        effort: str | None = None,
    ) -> list[BusResult]:
        """Executa o agente do card (supervisionado), aplica patches e move o card.

        `provider`/`effort` permitem escolher o executor e o esforço por etapa. Em
        falha, o roteamento (ADR-0019) pode mandar re-tentar dentro deste mesmo laço
        (mesmo agente, effort maior, outro executor) antes de bloquear ou escalar —
        "retorna exatamente ao ponto responsável pelo erro" (§13 do fluxo.md).

        Claim atômico (ADR-0058): guards + claim sob `_lock_for`, agente FORA do lock
        (execução longa não segura a orquestração), resultado aplicado sob lock e claim
        liberado num `finally` — inclusive em exceção inesperada. O laço de retry mantém
        o claim: não solta e re-adquire entre tentativas.
        """
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            if b.orchestration.status == "cancelled":  # kill-switch (M6)
                raise ValueError("Orquestração cancelada: execução bloqueada.")
            self._recusar_se_estrategia_pendente(b)
            self._recusar_se_orcamento_estourado(b)
            card = b.board_service.get_card(card_id)
            if card is None or card.assignee is None:
                raise KeyError(f"Card inválido ou sem agente: {card_id}")
            # Falha rápido antes de qualquer efeito (checklist, bloqueio por dependência).
            self._recusar_se_em_execucao(card)
            if card.pausado:
                raise ValueError(
                    "Card pausado (Tela 15, wf §17.2) — retome com POST .../pause "
                    "antes de executar."
                )
            self._recusar_se_limite_do_agente_estourado(b, card)
            pendentes = self._pending_dependencies(b, card)
            # §10, ADR-0030: o guard rodou — fato estrutural, independente do resultado.
            card.preparation_checklist = marcar_item(
                card.preparation_checklist, ITEM_DEPENDENCIAS_VERIFICADAS
            )
            if pendentes:
                card.blocked_by = [dep.id for dep in pendentes]
                titulos = ", ".join(dep.title for dep in pendentes)
                if card.dependency_task_id is None:
                    tarefa = self._criar_tarefa_vinculada(b, card, titulos)
                    card.dependency_task_id = tarefa.id
                b.board_service.move_card(
                    card_id,
                    ColumnKey.BLOCKED,
                    reason=(
                        f"aguardando dependência(s): {titulos} "
                        f"(tarefa vinculada: {card.dependency_task_id})"
                    ),
                )
                self._persist(b)
                raise ValueError(f"Card {card_id} tem dependência(s) pendente(s): {titulos}")
            if card.blocked_by:
                card.blocked_by = []  # dependências resolvidas: limpa o registro obsoleto
            card.dependency_task_id = None  # nenhum bloqueio ativo — ponteiro não se aplica
            # §10, ADR-0030: chegou até aqui sem pendência — o card está desbloqueado.
            card.preparation_checklist = marcar_item(
                card.preparation_checklist, ITEM_CARD_DESBLOQUEADO
            )
            agent = b.agent_registry.get(card.assignee)
            if agent is None:
                raise KeyError(f"Agente não registrado: {card.assignee}")
            # Chamada direta (ex.: /cards/{id}/run, /retry) sem provider → resolve pelo
            # executor da fase **do card** (não a fase corrente da orquestração: um retry
            # em F5 com a esteira já em F6 continua usando o agente configurado para F5).
            executor_atual = ""
            if provider is None:
                # Controles em voo (Tela 15, wf §17.2, ADR-0048): override do card vence a
                # resolução normal de etapa, igual a um parâmetro explícito de chamada —
                # mesma ordem de precedência que `_effective_effort`/`_effective_executor`
                # já documentam, só que a "chamada explícita" aqui é o card, não o argumento.
                effort = effort or card.effort_override
                effort = self._effective_effort(b, card.executor_override, effort, phase=card.phase)
                executor_atual = (
                    self._effective_executor(b, card.executor_override, phase=card.phase) or ""
                )
                provider = self._provider_for(b, card.executor_override, effort, phase=card.phase)
            else:
                executor_atual = _catalog_name_of(provider)
            execution_id = gen_id("exec")
            self._reivindicar_card(b, card, execution_id=execution_id, effort=effort)
        results: list[BusResult] = []
        output: AgentOutput | None = None
        error: Exception | None = None
        try:
            while True:
                # Job cancelado (ADR-0067): nenhuma tentativa nova; o `finally` libera o claim.
                verificar_cancelamento()
                task = self._build_task(b, card, agent, effort=effort)
                task["run_id"] = execution_id  # um AgentRun por tentativa (ADR-0065)
                task["attempt"] = card.tentativa_atual + 1
                output, events, error = self._execute_isolated(agent, task, provider)
                executor_name = provider.id if provider is not None else None
                with self._lock_for(orchestration_id):
                    results, decisao = self._apply_execution(
                        b,
                        card_id,
                        output,
                        events,
                        error,
                        executor_name=executor_name,
                        catalog_executor=executor_atual,
                        effort=effort,
                        execution_id=execution_id,
                    )
                self._registrar_decisao_no_run(execution_id, decisao)
                if error is None:
                    break
                retentavel = (ACAO_MESMO_AGENTE, ACAO_AUMENTAR_EFFORT, ACAO_TROCAR_EXECUTOR)
                if decisao is None or decisao.acao not in retentavel:
                    break
                # Retry único (ADR-0071): cada nova chamada ao provider vem de uma decisão
                # do roteamento — o evento mantém a métrica de retries (`AgentRetry`).
                with self._lock_for(orchestration_id):
                    b.event_log.append(
                        "AgentRetry",
                        {
                            "agent": agent.role,
                            "card_id": card_id,
                            "acao": decisao.acao,
                            "error": str(error)[:500],
                            "run_id": execution_id,
                        },
                    )
                if decisao.acao == ACAO_AUMENTAR_EFFORT and decisao.effort:
                    effort = decisao.effort
                elif decisao.acao == ACAO_TROCAR_EXECUTOR and decisao.executor:
                    executor_atual = decisao.executor
                    provider = self.resolve_provider(
                        decisao.executor, target_path=b.orchestration.target_path, effort=effort
                    )
                # Nova tentativa sob o MESMO claim: só troca o id da execução e volta a
                # coluna para InProgress (o roteamento de falha a tinha movido).
                with self._lock_for(orchestration_id):
                    execution_id = gen_id("exec")
                    card.execution_id = execution_id
                    b.board_service.apply_event(
                        card_id,
                        "AgentStarted",
                        effort=effort,
                        phase=card.phase.value,
                        execution_id=execution_id,
                    )
        finally:
            with self._lock_for(orchestration_id):
                self._liberar_claim(card)
                self._persist(b)
        if error is None and output is not None and output.artifacts.get("branch"):
            self.open_pr(orchestration_id, card_id, branch=str(output.artifacts["branch"]))
        with self._lock_for(orchestration_id):
            self._persist(b)
        return results
