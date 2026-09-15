"""Contrato OpenAPI gerado a partir das rotas FastAPI (ADR-0064).

O `contracts/openapi.yaml` manual descrevia 19 paths contra ~200 rotas reais e citava paths
que não existiam. O contrato de máquina passa a ser **gerado do código** e versionado em
`contracts/openapi.json`; `tests/integration/test_openapi_contract.py` falha quando o arquivo
diverge do gerado. Regenerar: `python scripts/export-openapi.py`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CAMINHO_CONTRATO = Path(__file__).resolve().parents[3] / "contracts" / "openapi.json"


def gerar_openapi() -> dict[str, Any]:
    """Schema OpenAPI de uma app criada com serviço em memória (sem depender de ambiente)."""
    from aso.api.app import create_app
    from aso.api.auth import AuthService
    from aso.application.orchestration_service import OrchestrationService

    app = create_app(OrchestrationService(), auth=AuthService({}, dev_mode=True))
    return app.openapi()


def serializar(schema: dict[str, Any]) -> str:
    """JSON estável (chaves ordenadas) para diff legível e comparação exata."""
    return json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
