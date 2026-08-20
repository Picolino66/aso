"""Checklist de preparação para implementação (§10 do fluxo.md, wf §16) — ADR-0030.

`fluxo.md` §10 lista 8 itens que o agente responsável por um card cumpre antes de
alterar código. Nenhum deles era auditável — cumpridos implicitamente, sem registro.
Este módulo dá forma a esse checklist e o marca automaticamente nos pontos em que o
runtime já garante, de fato, cada item — nunca inventa uma confirmação que não
aconteceu (mesma disciplina de `control/qa.py`/`control/failure.py`: regra de
governança, não palpite).

**O que "concluído" significa aqui, item a item** — importante para não ler como
mais do que é: os itens 1/2/3/5/7 (especificação, critérios, código afetado, testes
existentes, plano de execução) são marcados no momento em que o runtime monta o
prompt do agente (`_build_task`) com essas informações incluídas — é um fato sobre o
que o agente *recebeu*, não uma confirmação de que ele *leu* ou *aplicou* nada. Os
itens 4/8 (dependências verificadas, card desbloqueado) e 6 (branch criada) são fatos
estruturais do próprio runtime (o guard de dependência rodou; o worktree existe).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from aso.shared.ids import now_iso

ITEM_ESPECIFICACAO_LIDA = "Especificação lida"
ITEM_CRITERIOS_ANALISADOS = "Critérios de aceite analisados"
ITEM_CODIGO_AFETADO_ANALISADO = "Código afetado analisado"
ITEM_DEPENDENCIAS_VERIFICADAS = "Dependências verificadas"
ITEM_TESTES_EXISTENTES_IDENTIFICADOS = "Testes existentes identificados"
ITEM_BRANCH_CRIADA = "Branch criada"
ITEM_PLANO_REGISTRADO = "Plano de execução registrado"
ITEM_CARD_DESBLOQUEADO = "Card desbloqueado"

# Ordem do §10 — a mesma ordem em que a UI (wf §16.1) deve listar o checklist.
ITENS_CHECKLIST_PREPARACAO: tuple[str, ...] = (
    ITEM_ESPECIFICACAO_LIDA,
    ITEM_CRITERIOS_ANALISADOS,
    ITEM_CODIGO_AFETADO_ANALISADO,
    ITEM_DEPENDENCIAS_VERIFICADAS,
    ITEM_TESTES_EXISTENTES_IDENTIFICADOS,
    ITEM_BRANCH_CRIADA,
    ITEM_PLANO_REGISTRADO,
    ITEM_CARD_DESBLOQUEADO,
)


class PreparationChecklistError(ValueError):
    """Item fora do vocabulário fechado do §10."""


class PreparationChecklistItem(BaseModel):
    """Um item marcado do checklist — sempre com autor e timestamp (auditável)."""

    item: str
    concluido: bool = True
    autor: str = "sistema"
    at: str = Field(default_factory=now_iso)


def marcar_item(
    checklist: list[dict[str, object]], item: str, *, autor: str = "sistema", concluido: bool = True
) -> list[dict[str, object]]:
    """Marca (ou desmarca) um item, substituindo qualquer marcação anterior dele.

    O checklist nunca cresce além dos 8 itens do vocabulário — reexecutar um item
    (ex.: nova tentativa após falha) atualiza o registro existente, não acumula
    histórico (diferente de `card.failures`/`qa_checks`, que são log de eventos;
    isto é estado — "o item está ou não cumprido agora").
    """
    if item not in ITENS_CHECKLIST_PREPARACAO:
        raise PreparationChecklistError(
            f"Item {item!r} fora do checklist do §10 (esperado um de {ITENS_CHECKLIST_PREPARACAO})."
        )
    novo = PreparationChecklistItem(item=item, concluido=concluido, autor=autor)
    resto = [c for c in checklist if c.get("item") != item]
    return [*resto, novo.model_dump(mode="json")]


def checklist_completo(checklist: list[dict[str, object]]) -> bool:
    """Todos os 8 itens do §10 presentes e marcados como concluídos."""
    concluidos = {c.get("item") for c in checklist if c.get("concluido")}
    return set(ITENS_CHECKLIST_PREPARACAO) <= concluidos
