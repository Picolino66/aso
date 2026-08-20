"""Máquina de estados do card (Tela 11, wf §35, ADR-0047).

`specs/kanban.md` (TASK-04/ADR-0002) já previa "movimentos inválidos são
rejeitados" — nunca implementado até aqui. Este módulo paga essa dívida, não é
escopo novo inventado pelo FID-20.

Só valida o caminho MANUAL de movimentação (drag-and-drop / `PUT` do endpoint
HTTP, via `OrchestrationService.move_card_validado`) — a automação interna do
runtime (roteamento de falha, liberação de dependência, eventos de execução)
continua chamando `BoardService.move_card` diretamente, sem esta restrição:
essas regras de negócio já decidem sozinhas transições sensatas, e algumas
(ex.: escalar para `Failed`) não têm correspondência nas 14 colunas do
wireframe — não faz sentido restringir uma decisão automática já madura para
caber num diagrama pensado para o operador humano mover cards manualmente.

Grafo derivado do diagrama de estados do wf §35, com os nomes do wireframe
mapeados para `ColumnKey` reais (`EmAnalise`→`PLANNING`,
`AguardandoAprovacao`→`WAITING_HUMAN`, `ProntoDesenvolvimento`→`READY`,
`EmDesenvolvimento`→`IN_PROGRESS`, `EmTestes`→`TESTING`, `EmRevisao`→`REVIEW`,
`AguardandoCorrecao`→`NEEDS_FIX`, `EmImplantacao`→`DEPLOYING`,
`EmValidacao`→`VALIDATING`, `Concluido`→`DONE`, `Cancelado`→`CANCELLED`,
`Bloqueado`→`BLOCKED`). Dois estados do diagrama não têm `ColumnKey` própria:
"Pronto para implantação" (entre Review e Deploying) e "Rollback" (estado
transitório entre Validating e NeedsFix) — colapsados nas arestas reais
adjacentes (`REVIEW→DEPLOYING` direto; `VALIDATING→NEEDS_FIX` direto),
documentado na ADR-0047, não escondido. `WAITING_AGENT`/`FAILED`/`ARCHIVED`
não aparecem nem no wireframe nem na automação real (`_EVENT_TRANSITIONS`,
`board_service.py`) — o grafo não define nenhuma aresta de/para eles no
caminho manual; continuam alcançáveis só pelos caminhos internos que já os
usam hoje (ex.: roteamento de falha grava `Failed` via `BoardService`
diretamente).
"""

from __future__ import annotations

from aso.shared.types import ColumnKey

# Rótulo do wireframe (wf §13.1) — só para os 11 que têm nome próprio ali;
# os outros 5 ColumnKey (WaitingAgent/Failed/Archived + os 2 colapsados) usam
# o próprio nome do enum como rótulo (sem fabricar um nome que o wireframe
# não deu).
ROTULOS_WIREFRAME: dict[ColumnKey, str] = {
    ColumnKey.BACKLOG: "Backlog",
    ColumnKey.PLANNING: "Em análise",
    ColumnKey.WAITING_HUMAN: "Aguardando aprovação",
    ColumnKey.READY: "Pronto para desenvolvimento",
    ColumnKey.IN_PROGRESS: "Em desenvolvimento",
    ColumnKey.TESTING: "Em testes",
    ColumnKey.REVIEW: "Em revisão",
    ColumnKey.NEEDS_FIX: "Aguardando correção",
    ColumnKey.DEPLOYING: "Em implantação",
    ColumnKey.VALIDATING: "Em validação",
    ColumnKey.DONE: "Concluído",
    ColumnKey.BLOCKED: "Bloqueado",
    ColumnKey.CANCELLED: "Cancelado",
}

TRANSICOES_VALIDAS: dict[ColumnKey, frozenset[ColumnKey]] = {
    ColumnKey.BACKLOG: frozenset({ColumnKey.PLANNING, ColumnKey.CANCELLED}),
    ColumnKey.PLANNING: frozenset({ColumnKey.WAITING_HUMAN, ColumnKey.CANCELLED}),
    ColumnKey.WAITING_HUMAN: frozenset({ColumnKey.READY, ColumnKey.PLANNING}),
    ColumnKey.READY: frozenset({ColumnKey.IN_PROGRESS}),
    ColumnKey.IN_PROGRESS: frozenset({ColumnKey.TESTING, ColumnKey.BLOCKED}),
    ColumnKey.BLOCKED: frozenset({ColumnKey.READY, ColumnKey.CANCELLED}),
    ColumnKey.TESTING: frozenset({ColumnKey.REVIEW, ColumnKey.NEEDS_FIX}),
    ColumnKey.REVIEW: frozenset({ColumnKey.DEPLOYING, ColumnKey.NEEDS_FIX}),
    ColumnKey.NEEDS_FIX: frozenset({ColumnKey.IN_PROGRESS}),
    ColumnKey.DEPLOYING: frozenset({ColumnKey.VALIDATING, ColumnKey.NEEDS_FIX}),
    ColumnKey.VALIDATING: frozenset({ColumnKey.DONE, ColumnKey.NEEDS_FIX}),
    ColumnKey.DONE: frozenset(),
    ColumnKey.CANCELLED: frozenset(),
    ColumnKey.WAITING_AGENT: frozenset(),
    ColumnKey.FAILED: frozenset(),
    ColumnKey.ARCHIVED: frozenset(),
}


def transicao_valida(de: ColumnKey, para: ColumnKey) -> bool:
    """Mover para a mesma coluna é sempre um no-op válido (não é uma "transição")."""
    if de == para:
        return True
    return para in TRANSICOES_VALIDAS.get(de, frozenset())


def motivo_transicao_invalida(de: ColumnKey, para: ColumnKey) -> str:
    permitidas = sorted(c.value for c in TRANSICOES_VALIDAS.get(de, frozenset()))
    destino = ", ".join(permitidas) if permitidas else "nenhuma (estado terminal ou sem uso manual)"
    return (
        f"Transição inválida: '{de.value}' não pode ir direto para '{para.value}'. "
        f"Transições permitidas a partir de '{de.value}': {destino}."
    )
