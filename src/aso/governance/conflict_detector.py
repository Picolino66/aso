"""ConflictDetector (§20).

Analisa um ContextPatch contra o estado do contexto, os snapshots congelados e
as ADRs aceitas, retornando o tipo de conflito quando houver. Usado pelo ContextBus.
"""

from __future__ import annotations

from dataclasses import dataclass

from aso.governance.context_store import OrchestratorContextStore
from aso.governance.models import ContextPatch
from aso.shared.types import ConflictType, PatchType


@dataclass(frozen=True)
class ConflictCheck:
    """Resultado de uma verificação de conflito."""

    ok: bool
    conflict_type: ConflictType | None = None
    reason: str | None = None

    @classmethod
    def clear(cls) -> ConflictCheck:
        return cls(ok=True)


class ConflictDetector:
    """Detecta conflitos entre um patch e o estado governado."""

    def check_snapshot_lock(
        self, patch: ContextPatch, store: OrchestratorContextStore
    ) -> ConflictCheck:
        """Escrita em seção congelada só é permitida com ADR de override."""
        if store.is_frozen(patch.target_path):
            has_override = patch.requires_adr and bool(patch.linked_adrs)
            if not has_override:
                return ConflictCheck(
                    ok=False,
                    conflict_type=ConflictType.SNAPSHOT_LOCK,
                    reason=(
                        f"target_path '{patch.target_path}' está em seção congelada; "
                        "requer ADR de override (requires_adr + linked_adrs)."
                    ),
                )
        return ConflictCheck.clear()

    def check_contract_compatibility(self, patch: ContextPatch) -> ConflictCheck:
        """Protege contratos publicados: versão imutável e sem remoção in-place."""
        if patch.target_path == "contracts.api_version":
            return ConflictCheck(
                ok=False,
                conflict_type=ConflictType.CONTRACT,
                reason="Versão de API é imutável; crie uma nova versão em vez de alterar.",
            )
        if patch.patch_type == PatchType.REMOVE and patch.target_path.startswith("contracts"):
            return ConflictCheck(
                ok=False,
                conflict_type=ConflictType.CONTRACT,
                reason="Não é permitido remover contrato publicado; crie uma nova versão.",
            )
        return ConflictCheck.clear()

    def check_adr_contradiction(
        self, patch: ContextPatch, locked: dict[str, list[str]]
    ) -> ConflictCheck:
        """Contradição com ADR aceita: escrever em caminho travado sem referenciá-la."""
        for adr_id, paths in locked.items():
            for locked_path in paths:
                under = patch.target_path == locked_path or patch.target_path.startswith(
                    locked_path + "."
                )
                if under and adr_id not in patch.linked_adrs:
                    return ConflictCheck(
                        ok=False,
                        conflict_type=ConflictType.ARCHITECTURE,
                        reason=(
                            f"'{patch.target_path}' é governado por {adr_id} (locked); "
                            "referencie a ADR em linked_adrs para override."
                        ),
                    )
        return ConflictCheck.clear()
