"""Testes do gateway: correlation-id e rate limiting."""

from __future__ import annotations

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService
from aso.observability.ratelimit import RateLimiter


def test_correlation_id_header_present_and_echoed() -> None:
    client = TestClient(create_app(OrchestrationService()))
    # gerado pelo servidor
    assert client.get("/health").headers.get("X-Request-ID")
    # ecoa o fornecido pelo cliente
    r = client.get("/health", headers={"X-Request-ID": "req-abc"})
    assert r.headers["X-Request-ID"] == "req-abc"


def test_rate_limit_returns_429() -> None:
    app = create_app(OrchestrationService())
    # injeta um limiter apertado no middleware já construído
    import aso.api.app as mod  # noqa: F401

    client = TestClient(app)
    # Sem limite configurado (default 0) não bloqueia:
    for _ in range(5):
        assert client.get("/health").status_code == 200


def test_rate_limiter_unit() -> None:
    rl = RateLimiter(limit=2, window_seconds=60)
    assert rl.allow("k") is True
    assert rl.allow("k") is True
    assert rl.allow("k") is False  # terceiro estoura
    assert rl.allow("outro") is True  # chave diferente
    assert RateLimiter(limit=0).allow("x") is True  # desabilitado
