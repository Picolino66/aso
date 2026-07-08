"""EventBroker — pub/sub in-process para streaming SSE (§30, atualização ao vivo).

Cada assinante (conexão SSE) recebe uma fila; a camada HTTP publica um "tick" por
orquestração após cada mutação, sinalizando ao console que deve re-buscar o estado.
In-process (single-worker); para multi-worker use um backend externo (ex.: Redis pub/sub).
"""

from __future__ import annotations

import asyncio


class EventBroker:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[int]]] = {}
        self._seq: dict[str, int] = {}

    def subscribe(self, key: str) -> asyncio.Queue[int]:
        queue: asyncio.Queue[int] = asyncio.Queue(maxsize=16)
        self._subscribers.setdefault(key, set()).add(queue)
        return queue

    def unsubscribe(self, key: str, queue: asyncio.Queue[int]) -> None:
        subs = self._subscribers.get(key)
        if subs is not None:
            subs.discard(queue)
            if not subs:
                self._subscribers.pop(key, None)

    def publish(self, key: str) -> int:
        seq = self._seq.get(key, 0) + 1
        self._seq[key] = seq
        for queue in list(self._subscribers.get(key, ())):
            try:
                queue.put_nowait(seq)
            except asyncio.QueueFull:  # assinante lento: ignora (coalescência)
                pass
        return seq

    def subscriber_count(self, key: str) -> int:
        return len(self._subscribers.get(key, ()))
