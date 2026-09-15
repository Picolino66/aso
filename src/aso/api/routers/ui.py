"""Rotas de console web: páginas estáticas do console.

Extraídas do `create_app` monolítico no MEL-32 passo 10 (ADR-0066).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

from aso.api.deps import ApiDeps

_STATIC_DIR = Path(__file__).resolve().parents[1] / "static"


def criar_router(deps: ApiDeps) -> APIRouter:
    router = APIRouter()

    # -- UI: rotas explícitas (precedem o mount de arquivos estáticos) ----------
    @router.get("/ui/", include_in_schema=False)
    def ui_macro() -> FileResponse:
        """Kanban Macro: visão global de todos os projetos e cards (tela inicial)."""
        return FileResponse(_STATIC_DIR / "macro.html")

    @router.get("/ui/nova", include_in_schema=False)
    def ui_nova() -> FileResponse:
        """Formulário focado de nova orquestração (sem outras orquestrações)."""
        return FileResponse(_STATIC_DIR / "nova.html")

    @router.get("/ui/detalhe", include_in_schema=False)
    def ui_detalhe() -> FileResponse:
        """Sala de controle de UMA orquestração: fase, próximo passo e pendências."""
        return FileResponse(_STATIC_DIR / "detalhe.html")

    @router.get("/ui/console", include_in_schema=False)
    def ui_console() -> FileResponse:
        """Console técnico completo (abas de auditoria) — mantido para operação avançada."""
        return FileResponse(_STATIC_DIR / "index.html")

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
