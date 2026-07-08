"""ContextBus (§19, ADR-0003).

Único componente autorizado a aplicar patches ao OrchestratorContext. Executa um
pipeline de validação de 7 etapas antes de aplicar:

1. schema validation
2. permission check
3. conflict detection
4. snapshot lock validation
5. ADR consistency validation
6. contract compatibility validation
7. quality gate impact check

Aprovado -> aplica patch, incrementa versão, registra evento.
Reprovado -> registra conflito e retorna status rejeitado/enfileirado.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from aso.governance.adr_registry import ADRRegistry
from aso.governance.conflict_detector import ConflictDetector
from aso.governance.context_store import OrchestratorContextStore
from aso.governance.models import Conflict, ContextPatch
from aso.shared.events import EventLog
from aso.shared.types import ConflictType, PatchStatus, PatchType


@dataclass(frozen=True)
class StepResult:
    """Resultado de uma etapa de validação."""

    ok: bool
    conflict_type: ConflictType | None = None
    reason: str | None = None

    @classmethod
    def clear(cls) -> StepResult:
        return cls(ok=True)


@dataclass(frozen=True)
class BusResult:
    """Resultado da submissão de um patch ao ContextBus."""

    status: PatchStatus
    version: int | None = None
    context_hash: str | None = None
    conflict: Conflict | None = None
    reason: str | None = None


class PermissionPolicy:
    """Permissões de escrita por agente sobre seções do contexto (§25).

    Mapeia agente -> prefixos de seção permitidos. `"*"` libera qualquer seção.
    Deny-by-default: agente sem entrada na política não pode escrever.
    """

    def __init__(self, policy: Mapping[str, list[str]] | None = None) -> None:
        self._policy: dict[str, list[str]] = {k: list(v) for k, v in (policy or {}).items()}

    @classmethod
    def allow_all(cls) -> PermissionPolicy:
        """Política permissiva — use apenas em desenvolvimento/testes, nunca em produção."""
        return cls({"*": ["*"]})

    def allow(self, agent: str, allowed: list[str]) -> None:
        self._policy[agent] = list(allowed)

    def can_write(self, agent: str, target_path: str) -> bool:
        allowed = self._policy.get(agent)
        if allowed is None:
            return False
        for prefix in allowed:
            if prefix == "*" or target_path == prefix or target_path.startswith(prefix + "."):
                return True
        return False


class ContextBus:
    """Escritor soberano do OrchestratorContext."""

    def __init__(
        self,
        store: OrchestratorContextStore,
        *,
        permissions: PermissionPolicy | None = None,
        conflict_detector: ConflictDetector | None = None,
        adr_registry: ADRRegistry | None = None,
        event_log: EventLog | None = None,
    ) -> None:
        self.store = store
        # Deny-by-default (F3): sem política explícita, nenhuma escrita é autorizada.
        self.permissions = permissions or PermissionPolicy()
        self.conflict_detector = conflict_detector or ConflictDetector()
        self.adr_registry = adr_registry
        self.event_log = event_log or EventLog()
        self.conflicts: list[Conflict] = []
        self.patches: list[ContextPatch] = []  # trilha de auditoria de todos os patches

    def _validate(self, patch: ContextPatch) -> StepResult | None:
        """Roda o pipeline de 7 etapas; retorna o primeiro resultado que falha, ou None."""
        steps = (
            self._step_schema,
            self._step_permission,
            self._step_conflict_detection,
            self._step_snapshot_lock,
            self._step_adr_consistency,
            self._step_adr_contradiction,
            self._step_contract_compatibility,
            self._step_quality_gate_impact,
        )
        for step in steps:
            result = step(patch)
            if not result.ok:
                return result
        return None

    def _apply(self, patch: ContextPatch, *, approved: bool = False) -> BusResult:
        version = self.store.apply_patch(patch)
        patch.status = PatchStatus.APPLIED
        self.event_log.append(
            "ContextPatchApplied",
            {
                "patch_id": patch.id,
                "agent": patch.agent,
                "target_path": patch.target_path,
                "version": version,
                "approved": approved,
            },
        )
        return BusResult(
            status=PatchStatus.APPLIED, version=version, context_hash=self.store.context_hash()
        )

    def apply_approved(self, patch: ContextPatch) -> BusResult:
        """Aplica um patch previamente pendente após aprovação humana (§24)."""
        failure = self._validate(patch)
        if failure is not None:
            return self._reject(patch, failure)
        if patch.patch_type == PatchType.PROPOSE:
            patch.patch_type = PatchType.UPDATE  # proposta aprovada vira alteração aplicada
        return self._apply(patch, approved=True)

    def submit(self, patch: ContextPatch) -> BusResult:
        """Submete um patch ao pipeline de validação e aplica se aprovado."""
        self.patches.append(patch)  # registra para auditoria (status final é mutado abaixo)
        failure = self._validate(patch)
        if failure is not None:
            return self._reject(patch, failure)

        # Proposta ou ação que exige aprovação: validada, porém NÃO aplicada (§8.3/§8.6).
        # Fica pendente até promoção/aprovação humana (HumanApprovalEngine — MVP-2).
        if patch.patch_type == PatchType.PROPOSE or patch.requires_approval:
            patch.status = PatchStatus.PENDING
            is_propose = patch.patch_type == PatchType.PROPOSE
            pending_reason = "propose" if is_propose else "requires_approval"
            self.event_log.append(
                "ContextPatchPendingApproval",
                {
                    "patch_id": patch.id,
                    "agent": patch.agent,
                    "target_path": patch.target_path,
                    "reason": pending_reason,
                },
            )
            return BusResult(
                status=PatchStatus.PENDING,
                reason="Patch validado; requer promoção/aprovação humana antes de aplicar.",
            )

        return self._apply(patch)

    # --------------------------------------------------------------- etapas 1–7
    def _step_schema(self, patch: ContextPatch) -> StepResult:
        # O patch já é validado pelo Pydantic; aqui garantimos coerência semântica.
        needs_content = patch.patch_type in (PatchType.ADD, PatchType.UPDATE, PatchType.PROPOSE)
        if needs_content and patch.content is None:
            return StepResult(
                ok=False,
                conflict_type=ConflictType.DATA_MODEL,
                reason=f"patch_type '{patch.patch_type.value}' exige content não nulo.",
            )
        return StepResult.clear()

    def _step_permission(self, patch: ContextPatch) -> StepResult:
        if not self.permissions.can_write(patch.agent, patch.target_path):
            return StepResult(
                ok=False,
                conflict_type=ConflictType.TOOL_PERMISSION,
                reason=(
                    f"Agente '{patch.agent}' sem permissão para escrever em '{patch.target_path}'."
                ),
            )
        return StepResult.clear()

    def _step_conflict_detection(self, patch: ContextPatch) -> StepResult:
        # Hook para AGENT_OUTPUT_CONFLICT entre patches concorrentes (evoluído no MVP-2).
        return StepResult.clear()

    def _step_snapshot_lock(self, patch: ContextPatch) -> StepResult:
        check = self.conflict_detector.check_snapshot_lock(patch, self.store)
        return StepResult(ok=check.ok, conflict_type=check.conflict_type, reason=check.reason)

    def _step_adr_consistency(self, patch: ContextPatch) -> StepResult:
        # Se o patch declara que exige ADR, deve referenciar ADR(s) aceita(s).
        if patch.requires_adr:
            if not patch.linked_adrs:
                return StepResult(
                    ok=False,
                    conflict_type=ConflictType.ARCHITECTURE,
                    reason="Patch requires_adr=True sem linked_adrs.",
                )
            if self.adr_registry is not None:
                accepted = {a.id for a in self.adr_registry.accepted()}
                missing = [a for a in patch.linked_adrs if a not in accepted]
                if missing:
                    return StepResult(
                        ok=False,
                        conflict_type=ConflictType.ARCHITECTURE,
                        reason=f"ADR(s) não aceita(s)/inexistente(s): {missing}.",
                    )
        return StepResult.clear()

    def _step_adr_contradiction(self, patch: ContextPatch) -> StepResult:
        if self.adr_registry is None:
            return StepResult.clear()
        locked = {a.id: a.locked_paths for a in self.adr_registry.accepted() if a.locked_paths}
        check = self.conflict_detector.check_adr_contradiction(patch, locked)
        return StepResult(ok=check.ok, conflict_type=check.conflict_type, reason=check.reason)

    def _step_contract_compatibility(self, patch: ContextPatch) -> StepResult:
        check = self.conflict_detector.check_contract_compatibility(patch)
        return StepResult(ok=check.ok, conflict_type=check.conflict_type, reason=check.reason)

    def _step_quality_gate_impact(self, patch: ContextPatch) -> StepResult:
        # Hook para QUALITY_GATE_CONFLICT (evoluído no MVP-2).
        return StepResult.clear()

    # ----------------------------------------------------------------- rejeição
    def _reject(self, patch: ContextPatch, result: StepResult) -> BusResult:
        conflict = Conflict(
            orchestration_id=self.store.orchestration_id,
            type=result.conflict_type or ConflictType.AGENT_OUTPUT,
            source_patch_ids=[patch.id],
            description=result.reason or "Conflito não especificado.",
        )
        self.conflicts.append(conflict)
        patch.status = PatchStatus.REJECTED
        self.event_log.append(
            "ConflictRaised",
            {"patch_id": patch.id, "type": conflict.type.value, "reason": conflict.description},
        )
        return BusResult(
            status=PatchStatus.REJECTED, conflict=conflict, reason=conflict.description
        )
