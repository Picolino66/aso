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

from aso.execution.catalog import ExecutorProfile, migrar_perfis_salvos


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
                perfis = migrar_perfis_salvos([ExecutorProfile.model_validate(i) for i in raw])
            except (json.JSONDecodeError, ValueError, OSError):
                return []
            # Migração única (ADR-0076): se a leitura normalizou algo (flags do comando viraram
            # campos, chave LLM ganhou nome), grava de volta — sem perder campo nenhum.
            atual = [p.model_dump() for p in perfis if p.name != "mock"]
            if atual != [item for item in raw if item.get("name") != "mock"]:
                copia = self._path.with_name(self._path.name + ".antes-adr-0076")
                if not copia.exists():
                    copia.write_text(
                        json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                self._gravar(perfis)
            return perfis

    def save(self, profiles: list[ExecutorProfile]) -> None:
        with self._lock:
            self._gravar(profiles)

    def _gravar(self, profiles: list[ExecutorProfile]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = [p.model_dump() for p in profiles if p.name != "mock"]
        self._path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
