"""`WorkflowService` — fases, quality gate, autopilot e plano (ADR-0066).

MEL-32, passo 7: o **único lugar que muda fase** (regra inviolável 3, ADR-0060) — gate por
fase, `SKIPPED`, avanço governado, autopilot, `run_plan`, retry e roteamento manual.
"""

from __future__ import annotations

import os
import shlex
import threading
from collections.abc import Callable
from typing import Any

from aso.application.agent_task import AgentTaskService
from aso.application.bundles import BundleStore, OrchestrationBundle
from aso.application.execution import ExecutionService
from aso.application.ondas import CoordenadorDeOndas, limite_da_estrategia
from aso.control.deploy import ACEITE_APROVADO, pipeline_aprovado
from aso.control.discovery import STATUS_APROVADO
from aso.control.documentos import versao_atual
from aso.control.models import (
    Environment,
    Orchestration,
    ValidationCheck,
)
from aso.control.spec import STATUS_APROVADOS as SPEC_STATUS_APROVADOS
from aso.control.spec import SpecDocument
from aso.control.validation import NOME_CHECK_LEGADO, checks_efetivos
from aso.execution.catalog import ExecutorCatalog
from aso.execution.docs_drift import DocsDriftReport, check_drift
from aso.execution.gate_command import run_gate_command
from aso.execution.workspace import WorkspaceError
from aso.governance.contextbus import BusResult
from aso.governance.gate_definitions import (
    CardNoGate,
    EstadoDoGate,
    VerificacaoDaBateria,
    criterios_da_fase,
)
from aso.governance.models import HumanApproval, QualityGateResult
from aso.governance.snapshot_engine import secoes_congeladas
from aso.shared.types import CardType, ColumnKey, ExecutionMode, GateStatus, PatchStatus, Phase


def _drift_summary(rep: DocsDriftReport) -> str:
    """Resumo textual (pt-BR) do drift de docs para evidência do gate/UI."""
    partes: list[str] = []
    if rep.undocumented_modules:
        partes.append("módulos sem doc: " + ", ".join(rep.undocumented_modules))
    if rep.orphan_module_docs:
        partes.append("docs órfãs: " + ", ".join(rep.orphan_module_docs))
    if rep.broken_links:
        partes.append(f"{len(rep.broken_links)} link(s) quebrado(s)")
    if rep.unfilled_features:
        partes.append(f"{len(rep.unfilled_features)} doc(s) por preencher")
    return "; ".join(partes)


def _verificacao_de_comando(comando: str, repo: str) -> Callable[[], tuple[bool, str]]:
    """Fábrica de uma verificação da bateria para `gate_definitions` (ADR-0060).

    Fecha `comando`/`repo` por parâmetro da fábrica, não por variável de laço: evita a
    armadilha clássica de closure em `for` (§4.2/§5 do plano5.md)."""

    def verificar() -> tuple[bool, str]:
        return run_gate_command(shlex.split(comando), repo)

    return verificar


def _verificacao_de_docs(root: str) -> Callable[[], tuple[bool, str]]:
    def verificar() -> tuple[bool, str]:
        return _docs_sync_check(root)

    return verificar


def _docs_sync_check(root: str) -> tuple[bool, str]:
    """Predicado (não-bloqueante) do gate F5/F6: docs-first em sincronia com o código?"""
    try:
        rep = check_drift(root)
    except ValueError:
        return True, "sem pasta para checar docs"
    if not rep.has_docs:
        return True, "docs-first ainda não gerada"
    if not rep.has_drift:
        return True, "docs em sincronia com o código"
    return False, "drift de docs — " + _drift_summary(rep)


