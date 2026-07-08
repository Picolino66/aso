"""ADRRegistry (§21).

Cria e lista ADRs com numeração sequencial (ADR-0001, ADR-0002, ...).
ADRs nunca são deletadas — apenas marcadas como SUPERSEDED/DEPRECATED.
"""

from __future__ import annotations

from aso.governance.models import ADR
from aso.shared.types import ADRStatus, Phase


class ADRRegistry:
    """Registro de Architecture Decision Records de uma orquestração."""

    def __init__(self, orchestration_id: str) -> None:
        self.orchestration_id = orchestration_id
        self._adrs: dict[str, ADR] = {}
        self._seq = 0

    def _next_id(self) -> str:
        self._seq += 1
        return f"ADR-{self._seq:04d}"

    def create(
        self,
        title: str,
        decision: str,
        phase: Phase,
        *,
        context: str = "",
        rationale: str = "",
        status: ADRStatus = ADRStatus.ACCEPTED,
        supersedes: str | None = None,
        **kwargs: object,
    ) -> ADR:
        adr = ADR(
            id=self._next_id(),
            orchestration_id=self.orchestration_id,
            title=title,
            decision=decision,
            phase=phase,
            context=context,
            rationale=rationale,
            status=status,
            supersedes=supersedes,
            **kwargs,  # type: ignore[arg-type]
        )
        if supersedes and supersedes in self._adrs:
            old = self._adrs[supersedes]
            self._adrs[supersedes] = old.model_copy(
                update={"status": ADRStatus.SUPERSEDED, "superseded_by": adr.id}
            )
        self._adrs[adr.id] = adr
        return adr

    def hydrate(self, adrs: list[ADR]) -> None:
        """Reidrata o registro a partir de ADRs persistidas."""
        self._adrs = {a.id: a for a in adrs}
        self._seq = max((int(a.id.split("-")[1]) for a in adrs), default=0)

    def get(self, adr_id: str) -> ADR | None:
        return self._adrs.get(adr_id)

    def list_all(self) -> list[ADR]:
        return sorted(self._adrs.values(), key=lambda a: a.id)

    def accepted(self) -> list[ADR]:
        return [a for a in self.list_all() if a.status == ADRStatus.ACCEPTED]
