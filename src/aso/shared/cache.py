"""Cache de leitura simples com TTL (in-memory)."""

from __future__ import annotations

import time
from typing import Any


class TTLCache:
    """Cache chave→valor com expiração por tempo. Não thread-safe (uso single-process)."""

    def __init__(self, ttl_seconds: float = 1.0) -> None:
        self.ttl = ttl_seconds
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.monotonic() >= expires_at:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        self._store[key] = (time.monotonic() + self.ttl, value)

    def clear(self) -> None:
        self._store.clear()
