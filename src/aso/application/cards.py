"""`CardService` — operações manuais do board e diagnóstico de cards (ADR-0066).

MEL-32, passo 11c: criação/movimentação/bloqueio de cards, controles em voo (pausa,
contexto adicional), diffs e diagnósticos de falha saem da façade. Toda mutação passa pelo
lock do `BundleStore`; card em execução não é movido (claim, ADR-0058).
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from aso.application.bundles import BundleStore, OrchestrationBundle
from aso.application.execution import ExecutionService
from aso.application.queries import QueryService
from aso.application.settings import ExecutionSettingsService
from aso.control.failure import FailureRecord, confianca_diagnostico, diagnosticar
from aso.control.models import Orchestration
from aso.execution.catalog import ExecutorCatalog
from aso.execution.worktree import WorktreeError, WorktreeManager
from aso.kanban.models import KanbanCard
from aso.kanban.transitions import (
    ROTULOS_WIREFRAME,
    TRANSICOES_VALIDAS,
    motivo_transicao_invalida,
    transicao_valida,
)
from aso.persistence.ports import OrchestrationRepository
from aso.shared.ids import now_iso
from aso.shared.types import AssigneeType, CardType, ColumnKey, Phase


class CardService:
    """Operações manuais do board (criar, mover, bloquear, pausar) e diagnóstico de cards."""

    def __init__(
        self,
        store: BundleStore,
        *,
        repository: OrchestrationRepository,
        queries: QueryService,
        settings: ExecutionSettingsService,
        catalogo: Callable[[], ExecutorCatalog | None],
    ) -> None:
        self._bundle_store = store
        self._repo = repository
        self._queries = queries
        self._settings = settings
        self._catalogo = catalogo

    @property
    def _catalog(self) -> ExecutorCatalog | None:
        return self._catalogo()

    def _bundle(self, orchestration_id: str) -> OrchestrationBundle:
        return self._bundle_store.get(orchestration_id)

    def _persist(self, b: OrchestrationBundle) -> None:
        self._bundle_store.persist(b)

    def _lock_for(self, orchestration_id: str) -> threading.RLock:
        return self._bundle_store.lock_for(orchestration_id)

    def _workspace_for(self, b: OrchestrationBundle) -> WorktreeManager:
        return self._settings._workspace_for(b)

    def get_cards(self, orchestration_id: str) -> list[KanbanCard]:
        return self._queries.get_cards(orchestration_id)

    @staticmethod
    def _recusar_se_em_execucao(card: KanbanCard) -> None:
        ExecutionService._recusar_se_em_execucao(card)

    def create_card(
        self,
        orchestration_id: str,
        *,
        title: str,
        type: CardType = CardType.TASK,
        parent_id: str | None = None,
        description: str = "",
    ) -> KanbanCard:
        """Tela 10 (wf §12, ADR-0040): cria um item em qualquer nível da
        hierarquia — reaproveita `BoardService.add_card`, que já valida
        `parent_id` (existência, ciclo, profundidade máxima)."""
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            card = KanbanCard(
                board_id=b.board.id,
                orchestration_id=orchestration_id,
                phase=b.orchestration.current_phase,
                type=type,
                title=title,
                description=description,
                parent_id=parent_id,
                status=ColumnKey.BACKLOG,
            )
            b.board_service.add_card(card)
            self._persist(b)
            return card

    def recover_invalid_execution(self, orchestration_id: str) -> Orchestration:
        """Invalida execuções históricas sem diff/exit válido e retorna à F5.

        Reparo de dados antigos, mantido pela MEL-53 (ADR-0075) — revisar para remoção a partir
        de 2027-03-15, quando nenhuma orquestração anterior ao executor CLI real existir.

        É uma ação administrativa explícita: não reescreve patches nem snapshots;
        apenas fecha aprovações futuras e torna o card reexecutável sob as regras novas.
        """
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            invalid_cards = {
                patch.card_id
                for patch in b.bus.patches
                if patch.card_id
                and isinstance(patch.content, dict)
                and (patch.content.get("exit_code", 0) != 0 or patch.content.get("diff_lines") == 0)
            }
            if not invalid_cards:
                raise ValueError("Não há execução inválida para recuperar.")
            for card_id in invalid_cards:
                card = b.board_service.get_card(card_id)
                if card is not None:
                    b.board_service.move_card(
                        card_id, ColumnKey.FAILED, reason="Execução histórica sem diff válido"
                    )
            for approval in b.approvals:
                if approval.status == "pending" and approval.payload.get("kind") == "phase_gate":
                    approval.status = "cancelled"
            b.orchestration.current_phase = Phase.F5
            b.orchestration.status = "waiting_human"
            b.event_log.append(
                "InvalidExecutionRecovered", {"cards": sorted(invalid_cards), "phase": "F5"}
            )
            self._persist(b)
            return b.orchestration

    # ------------------------------------------------- cards: mover/atribuir (§28.2)
    def move_card(self, orchestration_id: str, card_id: str, to_column: str) -> KanbanCard:
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            card = b.board_service.move_card(card_id, ColumnKey(to_column))
            self._persist(b)
            return card

    def move_card_validado(self, orchestration_id: str, card_id: str, to_column: str) -> KanbanCard:
        """Movimentação MANUAL (Tela 11, wf §35, ADR-0047) — único chamador real de
        `move_card` que precisa respeitar a máquina de estados; usado pelo endpoint
        HTTP de mover card (drag-and-drop). Automação interna continua chamando
        `board_service.move_card` diretamente (ou este `move_card` sem validação),
        sem essa restrição — ver `kanban/transitions.py`."""
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            card = b.board_service.get_card(card_id)
            if card is None:
                raise KeyError(f"Card inexistente: {card_id}")
            # Arrastar um card em execução para outra coluna desfaria o claim por baixo
            # do agente que ainda está rodando (ADR-0058).
            self._recusar_se_em_execucao(card)
            destino = ColumnKey(to_column)
            if not transicao_valida(card.status, destino):
                raise ValueError(motivo_transicao_invalida(card.status, destino))
            moved = b.board_service.move_card(card_id, destino)
            self._persist(b)
            return moved

    def kanban_board(self, orchestration_id: str) -> dict[str, object]:
        """Tela 11 (wf §13, ADR-0047): as 16 colunas reais, cada uma com o rótulo do
        wireframe quando existe (§13.1 tem só 14 nomes) e os cards com os 11 campos
        do §13.3 já resolvidos (agente/modelo/effort cruzados, aprovação humana
        pendente já filtrada por card) — evita N+1 no cliente."""
        b = self._bundle(orchestration_id)
        cards = b.board_service.cards_of(b.board.id)
        pendentes = {a.card_id for a in b.approvals if a.status == "pending" and a.card_id}
        colunas = []
        for coluna in ColumnKey:
            cards_da_coluna = [c for c in cards if c.status == coluna]
            colunas.append(
                {
                    "coluna": coluna.value,
                    "rotulo": ROTULOS_WIREFRAME.get(coluna, coluna.value),
                    "cards": [self._resumo_kanban(c, pendentes) for c in cards_da_coluna],
                }
            )
        return {
            "colunas": colunas,
            "transicoes": {
                k.value: sorted(v.value for v in vs) for k, vs in TRANSICOES_VALIDAS.items()
            },
        }

    def _resumo_kanban(self, card: KanbanCard, pendentes: set[str]) -> dict[str, object]:
        ultima_tentativa = card.tentativas[-1] if card.tentativas else {}
        executor = ultima_tentativa.get("executor") or card.executor
        perfil = self._catalog.get(executor) if self._catalog and executor else None
        return {
            "id": card.id,
            "titulo": card.title,
            "prioridade": card.priority.value,
            "agente": card.assignee,
            "modelo": (perfil.model if perfil and perfil.model else executor),
            "effort": ultima_tentativa.get("effort"),
            "tentativas": card.tentativa_atual,
            "falhas": len(card.failures),
            "falhas_truncadas": len(card.failures) >= 5,
            "bloqueado": card.status == ColumnKey.BLOCKED,
            "block_reason": card.block_reason,
            "aprovacao_humana_pendente": card.id in pendentes,
            "atualizado_em": card.updated_at,
        }

    def block_card(self, orchestration_id: str, card_id: str, reason: str) -> KanbanCard:
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            card = b.board_service.move_card(card_id, ColumnKey.BLOCKED, reason=reason)
            self._persist(b)
            return card

    def unblock_card(self, orchestration_id: str, card_id: str) -> KanbanCard:
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            card = b.board_service.move_card(card_id, ColumnKey.READY)
            self._persist(b)
            return card

    def cancel_card(self, orchestration_id: str, card_id: str, reason: str = "") -> KanbanCard:
        """Cancela um card individualmente (§8 do fluxo.md) — distinto de `cancel`,
        que é o kill-switch da orquestração inteira."""
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            card = b.board_service.move_card(card_id, ColumnKey.CANCELLED, reason=reason)
            self._persist(b)
            return card

    def assign_agent(self, orchestration_id: str, card_id: str, agent: str) -> KanbanCard:
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            card = b.board_service.get_card(card_id)
            if card is None:
                raise KeyError(f"Card inexistente: {card_id}")
            card.assignee = agent
            card.assignee_type = AssigneeType.AGENT
            b.event_log.append("CardAssigned", {"card_id": card_id, "agent": agent})
            self._persist(b)
            return card

    # ------------------------------------------------------- consultas (leitura)
    def cards_by_status(self, orchestration_id: str, status: str) -> list[str]:
        self._bundle(orchestration_id)
        return self._repo.cards_by_status(orchestration_id, status)

    def adrs_by_status(self, orchestration_id: str, status: str) -> list[str]:
        self._bundle(orchestration_id)
        return self._repo.adrs_by_status(orchestration_id, status)

    def cards_linked_to_adr(self, orchestration_id: str, adr_id: str) -> list[str]:
        self._bundle(orchestration_id)
        return self._repo.cards_linked_to_adr(orchestration_id, adr_id)

    def filter_cards(
        self,
        orchestration_id: str,
        *,
        status: str | None = None,
        card_type: str | None = None,
        assignee: str | None = None,
    ) -> list[KanbanCard]:
        cards = self.get_cards(orchestration_id)
        if status:
            cards = [c for c in cards if c.status.value == status]
        if card_type:
            cards = [c for c in cards if c.type.value == card_type]
        if assignee:
            cards = [c for c in cards if c.assignee == assignee]
        return cards

    def get_card_failures(self, orchestration_id: str, card_id: str) -> list[dict[str, object]]:
        """Histórico de falhas do card (§13, ADR-0019) — ring das últimas 5."""
        b = self._bundle(orchestration_id)
        card = b.board_service.get_card(card_id)
        if card is None:
            raise KeyError(f"Card inexistente: {card_id}")
        return list(card.failures)

    def get_card_closure(self, orchestration_id: str, card_id: str) -> dict[str, object]:
        """Ficha de encerramento do card (§23, ADR-0021) — vazio = card ainda não
        encerrado (preenchida em `merge_pr`)."""
        b = self._bundle(orchestration_id)
        card = b.board_service.get_card(card_id)
        if card is None:
            raise KeyError(f"Card inexistente: {card_id}")
        return dict(card.closure)

    def get_card_failure_diagnostics(
        self, orchestration_id: str, card_id: str
    ) -> list[dict[str, object]]:
        """Tela 17 (wf §19.1/§19.3): histórico de falhas com diagnóstico e confiança
        calculados NA LEITURA (nunca persistidos como palpite) — mesmas funções
        puras `diagnosticar`/`confianca_diagnostico` já usadas no roteamento
        automático de falha (ADR-0019)."""
        b = self._bundle(orchestration_id)
        card = b.board_service.get_card(card_id)
        if card is None:
            raise KeyError(f"Card inexistente: {card_id}")
        resultado: list[dict[str, object]] = []
        for bruto in card.failures:
            record = FailureRecord.model_validate(bruto)
            resultado.append(
                {
                    **bruto,
                    "diagnostico": diagnosticar(record),
                    "confianca": confianca_diagnostico(record),
                }
            )
        return resultado

    def get_card_changed_files(self, orchestration_id: str, card_id: str) -> list[str]:
        """Arquivos alterados (Tela 15, wf §17.1) — diff real da branch do card
        contra HEAD; lista vazia quando o card nunca teve worktree/branch (honesto,
        não fabricado)."""
        b = self._bundle(orchestration_id)
        card = b.board_service.get_card(card_id)
        if card is None:
            raise KeyError(f"Card inexistente: {card_id}")
        if not card.branch or not b.orchestration.target_path:
            return []
        try:
            return self._workspace_for(b).changed_files(card.branch)
        except WorktreeError:
            return []

    def get_card_diff_stats(self, orchestration_id: str, card_id: str) -> dict[str, int]:
        """Resumo do review (Tela 18, wf §20.1, ADR-0049): commits, arquivos
        alterados, linhas adicionadas/removidas — tudo zero quando o card nunca
        teve worktree/branch (honesto, não fabricado), mesmo raciocínio de
        `get_card_changed_files`."""
        b = self._bundle(orchestration_id)
        card = b.board_service.get_card(card_id)
        if card is None:
            raise KeyError(f"Card inexistente: {card_id}")
        vazio = {
            "commits": 0,
            "arquivos_alterados": 0,
            "linhas_adicionadas": 0,
            "linhas_removidas": 0,
        }
        if not card.branch or not b.orchestration.target_path:
            return vazio
        try:
            workspace = self._workspace_for(b)
            commits = workspace.commit_count(card.branch)
            arquivos = len(workspace.changed_files(card.branch))
            adicionadas, removidas = workspace.line_stats(card.branch)
        except WorktreeError:
            return vazio
        return {
            "commits": commits,
            "arquivos_alterados": arquivos,
            "linhas_adicionadas": adicionadas,
            "linhas_removidas": removidas,
        }

    def pause_card(
        self, orchestration_id: str, card_id: str, *, pausado: bool, actor: str = "system"
    ) -> KanbanCard:
        """Pausar/retomar (Tela 15, wf §17.2) — reinterpretação honesta e restrita:
        impede a PRÓXIMA execução (manual ou via `/retry`), não interrompe um
        processo em andamento (nada no runtime hoje suporta isso — ver ADR-0048)."""
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            card = b.board_service.get_card(card_id)
            if card is None:
                raise KeyError(f"Card inexistente: {card_id}")
            card.pausado = pausado
            card.updated_at = now_iso()
            b.event_log.append(
                "CardPausedToggled",
                {
                    "orchestration_id": orchestration_id,
                    "actor": actor,
                    "card_id": card_id,
                    "pausado": pausado,
                },
            )
            self._persist(b)
            return card

    def add_card_context(
        self, orchestration_id: str, card_id: str, texto: str, *, actor: str = "system"
    ) -> KanbanCard:
        """Adicionar contexto (Tela 15, wf §17.2) — entra no próximo prompt do
        agente (`_build_task`), junto de `correction_actions`."""
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            card = b.board_service.get_card(card_id)
            if card is None:
                raise KeyError(f"Card inexistente: {card_id}")
            card.contexto_adicional = [*card.contexto_adicional, texto]
            card.updated_at = now_iso()
            b.event_log.append(
                "CardContextoAdicionado",
                {"orchestration_id": orchestration_id, "actor": actor, "card_id": card_id},
            )
            self._persist(b)
            return card
