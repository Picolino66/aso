"""(c) EventBroker (pub/sub do streaming SSE).

O endpoint SSE em si é validado ao vivo contra o servidor real (uvicorn) no Docker —
o TestClient do Starlette não lida bem com streams infinitos (trava no teardown).
"""

from __future__ import annotations

import asyncio


def test_broker_pub_sub() -> None:
    from aso.observability.broker import EventBroker

    async def run() -> None:
        broker = EventBroker()
        q1 = broker.subscribe("o1")
        q2 = broker.subscribe("o1")
        assert broker.subscriber_count("o1") == 2
        seq = broker.publish("o1")
        assert await asyncio.wait_for(q1.get(), timeout=1.0) == seq
        assert await asyncio.wait_for(q2.get(), timeout=1.0) == seq
        # segunda publicação incrementa a sequência
        assert broker.publish("o1") == seq + 1
        broker.unsubscribe("o1", q1)
        broker.unsubscribe("o1", q2)
        assert broker.subscriber_count("o1") == 0
        # publicar sem assinantes é no-op seguro
        broker.publish("o1")

    asyncio.run(run())


def test_broker_isolated_per_key() -> None:
    from aso.observability.broker import EventBroker

    async def run() -> None:
        broker = EventBroker()
        qa = broker.subscribe("A")
        broker.subscribe("B")
        broker.publish("B")
        assert qa.empty()  # assinante de A não recebe evento de B

    asyncio.run(run())
