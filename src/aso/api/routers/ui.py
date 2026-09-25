"""Rotas de console web: páginas estáticas do console.

Extraídas do `create_app` monolítico no MEL-32 passo 10 (ADR-0066).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, RedirectResponse

from aso.api.deps import ApiDeps

_STATIC_DIR = Path(__file__).resolve().parents[1] / "static"


def criar_router(deps: ApiDeps) -> APIRouter:
    router = APIRouter()

    # -- Rotas legadas: redirecionam para a página equivalente da sidebar (ADR-0078, MEL-55).
    # As quatro páginas legadas (`macro.html`, `nova.html`, `detalhe.html`, `index.html`) foram
    # consolidadas: nenhuma funcionalidade ficou só nelas (inventário na ADR-0078). Os
    # redirecionamentos ficam porque link salvo e marcador do operador não podem quebrar; a
    # query string é preservada para `?id=` continuar abrindo a mesma demanda. 307 (temporário)
    # de propósito: um 301 ficaria no cache do navegador mesmo depois de a rota sair.
    def _redirecionar(destino: str) -> Callable[[Request], RedirectResponse]:
        def handler(request: Request) -> RedirectResponse:
            consulta = request.url.query
            return RedirectResponse(f"{destino}?{consulta}" if consulta else destino, 307)

        return handler

    _LEGADAS = {
        "/ui/": "/ui/dashboard",  # kanban macro → visão geral (projetos ficam em Configurações)
        "/ui/nova": "/ui/demanda-nova",
        "/ui/detalhe": "/ui/esteira",  # sala de controle, agora dentro da sidebar
        "/ui/console": "/ui/demanda-detalhe",  # auditoria técnica → aba Governança da demanda
    }
    for _rota, _destino in _LEGADAS.items():
        router.add_api_route(
            _rota, _redirecionar(_destino), methods=["GET"], include_in_schema=False
        )

    @router.get("/ui/demanda-nova", include_in_schema=False)
    def ui_demanda_nova() -> FileResponse:
        """Tela 03 — cadastro completo de demanda (wf §5.2, ADR-0039)."""
        return FileResponse(_STATIC_DIR / "demanda-nova.html")

    @router.get("/ui/demanda-estrutura", include_in_schema=False)
    def ui_demanda_estrutura() -> FileResponse:
        """Tela 10 — estrutura da demanda em árvore (wf §12, ADR-0040)."""
        return FileResponse(_STATIC_DIR / "demanda-estrutura.html")

    @router.get("/ui/card-detalhe", include_in_schema=False)
    def ui_card_detalhe() -> FileResponse:
        """Tela 12 — detalhes do card com 10 abas (wf §14, ADR-0041)."""
        return FileResponse(_STATIC_DIR / "card-detalhe.html")

    @router.get("/ui/regras-roteamento", include_in_schema=False)
    def ui_regras_roteamento() -> FileResponse:
        """Tela 31 — editor visual de regras de roteamento (wf §33, ADR-0042)."""
        return FileResponse(_STATIC_DIR / "regras-roteamento.html")

    @router.get("/ui/demanda-detalhe", include_in_schema=False)
    def ui_demanda_detalhe() -> FileResponse:
        """Tela 04 — detalhes da demanda com 11 abas e progresso (wf §6, ADR-0043)."""
        return FileResponse(_STATIC_DIR / "demanda-detalhe.html")

    # Sidebar de 16 seções (wf §2.4, ADR-0036) — ver docs/mapa-paginas.md para o
    # card FID que implementa o conteúdo de cada uma. Registradas como rotas
    # explícitas de nome fixo (mesmo padrão das 4 acima, geradas em laço só para
    # não repetir 16 funções quase idênticas) — NUNCA um path curinga: um
    # `/ui/{secao}` interceptaria `/ui/tokens.css`/`components.css`/`header.js`/
    # `sidebar.js` antes deles chegarem ao mount de `StaticFiles` abaixo.
    _SIDEBAR_SECOES = (
        "dashboard",
        "demandas",
        "esteira",
        "kanban",
        "agentes",
        "modelos",
        "documentos",
        "aprovacoes",
        "execucoes",
        "testes",
        "code-reviews",
        "implantacoes",
        "incidentes",
        "auditoria",
        "metricas",
        "configuracoes",
    )

    def _ui_secao_handler(nome_arquivo: str) -> Callable[[], FileResponse]:
        def handler() -> FileResponse:
            return FileResponse(_STATIC_DIR / nome_arquivo)

        return handler

    for _secao in _SIDEBAR_SECOES:
        router.add_api_route(
            f"/ui/{_secao}",
            _ui_secao_handler(f"{_secao}.html"),
            methods=["GET"],
            include_in_schema=False,
        )

    return router
