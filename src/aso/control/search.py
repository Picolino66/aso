"""Busca global de texto livre (wf §2.3, "Campo de busca") — ADR-0035.

Varre demandas, cards e ADRs por substring case-insensitive no título. Sem
índice, sem ranking: o runtime não tem volume que justifique isso hoje — o
mesmo raciocínio "dev-scale, não hyperscale" já aplicado a `list_all_approvals`
(itera todas as orquestrações a cada chamada). Puro: recebe os itens já
buscados pelo serviço (que faz o I/O) e devolve os que casam.
"""

from __future__ import annotations

from pydantic import BaseModel


class SearchItem(BaseModel):
    """Um item buscável — mesma forma serve de índice e de resultado, já que a
    única operação é substring no título."""

    tipo: str  # demanda | card | documento
    titulo: str
    orchestration_id: str
    card_id: str | None = None
    adr_id: str | None = None


def buscar(query: str, itens: list[SearchItem], *, limite: int = 30) -> list[SearchItem]:
    """Substring case-insensitive no título. Query vazia (ou só espaços) não
    devolve tudo — devolve nada, para não fingir busca no primeiro caractere."""
    termo = query.strip().lower()
    if not termo:
        return []
    return [item for item in itens if termo in item.titulo.lower()][:limite]
