"""`DocsFirstService` — análise docs-first do workspace e self-heal de docs (ADR-0066).

MEL-32, passo 11b: `analyze_folder`/`heal_docs` saem da façade. A entrega continua governada
(ADR-0062): card `Documentation` + PR pelo `DeliveryService`; commit direto só em repositório
recém-criado pelo ASO e sem histórico.
"""

from __future__ import annotations

import subprocess
import threading
import uuid
from pathlib import Path
from typing import Any

from aso.agents.contract import KIND_EXECUTE, TaskEnvelope
from aso.agents.executor import AgentExecutionError, ExecutionProvider, LocalMockExecutionProvider
from aso.application.bundles import BundleStore, OrchestrationBundle
from aso.application.delivery import DeliveryService
from aso.application.execution import ExecutionService
from aso.application.settings import ExecutionSettingsService
from aso.execution.docs_drift import DocsDriftReport, check_drift
from aso.execution.docs_scaffold import write_scaffold
from aso.execution.workspace import (
    WorkspaceAnalyzer,
    WorkspaceError,
    WorkspaceReport,
    WorkspaceService,
)
from aso.execution.worktree import WorktreeManager
from aso.governance.models import ContextPatch, PullRequest
from aso.kanban.models import KanbanCard
from aso.shared.ids import now_iso
from aso.shared.types import AssigneeType, CardType, ColumnKey, PatchType, Phase

# Como a documentação gerada chegou (ou não) à branch base (ADR-0062).
ENTREGA_COMMIT_DIRETO = "commit_direto"


ENTREGA_PR = "pr"


ENTREGA_SEM_ALTERACAO = "sem_alteracao"


def _scaffold_em_branch(
    root: Path, modulos: list[str], mensagem: str
) -> tuple[str | None, list[str]]:
    """Escreve o scaffold num worktree isolado e commita num branch próprio (ADR-0062).

    Devolve `(branch, criados)`; `branch` é `None` quando nada novo foi escrito (o branch
    vazio é descartado). O worktree é removido — só o branch fica, para a PR.
    """
    manager = WorktreeManager(str(root))
    nome = f"docs-first-{uuid.uuid4().hex[:8]}"
    caminho, branch = manager.create(nome, branch=f"docs/{nome}")
    try:
        criados = write_scaffold(caminho, modulos)
        if criados:
            manager.collect_diff(caminho)  # `git add -A` sob o lock de metadados git
            manager.commit(caminho, mensagem)
    finally:
        manager.remove(caminho)
    if not criados:
        subprocess.run(
            ["git", "branch", "-D", branch], cwd=str(root), capture_output=True, text=True
        )
        return None, []
    return branch, criados