class WorkflowService:
    """Esteira de fases: único lugar que roda gate, pula e avança fase, e conduz o autopilot."""

    def __init__(
        self,
        store: BundleStore,
        *,
        execution: ExecutionService,
        agent_task: AgentTaskService,
        log: Any,
        max_escalonamentos: int,
        catalogo: Callable[[], ExecutorCatalog | None],
        assignment: Callable[..., Any],
        effective_effort: Callable[..., str | None],
        effective_executor: Callable[..., str | None],
        provider_for: Callable[..., Any],
        analyze_folder: Callable[..., dict[str, object]],
        heal_docs: Callable[..., dict[str, object]],
    ) -> None:
        self._bundle_store = store
        self._execution = execution
        self._agent_task = agent_task
        self._log = log
        self._max_escalonamentos = max_escalonamentos
        self._catalogo = catalogo
        self._assignment_de = assignment
        self._effort_de = effective_effort
        self._executor_de = effective_executor
        self._provider_de = provider_for
        self._analyze_folder = analyze_folder
        self._heal_docs = heal_docs
        # Único caminho de execução em lote (ADR-0074), usado por `run_phase` e `run_plan`.
        self._ondas = CoordenadorDeOndas(store, run_card=execution.run_card)
        # Execução assíncrona (ADR-0067): quando a API liga a fila, a próxima fase aprovada é
        # enfileirada em vez de rodar dentro da requisição de aprovação.
        self._agendar_fase: Callable[[str, Phase, str | None, str | None], str] | None = None

    def definir_agendador_de_fase(
        self, agendar: Callable[[str, Phase, str | None, str | None], str] | None
    ) -> None:
        """`agendar(orchestration_id, fase, executor, effort) -> job_id`; `None` desliga."""
        self._agendar_fase = agendar

    @property
    def _catalog(self) -> ExecutorCatalog | None:
        return self._catalogo()

    def _bundle(self, orchestration_id: str) -> OrchestrationBundle:
        return self._bundle_store.get(orchestration_id)

    def _persist(self, b: OrchestrationBundle) -> None:
        self._bundle_store.persist(b)

    def _lock_for(self, orchestration_id: str) -> threading.RLock:
        return self._bundle_store.lock_for(orchestration_id)

    def _assignment(self, *args: Any, **kwargs: Any) -> Any:
        return self._assignment_de(*args, **kwargs)

    def _effective_effort(self, *args: Any, **kwargs: Any) -> str | None:
        return self._effort_de(*args, **kwargs)

    def _effective_executor(self, *args: Any, **kwargs: Any) -> str | None:
        return self._executor_de(*args, **kwargs)

    def _provider_for(self, *args: Any, **kwargs: Any) -> Any:
        return self._provider_de(*args, **kwargs)

    def analyze_folder(self, *args: Any, **kwargs: Any) -> dict[str, object]:
        return self._analyze_folder(*args, **kwargs)

    def heal_docs(self, *args: Any, **kwargs: Any) -> dict[str, object]:
        return self._heal_docs(*args, **kwargs)

    def run_card(self, *args: Any, **kwargs: Any) -> list[BusResult]:
        return self._execution.run_card(*args, **kwargs)

    def _apply_execution(self, *args: Any, **kwargs: Any) -> Any:
        return self._execution._apply_execution(*args, **kwargs)

    def _execute_wave(self, *args: Any, **kwargs: Any) -> Any:
        return self._execution._execute_wave(*args, **kwargs)

    def _liberar_claim(self, *args: Any, **kwargs: Any) -> Any:
        return self._execution._liberar_claim(*args, **kwargs)

    def _recusar_se_estrategia_pendente(self, *args: Any, **kwargs: Any) -> Any:
        return self._execution._recusar_se_estrategia_pendente(*args, **kwargs)

    def _recusar_se_orcamento_estourado(self, *args: Any, **kwargs: Any) -> Any:
        return self._execution._recusar_se_orcamento_estourado(*args, **kwargs)

    def _reivindicar_card(self, *args: Any, **kwargs: Any) -> Any:
        return self._execution._reivindicar_card(*args, **kwargs)

    def _build_task(self, *args: Any, **kwargs: Any) -> Any:
        return self._agent_task._build_task(*args, **kwargs)

    def _registrar_decisao_no_run(self, *args: Any, **kwargs: Any) -> Any:
        return self._agent_task._registrar_decisao_no_run(*args, **kwargs)

    def _advance_after_phase_gate(
        self,
        orchestration_id: str,
        completed_phase: str,
        *,
        executor: str | None = None,
        effort: str | None = None,
        agendar: bool = False,
    ) -> dict[str, object] | None:
        """Auto-avanço do autopilot: fase aprovada → próxima fase roda sozinha (M4).

        Não recursa: `run_phase` da próxima fase abre uma NOVA aprovação pendente e
        para ali, aguardando o humano (pausa só na aprovação, como pedido).
        """
        try:
            nxt = self._next_phase(Phase(completed_phase))
        except ValueError:
            return None
        if nxt is None:
            # Última fase aprovada → esteira concluída.
            with self._lock_for(orchestration_id):
                b = self._bundle(orchestration_id)
                b.orchestration.status = "completed"
                b.event_log.append("AutopilotCompleted", {"phase": completed_phase})
                self._persist(b)
            self._log.info(
                "autopilot_completed", orchestration_id=orchestration_id, phase=completed_phase
            )
            return None
        try:
            # Mesmo caminho governado do avanço manual: se um gate reprovado foi rodado
            # depois da abertura da aprovação, o avanço é recusado (evento
            # PhaseAdvanceRefused na timeline) e o autopilot para — a decisão humana já
            # persistida continua válida, só não arrasta a fase com gate reprovado.
            self.advance_phase(orchestration_id)
        except ValueError as exc:
            self._log.warning(
                "autopilot_advance_refused", orchestration_id=orchestration_id, reason=str(exc)
            )
            return None
        self._log.info("autopilot_advanced", orchestration_id=orchestration_id, to=nxt.value)
        # A escolha herdada da fase anterior só vale se a próxima etapa não tiver
        # executor próprio (ADR-0014) — senão a configuração por etapa nunca valeria
        # no autopilot, que é justamente onde ela mais importa.
        if self._assignment(self._bundle(orchestration_id), nxt.value) is not None:
            executor, effort = None, None
        # Só a aprovação humana agenda (a requisição de aprovação não pode esperar a fase);
        # pular fases vazias continua no mesmo job que já está rodando.
        if agendar and self._agendar_fase is not None:
            job_id = self._agendar_fase(orchestration_id, nxt, executor, effort)
            with self._lock_for(orchestration_id):
                b = self._bundle(orchestration_id)
                b.event_log.append("PhaseScheduled", {"phase": nxt.value, "job_id": job_id})
                self._persist(b)
            return {"phase": nxt.value, "agendada": True, "job_id": job_id}
        return self.run_phase(
            orchestration_id, nxt, executor=executor, effort=effort, autopilot=True
        )

    def start_autopilot(
        self,
        orchestration_id: str,
        *,
        executor: str | None = None,
        effort: str | None = None,
        inicializar_git: bool = False,
    ) -> dict[str, object]:
        """Dá partida no autopilot: roda a fase atual e abre a 1ª aprovação de avanço.

        `executor`/`effort` escolhem o agente e o esforço; a escolha se propaga a cada
        fase automaticamente via a aprovação (todo o pipeline usa o mesmo, salvo troca).
        """
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            # Antes de qualquer efeito (status running, analyze_folder com agente).
            self._recusar_se_estrategia_pendente(b)
            effective_executor = executor or b.orchestration.selected_executor
            effective_effort = effort or b.orchestration.selected_effort
            b.orchestration.selected_executor = effective_executor
            b.orchestration.selected_effort = effective_effort
            if not b.orchestration.workspace_prepared and b.orchestration.target_path:
                self.analyze_folder(
                    orchestration_id,
                    executor=effective_executor,
                    effort=effective_effort,
                    inicializar_git=inicializar_git,
                )
                b = self._bundle(orchestration_id)
                b.orchestration.workspace_prepared = True
            if b.orchestration.execution_mode == ExecutionMode.CODE_EXECUTION and not (
                b.orchestration.validation_command or os.environ.get("ASO_GATE_TEST_COMMAND")
            ):
                raise ValueError("Configure o comando de validação antes de executar código.")
            b.orchestration.status = "running"
            b.event_log.append("AutopilotStarted", {"phase": b.orchestration.current_phase.value})
            self._persist(b)
        return self.run_phase(
            orchestration_id,
            executor=effective_executor,
            effort=effective_effort,
            autopilot=True,
        )

    def run_plan(self, orchestration_id: str, *, concurrent: bool = True) -> dict[str, object]:
        """Executa os cards `Ready` (com responsável e não pausados) pelo coordenador de ondas.

        ADR-0074: deixou de ter laço próprio — é o mesmo caminho do `run_phase` (onda = cards
        cujas dependências estão `Done`, cada card via `run_card`), só que sobre o board inteiro.
        `concurrent=False` força um card por vez.
        """
        b = self._bundle(orchestration_id)
        # Mesmos freios de `run_card` (DISCOVERED-01): kill-switch e orçamento.
        if b.orchestration.status == "cancelled":  # kill-switch (M6)
            raise ValueError("Orquestração cancelada: execução bloqueada.")
        self._recusar_se_estrategia_pendente(b)
        self._recusar_se_orcamento_estourado(b)
        candidatos = [
            c.id
            for c in b.board_service.cards_of(b.board.id)
            if c.status == ColumnKey.READY and not c.pausado and c.assignee
        ]
        limite = limite_da_estrategia(b.plan.strategy) if concurrent else 1
        ondas = self._ondas.executar(orchestration_id, candidatos, limite=limite)
        executados = [*ondas.executados, *ondas.falhos]
        return {
            "strategy": b.plan.strategy.value,
            "executed": executados,
            "count": len(executados),
            "waves": ondas.ondas,
            "concurrent": concurrent,
            "paralelismo": ondas.paralelismo,
            "aguardando_dependencia": ondas.aguardando_dependencia,
        }

    def run_quality_gate(
        self, orchestration_id: str, phase: Phase | None = None
    ) -> QualityGateResult:
        """Roda o quality gate da fase e, se aprovado, gera snapshot (ADR-0060).

        Os critérios vêm de `governance/gate_definitions.py` — aqui só se monta o retrato
        (`EstadoDoGate`) da orquestração. `SKIPPED` (nada bloqueante a verificar) não gera
        snapshot.
        """
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            target_phase = phase or b.orchestration.current_phase
            cards_da_fase = [
                CardNoGate(id=c.id, titulo=c.title, status=c.status, tem_branch=bool(c.branch))
                for c in b.board_service.cards_of(b.board.id)
                if c.phase == target_phase
            ]
            discovery_status: str | None = None
            if target_phase == Phase.F1 and b.orchestration.discovery_reports:
                discovery_status = str(b.orchestration.discovery_reports[-1].get("status", ""))
            deploy: tuple[bool, str] | None = None
            # Implantação (§18-22, ADR-0023): só entra quando uma tentativa de implantação
            # de fato existe; com pipeline (§19, ADR-0029) exige TODOS os estágios.
            if target_phase == Phase.F6 and b.orchestration.deploy_runs:
                if b.orchestration.deploy_pipeline:
                    pipeline_atual = [Environment(**e) for e in b.orchestration.deploy_pipeline]
                    deploy_ok = pipeline_aprovado(pipeline_atual, b.orchestration.deploy_runs)
                    deploy = (
                        deploy_ok,
                        "pipeline completo" if deploy_ok else "pipeline incompleto",
                    )
                else:
                    aceite = str(b.orchestration.deploy_runs[-1].get("aceite_status", ""))
                    deploy = (aceite == ACEITE_APROVADO, aceite)
            # Bateria nomeada do §12 (ADR-0022) nas fases de código; sem bateria, o
            # `validation_command` legado (ou `ASO_GATE_TEST_COMMAND`) vira "testes".
            repo = b.orchestration.target_path or os.environ.get("ASO_TARGET_REPO")
            checks = checks_efetivos(b.orchestration)
            if not checks:
                gate_cmd_legado = os.environ.get("ASO_GATE_TEST_COMMAND")
                if gate_cmd_legado:
                    checks = [ValidationCheck(nome=NOME_CHECK_LEGADO, comando=gate_cmd_legado)]
            codigo = target_phase in (Phase.F5, Phase.F6)
            bateria = (
                [
                    VerificacaoDaBateria(
                        nome=check.nome,
                        executar=_verificacao_de_comando(check.comando, repo),
                        bloqueante=check.bloqueante,
                    )
                    for check in checks
                ]
                if checks and repo and codigo
                else []
            )
            estado = EstadoDoGate(
                fase=target_phase,
                cards=cards_da_fase,
                fases_com_patch_aplicado=frozenset(
                    p.phase for p in b.bus.patches if p.status == PatchStatus.APPLIED
                ),
                discovery_status=discovery_status,
                discovery_aprovado=discovery_status == STATUS_APROVADO,
                deploy=deploy,
                validacao_configurada=bool(
                    b.orchestration.validation_checks or b.orchestration.validation_command
                ),
                bateria=bateria,
                # Drift de docs (não bloqueante, §ai-docs-self-healing) nas fases de código.
                docs_sync=_verificacao_de_docs(repo) if repo and codigo else None,
            )
            criteria = criterios_da_fase(estado)
            b.gate_engine.register(target_phase, criteria)
            result = b.gate_engine.run(target_phase, orchestration_id, b.store.get())
            if result.status == GateStatus.PASSED:
                version = f"O{target_phase.value[-1]}"
                snapshot = b.snapshot_engine.create(
                    b.store,
                    snapshot_version=version,
                    phase=target_phase,
                    frozen_sections=secoes_congeladas(target_phase),
                    gate_result=result,
                    adrs=[a.id for a in b.adr_registry.list_all()],
                )
                # Recriar o snapshot da mesma fase SUBSTITUI o anterior (ADR-0061): a lista
                # duplicava a versão a cada gate aprovado (`['O5', 'O5']`).
                b.snapshots[:] = [s for s in b.snapshots if s.snapshot_version != version]
                b.snapshots.append(snapshot)
                b.orchestration.snapshot_version = version
            b.gate_results.append(result)
            self._persist(b)
            return result

    def _maybe_autoheal_docs(
        self,
        orchestration_id: str,
        phase: Phase,
        executor: str | None,
        effort: str | None,
    ) -> dict[str, object] | None:
        """Ao fim de F5/F6, sincroniza docs-first automaticamente quando há drift.

        Best-effort: nunca derruba a fase/autopilot. Só roda quando há pasta, docs
        geradas e drift real. Pode ser desligado com `ASO_AUTOHEAL_DOCS=0`.
        """
        if os.environ.get("ASO_AUTOHEAL_DOCS", "1") == "0":
            return None
        if phase not in (Phase.F5, Phase.F6):
            return None
        tp = self._bundle(orchestration_id).orchestration.target_path
        if not tp:
            return None
        try:
            drift = check_drift(tp)
        except ValueError:
            return None
        if not (drift.has_docs and drift.has_drift):
            return None
        b = self._bundle(orchestration_id)
        if any(
            pr.status == "open"
            and (card := b.board_service.get_card(pr.card_id or "")) is not None
            and card.type == CardType.DOCUMENTATION
            for pr in b.pull_requests
        ):
            # Já há entrega de docs aguardando merge: não empilha outra PR a cada fase.
            return None
        try:
            result = self.heal_docs(orchestration_id, executor=executor, effort=effort)
        except (WorkspaceError, ValueError) as exc:  # não derruba a esteira
            self._log.warning(
                "autoheal_docs_failed", orchestration_id=orchestration_id, error=str(exc)
            )
            return None
        self._log.info("autoheal_docs", orchestration_id=orchestration_id, mode=result.get("mode"))
        return result

    # ------------------------------------------------------------- autopilot (M3)
    def run_phase(
        self,
        orchestration_id: str,
        phase: Phase | None = None,
        *,
        executor: str | None = None,
        effort: str | None = None,
        autopilot: bool = False,
    ) -> dict[str, object]:
        """Executa uma fase ponta a ponta: roda os cards Ready da fase, roda o gate,
        gera snapshot (se aprovado) e abre uma aprovação humana de avanço de fase (§8.6).

        `executor`/`effort` escolhem o agente e o esforço desta etapa; a escolha é
        guardada na aprovação para o auto-avanço (M4) manter a mesma configuração.

        Gate `SKIPPED` (ADR-0060): sem snapshot e sem aprovação humana de fase vazia —
        registra `PhaseSkipped`; no `autopilot`, avança e roda a próxima fase direto.
        """
        # Resolve o provider da **etapa** (ADR-0014), já atrelado à pasta (workspace).
        b0 = self._bundle(orchestration_id)
        self._recusar_se_estrategia_pendente(b0)
        target = phase or b0.orchestration.current_phase
        effective_executor = self._effective_executor(b0, executor, phase=target)
        effort = self._effective_effort(b0, effective_executor, effort, phase=target)
        provider = self._provider_for(b0, effective_executor, effort, phase=target)
        # Sem esforço explícito, herda o esforço do perfil do executor efetivo
        # (o escolhido ou, quando há pasta, o default do catálogo).
        if effort is None and self._catalog is not None:
            name_for_effort = effective_executor or (
                self._catalog.default_name() if b0.orchestration.target_path else None
            )
            if name_for_effort:
                prof = self._catalog.get(name_for_effort)
                if prof is not None and prof.effort:
                    effort = prof.effort
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            if b.orchestration.status == "cancelled":  # kill-switch (M6)
                raise ValueError("Orquestração cancelada: execução bloqueada.")
            # F5 não começa sem especificação aprovada em full-pipeline (§5/§6, ADR-0021)
            # — só quando o fluxo de discovery foi de fato usado (mesma regra de
            # não-regressão do critério de gate da ADR-0020 §6): orquestrações que
            # nunca chamam /discovery/run (a maioria da suíte pré-existente, e todo
            # CODE_EXECUTION) não mudam de comportamento em F5.
            exige_spec = (
                target == Phase.F5
                and b.orchestration.execution_mode == ExecutionMode.FULL_PIPELINE
                and bool(b.orchestration.discovery_reports)
            )
            if exige_spec:
                spec_atual = versao_atual(b.orchestration.spec_documents, SpecDocument)
                if spec_atual.status not in SPEC_STATUS_APROVADOS:
                    raise ValueError(
                        "F5 não começa sem especificação aprovada (§5/§6 do fluxo.md) — "
                        f"status atual: '{spec_atual.status or 'nunca gerada'}'."
                    )
            card_ids = [
                c.id
                for c in b.board_service.cards_of(b.board.id)
                if c.phase == target and c.status == ColumnKey.READY
            ]

        # Ondas (ADR-0074): cards independentes em paralelo até o limite da estratégia;
        # dependência pendente não entra na onda.
        ondas = self._ondas.executar(
            orchestration_id,
            card_ids,
            limite=limite_da_estrategia(b.plan.strategy),
            provider=provider,
            effort=effort,
        )
        ran, failed = ondas.executados, ondas.falhos
        if ondas.aguardando_dependencia:
            with self._lock_for(orchestration_id):
                b = self._bundle(orchestration_id)
                b.event_log.append(
                    "CardsAguardandoDependencia",
                    {"phase": target.value, "cards": list(ondas.aguardando_dependencia)},
                )
                self._persist(b)

        if self._bundle(orchestration_id).orchestration.validation_command and target in (
            Phase.F5,
            Phase.F6,
        ):
            phase_cards = [
                c
                for c in self._bundle(orchestration_id).board_service.cards_of(b.board.id)
                if c.phase == target
            ]
            if any(c.status != ColumnKey.DONE for c in phase_cards):
                with self._lock_for(orchestration_id):
                    self._bundle(orchestration_id).event_log.append(
                        "PhaseAwaitingDelivery", {"phase": target.value, "cards_failed": failed}
                    )
                    self._persist(self._bundle(orchestration_id))
                return {
                    "phase": target.value,
                    "cards_ran": ran,
                    "cards_failed": failed,
                    "gate_status": "WAITING_DELIVERY",
                    "snapshot": None,
                    "approval_id": None,
                    "next_phase": target.value,
                }

        gate = self.run_quality_gate(orchestration_id, target)
        # Self-heal automático da documentação docs-first ao fim de F5/F6 (§ADR-0012).
        autoheal = self._maybe_autoheal_docs(orchestration_id, target, effective_executor, effort)
        approval_id: str | None = None
        snapshot: str | None = None
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            if gate.status == GateStatus.PASSED:
                snapshot = b.orchestration.snapshot_version
                approval = HumanApproval(
                    orchestration_id=orchestration_id,
                    action=f"Aprovar avanço da fase {target.value}",
                    tipo="fase_gate",
                    risk="medium",
                    reason=f"Fase {target.value} concluída (gate PASSED): "
                    f"{len(ran)} cards executados.",
                    payload={
                        "kind": "phase_gate",
                        "phase": target.value,
                        "executor": executor,
                        "effort": effort,
                    },
                )
                b.approvals.append(approval)
                approval_id = approval.id
            elif gate.status == GateStatus.SKIPPED:
                b.event_log.append(
                    "PhaseSkipped",
                    {"phase": target.value, "reason": "nenhum critério bloqueante aplicável"},
                )
            b.event_log.append(
                "PhaseCompleted",
                {"phase": target.value, "cards": len(ran), "gate": gate.status.value},
            )
            self._persist(b)
            nxt = self._next_phase(target)
        self._log.info(
            "phase_completed",
            orchestration_id=orchestration_id,
            phase=target.value,
            gate=gate.status.value,
            cards_ran=len(ran),
            cards_failed=len(failed),
        )
        resultado: dict[str, object] = {
            "phase": target.value,
            "cards_ran": ran,
            "cards_failed": failed,
            "gate_status": gate.status.value,
            "snapshot": snapshot,
            "approval_id": approval_id,
            "next_phase": nxt.value if nxt else None,
            "docs_autoheal": autoheal,
        }
        if autopilot and gate.status == GateStatus.SKIPPED:
            seguinte = self._advance_after_phase_gate(
                orchestration_id, target.value, executor=executor, effort=effort
            )
            if seguinte is not None:
                # Devolve onde o autopilot parou, com o rastro das fases puladas.
                puladas = seguinte.get("fases_puladas")
                seguinte["fases_puladas"] = [
                    target.value,
                    *(puladas if isinstance(puladas, list) else []),
                ]
                return seguinte
            resultado["fases_puladas"] = [target.value]
        return resultado

    @staticmethod
    def _next_phase(phase: Phase) -> Phase | None:
        order = list(Phase)
        idx = order.index(phase)
        return order[idx + 1] if idx + 1 < len(order) else None

    def advance_phase(self, orchestration_id: str) -> Orchestration:
        """Avança a orquestração para a próxima fase (F1→…→F7). Ação governada.

        Regra inviolável 3: só avança quando o ÚLTIMO gate da fase atual está `PASSED`.
        Um PASSED antigo seguido de FAILED não vale — o estado mais recente é o que conta.
        A verificação fica dentro do lock (check-then-act) para que um gate reprovado
        rodado em paralelo não escape entre a checagem e a mudança de fase.
        """
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            atual = b.orchestration.current_phase
            nxt = self._next_phase(atual)
            if nxt is None:
                raise ValueError("Já está na última fase (F7); não há próxima.")
            ultimo_gate = next((g for g in reversed(b.gate_results) if g.phase == atual), None)
            # SKIPPED (fase sem nada bloqueante a verificar, ADR-0060) libera como PASSED.
            liberados = (GateStatus.PASSED, GateStatus.SKIPPED)
            if ultimo_gate is None or ultimo_gate.status not in liberados:
                motivo = (
                    f"gate de {atual.value} nunca executado"
                    if ultimo_gate is None
                    else f"gate de {atual.value} não aprovado: {ultimo_gate.status.value}"
                )
                b.event_log.append("PhaseAdvanceRefused", {"phase": atual.value, "reason": motivo})
                self._persist(b)
                raise ValueError(f"Avanço de fase recusado — {motivo}.")
            b.orchestration.current_phase = nxt
            b.event_log.append("PhaseAdvanced", {"to": nxt.value})
            self._persist(b)
            return b.orchestration
