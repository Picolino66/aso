"""`ExecutionSettingsService` — executor e esforço efetivos, atribuições e validações (ADR-0066).

MEL-32, passo 11a: a resolução de executor/esforço (§9, ADR-0022), as atribuições por etapa,
os checks de validação, o orçamento (ADR-0026) e a limpeza de worktrees órfãos (ADR-0027)
saem da façade; os demais serviços recebem essas resoluções por construtor.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from aso.agents.executor import ExecutionProvider
from aso.application.bundles import BundleStore, OrchestrationBundle
from aso.control.failure import proximo_effort, proximo_executor
from aso.control.models import (
    DISCOVERY_KEY,
    NAMING_KEY,
    PLANNING_KEY,
    REVIEW_KEY,
    SPEC_KEY,
    TRIAGE_KEY,
    AgentAssignment,
    Orchestration,
    ValidationCheck,
)
from aso.control.selecao import resolver_topo, sugerir_effort
from aso.control.triage import DemandBrief
from aso.control.validation import checks_efetivos, sugerir_bateria
from aso.execution.catalog import ExecutorCatalog, ExecutorProfile
from aso.execution.gate_validation import validate_gate_command
from aso.execution.llm_client import LlmClient
from aso.execution.worktree import WorktreeManager
from aso.kanban.models import KanbanCard
from aso.observability.agent_log import AgentLogBus
from aso.shared.ids import now_iso
from aso.shared.types import ColumnKey, Phase


class ExecutionSettingsService:
    """Configuração de execução de uma orquestração e resolução do executor/esforço efetivos."""

    # -------------------------------------- worktrees órfãos (§1.4/§3.3, ADR-0027)
    _STATUS_INATIVOS = (ColumnKey.DONE, ColumnKey.CANCELLED, ColumnKey.ARCHIVED)

    def __init__(
        self,
        store: BundleStore,
        *,
        log_bus: AgentLogBus,
        effort_automatico: bool,
        catalogo: Callable[[], ExecutorCatalog | None],
        provider: Callable[[], ExecutionProvider | None],
        validate_executor: Callable[..., ExecutorProfile],
    ) -> None:
        self._bundle_store = store
        self._log_bus = log_bus
        self._effort_automatico = effort_automatico
        self._catalogo = catalogo
        self._provedor = provider
        self._validar_executor = validate_executor

    @property
    def _catalog(self) -> ExecutorCatalog | None:
        return self._catalogo()

    @property
    def _provider(self) -> ExecutionProvider | None:
        return self._provedor()

    def _bundle(self, orchestration_id: str) -> OrchestrationBundle:
        return self._bundle_store.get(orchestration_id)

    def _persist(self, b: OrchestrationBundle) -> None:
        self._bundle_store.persist(b)

    def _lock_for(self, orchestration_id: str) -> threading.RLock:
        return self._bundle_store.lock_for(orchestration_id)

    def _validate_executor(self, name: str, effort: str | None = None) -> ExecutorProfile:
        return self._validar_executor(name, effort)

    # ------------------------------------------------------------------ execução
    def resolve_provider(
        self,
        executor: str | None,
        *,
        target_path: str | None = None,
        effort: str | None = None,
    ) -> ExecutionProvider | None:
        """Resolve o provider de um executor escolhido (catálogo); None → default.

        `target_path` é a pasta da orquestração (workspace): repassada ao catálogo
        como `repo_override`, faz os agentes CLI operarem nela em vez do repo global.
        """
        if not executor or self._catalog is None:
            return None
        return self._catalog.build(
            executor,
            repo_override=target_path,
            effort_override=effort,
            log_bus=self._log_bus,
        )

    def cliente_de_planejamento(self, orchestration_id: str | None = None) -> LlmClient | None:
        """Cliente LLM do planejamento, vindo do catálogo (ADR-0076).

        Ordem: executor atribuído à etapa `planejamento` da orquestração → LLM padrão do
        catálogo. None = nenhum LLM utilizável (a rota responde 409). Atribuição explícita
        que não serve (sem chave, indisponível) levanta: o operador escolheu e precisa saber
        por que não vale, em vez de cair silenciosamente em outro executor."""
        catalogo = self._catalog
        if catalogo is None:
            return None
        if orchestration_id is not None:
            escolha = self._assignment(self._bundle(orchestration_id), PLANNING_KEY)
            if escolha is not None:
                return catalogo.llm_client(escolha.executor, effort_override=escolha.effort)
        nome = catalogo.llm_padrao()
        return catalogo.llm_client(nome) if nome is not None else None

    def candidatos_da_corrida(
        self, orchestration_id: str, executores: list[str] | None = None
    ) -> list[ExecutionProvider]:
        """Providers da corrida de candidatos (§26A.6), todos do catálogo (ADR-0076).

        `executores` escolhidos na requisição; sem lista, os perfis marcados `candidato`.
        Só agentes CLI competem: a corrida compara diffs de worktrees isolados."""
        catalogo = self._catalog
        if catalogo is None:
            return []
        b = self._bundle(orchestration_id)
        nomes = (
            list(dict.fromkeys(executores))
            if executores
            else [p.name for p in catalogo.profiles() if p.candidato and p.available]
        )
        providers: list[ExecutionProvider] = []
        for nome in nomes:
            perfil = catalogo.validate(nome)
            if perfil.kind != "cli":
                raise ValueError(
                    f"Candidato '{nome}' não é um agente CLI: a corrida compara diffs de worktree."
                )
            providers.append(
                catalogo.build(
                    nome, repo_override=b.orchestration.target_path, log_bus=self._log_bus
                )
            )
        return providers

    @staticmethod
    def _assignment(b: OrchestrationBundle, key: str | None) -> AgentAssignment | None:
        """Executor configurado para uma etapa (ou para `naming`), se houver."""
        if not key:
            return None
        return b.orchestration.agent_assignments.get(key)

    def _effective_executor(
        self, b: OrchestrationBundle, executor: str | None, *, phase: Phase | None = None
    ) -> str | None:
        """Executor a usar, na ordem: chamada explícita → etapa → padrão → default."""
        if executor:
            return executor
        escolha = self._assignment(b, phase.value if phase else None)
        if escolha is not None:
            return escolha.executor
        if b.orchestration.selected_executor:
            return b.orchestration.selected_executor
        if b.orchestration.target_path and self._catalog is not None:
            return self._catalog.default_name()
        return None

    def _effective_effort(
        self,
        b: OrchestrationBundle,
        executor: str | None,
        effort: str | None,
        *,
        phase: Phase | None = None,
    ) -> str | None:
        """Ordem de resolução (§9 do fluxo.md, ADR-0022): explícito → etapa →
        padrão da orquestração → sugestão automática da ficha → default do perfil.
        A sugestão só preenche o vazio que, sem ela, cairia direto no perfil — toda
        escolha humana (explícita, de etapa ou da orquestração) continua vencendo."""
        if effort:
            return effort
        escolha = self._assignment(b, phase.value if phase else None)
        if escolha is not None:
            # Etapa com executor próprio não herda o esforço global: esforço casa com o
            # modelo, não com a orquestração (um "high" do Codex pode nem existir no
            # modelo escolhido para esta fase). Sem esforço na etapa, usa o do perfil.
            if escolha.effort:
                return escolha.effort
        elif b.orchestration.selected_effort:
            return b.orchestration.selected_effort
        sugerido = self._effort_sugerido(b, executor, phase=phase)
        if sugerido:
            return sugerido
        if executor and self._catalog is not None:
            profile = self._catalog.get(executor)
            return profile.effort if profile is not None else None
        return None

    def _effort_sugerido(
        self, b: OrchestrationBundle, executor: str | None, *, phase: Phase | None = None
    ) -> str | None:
        """§9: complexidade + risco da ficha da demanda sugerem o esforço.

        Só age quando a triagem de fato rodou (`demand_brief` não vazio) — ficha
        vazia é o mesmo "nunca triou" das demais orquestrações, e não pode mudar o
        comportamento de nenhuma delas. `ASO_EFFORT_AUTOMATICO=0` desliga por
        completo (interruptor de emergência).
        """
        if not self._effort_automatico or not b.orchestration.demand_brief:
            return None
        brief = DemandBrief.model_validate(b.orchestration.demand_brief)
        sugestao = sugerir_effort(brief.complexidade, brief.risco)
        suportados: list[str] = []
        if executor and self._catalog is not None:
            perfil = self._catalog.get(executor)
            if perfil is not None:
                suportados = list(perfil.supported_efforts)
        resolvido = resolver_topo(sugestao, suportados)
        b.event_log.append(
            "EffortSugerido",
            {
                "orchestration_id": b.orchestration.id,
                "fase": phase.value if phase else None,
                "complexidade": brief.complexidade,
                "risco": brief.risco.value,
                "effort": resolvido,
            },
        )
        return resolvido

    def _provider_for(
        self,
        b: OrchestrationBundle,
        executor: str | None,
        effort: str | None = None,
        *,
        phase: Phase | None = None,
    ) -> ExecutionProvider | None:
        """Provider a usar nesta etapa, atrelado à pasta da orquestração (se houver).

        - executor escolhido (chamada ou etapa) → resolve do catálogo com a pasta;
        - sem executor, mas com pasta definida → usa o executor default do catálogo,
          também atrelado à pasta (evita cair no provider global, que aponta para
          o `ASO_TARGET_REPO`);
        - senão → provider injetado na composição (testes); sem ele, o padrão do catálogo
          que roda sem pasta (ADR-0076); None = mock.
        """
        tp = b.orchestration.target_path
        effective_executor = self._effective_executor(b, executor, phase=phase)
        effective_effort = self._effective_effort(b, effective_executor, effort, phase=phase)
        if effective_executor and self._catalog is not None:
            try:
                self._validate_executor(effective_executor, effective_effort)
            except ValueError as exc:
                b.event_log.append(
                    "ExecutorRejected",
                    {
                        "orchestration_id": b.orchestration.id,
                        "executor": effective_executor,
                        "reason": str(exc),
                    },
                )
                self._persist(b)
                raise
            return self.resolve_provider(
                effective_executor, target_path=tp, effort=effective_effort
            )
        if self._provider is None and self._catalog is not None:
            # Sem provider global (ADR-0076): orquestração sem pasta usa o padrão do catálogo
            # quando ele roda sem pasta (LLM, mock, ou CLI com `ASO_TARGET_REPO`); senão, mock.
            padrao = self._catalog.default_sem_pasta()
            if padrao is not None:
                return self.resolve_provider(padrao, effort=effective_effort)
        return self._provider

    def _workspace_for(self, b: OrchestrationBundle) -> WorktreeManager:
        """Resolve o worktree da própria orquestração, nunca o provider global."""
        if b.orchestration.target_path:
            return WorktreeManager(b.orchestration.target_path)
        legacy = getattr(self._provider, "worktree", None)
        if isinstance(legacy, WorktreeManager):
            return legacy
        raise ValueError("Orquestração sem pasta de trabalho para operação git.")

    def _branches_ativas(self, b: OrchestrationBundle) -> set[str]:
        """Branches que ainda importam: cards não terminais referenciam por
        `branch`/`worktree` — um worktree fora daqui é candidato a órfão."""
        ativos: set[str] = set()
        for card in b.board_service.cards_of(b.board.id):
            if card.status in self._STATUS_INATIVOS:
                continue
            if card.branch:
                ativos.add(card.branch)
            if card.worktree:
                ativos.add(card.worktree)
        return ativos

    def list_worktrees(self, orchestration_id: str) -> list[dict[str, Any]]:
        """O que existe em disco para esta orquestração, com `orfao` marcado — sempre
        a lista completa (com o que **seria** removido), nunca só os órfãos: o
        operador precisa ver o que está ativo para confiar no que não está."""
        b = self._bundle(orchestration_id)
        ativos = self._branches_ativas(b)
        encontrados = self._workspace_for(b).list_worktrees()
        return [{**w, "orfao": w.get("branch", "") not in ativos} for w in encontrados]

    def prune_worktrees(
        self, orchestration_id: str, *, actor: str = "system"
    ) -> list[dict[str, Any]]:
        """Remove só os órfãos (`git worktree remove` + `prune`, nunca `rm -rf`) e
        devolve o que foi removido — o banco não é tocado."""
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            ativos = self._branches_ativas(b)
            workspace = self._workspace_for(b)
            todos = workspace.list_worktrees()
            orfaos = [w for w in todos if w.get("branch", "") not in ativos]
            workspace.prune([Path(w["path"]) for w in orfaos if w.get("path")])
            b.event_log.append(
                "WorktreesPruned",
                {"orchestration_id": orchestration_id, "actor": actor, "removidos": orfaos},
            )
            self._persist(b)
            return orfaos

    def update_execution_settings(
        self,
        orchestration_id: str,
        *,
        executor: str | None = None,
        effort: str | None = None,
        validation_command: str | None = None,
        actor: str = "system",
    ) -> Orchestration:
        """Atualiza uma execução ainda não iniciada, com evento auditável."""
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            if b.orchestration.status not in {"created", "blocked"}:
                raise ValueError(
                    "Configurações só podem mudar em orquestrações criadas ou bloqueadas."
                )
            next_executor = executor or b.orchestration.selected_executor
            next_effort = effort or b.orchestration.selected_effort
            if next_executor is not None and self._catalog is not None:
                self._validate_executor(next_executor, next_effort)
            before = {
                "executor": b.orchestration.selected_executor,
                "effort": b.orchestration.selected_effort,
                "validation_command": b.orchestration.validation_command,
            }
            if executor is not None:
                b.orchestration.selected_executor = executor
            if effort is not None:
                b.orchestration.selected_effort = effort
            if validation_command is not None:
                b.orchestration.validation_command = validate_gate_command(validation_command)
            b.orchestration.updated_at = now_iso()
            after = {
                "executor": b.orchestration.selected_executor,
                "effort": b.orchestration.selected_effort,
                "validation_command": b.orchestration.validation_command,
            }
            b.event_log.append(
                "ExecutionSettingsUpdated",
                {
                    "orchestration_id": orchestration_id,
                    "actor": actor,
                    "before": before,
                    "after": after,
                },
            )
            self._persist(b)
            return b.orchestration

    def get_validation_checks(self, orchestration_id: str) -> list[ValidationCheck]:
        """A bateria efetiva (§12, ADR-0022) — bateria configurada, ou o
        `validation_command` legado convertido numa única verificação "testes"."""
        b = self._bundle(orchestration_id)
        return checks_efetivos(b.orchestration)

    def set_validation_checks(
        self, orchestration_id: str, checks: list[ValidationCheck], *, actor: str = "system"
    ) -> Orchestration:
        """Substitui a bateria de validações (§12). Ação de operador (`PUT`) —
        cada comando passa por `validate_gate_command`, exatamente como o
        `validation_command` legado: um `npm run dev` no meio da lista travaria o
        gate para sempre, tanto quanto travaria sozinho."""
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            validados = [
                check.model_copy(update={"comando": validate_gate_command(check.comando)})
                for check in checks
            ]
            antes = [c.model_dump(mode="json") for c in b.orchestration.validation_checks]
            b.orchestration.validation_checks = validados
            b.orchestration.updated_at = now_iso()
            b.event_log.append(
                "ValidationChecksUpdated",
                {
                    "orchestration_id": orchestration_id,
                    "actor": actor,
                    "before": antes,
                    "after": [c.model_dump(mode="json") for c in validados],
                },
            )
            self._persist(b)
            return b.orchestration

    def suggest_validation_checks(self, orchestration_id: str) -> list[ValidationCheck]:
        """Sugestão determinística por stack (§4.5) — não grava nada. Sem
        `target_path`, não há workspace para inspecionar: lista vazia, não erro."""
        b = self._bundle(orchestration_id)
        if not b.orchestration.target_path:
            return []
        return sugerir_bateria(b.orchestration.target_path)

    # -------------------------------------------- orçamento com freio (§1.2/§3.2)
    def set_orcamento(
        self, orchestration_id: str, teto_usd: float | None, *, actor: str = "system"
    ) -> Orchestration:
        """Eleva (ou remove) o teto de gasto (ADR-0026). `None`/`<= 0` volta ao
        comportamento sem teto. Ação crítica (`admin`, ver `api/auth.py`): autorizar
        mais gasto é decisão humana, mesmo espírito da regra 4 do CLAUDE.md."""
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            antes = b.orchestration.orcamento_usd
            b.orchestration.orcamento_usd = teto_usd if teto_usd and teto_usd > 0 else None
            b.orchestration.updated_at = now_iso()
            b.event_log.append(
                "OrcamentoAtualizado",
                {
                    "orchestration_id": orchestration_id,
                    "actor": actor,
                    "antes": antes,
                    "depois": b.orchestration.orcamento_usd,
                },
            )
            self._persist(b)
            return b.orchestration

    @staticmethod
    def _validate_assignment_key(orchestration: Orchestration, key: str) -> str:
        """Valida a chave da etapa e o momento em que ela ainda pode ser configurada.

        `naming`, `triagem`, `revisao`, `discovery` e `especificacao` são sempre
        editáveis (não são fases da esteira). Uma fase só aceita troca de agente
        enquanto não ficou para trás: reconfigurar F2 com a orquestração já em F5
        daria a falsa impressão de que o trabalho seria refeito com o novo agente.
        """
        if key in (NAMING_KEY, TRIAGE_KEY, REVIEW_KEY, DISCOVERY_KEY, SPEC_KEY, PLANNING_KEY):
            return key
        try:
            fase = Phase(key)
        except ValueError:
            raise ValueError(
                f"Etapa inválida: '{key}'. Use F1..F7, '{NAMING_KEY}', '{TRIAGE_KEY}', "
                f"'{REVIEW_KEY}', '{DISCOVERY_KEY}', '{SPEC_KEY}' ou '{PLANNING_KEY}'."
            ) from None
        ordem = list(Phase)
        if ordem.index(fase) < ordem.index(orchestration.current_phase):
            raise ValueError(
                f"A fase {fase.value} já passou (esteira em "
                f"{orchestration.current_phase.value}): a escolha não teria efeito."
            )
        return fase.value

    def set_agent_assignment(
        self,
        orchestration_id: str,
        key: str,
        *,
        executor: str,
        effort: str | None = None,
        actor: str = "system",
    ) -> Orchestration:
        """Define o executor de uma etapa (F1..F7) ou do nomeador. Ação auditável."""
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            if b.orchestration.status == "cancelled":
                raise ValueError("Orquestração cancelada: configuração bloqueada.")
            chave = self._validate_assignment_key(b.orchestration, key)
            if self._catalog is not None:
                perfil = self._validate_executor(executor, effort)
                if chave == PLANNING_KEY and perfil.kind != "llm":
                    raise ValueError(
                        f"O planejamento usa um executor LLM; '{executor}' é do tipo {perfil.kind}."
                    )
            antes = b.orchestration.agent_assignments.get(chave)
            b.orchestration.agent_assignments[chave] = AgentAssignment(
                executor=executor, effort=effort
            )
            b.orchestration.updated_at = now_iso()
            b.event_log.append(
                "AgentAssignmentUpdated",
                {
                    "orchestration_id": orchestration_id,
                    "actor": actor,
                    "key": chave,
                    "before": antes.model_dump() if antes else None,
                    "after": {"executor": executor, "effort": effort},
                },
            )
            self._persist(b)
            return b.orchestration

    def clear_agent_assignment(
        self, orchestration_id: str, key: str, *, actor: str = "system"
    ) -> Orchestration:
        """Remove o executor da etapa: ela volta a herdar o padrão da orquestração."""
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            chave = self._validate_assignment_key(b.orchestration, key)
            antes = b.orchestration.agent_assignments.pop(chave, None)
            if antes is None:
                return b.orchestration  # já era o padrão: nada a auditar
            b.orchestration.updated_at = now_iso()
            b.event_log.append(
                "AgentAssignmentUpdated",
                {
                    "orchestration_id": orchestration_id,
                    "actor": actor,
                    "key": chave,
                    "before": antes.model_dump(),
                    "after": None,
                },
            )
            self._persist(b)
            return b.orchestration

    def increase_card_effort(
        self, orchestration_id: str, card_id: str, *, actor: str = "system"
    ) -> KanbanCard:
        """Aumentar effort (Tela 15/17, wf §17.2/§19.2) — reaproveita `proximo_effort`
        (mesma função pura do roteamento automático de falha, ADR-0019), acionada
        aqui manualmente pelo operador."""
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            card = b.board_service.get_card(card_id)
            if card is None:
                raise KeyError(f"Card inexistente: {card_id}")
            executor_atual = card.executor_override or self._effective_executor(
                b, None, phase=card.phase
            )
            perfil = self._catalog.get(executor_atual) if self._catalog and executor_atual else None
            suportados = (
                list(perfil.supported_efforts)
                if perfil and perfil.supported_efforts
                else ["low", "medium", "high"]
            )
            atual = (
                card.effort_override
                or self._effective_effort(b, executor_atual, None, phase=card.phase)
                or "low"
            )
            novo = proximo_effort(atual, suportados)
            if novo is None:
                raise ValueError(f"Effort já está no topo ({atual}) — não há próximo degrau.")
            card.effort_override = novo
            card.updated_at = now_iso()
            b.event_log.append(
                "CardEffortIncreased",
                {
                    "orchestration_id": orchestration_id,
                    "actor": actor,
                    "card_id": card_id,
                    "de": atual,
                    "para": novo,
                },
            )
            self._persist(b)
            return card

    def transfer_card_model(
        self, orchestration_id: str, card_id: str, *, actor: str = "system"
    ) -> KanbanCard:
        """Trocar modelo (Tela 15/17, wf §17.2/§19.2) — reaproveita `proximo_executor`
        (mesma função pura do roteamento automático de falha, ADR-0019)."""
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            card = b.board_service.get_card(card_id)
            if card is None:
                raise KeyError(f"Card inexistente: {card_id}")
            if self._catalog is None:
                raise ValueError("Nenhum catálogo de executores configurado.")
            atual = (
                card.executor_override or self._effective_executor(b, None, phase=card.phase) or ""
            )
            novo = proximo_executor(atual, self._catalog)
            if novo is None:
                raise ValueError(
                    f"Nenhum outro executor disponível para trocar (atual: {atual!r})."
                )
            card.executor_override = novo
            card.updated_at = now_iso()
            b.event_log.append(
                "CardModelTransferred",
                {
                    "orchestration_id": orchestration_id,
                    "actor": actor,
                    "card_id": card_id,
                    "de": atual,
                    "para": novo,
                },
            )
            self._persist(b)
            return card

    def _executor_availability(self, name: str | None) -> tuple[bool | None, str]:
        """Disponibilidade do executor escolhido (None = catálogo não configurado)."""
        if self._catalog is None or not name:
            return None, ""
        entry = next((e for e in self._catalog.entries() if e.get("name") == name), None)
        if entry is None:
            return False, f"Executor '{name}' não está mais no catálogo."
        if entry.get("available"):
            return True, str(entry.get("runtime_version") or "")
        return False, str(entry.get("availability_reason") or "Executor indisponível.")