class DocsFirstService:
    """Análise docs-first da pasta e self-heal de docs, entregues por card `Documentation` + PR."""

    def __init__(
        self,
        store: BundleStore,
        *,
        settings: ExecutionSettingsService,
        delivery: DeliveryService,
        log: Any,
    ) -> None:
        self._bundle_store = store
        self._settings = settings
        self._delivery = delivery
        self._log = log

    def _bundle(self, orchestration_id: str) -> OrchestrationBundle:
        return self._bundle_store.get(orchestration_id)

    def _persist(self, b: OrchestrationBundle) -> None:
        self._bundle_store.persist(b)

    def _lock_for(self, orchestration_id: str) -> threading.RLock:
        return self._bundle_store.lock_for(orchestration_id)

    def _provider_for(self, *args: Any, **kwargs: Any) -> ExecutionProvider | None:
        return self._settings._provider_for(*args, **kwargs)

    def open_pr(self, *args: Any, **kwargs: Any) -> PullRequest:
        return self._delivery.open_pr(*args, **kwargs)

    @staticmethod
    def _recusar_se_estrategia_pendente(b: OrchestrationBundle) -> None:
        ExecutionService._recusar_se_estrategia_pendente(b)

    # ---------------------------------------------------- workspace + docs-first
    def _docs_task(
        self, b: OrchestrationBundle, report: WorkspaceReport, *, effort: str | None = None
    ) -> dict[str, Any]:
        """Monta a tarefa (JSON via stdin) que instrui o agente a documentar docs-first."""
        acao = "atualizar (de forma localizada, sem recriar)" if report.has_aso_docs else "criar"
        modulos = ", ".join(report.detected_modules) or "(nenhum detectado)"
        instrucao = (
            "Documente este projeto no padrão docs-first (IA-first), em pt-BR. "
            f"Ação: {acao} a documentação em /docs. "
            "Estrutura obrigatória: docs/index.md (ponto de entrada que a IA lê antes do "
            "código) e docs/modules/<módulo>/<feature>.md. Cada feature deve conter as 8 "
            "seções: Descrição, Localização no código, Entrada, Saída, Dependências, "
            "Regras de negócio, Fluxo resumido, Possíveis erros. Leia o código para "
            "preencher com fatos reais, mantenha índices e links internos válidos e, se já "
            "houver documentação ASO, atualize sem recriar tudo. "
            f"Módulos detectados: {modulos}."
        )
        task: dict[str, Any] = {
            "orchestration_id": b.orchestration.id,
            "phase": Phase.F6.value,
            "target_path": "engineering.docs_first",
            "content": {"request": instrucao, "by": "DocumentationAgent"},
            "envelope": TaskEnvelope(
                kind=KIND_EXECUTE,
                task_type="docs",
                request=instrucao,
                effort=effort or "",
                phase=Phase.F6.value,
                target_path="engineering.docs_first",
            ).model_dump(),
        }
        if effort:
            task["effort"] = effort
        return task

    def analyze_folder(
        self,
        orchestration_id: str,
        *,
        executor: str | None = None,
        effort: str | None = None,
        inicializar_git: bool = False,
    ) -> dict[str, object]:
        """Analisa a pasta da orquestração e gera/atualiza a documentação docs-first.

        Entrega governada (ADR-0062, regras 5 e 6):
        - Pasta sem git só é inicializada com `inicializar_git=True` (evento registrado).
        - Pasta vazia num repo recém-criado pelo ASO → scaffold commitado direto (não há
          trabalho de ninguém na base) + rede de segurança.
        - Todo o resto → docs num branch isolado (agente real ou scaffold) e card
          `Documentation` com PR aberta; a base só muda no merge governado.
        - Registra evento + ContextPatch de resumo (rastreabilidade, sem aprovação —
          docs = baixo risco).
        """
        b = self._bundle(orchestration_id)
        self._recusar_se_estrategia_pendente(b)  # pode acionar agente real
        tp = b.orchestration.target_path
        if not tp:
            raise ValueError("Orquestração sem pasta de trabalho (workspace) definida.")
        ws = WorkspaceService()
        root = ws.validate(tp)
        git_initialized = self._garantir_git(b, root, ws, inicializar_git=inicializar_git)
        report = WorkspaceAnalyzer(ws).analyze(root)

        created: list[str] = []
        mode: str
        entrega = ENTREGA_SEM_ALTERACAO
        card_id: str | None = None
        pr_id: str | None = None
        # Commit direto na branch base só num repositório que o próprio ASO acabou de criar
        # para uma pasta vazia (ADR-0062): não há trabalho de ninguém a proteger.
        if report.is_empty and ws.sem_historico(root):
            mode = "scaffold"
            created = write_scaffold(root, report.detected_modules)
            if ws.commit_all(root, "aso: docs-first (scaffold)"):
                entrega = ENTREGA_COMMIT_DIRETO
        else:
            provider = self._provider_for(b, executor, effort)
            spec = b.agent_registry.get("DocumentationAgent")
            branch: str | None = None
            if (
                not report.is_empty
                and provider is not None
                and spec is not None
                and not isinstance(provider, LocalMockExecutionProvider)
            ):
                mode = "agent"
                task = self._docs_task(b, report, effort=effort)
                try:
                    output = provider.execute(spec, task)
                except AgentExecutionError as exc:
                    with self._lock_for(orchestration_id):
                        failed = self._bundle(orchestration_id)
                        failed.orchestration.workspace_prepared = False
                        failed.event_log.append(
                            "WorkspaceDocumentationFailed",
                            {
                                "orchestration_id": orchestration_id,
                                "executor": executor or failed.orchestration.selected_executor,
                                "reason": str(exc)[:500],
                            },
                        )
                        self._persist(failed)
                    raise WorkspaceError(f"Falha ao documentar com o agente: {exc}") from exc
                bruto = output.artifacts.get("branch")
                branch = str(bruto) if bruto else None
            else:
                mode = "scaffold"
                branch, created = _scaffold_em_branch(
                    root, report.detected_modules, "aso: docs-first (scaffold)"
                )
            if branch:
                card_id, pr_id = self._entregar_docs_por_pr(
                    orchestration_id,
                    branch,
                    titulo="Documentação docs-first do workspace",
                    descricao=f"Docs-first gerado ({mode}) para {root}; merge governado.",
                )
                entrega = ENTREGA_PR

        after = WorkspaceAnalyzer(ws).analyze(root)
        if not after.has_aso_docs and entrega == ENTREGA_COMMIT_DIRETO:
            # Rede de segurança só no repositório recém-criado pelo ASO (commit direto).
            extra = write_scaffold(root, after.detected_modules)
            if extra:
                created += extra
                ws.commit_all(root, "aso: docs-first (scaffold de segurança)")
                after = WorkspaceAnalyzer(ws).analyze(root)

        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            b.orchestration.workspace_prepared = True
            b.orchestration.updated_at = now_iso()
            b.event_log.append(
                "WorkspaceAnalyzed",
                {
                    "orchestration_id": orchestration_id,
                    "path": str(root),
                    "mode": mode,
                    "entrega": entrega,
                    "card_id": card_id,
                    "pr_id": pr_id,
                    "has_aso_docs": after.has_aso_docs,
                    "git_initialized": git_initialized,
                },
            )
            patch = ContextPatch(
                orchestration_id=orchestration_id,
                agent="DocumentationAgent",
                phase=b.orchestration.current_phase,
                patch_type=PatchType.UPDATE,
                target_path="engineering.docs_first",
                content={
                    "path": str(root),
                    "mode": mode,
                    "entrega": entrega,
                    "pr_id": pr_id,
                    "created": created,
                    "detected_modules": after.detected_modules,
                    "has_aso_docs": after.has_aso_docs,
                },
                evidence=[
                    f"mode={mode}",
                    f"entrega={entrega}",
                    f"has_aso_docs={after.has_aso_docs}",
                ],
            )
            b.bus.submit(patch)
            self._persist(b)
        self._log.info(
            "workspace_analyzed",
            orchestration_id=orchestration_id,
            mode=mode,
            entrega=entrega,
            has_aso_docs=after.has_aso_docs,
        )
        return {
            "path": str(root),
            "mode": mode,
            "entrega": entrega,
            "card_id": card_id,
            "pr_id": pr_id,
            "git_initialized": git_initialized,
            "created": created,
            "report": after.model_dump(),
        }

    def _garantir_git(
        self,
        b: OrchestrationBundle,
        root: Path,
        ws: WorkspaceService,
        *,
        inicializar_git: bool,
    ) -> bool:
        """`git init` na pasta do usuário só com confirmação explícita (ADR-0062)."""
        if ws.is_git(root):
            ws.ensure_git(root)  # repo existente sem commit ganha HEAD
            return False
        if not inicializar_git:
            raise WorkspaceError(
                f"A pasta {root} não é um repositório git. Confirme a inicialização "
                "(inicializar_git=true) ou rode `git init` antes."
            )
        ws.ensure_git(root)
        with self._lock_for(b.orchestration.id):
            b.event_log.append(
                "WorkspaceGitInitialized",
                {"orchestration_id": b.orchestration.id, "path": str(root)},
            )
            self._persist(b)
        return True

    def _entregar_docs_por_pr(
        self, orchestration_id: str, branch: str, *, titulo: str, descricao: str
    ) -> tuple[str, str]:
        """Documentação gerada vira card `Documentation` + PR interna (ADR-0062).

        Mesmo caminho de qualquer entrega de código: CI (quando houver bateria) → revisão →
        merge admin. Nada vai para a branch base sem esse fluxo.
        """
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            card = KanbanCard(
                board_id=b.board.id,
                orchestration_id=orchestration_id,
                phase=b.orchestration.current_phase,
                type=CardType.DOCUMENTATION,
                title=titulo,
                description=descricao,
                status=ColumnKey.READY,
                assignee_type=AssigneeType.AGENT,
                assignee="DocumentationAgent",
                branch=branch,
            )
            b.board_service.add_card(card)
            b.event_log.append(
                "DocsEntregaAberta", {"card_id": card.id, "branch": branch, "titulo": titulo}
            )
            self._persist(b)
        pr = self.open_pr(orchestration_id, card.id, branch=branch, title=titulo)
        return card.id, pr.id

    def docs_drift(self, orchestration_id: str) -> dict[str, object]:
        """Relatório determinístico (só leitura) do drift docs↔código do workspace."""
        b = self._bundle(orchestration_id)
        tp = b.orchestration.target_path
        if not tp:
            raise ValueError("Orquestração sem pasta de trabalho (workspace) definida.")
        return check_drift(tp).model_dump()

    def _docs_heal_task(
        self, b: OrchestrationBundle, drift: DocsDriftReport, *, effort: str | None = None
    ) -> dict[str, Any]:
        """Tarefa (JSON via stdin) que instrui o agente a sincronizar docs com o código."""
        partes: list[str] = []
        if drift.undocumented_modules:
            partes.append(
                "crie docs/modules/<módulo>/<feature>.md para: "
                + ", ".join(drift.undocumented_modules)
            )
        if drift.orphan_module_docs:
            partes.append(
                "revise/remova docs de módulos que não existem mais no código: "
                + ", ".join(drift.orphan_module_docs)
            )
        if drift.broken_links:
            partes.append(
                "conserte os links internos quebrados: " + "; ".join(drift.broken_links[:20])
            )
        if drift.unfilled_features:
            partes.append(
                "preencha, com fatos reais do código, as docs ainda em placeholder: "
                + ", ".join(drift.unfilled_features[:20])
            )
        instrucao = (
            "Sincronize a documentação docs-first (IA-first) com o código atual, em pt-BR, "
            "de forma LOCALIZADA (não recrie tudo). Mantenha o template de 8 seções por "
            "feature (Descrição, Localização no código, Entrada, Saída, Dependências, "
            "Regras de negócio, Fluxo resumido, Possíveis erros), o índice e os links "
            "internos válidos. Pontos de drift a resolver: " + "; ".join(partes) + "."
        )
        task: dict[str, Any] = {
            "orchestration_id": b.orchestration.id,
            "phase": Phase.F6.value,
            "target_path": "engineering.docs_drift",
            "content": {"request": instrucao, "by": "DocumentationAgent"},
            "envelope": TaskEnvelope(
                kind=KIND_EXECUTE,
                task_type="docs",
                request=instrucao,
                effort=effort or "",
                phase=Phase.F6.value,
                target_path="engineering.docs_drift",
            ).model_dump(),
        }
        if effort:
            task["effort"] = effort
        return task

    def heal_docs(
        self,
        orchestration_id: str,
        *,
        executor: str | None = None,
        effort: str | None = None,
        inicializar_git: bool = False,
    ) -> dict[str, object]:
        """Sincroniza (self-heal) a documentação docs-first com o código do workspace.

        Entrega governada (ADR-0062): a correção vai para um branch isolado e vira card
        `Documentation` com PR — a base só muda no merge governado.
        - Agente (se houver executor real): recebe todos os pontos de drift.
        - Sem agente real: scaffold determinístico dos módulos de código sem doc.
        - Registra evento `DocsHealed` + ContextPatch (`engineering.docs_drift`).
        """
        b = self._bundle(orchestration_id)
        self._recusar_se_estrategia_pendente(b)  # pode acionar agente real
        tp = b.orchestration.target_path
        if not tp:
            raise ValueError("Orquestração sem pasta de trabalho (workspace) definida.")
        ws = WorkspaceService()
        root = ws.validate(tp)
        self._garantir_git(b, root, ws, inicializar_git=inicializar_git)
        before = check_drift(root, ws)

        healed: list[str] = []
        mode = "noop"
        entrega = ENTREGA_SEM_ALTERACAO
        card_id: str | None = None
        pr_id: str | None = None
        if before.has_drift:
            provider = self._provider_for(b, executor, effort)
            spec = b.agent_registry.get("DocumentationAgent")
            branch: str | None = None
            if (
                provider is not None
                and spec is not None
                and not isinstance(provider, LocalMockExecutionProvider)
            ):
                # O agente recebe todos os pontos de drift (inclusive módulos sem doc).
                task = self._docs_heal_task(b, before, effort=effort)
                try:
                    output = provider.execute(spec, task)
                except AgentExecutionError as exc:
                    raise WorkspaceError(f"Falha ao sincronizar docs com o agente: {exc}") from exc
                bruto = output.artifacts.get("branch")
                if bruto:
                    branch, mode = str(bruto), "agent"
            elif before.undocumented_modules:
                branch, healed = _scaffold_em_branch(
                    root, before.undocumented_modules, "aso: docs-first (módulos sem doc)"
                )
                if branch:
                    mode = "scaffold"
            if branch:
                card_id, pr_id = self._entregar_docs_por_pr(
                    orchestration_id,
                    branch,
                    titulo="Sincronizar documentação docs-first",
                    descricao="Self-heal de drift docs↔código; merge governado (ADR-0062).",
                )
                entrega = ENTREGA_PR

        after = check_drift(root, ws)
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            b.orchestration.updated_at = now_iso()
            b.event_log.append(
                "DocsHealed",
                {
                    "orchestration_id": orchestration_id,
                    "mode": mode,
                    "entrega": entrega,
                    "pr_id": pr_id,
                    "had_drift": before.has_drift,
                    "has_drift": after.has_drift,
                },
            )
            patch = ContextPatch(
                orchestration_id=orchestration_id,
                agent="DocumentationAgent",
                phase=b.orchestration.current_phase,
                patch_type=PatchType.UPDATE,
                target_path="engineering.docs_drift",
                content={
                    "mode": mode,
                    "healed": healed,
                    "before": before.model_dump(),
                    "after": after.model_dump(),
                },
                evidence=[
                    f"mode={mode}",
                    f"had_drift={before.has_drift}",
                    f"has_drift={after.has_drift}",
                ],
            )
            b.bus.submit(patch)
            self._persist(b)
        self._log.info(
            "docs_healed",
            orchestration_id=orchestration_id,
            mode=mode,
            has_drift=after.has_drift,
        )
        return {
            "path": str(root),
            "mode": mode,
            "entrega": entrega,
            "card_id": card_id,
            "pr_id": pr_id,
            "healed": healed,
            "before": before.model_dump(),
            "after": after.model_dump(),
        }
