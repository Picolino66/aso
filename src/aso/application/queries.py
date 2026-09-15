"""`QueryService` — consultas de leitura extraídas do `OrchestrationService` (ADR-0066).

MEL-32, passo 2.

Listagens, busca, dashboard, header, auditoria e leituras por orquestração. Não muta estado:
lê bundles pelo `BundleStore` (cache compartilhado com a façade) e o repositório direto quando
a consulta não precisa hidratar agregados.
"""

from __future__ import annotations

import csv
import io
from typing import Any

from aso.application.bundles import BundleStore, OrchestrationBundle
from aso.control.models import ExecutionPlan, Orchestration
from aso.control.search import SearchItem, buscar
from aso.control.triage import DemandBrief
from aso.governance.models import (
    ADR,
    BugReport,
    CandidateRun,
    Conflict,
    ContextPatch,
    HumanApproval,
    Incident,
    PullRequest,
    QualityGateResult,
    ReviewComment,
    SloEvaluation,
    Snapshot,
)
from aso.kanban.hierarchy import montar_arvore
from aso.kanban.models import CardEvent, KanbanCard
from aso.persistence.ports import OrchestrationRepository
from aso.shared.cache import TTLCache
from aso.shared.events import DomainEvent


class QueryService:
    """Consultas de leitura (sem mutação)."""

    # Limite defensivo do export — a auditoria é append-only e cresce sem
    # limite; exportar "tudo" sem teto arrisca esgotar memória num sistema
    # maduro. Filtre antes de exportar para um recorte menor que este teto.
    _AUDIT_EXPORT_LIMITE = 5000
    _AUDIT_CSV_COLUNAS: tuple[tuple[str, str], ...] = (
        ("created_at", "Data e hora"),
        ("project_id", "Projeto"),
        ("demanda", "Demanda"),
        ("card_titulo", "Card"),
        ("phase", "Etapa"),
        ("actor", "Agente"),
        ("model", "Modelo"),
        ("effort", "Effort"),
        ("type", "Ação"),
        ("reason", "Motivo"),
        ("result", "Resultado"),
        ("evidence", "Evidências"),
        ("next_action", "Próxima ação"),
        ("execution_id", "Identificador da execução"),
    )

    def __init__(
        self, store: BundleStore, repository: OrchestrationRepository, read_cache: TTLCache
    ) -> None:
        self._bundle_store = store
        self._repo = repository
        self._read_cache = read_cache

    def _bundle(self, orchestration_id: str) -> OrchestrationBundle:
        return self._bundle_store.get(orchestration_id)

    def list_all(
        self,
        *,
        project_id: str | None = None,
        status: str | None = None,
        q: str | None = None,
        executor: str | None = None,
        created_from: str | None = None,
        created_to: str | None = None,
        tipo: str | None = None,
        risco: str | None = None,
        complexidade: str | None = None,
        impacto: str | None = None,
        aprovacao_humana: bool | None = None,
    ) -> list[Orchestration]:
        # Leitura leve: consulta a tabela de orquestrações, sem hidratar aggregates.
        # Sem filtro "caro" (Tela 02, ver `list_orchestrations_page`), uma única
        # query SQL; com filtro caro, filtra em memória sobre os candidatos
        # baratos — devolve tudo (sem paginar), então não há matemática de página
        # a preservar aqui, só o mesmo filtro de `list_orchestrations_page`.
        if self._sem_filtro_caro(tipo, risco, complexidade, impacto, aprovacao_humana):
            return self._repo.list_orchestrations(
                project_id=project_id,
                status=status,
                q=q,
                executor=executor,
                created_from=created_from,
                created_to=created_to,
            )[0]
        candidatos, _ = self._repo.list_orchestrations(
            project_id=project_id,
            status=status,
            q=q,
            executor=executor,
            created_from=created_from,
            created_to=created_to,
        )
        return self._filtra_por_brief_e_aprovacao(
            candidatos,
            tipo=tipo,
            risco=risco,
            complexidade=complexidade,
            impacto=impacto,
            aprovacao_humana=aprovacao_humana,
        )

    @staticmethod
    def _sem_filtro_caro(
        tipo: str | None,
        risco: str | None,
        complexidade: str | None,
        impacto: str | None,
        aprovacao_humana: bool | None,
    ) -> bool:
        return (
            tipo is None
            and risco is None
            and complexidade is None
            and impacto is None
            and aprovacao_humana is None
        )

    def _filtra_por_brief_e_aprovacao(
        self,
        candidatos: list[Orchestration],
        *,
        tipo: str | None,
        risco: str | None,
        complexidade: str | None,
        impacto: str | None,
        aprovacao_humana: bool | None,
    ) -> list[Orchestration]:
        pendentes = (
            self._repo.orchestration_ids_with_pending_approval()
            if aprovacao_humana is not None
            else set()
        )
        return [
            o
            for o in candidatos
            if self._bate_filtros_de_brief(
                o, tipo=tipo, risco=risco, complexidade=complexidade, impacto=impacto
            )
            and (aprovacao_humana is None or (o.id in pendentes) == aprovacao_humana)
        ]

    def list_orchestrations_page(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        project_id: str | None = None,
        status: str | None = None,
        q: str | None = None,
        executor: str | None = None,
        created_from: str | None = None,
        created_to: str | None = None,
        tipo: str | None = None,
        risco: str | None = None,
        complexidade: str | None = None,
        impacto: str | None = None,
        aprovacao_humana: bool | None = None,
    ) -> dict[str, object]:
        """Tela 02 (Lista de demandas, wf §4.2, ADR-0038) — 6 filtros baratos
        (coluna real/indexada, aplicados em SQL: `project_id`, `status`, `q`,
        `executor`, `created_from`/`created_to`) e 5 que exigem ler
        `demand_brief` (JSON sem índice) ou aprovação pendente (`tipo`, `risco`,
        `complexidade`, `impacto`, `aprovacao_humana`) — esses últimos rodam em
        memória, SOBRE o resultado já filtrado pelos baratos (nunca sobre todas
        as orquestrações do sistema), preservando a paginação correta.
        """
        page = max(page, 1)
        if self._sem_filtro_caro(tipo, risco, complexidade, impacto, aprovacao_humana):
            items, total = self._repo.list_orchestrations(
                limit=page_size,
                offset=(page - 1) * page_size,
                project_id=project_id,
                status=status,
                q=q,
                executor=executor,
                created_from=created_from,
                created_to=created_to,
            )
            return {"items": items, "total": total, "page": page, "page_size": page_size}

        candidatos, _ = self._repo.list_orchestrations(
            project_id=project_id,
            status=status,
            q=q,
            executor=executor,
            created_from=created_from,
            created_to=created_to,
        )
        filtrados = self._filtra_por_brief_e_aprovacao(
            candidatos,
            tipo=tipo,
            risco=risco,
            complexidade=complexidade,
            impacto=impacto,
            aprovacao_humana=aprovacao_humana,
        )
        total = len(filtrados)
        inicio = (page - 1) * page_size
        return {
            "items": filtrados[inicio : inicio + page_size],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    @staticmethod
    def _bate_filtros_de_brief(
        orchestration: Orchestration,
        *,
        tipo: str | None,
        risco: str | None,
        complexidade: str | None,
        impacto: str | None,
    ) -> bool:
        """Puro: os 4 filtros de demanda (Tela 02) que vivem dentro de
        `demand_brief` (ADR-0016) — não têm coluna própria, então não dá para
        aplicar em SQL sem um índice novo (fora do escopo deste card)."""
        if tipo is None and risco is None and complexidade is None and impacto is None:
            return True
        brief = DemandBrief.model_validate(orchestration.demand_brief)
        if tipo is not None and brief.tipo != tipo:
            return False
        if risco is not None and brief.risco.value != risco:
            return False
        if complexidade is not None and brief.complexidade != complexidade:
            return False
        if impacto is not None and impacto not in brief.impactos:
            return False
        return True

    def aggregate_metrics(self) -> dict[str, object]:
        cached = self._read_cache.get("aggregate")
        if cached is not None:
            return cached  # type: ignore[no-any-return]
        data = self._repo.aggregate_metrics()
        self._read_cache.set("aggregate", data)
        return data

    def header_summary(self, *, project_id: str | None = None) -> dict[str, object]:
        """Indicadores do header (wf §2.3, ADR-0035): execuções ativas, falhas e
        aprovações pendentes — escopados ao projeto quando informado, senão
        globais. Mesmo padrão N+1 já usado por `list_all_approvals` (itera as
        orquestrações do escopo a cada chamada — sem índice dedicado, dev-scale)."""
        orchestrations = self.list_all(project_id=project_id)
        ids = {o.id for o in orchestrations}
        execucoes_ativas = sum(1 for o in orchestrations if o.status == "running")
        falhas = sum(self.count_cards_by_status(o.id).get("Failed", 0) for o in orchestrations)
        aprovacoes_pendentes = sum(
            1
            for a in self.list_all_approvals()
            if a.orchestration_id in ids and a.status == "pending"
        )
        return {
            "execucoes_ativas": execucoes_ativas,
            "falhas": falhas,
            "aprovacoes_pendentes": aprovacoes_pendentes,
        }

    def search(
        self, query: str, *, project_id: str | None = None, limit: int = 30
    ) -> list[SearchItem]:
        """Busca global (wf §2.3, "Campo de busca", ADR-0035): demandas, cards e
        ADRs por substring no título — escopada ao projeto quando informado.
        Bounded a 100 orquestrações por chamada (`list_orchestrations_page`) —
        buscar título de card/ADR exige hidratar o bundle de cada uma, mais caro
        que a listagem leve usada por `header_summary`."""
        pagina = self.list_orchestrations_page(page_size=100, project_id=project_id)
        orchestrations = pagina["items"]
        assert isinstance(orchestrations, list)  # noqa: S101 - devolvido por nós mesmos
        itens: list[SearchItem] = []
        for o in orchestrations:
            if o.user_request:
                itens.append(
                    SearchItem(tipo="demanda", titulo=o.user_request, orchestration_id=o.id)
                )
            for card in self.get_cards(o.id):
                itens.append(
                    SearchItem(
                        tipo="card", titulo=card.title, orchestration_id=o.id, card_id=card.id
                    )
                )
            for adr in self.list_adrs(o.id):
                itens.append(
                    SearchItem(
                        tipo="documento", titulo=adr.title, orchestration_id=o.id, adr_id=adr.id
                    )
                )
        return buscar(query, itens, limite=limit)

    def dashboard_summary(self, *, project_id: str | None = None) -> dict[str, object]:
        """Indicadores do Dashboard (wf §3.3, Tela 01, ADR-0037): demandas ativas,
        em execução, bloqueadas, falhas abertas, cards por status e aprovações
        pendentes por tipo — escopados ao projeto quando informado, senão globais.

        "Bloqueadas" reaproveita o status real `waiting_human` (uma orquestração
        parada esperando decisão humana É, de fato, uma demanda bloqueada) — não
        existe (nem é criado aqui) nenhum status `blocked` de orquestração; o único
        outro candidato do vocabulário do runtime seria `ColumnKey.BLOCKED`, que é
        de CARD, não de demanda.

        Sem campo de "variação": não existe hoje nenhuma série temporal dos
        indicadores globais para calcular isso a partir de dado real (`fato, não
        palpite`) — inventar um número seria pior que omiti-lo.
        """
        orchestrations = self.list_all(project_id=project_id)
        demandas_ativas = sum(
            1 for o in orchestrations if o.status not in ("completed", "cancelled")
        )
        em_execucao = sum(1 for o in orchestrations if o.status == "running")
        bloqueadas = sum(1 for o in orchestrations if o.status == "waiting_human")
        if project_id is None:
            metrics = self.aggregate_metrics()
            bruto = metrics.get("cards_by_status")
            cards_por_status = dict(bruto) if isinstance(bruto, dict) else {}
        else:
            cards_por_status = {}
            for o in orchestrations:
                for status, count in self.count_cards_by_status(o.id).items():
                    cards_por_status[status] = cards_por_status.get(status, 0) + count
        falhas_abertas = int(cards_por_status.get("Failed", 0))
        ids = {o.id for o in orchestrations}
        pendentes = [
            a
            for a in self.list_all_approvals()
            if a.status == "pending" and (project_id is None or a.orchestration_id in ids)
        ]
        aprovacoes_por_tipo: dict[str, int] = {}
        for aprovacao in pendentes:
            aprovacoes_por_tipo[aprovacao.tipo] = aprovacoes_por_tipo.get(aprovacao.tipo, 0) + 1
        return {
            "demandas_ativas": demandas_ativas,
            "em_execucao": em_execucao,
            "bloqueadas": bloqueadas,
            "falhas_abertas": falhas_abertas,
            "cards_por_status": cards_por_status,
            "aprovacoes_por_tipo": aprovacoes_por_tipo,
        }

    def recent_activity(self, *, limit: int = 20) -> list[dict[str, object]]:
        """Atividade recente GLOBAL (wf §3.3, ADR-0037) — diferente de `timeline`
        (por orquestração): uma query só, sem hidratar nenhum bundle. `ator` é
        melhor esforço a partir do payload do evento (`actor` ou `agent`) — nem
        todo evento tem um responsável humano, cai em "sistema"."""
        eventos = self._repo.recent_events(limit=limit)
        resultado: list[dict[str, object]] = []
        for evento in eventos:
            payload = evento.get("payload")
            payload_dict = payload if isinstance(payload, dict) else {}
            ator = payload_dict.get("actor") or payload_dict.get("agent") or "sistema"
            resultado.append(
                {
                    "orchestration_id": evento.get("orchestration_id"),
                    "tipo": evento.get("type"),
                    "ator": ator,
                    "at": evento.get("created_at"),
                }
            )
        return resultado

    def audit_page(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        project_id: str | None = None,
        orchestration_id: str | None = None,
        agente: str | None = None,
        etapa: str | None = None,
        resultado: str | None = None,
        data_de: str | None = None,
        data_ate: str | None = None,
    ) -> dict[str, object]:
        """Tela 28 (Auditoria, wf §30, ADR-0051) — 6 filtros cross-demanda sobre
        `CardEvent` (append-only, nunca truncado). "Modelo"/"Effort"/"Etapa"/
        "Identificador da execução" ficam `None` nos registros anteriores a
        esta ADR ou nascidos de movimentação manual (honesto, não fabricado)."""
        page = max(page, 1)
        page_size = max(1, min(page_size, 200))
        itens, total = self._repo.audit_page(
            limit=page_size,
            offset=(page - 1) * page_size,
            project_id=project_id,
            orchestration_id=orchestration_id,
            agente=agente,
            etapa=etapa,
            resultado=resultado,
            data_de=data_de,
            data_ate=data_ate,
        )
        return {"items": itens, "total": total, "page": page, "page_size": page_size}

    def export_audit(
        self,
        *,
        project_id: str | None = None,
        orchestration_id: str | None = None,
        agente: str | None = None,
        etapa: str | None = None,
        resultado: str | None = None,
        data_de: str | None = None,
        data_ate: str | None = None,
    ) -> str:
        """CSV do resultado filtrado (wf §30.3, "Exportação") — os mesmos 14
        campos do wf §30.2, na mesma ordem."""
        itens, _total = self._repo.audit_page(
            limit=self._AUDIT_EXPORT_LIMITE,
            offset=0,
            project_id=project_id,
            orchestration_id=orchestration_id,
            agente=agente,
            etapa=etapa,
            resultado=resultado,
            data_de=data_de,
            data_ate=data_ate,
        )
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(rotulo for _chave, rotulo in self._AUDIT_CSV_COLUNAS)
        for item in itens:
            linha = []
            for chave, _rotulo in self._AUDIT_CSV_COLUNAS:
                valor = item.get(chave)
                linha.append("; ".join(valor) if isinstance(valor, list) else (valor or ""))
            writer.writerow(linha)
        return buffer.getvalue()

    def get_context(self, orchestration_id: str) -> dict[str, object]:
        b = self._bundle(orchestration_id)
        return {
            "version": b.store.version,
            "context_hash": b.store.context_hash(),
            "payload": b.store.get(),
        }

    def get_plan(self, orchestration_id: str) -> ExecutionPlan:
        return self._bundle(orchestration_id).plan

    def get(self, orchestration_id: str) -> Orchestration:
        return self._bundle(orchestration_id).orchestration

    def get_cards(self, orchestration_id: str) -> list[KanbanCard]:
        b = self._bundle(orchestration_id)
        return b.board_service.cards_of(b.board.id)

    def get_card_tree(self, orchestration_id: str) -> list[dict[str, Any]]:
        """Tela 10 (Estrutura da demanda, wf §12, ADR-0040): árvore completa dos
        cards desta orquestração — raízes são os cards sem `parent_id` (hoje,
        tipicamente `Epic`; cards sem hierarquia atribuída também aparecem como
        raiz, já que `parent_id` é opcional)."""
        b = self._bundle(orchestration_id)
        cards = {c.id: c for c in b.board_service.cards_of(b.board.id)}
        return montar_arvore(cards)

    def get_card(self, orchestration_id: str, card_id: str) -> KanbanCard:
        """Ficha completa de UM card (Tela 12, wf §14, ADR-0041) — todos os campos
        do modelo de uma vez (identificação, dependências, rings de execução,
        arquivos vinculados etc.), sem a cliente ter que compor a partir da
        listagem inteira do board."""
        b = self._bundle(orchestration_id)
        card = b.board_service.get_card(card_id)
        if card is None:
            raise KeyError(f"Card inexistente: {card_id}")
        return card

    def get_card_events(self, orchestration_id: str, card_id: str) -> list[CardEvent]:
        """Histórico de movimentações do card (§8 do fluxo.md, ADR-0019, aba
        'Histórico' da Tela 12, ADR-0041) — log append-only, nunca truncado,
        diferente dos rings `failures`/`tentativas`/`qa_checks` (limitados a
        5/10/10)."""
        b = self._bundle(orchestration_id)
        card = b.board_service.get_card(card_id)
        if card is None:
            raise KeyError(f"Card inexistente: {card_id}")
        return [e for e in b.board_service.card_events if e.card_id == card_id]

    def list_adrs(self, orchestration_id: str) -> list[ADR]:
        return list(self._bundle(orchestration_id).adr_registry.list_all())

    def list_snapshots(self, orchestration_id: str) -> list[Snapshot]:
        return list(self._bundle(orchestration_id).snapshots)

    def timeline(self, orchestration_id: str) -> list[DomainEvent]:
        return self._bundle(orchestration_id).event_log.all()

    def conflicts(self, orchestration_id: str) -> list[Conflict]:
        return list(self._bundle(orchestration_id).bus.conflicts)

    def list_bug_reports(
        self, orchestration_id: str, card_original_id: str | None = None
    ) -> list[BugReport]:
        reports = self._bundle(orchestration_id).bug_reports
        if card_original_id is None:
            return list(reports)
        return [r for r in reports if r.card_original_id == card_original_id]

    def list_pulls(self, orchestration_id: str) -> list[PullRequest]:
        return list(self._bundle(orchestration_id).pull_requests)

    def list_review_comments(self, orchestration_id: str, pr_id: str) -> list[ReviewComment]:
        """Comentários de revisão ancorados em arquivo/linha da PR (wf §20.3/§21,
        ADR-0033) — alimenta a lista de correções obrigatórias da tela 19."""
        return [c for c in self._bundle(orchestration_id).review_comments if c.pr_id == pr_id]

    def list_candidate_runs(
        self, orchestration_id: str, card_id: str | None = None
    ) -> list[CandidateRun]:
        """Histórico de corridas de candidatos (opcionalmente filtrado por card)."""
        runs = self._bundle(orchestration_id).candidate_runs
        if card_id:
            return [r for r in runs if r.card_id == card_id]
        return list(runs)

    def list_slo_evaluations(
        self, orchestration_id: str, *, limit: int | None = None
    ) -> list[SloEvaluation]:
        """Amostras de SLO em ordem cronológica (as `limit` mais recentes, se dado)."""
        evals = list(self._bundle(orchestration_id).slo_evaluations)
        return evals[-limit:] if limit else evals

    # ------------------------------------------------- context patches / auditoria
    def list_patches(self, orchestration_id: str, status: str | None = None) -> list[ContextPatch]:
        patches = self._bundle(orchestration_id).bus.patches
        if status:
            return [p for p in patches if p.status.value == status]
        return list(patches)

    # ------------------------------------------------- gates / conflitos / approvals
    def list_gate_results(self, orchestration_id: str) -> list[QualityGateResult]:
        return list(self._bundle(orchestration_id).gate_results)

    def list_approvals(self, orchestration_id: str) -> list[HumanApproval]:
        return list(self._bundle(orchestration_id).approvals)

    def list_all_approvals(self) -> list[HumanApproval]:
        return [a for oid in self._repo.list_ids() for a in self._bundle(oid).approvals]

    def count_cards_by_status(self, orchestration_id: str) -> dict[str, int]:
        self._bundle(orchestration_id)
        return self._repo.count_cards_by_status(orchestration_id)

    def search_adrs(
        self, orchestration_id: str, *, status: str | None = None, query: str | None = None
    ) -> list[ADR]:
        adrs = self.list_adrs(orchestration_id)
        if status:
            adrs = [a for a in adrs if a.status.value == status]
        if query:
            q = query.lower()
            adrs = [a for a in adrs if q in a.title.lower() or q in a.decision.lower()]
        return adrs

    def timeline_page(
        self,
        orchestration_id: str,
        *,
        page: int = 1,
        page_size: int = 50,
        newest_first: bool = False,
    ) -> dict[str, object]:
        """Página da timeline. `newest_first` serve a quem quer "o que acabou de acontecer"."""
        self._bundle(orchestration_id)  # valida existência (404 se não existir)
        page = max(page, 1)
        items, total = self._repo.events_page(
            orchestration_id,
            limit=page_size,
            offset=(page - 1) * page_size,
            newest_first=newest_first,
        )
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "newest_first": newest_first,
        }

    def list_incidents(self, orchestration_id: str) -> list[Incident]:
        return list(self._bundle(orchestration_id).incidents)
