"""Logging estruturado (JSON) com correlation-id via contextvars (§33)."""

from __future__ import annotations

import logging
from typing import Any

import structlog

_configured = False

# Paths de infraestrutura ocultados do access log do uvicorn (healthcheck/scrape).
_QUIET_ACCESS_PATHS = ("/health", "/metrics")


class _QuietAccessFilter(logging.Filter):
    """Descarta os registros de access log do uvicorn para paths ruidosos.

    O access log do uvicorn formata a linha como '... "GET /health HTTP/1.1" 200'.
    Filtramos pelos args do record (o 3º arg é o request line), mantendo o access
    log para todos os demais paths (mantemos as duas pipelines, só tiramos o ruído).
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # uvicorn.access formata com args = (client, method, path, http_version, status).
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3:
            path = str(args[2]).split("?")[0]  # o 3º arg é o path (pode ter query string)
            return path not in _QUIET_ACCESS_PATHS
        return True


def configure_logging() -> None:
    """Configura o structlog (JSON) e filtra o ruído do access log do uvicorn."""
    global _configured
    if _configured:
        return
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=True,
    )
    # Mantém o access log do uvicorn, mas oculta /health e /metrics (idempotente).
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, _QuietAccessFilter) for f in access_logger.filters):
        access_logger.addFilter(_QuietAccessFilter())
    _configured = True


def get_logger() -> Any:
    configure_logging()
    return structlog.get_logger("aso")
