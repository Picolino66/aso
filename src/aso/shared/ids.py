"""Geração de identificadores e timestamps.

Regra (§39): toda entidade relevante tem `id` (UUID) e timestamps ISO8601 UTC.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime


def gen_id(prefix: str = "") -> str:
    """Gera um identificador único. Ex.: `gen_id("card")` -> `card_ab12...`."""
    value = uuid.uuid4().hex
    return f"{prefix}_{value}" if prefix else value


def now_iso() -> str:
    """Retorna o instante atual em ISO8601 UTC."""
    return datetime.now(UTC).isoformat()
