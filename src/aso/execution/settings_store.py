"""Persistência dos perfis de executor (tela de configurações).

Grava/lê os perfis num arquivo JSON (`ASO_EXECUTORS_FILE`, default `.aso/executors.json`).
Guarda APENAS metadados (nome, tipo, modelo, esforço, comando, nome da env var da
chave) — NUNCA o valor da chave (secrets permanecem só no ambiente, §governança).
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from aso.execution.catalog import ExecutorProfile


class ExecutorSettingsStore:
    """Lê e persiste a lista de ExecutorProfile em disco (thread-safe)."""

    def __init__(self, path: str | None = None) -> None:
        self._path = Path(path or os.environ.get("ASO_EXECUTORS_FILE", ".aso/executors.json"))
        self._lock = threading.Lock()

    def load(self) -> list[ExecutorProfile]:
        with self._lock:
            if not self._path.exists():
                return []
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                return [ExecutorProfile.model_validate(item) for item in raw]
            except (json.JSONDecodeError, ValueError, OSError):
                return []

    def save(self, profiles: list[ExecutorProfile]) -> None:
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = [p.model_dump() for p in profiles if p.name != "mock"]
            self._path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
