"""MEL-03 — contrato OpenAPI versionado = gerado das rotas (ADR-0064)."""

from __future__ import annotations

from fastapi.routing import APIRoute

from aso.api.app import create_app
from aso.api.auth import AuthService
from aso.api.openapi_export import CAMINHO_CONTRATO, gerar_openapi, serializar
from aso.control.orchestration_service import OrchestrationService

_REGENERAR = "Contrato desatualizado: rode `python scripts/export-openapi.py` e versione o arquivo."


def test_contrato_versionado_bate_com_o_gerado() -> None:
    assert CAMINHO_CONTRATO.read_text(encoding="utf-8") == serializar(gerar_openapi()), _REGENERAR


def test_contrato_contem_todas_as_rotas_v1() -> None:
    app = create_app(OrchestrationService(), auth=AuthService({}, dev_mode=True))
    rotas = {
        r.path
        for r in app.routes
        if isinstance(r, APIRoute) and r.include_in_schema and r.path.startswith("/v1")
    }
    paths = set(gerar_openapi()["paths"])
    assert rotas <= paths
    assert not any(p.startswith("/ui") for p in paths)


def test_rota_nova_sem_regenerar_e_detectada() -> None:
    app = create_app(OrchestrationService(), auth=AuthService({}, dev_mode=True))

    @app.get("/v1/rota-que-ninguem-documentou")
    def _nova() -> dict[str, str]:
        return {}

    assert serializar(app.openapi()) != CAMINHO_CONTRATO.read_text(encoding="utf-8")
