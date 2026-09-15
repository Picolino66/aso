"""`AgentTaskService` — tarefa do agente e registro de execuções (ADR-0066).

MEL-32, passo 4a: `TaskEnvelope` + contexto priorizado (ADR-0059/0063) e `AgentRun`
(ADR-0065), extraídos do `OrchestrationService`.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import structlog

from aso.agents.context_builder import (
    SECOES_DO_LEDGER,
    AdrResumida,
    FontesDoContexto,
    construir_contexto,
)
from aso.agents.contract import KIND_EXECUTE, SCHEMA_VERSION, CardBrief, TaskEnvelope
from aso.agents.executor import ExecutionProvider
from aso.agents.models import AgentOutput, AgentSpec
from aso.agents.prompt_builder import PromptBuilder
from aso.agents.render_prompt import renderizar_prompt
from aso.application.bundles import BundleStore, OrchestrationBundle
from aso.control.agent_ask import ContextoDeRun, contexto_de_run
from aso.control.discovery import STATUS_APROVADO, DiscoveryReport
from aso.control.documentos import versao_atual
from aso.control.failure import DecisaoDeFalha
from aso.control.models import NAMING_KEY, AgentAssignment
from aso.control.naming import BranchNaming, NamingService
from aso.control.preparation import (
    ITEM_CODIGO_AFETADO_ANALISADO,
    ITEM_CRITERIOS_ANALISADOS,
    ITEM_ESPECIFICACAO_LIDA,
    ITEM_PLANO_REGISTRADO,
    ITEM_TESTES_EXISTENTES_IDENTIFICADOS,
    marcar_item,
)
from aso.control.spec import SpecDocument
from aso.execution.llm_provider import LlmExecutionProvider
from aso.execution.precos import precificar
from aso.kanban.models import KanbanCard
from aso.observability.agent_runs import STATUS_FALHA as STATUS_RUN_FALHA
from aso.observability.agent_runs import STATUS_SUCESSO as STATUS_RUN_SUCESSO
from aso.observability.agent_runs import (
    AgentRun,
    AgentRunRepository,
    limite_de_retencao,
    retencao_em_dias,
)
from aso.shared.agent_usage import UsoDoAgente
from aso.shared.ids import now_iso

# Campos da ficha da demanda úteis ao agente (o resto é metadado de triagem).
_CAMPOS_DA_FICHA_NO_CONTEXTO = frozenset(
    {"objetivo", "problema", "resultado_esperado", "criterios_de_aceite", "riscos", "restricoes"}
)


def _prompt_da_tarefa(
    agent: AgentSpec, task: dict[str, Any], provider: ExecutionProvider | None
) -> str:
    """O prompt que o agente de fato recebe: PromptBuilder (LLM) ou wrapper CLI."""
    try:
        if isinstance(provider, LlmExecutionProvider):
            system, user = PromptBuilder().build_messages(agent, task, None)
            return f"{system}\n\n{user}"
        return renderizar_prompt(json.loads(json.dumps(task, default=str)))
    except (ValueError, TypeError, KeyError):
        return ""


def _metricas_de_contexto(task: dict[str, Any]) -> dict[str, object]:
    """Tamanho e omissões do contexto entregue, para o evento `AgentExecuted` (ADR-0063)."""
    envelope = task.get("envelope")
    contexto = envelope.get("contexto") if isinstance(envelope, dict) else None
    if not isinstance(contexto, dict):
        return {}
    return {
        "contexto_chars": contexto.get("tamanho", 0),
        "contexto_omitidos": list(contexto.get("omitidos") or []),
    }


def _uso_do_output(output: AgentOutput | None) -> UsoDoAgente:
    """Lê o consumo que `CliAgentExecutionProvider` deixou em `artifacts["uso"]`
    (§1.1, ADR-0026) — provider mock/legado sem esta chave cai no default
    `origem="indisponivel"`, sem quebrar nenhum executor existente."""
    if output is None:
        return UsoDoAgente()
    bruto = output.artifacts.get("uso")
    if not isinstance(bruto, dict):
        return UsoDoAgente()
    try:
        # Só tokens (LLM via API, Codex): custo pela tabela de preços, se houver (ADR-0070).
        return precificar(UsoDoAgente(**bruto))
    except TypeError:
        return UsoDoAgente()


def _effort_aplicado(provider: ExecutionProvider | None, effort: object) -> bool | None:
    """Registra se o esforço pedido tem efeito no executor (ADR-0073)."""
    if not effort:
        return None
    aplica = getattr(provider, "aplica_effort", None)
    return bool(aplica()) if callable(aplica) else False


class AgentTaskService:
    """Monta a tarefa do agente (envelope + contexto) e registra as execuções (AgentRun)."""

    def __init__(
        self,
        store: BundleStore,
        *,
        agent_runs: AgentRunRepository,
        naming: NamingService,
        log: Any,
        assignment: Callable[[OrchestrationBundle, str | None], AgentAssignment | None],
    ) -> None:
        self._bundle_store = store
        self._agent_runs = agent_runs
        self._naming = naming
        self._log = log
        self._assignment_de = assignment

    def _bundle(self, orchestration_id: str) -> OrchestrationBundle:
        return self._bundle_store.get(orchestration_id)

    def _assignment(self, b: OrchestrationBundle, key: str | None) -> AgentAssignment | None:
        return self._assignment_de(b, key)

    def _nomes_do_card(self, b: OrchestrationBundle, card: KanbanCard) -> BranchNaming:
        """Nomes do card: pergunta ao agente de nomeação só na primeira vez (ADR-0071)."""
        if card.branch_stem and card.commit_subject:
            return BranchNaming(
                branch_stem=card.branch_stem,
                commit_subject=card.commit_subject,
                source="card",
            )
        nomes = self._perguntar_registrando(
            b.orchestration.id,
            card.id,
            lambda: self._naming.suggest(
                self._assignment(b, NAMING_KEY),
                card_type=card.type,
                title=card.title,
                description=card.description,
                acceptance_criteria=card.acceptance_criteria,
                phase=card.phase,
            ),
        )
        with self._bundle_store.lock_for(b.orchestration.id):
            if nomes.fallback_reason:
                b.event_log.append(
                    "NamingFallback",
                    {"card_id": card.id, "reason": nomes.fallback_reason},
                )
            card.branch_stem = nomes.branch_stem
            card.commit_subject = nomes.commit_subject
        return nomes

    def _build_task(
        self,
        b: OrchestrationBundle,
        card: KanbanCard,
        agent: AgentSpec,
        *,
        effort: str | None = None,
    ) -> dict[str, Any]:
        section = agent.context_sections[0] if agent.context_sections else "engineering"
        nomes = self._nomes_do_card(b, card)
        task: dict[str, Any] = {
            "orchestration_id": b.orchestration.id,
            "card_id": card.id,
            "phase": card.phase.value,
            # Uma chave por card (ADR-0063): antes `mock_<papel>` fazia dois cards do mesmo
            # papel sobrescreverem a mesma saída no ledger.
            "target_path": f"{section}.{card.id}",
            # Batismo do trabalho (ADR-0014): a branch sai do card, e o assunto do
            # commit vai no prompt para o agente CLI seguir a convenção. O sufixo de
            # unicidade é fechado por quem cria o worktree — o mesmo card pode ter
            # várias branches vivas (retry, candidatos concorrentes).
            "branch_stem": nomes.branch_stem,
            "commit_subject": nomes.commit_subject,
            "content": {
                "by": agent.role,
                "request": b.orchestration.user_request,
                # Sem estes campos o agente executava cego: recebia só a demanda global
                # da orquestração e nunca sabia QUAL card estava implementando.
                "card_title": card.title,
                "card_description": card.description,
                "card_type": card.type.value,
                "acceptance_criteria": list(card.acceptance_criteria),
                # Ações objetivas de uma revisão reprovada (§15, ADR-0017): sem isto o
                # agente re-executava cego, sem saber O QUE especificamente corrigir.
                "correction_actions": list(card.correction_actions),
                # "Adicionar contexto" (Tela 15, wf §17.2, ADR-0048) — instruções
                # extras do operador, entram no próximo prompt junto das correções.
                "contexto_adicional": list(card.contexto_adicional),
                "commit_subject": nomes.commit_subject,
                "validation_command": b.orchestration.validation_command,
            },
        }
        if effort:
            task["effort"] = effort  # repassado ao agente (CLI/LLM) para calibrar o esforço
        # Contrato versionado com o agente CLI (ADR-0059); `content` segue para
        # compatibilidade com wrappers e providers que ainda leem o formato antigo.
        contexto = construir_contexto(self._fontes_do_contexto(b, card))
        task["envelope"] = TaskEnvelope(
            contexto=contexto,
            kind=KIND_EXECUTE,
            task_type="card",
            request=b.orchestration.user_request,
            card=CardBrief(
                titulo=card.title,
                tipo=card.type.value,
                descricao=card.description,
                criterios=list(card.acceptance_criteria),
                correcoes=list(card.correction_actions),
                contexto_adicional=list(card.contexto_adicional),
            ),
            effort=effort or "",
            validation_command=b.orchestration.validation_command,
            commit_subject=nomes.commit_subject,
            phase=card.phase.value,
            target_path=task["target_path"],
        ).model_dump()
        # §10, ADR-0030: o runtime está prestes a entregar ao agente a especificação
        # (card_description), os critérios de aceite, o repositório (worktree) e o
        # comando de validação/plano de naming — os 5 itens abaixo registram essa
        # PASSAGEM DE CONTEXTO, não uma confirmação de que o agente os aplicou com
        # juízo (isso nenhum runtime determinístico pode provar). Chamado por
        # `race_card`/`run_card`/`run_plan` — os três caminhos de execução.
        for item in (
            ITEM_ESPECIFICACAO_LIDA,
            ITEM_CRITERIOS_ANALISADOS,
            ITEM_CODIGO_AFETADO_ANALISADO,
            ITEM_TESTES_EXISTENTES_IDENTIFICADOS,
            ITEM_PLANO_REGISTRADO,
        ):
            card.preparation_checklist = marcar_item(card.preparation_checklist, item)
        return task

    # ------------------------------------------------ registro de execuções (ADR-0065)
    def _salvar_run(self, run: AgentRun) -> None:
        """Grava o registro sem nunca derrubar a execução; aplica a retenção de textos."""
        try:
            self._agent_runs.salvar(run)
            dias = retencao_em_dias()
            if dias is not None:
                self._agent_runs.expurgar_textos(limite_de_retencao(dias))
        except Exception as exc:  # noqa: BLE001 - observabilidade não é caminho crítico
            self._log.warning("agent_run_nao_registrado", run_id=run.id, error=str(exc))

    def _perguntar_registrando[T](
        self, orchestration_id: str, card_id: str | None, chamada: Callable[[], T]
    ) -> T:
        """Executa uma pergunta a agente registrando `AgentRun` kind=ask (ADR-0065)."""
        contexto = ContextoDeRun(
            registrar=self._salvar_run,
            orchestration_id=orchestration_id,
            card_id=card_id,
            request_id=str(structlog.contextvars.get_contextvars().get("request_id", "")),
            ao_evento=lambda tipo, payload: self._bundle_store.get(
                orchestration_id
            ).event_log.append(tipo, payload),
        )
        with contexto_de_run(contexto):
            return chamada()

    def _abrir_run(
        self, agent: AgentSpec, task: dict[str, Any], provider: ExecutionProvider | None
    ) -> AgentRun | None:
        run_id = task.get("run_id")
        if not run_id:
            return None
        envelope = task.get("envelope") if isinstance(task.get("envelope"), dict) else {}
        run = AgentRun(
            id=str(run_id),
            orchestration_id=str(task.get("orchestration_id", "")),
            card_id=task.get("card_id"),
            attempt=int(task.get("attempt", 0) or 0),
            task_type=str((envelope or {}).get("task_type") or "card"),
            papel=agent.role,
            executor=provider.id if provider is not None else "",
            effort=str(task.get("effort") or ""),
            effort_aplicado=_effort_aplicado(provider, task.get("effort")),
            prompt_version=f"task-envelope-v{SCHEMA_VERSION}",
            prompt=_prompt_da_tarefa(agent, task, provider),
            envelope=envelope or {},
            request_id=str(structlog.contextvars.get_contextvars().get("request_id", "")),
        )
        self._salvar_run(run)
        return run

    def _fechar_run(
        self,
        run: AgentRun | None,
        *,
        ms: float,
        output: AgentOutput | None = None,
        erro: Exception | None = None,
    ) -> None:
        if run is None:
            return
        atualizacao: dict[str, Any] = {"fim": now_iso(), "duracao_ms": ms}
        if output is not None:
            uso = _uso_do_output(output)
            conteudo = output.patches[0].content if output.patches else None
            diff = output.artifacts.get("diff")
            atualizacao.update(
                status=STATUS_RUN_SUCESSO,
                saida_resumo=output.summary[:4000],
                stdout_cauda=str(
                    output.artifacts.get("stdout") or output.artifacts.get("raw") or ""
                )[-4000:],
                branch=str(output.artifacts["branch"]) if output.artifacts.get("branch") else None,
                diff_lines=len(str(diff).splitlines()) if diff is not None else None,
                exit_code=conteudo.get("exit_code") if isinstance(conteudo, dict) else None,
                tokens_entrada=uso.tokens_entrada,
                tokens_saida=uso.tokens_saida,
                tokens_cache=uso.tokens_cache_leitura + uso.tokens_cache_escrita,
                custo_usd=uso.custo_usd,
                modelo=uso.modelo,
                uso_origem=uso.origem,
            )
        if erro is not None:
            atualizacao.update(
                status=STATUS_RUN_FALHA, erro=f"{type(erro).__name__}: {erro}"[:4000]
            )
        run_atual = self._agent_runs.obter(run.id) or run
        self._salvar_run(run_atual.model_copy(update=atualizacao))

    def _registrar_decisao_no_run(self, run_id: str, decisao: DecisaoDeFalha | None) -> None:
        """A decisão do roteamento de falha fica no MESMO registro da tentativa."""
        if decisao is None:
            return
        run = self._agent_runs.obter(run_id)
        if run is None:
            return
        self._salvar_run(
            run.model_copy(
                update={
                    "decisao": {
                        "acao": decisao.acao,
                        "motivo": decisao.motivo,
                        "effort": decisao.effort,
                        "executor": decisao.executor,
                    }
                }
            )
        )

    def list_agent_runs(
        self, orchestration_id: str, *, card_id: str | None = None
    ) -> list[AgentRun]:
        self._bundle(orchestration_id)  # 404 coerente para orquestração inexistente
        return self._agent_runs.listar(orchestration_id, card_id=card_id)

    def get_agent_run(self, run_id: str) -> AgentRun:
        run = self._agent_runs.obter(run_id)
        if run is None:
            raise KeyError(f"Execução inexistente: {run_id}")
        return run

    @staticmethod
    def _fontes_do_contexto(b: OrchestrationBundle, card: KanbanCard) -> FontesDoContexto:
        """Extrai do bundle o que o ContextBuilder pode oferecer ao agente (ADR-0063)."""
        item_de_spec: dict[str, Any] | None = None
        if b.orchestration.spec_documents:
            spec = versao_atual(b.orchestration.spec_documents, SpecDocument)
            pilha = list(spec.itens_de_trabalho)
            while pilha:
                item = pilha.pop(0)
                if item.titulo == card.title:
                    item_de_spec = item.model_dump(exclude={"itens_filhos"})
                    break
                pilha.extend(item.itens_filhos)
        discovery_resumo = ""
        if b.orchestration.discovery_reports:
            relatorio = versao_atual(b.orchestration.discovery_reports, DiscoveryReport)
            if relatorio.status == STATUS_APROVADO:
                linhas = [
                    f"Problema: {relatorio.problema}" if relatorio.problema else "",
                    f"Recomendação técnica: {relatorio.recomendacao_tecnica}"
                    if relatorio.recomendacao_tecnica
                    else "",
                    ("Componentes afetados: " + ", ".join(relatorio.componentes_afetados))
                    if relatorio.componentes_afetados
                    else "",
                    ("Restrições: " + "; ".join(relatorio.restricoes))
                    if relatorio.restricoes
                    else "",
                    ("Riscos: " + "; ".join(relatorio.riscos)) if relatorio.riscos else "",
                ]
                discovery_resumo = "\n".join(linha for linha in linhas if linha)
        ficha = {
            chave: valor
            for chave, valor in (b.orchestration.demand_brief or {}).items()
            if chave in _CAMPOS_DA_FICHA_NO_CONTEXTO and valor
        }
        adrs = [
            AdrResumida(id=a.id, titulo=a.title, decisao=a.decision)
            for a in b.adr_registry.accepted()
            if a.phase == card.phase or a.id in card.linked_adrs
        ]
        payload = b.store.get()
        return FontesDoContexto(
            card_titulo=card.title,
            card_descricao=card.description,
            card_criterios=list(card.acceptance_criteria),
            card_correcoes=list(card.correction_actions),
            card_contexto_adicional=list(card.contexto_adicional),
            item_de_spec=item_de_spec,
            discovery_resumo=discovery_resumo,
            ficha_da_demanda=ficha,
            adrs=adrs,
            ledger={secao: payload.get(secao) for secao in SECOES_DO_LEDGER},
        )
