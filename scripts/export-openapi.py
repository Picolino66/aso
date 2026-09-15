#!/usr/bin/env python3
"""Regenera `contracts/openapi.json` a partir das rotas FastAPI (ADR-0064)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
# A app é criada com auth injetada, mas o import de `aso.api.app` instancia a app global.
os.environ.setdefault("ASO_DEV_MODE", "1")

from aso.api.openapi_export import CAMINHO_CONTRATO, gerar_openapi, serializar  # noqa: E402

CAMINHO_CONTRATO.write_text(serializar(gerar_openapi()), encoding="utf-8")
print(f"OpenAPI gerado em {CAMINHO_CONTRATO}")
