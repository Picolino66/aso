"""Rotas de fluxo governado: fases, gates, snapshots, ADRs, aprovações e recuperação.

Extraídas do `create_app` monolítico no MEL-32 passo 10 (ADR-0066).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from aso.api.deps import ApiDeps
from aso.api.execucao_assincrona import OP_AUTOPILOT, OP_RUN_PHASE, OP_RUN_PLAN
from aso.api.schemas import (
    ApprovalBody,
    AutopilotBody,
    ContextPatchBody,
    RestoreSectionBody,
    RollbackBody,
    RunGateBody,
    RunPhaseBody,
)
from aso.execution.workspace import WorkspaceError
from aso.governance.models import ContextPatch


def criar_router(deps: ApiDeps) -> APIRouter:
    router = APIRouter()
    svc = deps.svc

    @router.post("/v1/orchestrations/{orchestration_id}/quality-gates/run")
    def run_gate(orchestration_id: str, body: RunGateBody) -> Any:
        deps.guard(orchestration_id)
        return svc.run_quality_gate(orchestration_id, body.phase)

    @router.post("/v1/orchestrations/{orchestration_id}/run-plan")
    def run_plan(orchestration_id: str, request: Request) -> Any:
        deps.guard(orchestration_id)
        if deps.fila is not None:
            return deps.enfileirar(OP_RUN_PLAN, orchestration_id, request)
        try:
            return svc.run_plan(orchestration_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @router.post("/v1/orchestrations/{orchestration_id}/run-phase")
    def run_phase(orchestration_id: str, body: RunPhaseBody, request: Request) -> Any:
        """Executa uma fase ponta a ponta e abre a aprovação de avanço (autopilot M3)."""
        deps.guard(orchestration_id)
        if deps.fila is not None:
            return deps.enfileirar(
                OP_RUN_PHASE, orchestration_id, request, parametros=body.model_dump(mode="json")
            )
        try:
            return svc.run_phase(
                orchestration_id, body.phase, executor=body.executor, effort=body.effort
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @router.post("/v1/orchestrations/{orchestration_id}/advance-phase")
    def advance_phase(orchestration_id: str) -> Any:
        """Avança para a próxima fase (governado)."""
        deps.guard(orchestration_id)
        try:
            return svc.advance_phase(orchestration_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @router.post("/v1/orchestrations/{orchestration_id}/recover-execution")
    def recover_invalid_execution(orchestration_id: str) -> Any:
        deps.guard(orchestration_id)
        try:
            return svc.recover_invalid_execution(orchestration_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @router.post("/v1/orchestrations/{orchestration_id}/autopilot")
    def start_autopilot(
        orchestration_id: str, request: Request, body: AutopilotBody | None = None
    ) -> Any:
        """Dá partida no autopilot (M4): roda a fase atual; aprovar avança sozinho."""
        deps.guard(orchestration_id)
        body = body or AutopilotBody()
        if deps.fila is not None:
            return deps.enfileirar(
                OP_AUTOPILOT, orchestration_id, request, parametros=body.model_dump(mode="json")
            )
        try:
            return svc.start_autopilot(
                orchestration_id,
                executor=body.executor,
                effort=body.effort,
                inicializar_git=body.inicializar_git,
            )
        except (KeyError, ValueError, WorkspaceError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @router.get("/v1/orchestrations/{orchestration_id}/adrs")
    def list_adrs(
        orchestration_id: str,
        status: str | None = None,
        q: str | None = None,
    ) -> Any:
        deps.guard(orchestration_id)
        if status or q:
            return svc.search_adrs(orchestration_id, status=status, query=q)
        return svc.list_adrs(orchestration_id)

    @router.get("/v1/orchestrations/{orchestration_id}/adrs/by-status/{status}")
    def adrs_by_status(orchestration_id: str, status: str) -> Any:
        deps.guard(orchestration_id)
        return svc.adrs_by_status(orchestration_id, status)

    @router.get("/v1/orchestrations/{orchestration_id}/adrs/{adr_id}/linked-cards")
    def adr_linked_cards(orchestration_id: str, adr_id: str) -> Any:
        deps.guard(orchestration_id)
        return svc.cards_linked_to_adr(orchestration_id, adr_id)

    @router.get("/v1/orchestrations/{orchestration_id}/snapshots")
    def list_snapshots(orchestration_id: str) -> Any:
        deps.guard(orchestration_id)
        return svc.list_snapshots(orchestration_id)

    # --- gates, conflitos e ciclo de vida (§28) ---
    @router.get("/v1/orchestrations/{orchestration_id}/quality-gates")
    def list_gates(orchestration_id: str) -> Any:
        deps.guard(orchestration_id)
        return svc.list_gate_results(orchestration_id)

    @router.get("/v1/quality-gates/{gate_id}")
    def get_gate(gate_id: str) -> Any:
        gate = svc.find_gate_result(gate_id)
        if gate is None:
            raise HTTPException(status_code=404, detail="Quality gate inexistente")
        return gate

    @router.get("/v1/orchestrations/{orchestration_id}/conflicts")
    def list_conflicts(orchestration_id: str) -> Any:
        deps.guard(orchestration_id)
        return svc.conflicts(orchestration_id)

    @router.post("/v1/orchestrations/{orchestration_id}/conflicts/{conflict_id}/resolve")
    def resolve_conflict(orchestration_id: str, conflict_id: str) -> Any:
        deps.guard(orchestration_id)
        try:
            return svc.resolve_conflict(orchestration_id, conflict_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None

    @router.post("/v1/orchestrations/{orchestration_id}/restaurar-ledger", status_code=202)
    def restaurar_ledger(orchestration_id: str, body: RollbackBody) -> Any:
        """Restaura só o ledger do contexto a um snapshot — não reverte código nem board
        (ADR-0061). Ação crítica: admin."""
        deps.guard(orchestration_id)
        try:
            return svc.restaurar_ledger(orchestration_id, body.to_snapshot)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None

    @router.post("/v1/orchestrations/{orchestration_id}/rollback", status_code=202, deprecated=True)
    def rollback(orchestration_id: str, body: RollbackBody) -> Any:
        """Alias obsoleto de `restaurar-ledger` (mantido por uma versão, ADR-0061)."""
        return restaurar_ledger(orchestration_id, body)

    @router.get("/v1/orchestrations/{orchestration_id}/snapshots/{version}/restore-section/preview")
    def preview_restore_section(orchestration_id: str, version: str, section: str) -> Any:
        """Dry-run: mostra o impacto da restauração seletiva sem aplicar (§23)."""
        deps.guard(orchestration_id)
        try:
            return svc.preview_restore_section(orchestration_id, version, section)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None

    @router.post(
        "/v1/orchestrations/{orchestration_id}/snapshots/{version}/restore-section",
        status_code=202,
    )
    def restore_section(orchestration_id: str, version: str, body: RestoreSectionBody) -> Any:
        """Restauração seletiva de uma seção a partir de um snapshot (§23; admin)."""
        deps.guard(orchestration_id)
        try:
            return svc.restore_section(orchestration_id, version, body.section)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None

    @router.post("/v1/orchestrations/{orchestration_id}/cancel")
    def cancel(orchestration_id: str) -> Any:
        deps.guard(orchestration_id)
        return svc.cancel(orchestration_id)

    @router.post("/v1/orchestrations/{orchestration_id}/resume")
    def resume(orchestration_id: str) -> Any:
        deps.guard(orchestration_id)
        return svc.resume(orchestration_id)

    @router.post("/v1/orchestrations/{orchestration_id}/retry")
    def retry(orchestration_id: str) -> Any:
        deps.guard(orchestration_id)
        return {"retried": svc.retry(orchestration_id)}

    @router.get("/v1/orchestrations/{orchestration_id}/snapshots/{from_v}/diff/{to_v}")
    def snapshot_diff(orchestration_id: str, from_v: str, to_v: str) -> Any:
        deps.guard(orchestration_id)
        try:
            return svc.snapshot_diff(orchestration_id, from_v, to_v)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None

    # --- approvals (§28.7) ---
    @router.post("/v1/orchestrations/{orchestration_id}/approvals", status_code=201)
    def create_approval(orchestration_id: str, body: ApprovalBody) -> Any:
        deps.guard(orchestration_id)
        return svc.request_approval(
            orchestration_id, body.action, risk=body.risk, reason=body.reason
        )

    @router.get("/v1/orchestrations/{orchestration_id}/approvals")
    def list_orch_approvals(orchestration_id: str) -> Any:
        deps.guard(orchestration_id)
        return svc.list_approvals(orchestration_id)

    @router.get("/v1/approvals")
    def list_approvals(
        status: str | None = Query(default=None),
        project_id: str | None = Query(default=None),
    ) -> Any:
        # Filtros na consulta, não em memória (MEL-52).
        ids = {o.id for o in svc.list_all(project_id=project_id)} if project_id else None
        return svc.list_all_approvals(status=status, orchestration_ids=ids)

    @router.get("/v1/approvals/{approval_id}")
    def get_approval(approval_id: str) -> Any:
        approval = svc.get_approval(approval_id)
        if approval is None:
            raise HTTPException(status_code=404, detail="Aprovação inexistente")
        return approval

    @router.post("/v1/approvals/{approval_id}/approve")
    def approve(approval_id: str, request: Request) -> Any:
        try:
            return svc.decide_approval(
                approval_id, approved=True, approved_by=request.state.principal.actor
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None

    @router.post("/v1/approvals/{approval_id}/reject")
    def reject(approval_id: str, request: Request) -> Any:
        try:
            return svc.decide_approval(
                approval_id, approved=False, approved_by=request.state.principal.actor
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None

    # --- context patches e auditoria (§18, §33) ---
    @router.get("/v1/orchestrations/{orchestration_id}/patches")
    def list_patches(orchestration_id: str, status: str | None = None) -> Any:
        deps.guard(orchestration_id)
        return svc.list_patches(orchestration_id, status=status)

    @router.get("/v1/orchestrations/{orchestration_id}/patches/{patch_id}")
    def get_patch(orchestration_id: str, patch_id: str) -> Any:
        deps.guard(orchestration_id)
        patch = svc.get_patch(orchestration_id, patch_id)
        if patch is None:
            raise HTTPException(status_code=404, detail="Patch inexistente")
        return patch

    @router.post("/v1/orchestrations/{orchestration_id}/context-patches")
    def submit_patch(orchestration_id: str, body: ContextPatchBody) -> Any:
        deps.guard(orchestration_id)
        patch = ContextPatch(
            orchestration_id=orchestration_id,
            card_id=body.card_id,
            agent=body.agent,
            phase=body.phase,
            patch_type=body.patch_type,
            target_path=body.target_path,
            content=body.content,
            requires_adr=body.requires_adr,
            requires_approval=body.requires_approval,
            linked_adrs=body.linked_adrs,
        )
        result = svc.submit_patch(orchestration_id, patch)
        return {"status": result.status.value, "version": result.version, "reason": result.reason}

    return router
