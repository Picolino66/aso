"""OrchestratorContext versionado (§17).

Estado canônico com versão incremental, histórico append-only, hash de conteúdo
e controle de seções congeladas por snapshot. É mutado exclusivamente via
`apply_patch`, invocado pelo ContextBus (ADR-0003) — nunca diretamente por agentes.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from aso.governance.models import ContextPatch
from aso.shared.ids import now_iso
from aso.shared.types import PatchType

# Sentinela para distinguir "chave ausente" de "valor None".
_MISSING = object()


@dataclass
class HistoryEntry:
    """Registro append-only de uma mutação aplicada ao contexto."""

    version: int
    patch_id: str
    agent: str
    target_path: str
    patch_type: str
    context_hash: str
    created_at: str = field(default_factory=now_iso)


class OrchestratorContextStore:
    """Armazena e versiona o OrchestratorContext de uma orquestração."""

    def __init__(
        self, orchestration_id: str, initial_payload: dict[str, Any] | None = None
    ) -> None:
        self.orchestration_id = orchestration_id
        self._payload: dict[str, Any] = initial_payload.copy() if initial_payload else {}
        self.version: int = 0
        self.history: list[HistoryEntry] = []
        self.frozen_sections: set[str] = set()

    # ------------------------------------------------------------------ leitura
    def get(self) -> dict[str, Any]:
        """Retorna uma cópia imutável do payload (read snapshot)."""
        return copy.deepcopy(self._payload)

    def get_path(self, path: str, default: Any = None) -> Any:
        node: Any = self._payload
        for part in path.split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                return default
        return copy.deepcopy(node)

    def context_hash(self) -> str:
        blob = json.dumps(self._payload, sort_keys=True, default=str, ensure_ascii=False)
        return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()

    # ---------------------------------------------------------- seções congeladas
    def freeze(self, sections: list[str]) -> None:
        """Marca seções como congeladas (imutáveis sem ADR de override)."""
        self.frozen_sections.update(sections)

    def is_frozen(self, target_path: str) -> bool:
        """Indica se `target_path` está sob alguma seção congelada."""
        for frozen in self.frozen_sections:
            if target_path == frozen or target_path.startswith(frozen + "."):
                return True
        return False

    # ------------------------------------------------------------------- escrita
    def apply_patch(self, patch: ContextPatch) -> int:
        """Aplica um patch já validado, incrementa versão e registra histórico.

        NÃO deve ser chamado diretamente por agentes — apenas pelo ContextBus.
        """
        if patch.patch_type in (PatchType.ADD, PatchType.UPDATE):
            self._set_path(patch.target_path, copy.deepcopy(patch.content))
        elif patch.patch_type == PatchType.REMOVE:
            self._remove_path(patch.target_path)
        else:  # PatchType.PROPOSE
            raise ValueError(
                "Patch 'propose' não pode ser aplicado diretamente ao contexto: "
                "requer promoção/aprovação (§8.3/§8.6)."
            )

        self.version += 1
        entry = HistoryEntry(
            version=self.version,
            patch_id=patch.id,
            agent=patch.agent,
            target_path=patch.target_path,
            patch_type=patch.patch_type.value,
            context_hash=self.context_hash(),
        )
        self.history.append(entry)
        return self.version

    def restore_from(self, payload: dict[str, Any], frozen_sections: list[str]) -> None:
        """Restaura o payload e as seções congeladas a partir de um snapshot.

        Faz cópia profunda para não compartilhar referências com o snapshot de origem
        (usado pelo SnapshotEngine no protocolo de rollback).
        """
        self._payload = copy.deepcopy(payload)
        self.frozen_sections = set(frozen_sections)
        self.version += 1

    def hydrate(
        self,
        *,
        payload: dict[str, Any],
        version: int,
        frozen_sections: list[str],
        history: list[dict[str, Any]],
    ) -> None:
        """Reidrata o store a partir de estado persistido (usado pela persistência)."""
        self._payload = copy.deepcopy(payload)
        self.version = version
        self.frozen_sections = set(frozen_sections)
        self.history = [HistoryEntry(**entry) for entry in history]

    def _set_path(self, path: str, value: Any) -> None:
        parts = path.split(".")
        node = self._payload
        for part in parts[:-1]:
            nxt = node.get(part, _MISSING)
            if not isinstance(nxt, dict):
                nxt = {}
                node[part] = nxt
            node = nxt
        node[parts[-1]] = value

    def _remove_path(self, path: str) -> None:
        parts = path.split(".")
        node = self._payload
        for part in parts[:-1]:
            nxt = node.get(part, _MISSING)
            if not isinstance(nxt, dict):
                return
            node = nxt
        node.pop(parts[-1], None)
