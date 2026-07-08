"""Logging estruturado (JSON) com correlation-id via contextvars (§33)."""

from __future__ import annotations

import logging
from typing import Any

import structlog

_configured = False


def configure_logging() -> None:
    """Configura o structlog para emitir JSON com nível e timestamp ISO."""
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
    _configured = True


def get_logger() -> Any:
    configure_logging()
    return structlog.get_logger("aso")
