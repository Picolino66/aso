"""Rotas de cards e Kanban: execução, controles em voo, QA e corridas de candidatos.

Extraídas do `create_app` monolítico no MEL-32 passo 10 (ADR-0066).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from aso.api.deps import ApiDeps, actor_de
from aso.api.execucao_assincrona import OP_RACE, OP_RUN_CARD
from aso.api.schemas import (
    AddContextBody,
    AssignAgentBody,
    BlockBody,
    BugReportBody,
    CreateCardBody,
    MoveBody,
    OpenPrBody,
    PauseBody,
    QaCheckBody,
    QaFailBody,
    RaceBody,
    RequestHelpBody,
)


def criar_router(deps: ApiDeps) -> APIRouter:
    router = APIRouter()
    svc = deps.svc

    @router.get("/v1/orchestrations/{orchestration_id}/cards")
    def get_cards(
        orchestration_id: str,
        status: str | None = None,
        card_type: str | None = Query(default=None, alias="type"),
        assignee: str | None = None,
    ) -> Any:
        deps.guard(orchestration_id)
        if status or card_type or assignee:
            return svc.filter_cards(
                orchestration_id, status=status, card_type=card_type, assignee=assignee
            )
        return svc.get_cards(orchestration_id)

    @router.get("/v1/orchestrations/{orchestration_id}/cards/tree")
    def get_card_tree(orchestration_id: str) -> Any:
        """Tela 10 (Estrutura da demanda, wf §12, ADR-0040)."""
        return deps.card_op(orchestration_id, lambda: svc.get_card_tree(orchestration_id))

    @router.get("/v1/orchestrations/{orchestration_id}/kanban")
    def get_kanban_board(orchestration_id: str) -> Any:
        """Tela 11 (Kanban operacional, wf §13/§35, ADR-0047): as 16 colunas reais
        (rótulo do wireframe quando existe), cards com os 11 campos do §13.3 já
        resolvidos, e o grafo de transições válidas."""
        deps.guard(orchestration_id)
        return svc.kanban_board(orchestration_id)

    @router.post("/v1/orchestrations/{orchestration_id}/cards", status_code=201)
    def create_card(orchestration_id: str, body: CreateCardBody) -> Any:
        """Tela 10 (wf §12, ADR-0040): cria um item em qualquer nível,
        respeitando a hierarquia (`parent_id` inexistente, ciclo ou profundidade
        excedida devolvem 409 — mesma validação de `BoardService.add_card`)."""
        return deps.card_op(
            orchestration_id,
            lambda: svc.create_card(
                orchestration_id,
                title=body.title,
                type=body.type,
                parent_id=body.parent_id,
                description=body.description,
            ),
        )

    @router.post("/v1/orchestrations/{orchestration_id}/cards/{card_id}/run")
    def run_card(orchestration_id: str, card_id: str, request: Request) -> Any:
        deps.guard(orchestration_id)
        if deps.fila is not None:
            return deps.enfileirar(OP_RUN_CARD, orchestration_id, request, card_id=card_id)
        try:
            return svc.run_card(orchestration_id, card_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @router.get("/v1/orchestrations/{orchestration_id}/cards/{card_id}/qa")
    def get_qa_checks(orchestration_id: str, card_id: str) -> Any:
        """Histórico de verificações manuais de QA do card (§16, ring de 10)."""
        return deps.card_op(orchestration_id, lambda: svc.get_qa_checks(orchestration_id, card_id))

    @router.get("/v1/orchestrations/{orchestration_id}/cards/{card_id}/checklist")
    def get_preparation_checklist(orchestration_id: str, card_id: str) -> Any:
        """Checklist de preparação para implementação (§10, ADR-0030) — só leitura."""
        return deps.card_op(
            orchestration_id, lambda: svc.get_preparation_checklist(orchestration_id, card_id)
        )

    @router.post("/v1/orchestrations/{orchestration_id}/cards/{card_id}/qa")
    def register_qa_check(
        orchestration_id: str, card_id: str, body: QaCheckBody, request: Request
    ) -> Any:
        """Registra uma verificação manual de QA (§16)."""
        return deps.card_op(
            orchestration_id,
            lambda: svc.register_qa_check(
                orchestration_id,
                card_id,
                cenario=body.cenario,
                titulo=body.titulo,
                pre_condicoes=body.pre_condicoes,
                passos=body.passos,
                ambiente=body.ambiente,
                resultado_esperado=body.resultado_esperado,
                resultado_obtido=body.resultado_obtido,
                evidencias=body.evidencias,
                gravidade=body.gravidade,
                status=body.status,
                tipo_responsavel=body.tipo_responsavel,
                actor=actor_de(request),
            ),
        )

    @router.post("/v1/orchestrations/{orchestration_id}/cards/{card_id}/qa/{index}/fail")
    def fail_qa_check(
        orchestration_id: str, card_id: str, index: int, body: QaFailBody, request: Request
    ) -> Any:
        """Reprova uma verificação de QA já registrada — cria o bug vinculado (§17)."""
        return deps.card_op(
            orchestration_id,
            lambda: svc.fail_qa_check(
                orchestration_id,
                card_id,
                index,
                resultado_obtido=body.resultado_obtido,
                evidencias=body.evidencias,
                gravidade=body.gravidade,
                actor=actor_de(request),
            ),
        )

    @router.get("/v1/orchestrations/{orchestration_id}/cards/stats")
    def cards_stats(orchestration_id: str) -> Any:
        deps.guard(orchestration_id)
        return svc.count_cards_by_status(orchestration_id)

    @router.get("/v1/orchestrations/{orchestration_id}/cards/by-status/{status}")
    def cards_by_status(orchestration_id: str, status: str) -> Any:
        deps.guard(orchestration_id)
        return svc.cards_by_status(orchestration_id, status)

    @router.get("/v1/orchestrations/{orchestration_id}/cards/{card_id}")
    def get_card(orchestration_id: str, card_id: str) -> Any:
        """Tela 12 (Detalhes do card, wf §14, ADR-0041): ficha completa de um
        único card — usada pelas abas Resumo/Plano/Implementação/Arquivos/
        Testes/Dependências/Execuções. Registrada depois de todas as rotas
        literais de um segmento sob `cards/` (`tree`, `stats`, `by-status/...`)
        para não sombreá-las — Starlette casa rotas na ordem de registro."""
        return deps.card_op(orchestration_id, lambda: svc.get_card(orchestration_id, card_id))

    @router.get("/v1/orchestrations/{orchestration_id}/cards/{card_id}/events")
    def get_card_events(orchestration_id: str, card_id: str) -> Any:
        """Tela 12 (aba Histórico, ADR-0041): log de movimentações do card,
        append-only, nunca truncado — diferente dos rings de tentativas/falhas."""
        return deps.card_op(
            orchestration_id, lambda: svc.get_card_events(orchestration_id, card_id)
        )

    # --- Pull Requests (§26, MVP-4) ---
    @router.post("/v1/orchestrations/{orchestration_id}/cards/{card_id}/open-pr", status_code=201)
    def open_pr(orchestration_id: str, card_id: str, body: OpenPrBody) -> Any:
        return deps.card_op(
            orchestration_id,
            lambda: svc.open_pr(orchestration_id, card_id, branch=body.branch, title=body.title),
        )

    @router.post("/v1/orchestrations/{orchestration_id}/cards/{card_id}/race")
    def race_card(
        orchestration_id: str, card_id: str, request: Request, body: RaceBody | None = None
    ) -> Any:
        """Roda os agentes CLI candidatos (§26A.6) em paralelo e compara os diffs.

        Candidatos são perfis do catálogo (ADR-0076): os nomes em `executores` ou, sem
        lista, os perfis marcados `candidato`. Rodam na pasta desta orquestração."""
        deps.guard(orchestration_id)
        executores = body.executores if body is not None else None
        try:
            providers = svc.candidatos_da_corrida(orchestration_id, executores)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc).strip("'\"")) from None
        if not providers:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Nenhum candidato: informe `executores` ou marque perfis CLI do catálogo "
                    "como candidatos (⚙ Config)."
                ),
            )
        if deps.fila is not None:
            return deps.enfileirar(
                OP_RACE,
                orchestration_id,
                request,
                card_id=card_id,
                parametros={"executores": executores},
            )
        return deps.card_op(
            orchestration_id, lambda: svc.race_card(orchestration_id, card_id, providers)
        )

    @router.get("/v1/orchestrations/{orchestration_id}/candidate-runs")
    def list_candidate_runs(orchestration_id: str, card_id: str | None = None) -> Any:
        """Histórico rastreável de corridas de candidatos (§26A.6)."""
        deps.guard(orchestration_id)
        return svc.list_candidate_runs(orchestration_id, card_id)

    @router.post("/v1/orchestrations/{orchestration_id}/cards/{card_id}/assign-agent")
    def assign_agent(orchestration_id: str, card_id: str, body: AssignAgentBody) -> Any:
        return deps.card_op(
            orchestration_id, lambda: svc.assign_agent(orchestration_id, card_id, body.agent)
        )

    @router.post("/v1/orchestrations/{orchestration_id}/cards/{card_id}/move")
    def move_card(orchestration_id: str, card_id: str, body: MoveBody) -> Any:
        """Movimentação manual (Tela 11, wf §35, ADR-0047) — valida a transição
        contra a máquina de estados; automação interna do runtime não passa por
        aqui (chama `BoardService`/`svc.move_card` sem validação)."""
        return deps.card_op(
            orchestration_id,
            lambda: svc.move_card_validado(orchestration_id, card_id, body.to_column),
        )

    @router.post("/v1/orchestrations/{orchestration_id}/cards/{card_id}/block")
    def block_card(orchestration_id: str, card_id: str, body: BlockBody) -> Any:
        return deps.card_op(
            orchestration_id, lambda: svc.block_card(orchestration_id, card_id, body.reason)
        )

    @router.post("/v1/orchestrations/{orchestration_id}/cards/{card_id}/unblock")
    def unblock_card(orchestration_id: str, card_id: str) -> Any:
        return deps.card_op(orchestration_id, lambda: svc.unblock_card(orchestration_id, card_id))

    @router.post("/v1/orchestrations/{orchestration_id}/cards/{card_id}/cancel")
    def cancel_card(orchestration_id: str, card_id: str, body: BlockBody) -> Any:
        """Cancela um card individualmente (§8 do fluxo.md, coluna `Cancelled`)."""
        return deps.card_op(
            orchestration_id, lambda: svc.cancel_card(orchestration_id, card_id, body.reason)
        )

    @router.get("/v1/orchestrations/{orchestration_id}/cards/{card_id}/failures")
    def get_card_failures(orchestration_id: str, card_id: str) -> Any:
        """Histórico de falhas do card (§13 do fluxo.md, ADR-0019)."""
        return deps.card_op(
            orchestration_id, lambda: svc.get_card_failures(orchestration_id, card_id)
        )

    @router.get("/v1/orchestrations/{orchestration_id}/cards/{card_id}/closure")
    def get_card_closure(orchestration_id: str, card_id: str) -> Any:
        """Ficha de encerramento do card (§23 do fluxo.md, ADR-0021)."""
        return deps.card_op(
            orchestration_id, lambda: svc.get_card_closure(orchestration_id, card_id)
        )

    @router.post("/v1/orchestrations/{orchestration_id}/cards/{card_id}/route")
    def route_card(orchestration_id: str, card_id: str) -> Any:
        """Aciona o roteamento de falha manualmente (ADR-0019) — para quando o
        automático parou por limite (bloqueado/escalado) e o operador já corrigiu a
        causa."""
        return deps.card_op(orchestration_id, lambda: svc.route_card(orchestration_id, card_id))

    # ---- Controles em voo (Tela 15, wf §17.2, ADR-0048) -----------------------

    @router.post("/v1/orchestrations/{orchestration_id}/cards/{card_id}/pause")
    def pause_card(orchestration_id: str, card_id: str, body: PauseBody, request: Request) -> Any:
        """Pausar/retomar — impede a próxima execução, não interrompe uma em
        andamento (reinterpretação honesta, ver ADR-0048)."""
        return deps.card_op(
            orchestration_id,
            lambda: svc.pause_card(
                orchestration_id, card_id, pausado=body.pausado, actor=actor_de(request)
            ),
        )

    @router.post("/v1/orchestrations/{orchestration_id}/cards/{card_id}/add-context")
    def add_card_context(
        orchestration_id: str, card_id: str, body: AddContextBody, request: Request
    ) -> Any:
        """Adicionar contexto — entra no próximo prompt do agente."""
        return deps.card_op(
            orchestration_id,
            lambda: svc.add_card_context(
                orchestration_id, card_id, body.texto, actor=actor_de(request)
            ),
        )

    @router.post("/v1/orchestrations/{orchestration_id}/cards/{card_id}/increase-effort")
    def increase_card_effort(orchestration_id: str, card_id: str, request: Request) -> Any:
        """Aumentar effort — reaproveita `proximo_effort` (mesma função do
        roteamento automático de falha)."""
        return deps.card_op(
            orchestration_id,
            lambda: svc.increase_card_effort(orchestration_id, card_id, actor=actor_de(request)),
        )

    @router.post("/v1/orchestrations/{orchestration_id}/cards/{card_id}/transfer-model")
    def transfer_card_model(orchestration_id: str, card_id: str, request: Request) -> Any:
        """Trocar modelo — reaproveita `proximo_executor` (mesma função do
        roteamento automático de falha)."""
        return deps.card_op(
            orchestration_id,
            lambda: svc.transfer_card_model(orchestration_id, card_id, actor=actor_de(request)),
        )

    @router.post("/v1/orchestrations/{orchestration_id}/cards/{card_id}/request-help")
    def request_card_help(orchestration_id: str, card_id: str, body: RequestHelpBody) -> Any:
        """Solicitar ajuda — reaproveita `request_approval` (ação rotulada)."""
        return deps.card_op(
            orchestration_id,
            lambda: svc.request_card_help(orchestration_id, card_id, reason=body.reason),
        )

    @router.get("/v1/orchestrations/{orchestration_id}/cards/{card_id}/changed-files")
    def get_card_changed_files(orchestration_id: str, card_id: str) -> Any:
        """Arquivos alterados (Tela 15, wf §17.1) — diff real da branch do card."""
        return deps.card_op(
            orchestration_id, lambda: svc.get_card_changed_files(orchestration_id, card_id)
        )

    @router.get("/v1/orchestrations/{orchestration_id}/cards/{card_id}/failure-diagnostics")
    def get_card_failure_diagnostics(orchestration_id: str, card_id: str) -> Any:
        """Tela 17 (wf §19): falhas com diagnóstico e confiança calculados na leitura."""
        return deps.card_op(
            orchestration_id,
            lambda: svc.get_card_failure_diagnostics(orchestration_id, card_id),
        )

    @router.get("/v1/orchestrations/{orchestration_id}/cards/{card_id}/diff-stats")
    def get_card_diff_stats(orchestration_id: str, card_id: str) -> Any:
        """Resumo do review — commits/arquivos/linhas (Tela 18, wf §20.1, ADR-0049)."""
        return deps.card_op(
            orchestration_id, lambda: svc.get_card_diff_stats(orchestration_id, card_id)
        )

    @router.get("/v1/orchestrations/{orchestration_id}/cards/{card_id}/bug-reports")
    def list_bug_reports_do_card(orchestration_id: str, card_id: str) -> Any:
        """Bugs registrados contra este card (`card_original_id`)."""
        deps.guard(orchestration_id)
        return svc.list_bug_reports(orchestration_id, card_id)

    @router.post("/v1/orchestrations/{orchestration_id}/cards/{card_id}/bug-reports")
    def create_bug_report(
        orchestration_id: str, card_id: str, body: BugReportBody, request: Request
    ) -> Any:
        """Registro manual de bug (Tela 21, wf §23) — cria o card Bug vinculado."""
        return deps.card_op(
            orchestration_id,
            lambda: svc.create_bug_report(
                orchestration_id,
                card_id,
                titulo=body.titulo,
                cenario=body.cenario,
                passos_para_reproduzir=body.passos_para_reproduzir,
                ambiente=body.ambiente,
                resultado_atual=body.resultado_atual,
                resultado_esperado=body.resultado_esperado,
                evidencias=body.evidencias,
                gravidade=body.gravidade,
                impacto=body.impacto,
                frequencia=body.frequencia,
                agente_sugerido=body.agente_sugerido,
                retorno_de_fluxo=body.retorno_de_fluxo,
                actor=actor_de(request),
            ),
        )

    return router
