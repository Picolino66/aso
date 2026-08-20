"""BoardService (§16, TASK-04).

Cria boards com as colunas padrão, gerencia cards e aplica a automação de
movimentação dirigida por eventos (§16.7). Kanban é o plano de execução (ADR-0002).
"""

from __future__ import annotations

from aso.kanban.hierarchy import (
    PROFUNDIDADE_MAXIMA,
    fecha_ciclo,
    filhos,
    filhos_em_aberto,
    profundidade,
)
from aso.kanban.models import Board, BoardColumn, CardEvent, KanbanCard
from aso.shared.events import EventLog
from aso.shared.ids import now_iso
from aso.shared.types import ColumnKey

# Colunas padrão na ordem canônica (§16.2).
_DEFAULT_COLUMNS: list[ColumnKey] = [
    ColumnKey.BACKLOG,
    ColumnKey.READY,
    ColumnKey.PLANNING,
    ColumnKey.IN_PROGRESS,
    ColumnKey.WAITING_AGENT,
    ColumnKey.WAITING_HUMAN,
    ColumnKey.REVIEW,
    ColumnKey.NEEDS_FIX,
    ColumnKey.TESTING,
    # Deploying/Validating (fluxo.md §8) são colunas selecionáveis via /cards/{id}/move
    # genérico — o gatilho automático de quando um card entra nelas é o Incremento F
    # (gate de implantação); aqui só a coluna existe.
    ColumnKey.DEPLOYING,
    ColumnKey.VALIDATING,
    ColumnKey.BLOCKED,
    ColumnKey.FAILED,
    ColumnKey.DONE,
    ColumnKey.CANCELLED,
    ColumnKey.ARCHIVED,
]

# Colunas terminais que abandonam (não satisfazem) uma dependência — ADR-0022.
_TERMINAIS_ABANDONAM: frozenset[ColumnKey] = frozenset({ColumnKey.CANCELLED, ColumnKey.ARCHIVED})

# Colunas que disparam o recálculo de dependentes ao serem alcançadas: `Done`
# satisfaz a dependência; `Cancelled`/`Archived` a abandonam (ADR-0022).
_TERMINAIS_QUE_RECOMPUTAM: frozenset[ColumnKey] = frozenset({ColumnKey.DONE, *_TERMINAIS_ABANDONAM})

# Automação: evento de runtime -> coluna destino (§16.7).
_EVENT_TRANSITIONS: dict[str, ColumnKey] = {
    "AgentStarted": ColumnKey.IN_PROGRESS,
    "AgentNeedsInput": ColumnKey.WAITING_HUMAN,
    "PROpened": ColumnKey.REVIEW,
    # CI reprovada volta para "Aguardando correção" (ADR-0019, §13 do fluxo.md): é uma
    # causa corrigível e reexecutável, não um beco sem saída — `Failed` fica reservado
    # para o que o roteamento de falha decidiu escalar para humano (ver `failure.py`).
    "CIFailed": ColumnKey.NEEDS_FIX,
    # Reprovada na revisão independente (ADR-0017) vai para "Aguardando correção"
    # (§8/§15 do fluxo.md) — distinta de "Em revisão", que ainda não tem veredito.
    "ReviewRequestedChanges": ColumnKey.NEEDS_FIX,
    "TestsPassed": ColumnKey.TESTING,
    "QualityGatePassed": ColumnKey.DONE,
    "QualityGateFailed": ColumnKey.BLOCKED,
}

# Resultado/próxima ação padrão de cada transição automática (§8 do fluxo.md,
# ADR-0019): `apply_event` preenche o `CardEvent` a partir disto — o mesmo dado que o
# §13 pede a cada falha é o que o §8 pede a cada movimentação, gravado no mesmo ponto.
_EVENT_RESULT: dict[str, tuple[str, str]] = {
    "AgentStarted": ("agente iniciou a execução", "aguardar conclusão"),
    "AgentNeedsInput": ("agente produziu patch que exige aprovação", "revisar e aprovar o patch"),
    "PROpened": ("PR aberta para o card", "rodar CI e a revisão independente"),
    "CIFailed": ("CI reprovada na branch candidata", "corrigir e reexecutar o card"),
    "ReviewRequestedChanges": (
        "revisão independente pediu alterações obrigatórias",
        "reexecutar o card com as correções listadas",
    ),
    "TestsPassed": ("execução concluída sem pendências", "abrir PR / rodar o quality gate"),
    "QualityGatePassed": ("merge governado concluído", "nenhuma — card encerrado"),
    "QualityGateFailed": ("quality gate da fase reprovado", "corrigir e rodar o gate novamente"),
}


