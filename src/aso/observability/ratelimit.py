"""Rate limiting simples (janela deslizante in-memory) por chave (§34).

Configurável via `ASO_RATE_LIMIT` (requisições por janela; 0 = desabilitado).
Em produção multiprocesso, trocar por um backend compartilhado (ex.: Redis).
"""

from __future__ import annotations

import os
import time


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float = 60.0) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, list[float]] = {}

    @classmethod
    def from_env(cls) -> RateLimiter:
        return cls(limit=int(os.environ.get("ASO_RATE_LIMIT", "0")))

    def allow(self, key: str) -> bool:
        if self.limit <= 0:
            return True  # desabilitado
        now = time.monotonic()
        window = self._hits.setdefault(key, [])
        cutoff = now - self.window
        window[:] = [t for t in window if t > cutoff]
        if len(window) >= self.limit:
            return False
        window.append(now)
        return True
