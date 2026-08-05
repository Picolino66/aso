"""Hierarquia épico → história → subtarefa (§7 do fluxo.md, ADR-0025).

Funções puras sobre um mapa `{id: KanbanCard}` — sem I/O — para serem testadas
isoladamente e reaproveitadas por `BoardService.add_card`/`move_card`. Pendência
nomeada três vezes (plano4 §2.4, plano5 §2.4, ADR-0022): até aqui `KanbanCard`
não tinha `parent_id` e nenhum caminho produzia card que não fosse `TASK`.
"""

from __future__ import annotations

from aso.kanban.models import KanbanCard
from aso.shared.types import ColumnKey

# Epic → Feature → Task. Sem limite, um agente (ou um LLM alucinando estrutura)
# cria uma árvore infinita e a UI trava (plano6 §3.3).
PROFUNDIDADE_MAXIMA = 3


def profundidade(cards: dict[str, KanbanCard], card_id: str) -> int:
    """Nível do card na hierarquia (1 = raiz, sem pai)."""
    nivel = 1
    visitados = {card_id}
    atual = cards.get(card_id)
    while atual is not None and atual.parent_id is not None:
        if atual.parent_id in visitados:
            break  # ciclo pré-existente — não trava a leitura, só para de subir
        visitados.add(atual.parent_id)
        atual = cards.get(atual.parent_id)
        nivel += 1
    return nivel


def fecha_ciclo(cards: dict[str, KanbanCard], card_id: str, novo_parent_id: str) -> bool:
    """True se `novo_parent_id` (ou algum ancestral dele) é o próprio `card_id`."""
    visitados: set[str] = set()
    atual: str | None = novo_parent_id
    while atual is not None:
        if atual == card_id:
            return True
        if atual in visitados:
            return False
        visitados.add(atual)
        pai = cards.get(atual)
        atual = pai.parent_id if pai is not None else None
    return False


def filhos(cards: dict[str, KanbanCard], card_id: str) -> list[KanbanCard]:
    return [c for c in cards.values() if c.parent_id == card_id]


def filhos_em_aberto(cards: dict[str, KanbanCard], card_id: str) -> list[KanbanCard]:
    """Filhos ainda não `Done`/`Cancelled` — impede o pai de fechar antes deles."""
    terminais = (ColumnKey.DONE, ColumnKey.CANCELLED)
    return [c for c in filhos(cards, card_id) if c.status not in terminais]