class BoardService:
    """Serviço in-memory de boards e cards de uma orquestração."""

    def __init__(self, event_log: EventLog | None = None) -> None:
        self._boards: dict[str, Board] = {}
        self._cards: dict[str, KanbanCard] = {}
        self.card_events: list[CardEvent] = []
        self.event_log = event_log or EventLog()

    def create_board(
        self, orchestration_id: str, name: str, project_id: str | None = None
    ) -> Board:
        columns = [BoardColumn(key=key, order=i + 1) for i, key in enumerate(_DEFAULT_COLUMNS)]
        board = Board(
            orchestration_id=orchestration_id, project_id=project_id, name=name, columns=columns
        )
        self._boards[board.id] = board
        return board

    def hydrate(
        self, boards: list[Board], cards: list[KanbanCard], card_events: list[CardEvent]
    ) -> None:
        """Reidrata o serviço a partir de estado persistido."""
        self._boards = {b.id: b for b in boards}
        self._cards = {c.id: c for c in cards}
        self.card_events = list(card_events)

    def get_board(self, board_id: str) -> Board | None:
        return self._boards.get(board_id)

    def add_card(self, card: KanbanCard) -> KanbanCard:
        """Adiciona o card ao board — valida a hierarquia (§7, ADR-0025) quando
        `parent_id` está preenchido; `None` (todo card anterior a esta ADR) segue
        sem checagem, a hierarquia é opcional."""
        if card.parent_id is not None:
            if card.parent_id not in self._cards:
                raise ValueError(f"parent_id inexistente: {card.parent_id}")
            if fecha_ciclo(self._cards, card.id, card.parent_id):
                raise ValueError(f"parent_id fecha um ciclo: {card.parent_id}")
            if profundidade(self._cards, card.parent_id) >= PROFUNDIDADE_MAXIMA:
                raise ValueError(
                    f"Hierarquia excede a profundidade máxima ({PROFUNDIDADE_MAXIMA}: "
                    "Epic → Feature → Task → Task/Subtarefa)"
                )
        self._cards[card.id] = card
        self.event_log.append("CardCreated", {"card_id": card.id, "title": card.title})
        return card

    def get_card(self, card_id: str) -> KanbanCard | None:
        return self._cards.get(card_id)

    def cards_of(self, board_id: str) -> list[KanbanCard]:
        return [c for c in self._cards.values() if c.board_id == board_id]

    def move_card(
        self,
        card_id: str,
        to_status: ColumnKey,
        *,
        actor: str = "system",
        reason: str = "",
        result: str = "",
        evidence: list[str] | None = None,
        next_action: str = "",
        model: str | None = None,
        effort: str | None = None,
        phase: str | None = None,
        execution_id: str | None = None,
    ) -> KanbanCard:
        """Move o card e registra a movimentação (§8 do fluxo.md, ADR-0019): motivo,
        resultado, evidências e próxima ação — não só data e ator.

        §7 (ADR-0025): um card com filho ainda aberto (fora de `Done`/`Cancelled`)
        não pode chegar a `Done` — é o que torna a hierarquia útil em vez de
        decorativa. Cancelar, ao contrário, cascateia para os filhos abaixo.
        """
        card = self._cards[card_id]
        if to_status == ColumnKey.DONE:
            abertos = filhos_em_aberto(self._cards, card_id)
            if abertos:
                raise ValueError(
                    f"Card tem {len(abertos)} subtarefa(s) ainda não concluída(s)/"
                    f"cancelada(s): {abertos[0].title}"
                )
        from_status = card.status
        card.status = to_status
        card.updated_at = now_iso()
        if to_status == ColumnKey.BLOCKED and reason:
            card.block_reason = reason
        event = CardEvent(
            card_id=card_id,
            type="CardMoved",
            from_status=from_status,
            to_status=to_status,
            actor=actor,
            reason=reason,
            result=result,
            evidence=list(evidence or []),
            next_action=next_action,
            model=model,
            effort=effort,
            phase=phase,
            execution_id=execution_id,
        )
        self.card_events.append(event)
        self.event_log.append(
            "CardMoved",
            {"card_id": card_id, "from": from_status.value, "to": to_status.value},
        )
        if to_status in _TERMINAIS_QUE_RECOMPUTAM:
            self._refresh_dependents(card_id)
        if to_status == ColumnKey.CANCELLED:
            self._cancelar_filhos(card_id, actor=actor, motivo_pai=card.title)
        return card

    def _cancelar_filhos(self, card_id: str, *, actor: str, motivo_pai: str) -> None:
        """§7 (ADR-0025): cancelar o pai cancela os filhos — mesmo espírito da
        ADR-0022, onde um dependente de card cancelado nunca fica órfão em silêncio."""
        for filho in filhos(self._cards, card_id):
            if filho.status in (ColumnKey.DONE, ColumnKey.CANCELLED):
                continue
            self.move_card(
                filho.id, ColumnKey.CANCELLED, actor=actor, reason=f"pai cancelado: {motivo_pai}"
            )

    def _refresh_dependents(self, done_card_id: str) -> None:
        """Observador ativo de `blocked_by` (§10 do fluxo.md, ADR-0018/ADR-0021/ADR-0022).

        Sem isto, `blocked_by` só se preenchia quando alguém tentava RODAR o card
        dependente (`OrchestrationService._pending_dependencies`) — um card com
        dependência pendente que ninguém tentou rodar continuava aparecendo como
        pronto. Libera automaticamente um card que já estava em `Blocked` POR
        dependência (`blocked_by` não vazio): não mexe em cards bloqueados por outro
        motivo (conflito, roteamento de falha) — `_pending_dependencies` continua
        sendo a checagem autoritativa antes de qualquer execução.

        `Cancelled`/`Archived` (ADR-0022) são terminais que NUNCA satisfazem uma
        dependência: ao contrário de `Done`, não liberam o dependente — bloqueiam
        com motivo explícito, porque a dependência não foi cumprida, foi abandonada.
        Liberar em silêncio deixaria o card rodar sem o que ele precisava.
        """
        if done_card_id not in self._cards:
            return
        for dependente in list(self._cards.values()):
            if (
                done_card_id not in dependente.dependencies
                or dependente.status in _TERMINAIS_QUE_RECOMPUTAM
            ):
                continue
            pendentes = [
                dep_id
                for dep_id in dependente.dependencies
                if (dep := self._cards.get(dep_id)) is not None and dep.status != ColumnKey.DONE
            ]
            abandonadas = [
                dep_id
                for dep_id in dependente.dependencies
                if (dep := self._cards.get(dep_id)) is not None
                and dep.status in _TERMINAIS_ABANDONAM
            ]
            tinha_pendencia = bool(dependente.blocked_by)
            dependente.blocked_by = pendentes
            if abandonadas:
                titulos = ", ".join(
                    self._cards[dep_id].title for dep_id in abandonadas if dep_id in self._cards
                )
                self.move_card(
                    dependente.id,
                    ColumnKey.BLOCKED,
                    reason=f"dependência(s) cancelada(s)/arquivada(s): {titulos}",
                )
            elif not pendentes and tinha_pendencia and dependente.status == ColumnKey.BLOCKED:
                self.move_card(dependente.id, ColumnKey.READY, reason="dependência(s) resolvida(s)")

    def apply_event(
        self,
        card_id: str,
        event_name: str,
        *,
        model: str | None = None,
        effort: str | None = None,
        phase: str | None = None,
        execution_id: str | None = None,
    ) -> KanbanCard:
        """Aplica a automação de coluna a partir de um evento de runtime (§16.7)."""
        to_status = _EVENT_TRANSITIONS.get(event_name)
        if to_status is None:
            raise KeyError(f"Evento sem transição automática definida: {event_name}")
        resultado, proxima = _EVENT_RESULT.get(event_name, ("", ""))
        return self.move_card(
            card_id,
            to_status,
            actor="automation",
            result=resultado,
            next_action=proxima,
            model=model,
            effort=effort,
            phase=phase,
            execution_id=execution_id,
        )
