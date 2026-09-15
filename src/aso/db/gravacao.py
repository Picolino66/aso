"""Decomposição do agregado em unidades de gravação incremental (ADR-0068, MEL-33).

Antes, `save` apagava todas as tabelas filhas da orquestração e reinseria o agregado inteiro a
cada `_persist` — o custo crescia com o histórico e o log "append-only" era regravado.

Aqui o estado vira **unidades** comparáveis por impressão (hash do conteúdo):

- `entidade`: uma linha com chave primária (card, PR, aprovação…) — mudou → `UPDATE` (merge);
- `grupo`: linhas de junção de um dono (links de um card, critérios de um gate…) — mudou →
  apaga só o grupo e reinsere;
- `sequencia`: `events` e `context_history`, só crescem — grava a cauda nova; se o prefixo
  mudou, remove o sufixo divergente antes.

`nivel` é a ordem de FK: inserts do menor para o maior, deletes do maior para o menor.
Funções puras: sem sessão nem banco — o repositório decide o que executar.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import DeclarativeBase

from aso.db.models import (
    AdrLinkRow,
    AdrOptionRow,
    AdrRow,
    BoardColumnRow,
    BoardRow,
    BugReportRow,
    CandidateRunRow,
    CardEventRow,
    CardLinkRow,
    CardRow,
    ConflictRow,
    ContextHistoryRow,
    ContextPatchRow,
    ContextRow,
    EventRow,
    ExecutionPlanRow,
    GateCriterionRow,
    HumanApprovalRow,
    IncidentRow,
    PlannedAgentRow,
    PullRequestRow,
    QualityGateResultRow,
    ReviewCommentRow,
    SloEvaluationRow,
    SnapshotRow,
    ValueItemRow,
)
from aso.persistence.state import OrchestrationState

ENTIDADE = "entidade"
GRUPO = "grupo"

CARD_RELS = (
    "agents",
    "dependencies",
    "blocked_by",
    "acceptance_criteria",
    "correction_actions",
    "linked_requirements",
    "linked_adrs",
    "linked_contracts",
    "linked_files",
    "linked_prs",
)
ADR_RELS = ("tradeoffs", "consequences", "linked_cards", "linked_requirements", "locked_paths")

TABELAS: dict[str, type[DeclarativeBase]] = {
    row.__tablename__: row
    for row in (
        AdrLinkRow,
        AdrOptionRow,
        AdrRow,
        BoardColumnRow,
        BoardRow,
        BugReportRow,
        CandidateRunRow,
        CardEventRow,
        CardLinkRow,
        CardRow,
        ConflictRow,
        ContextHistoryRow,
        ContextPatchRow,
        ContextRow,
        EventRow,
        ExecutionPlanRow,
        GateCriterionRow,
        HumanApprovalRow,
        IncidentRow,
        PlannedAgentRow,
        PullRequestRow,
        QualityGateResultRow,
        ReviewCommentRow,
        SloEvaluationRow,
        SnapshotRow,
        ValueItemRow,
    )
}


@dataclass(frozen=True)
class Unidade:
    tabela: str
    chave: tuple[Any, ...]
    tipo: str
    nivel: int
    # Colunas que identificam as linhas da unidade (WHERE do delete / chave do merge).
    filtro: tuple[tuple[str, Any], ...]
    linhas: tuple[dict[str, Any], ...]

    @property
    def id(self) -> tuple[str, tuple[Any, ...]]:
        return (self.tabela, self.chave)

    @property
    def impressao(self) -> str:
        return impressao(list(self.linhas))


@dataclass(frozen=True)
class MetaDaUnidade:
    """O que o repositório guarda de cada unidade gravada: basta para comparar e apagar."""

    tipo: str
    nivel: int
    filtro: tuple[tuple[str, Any], ...]
    impressao: str


def impressao(valor: Any) -> str:
    bruto = json.dumps(valor, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.blake2b(bruto.encode(), digest_size=16).hexdigest()


def _colunas(tabela: str) -> set[str]:
    return set(TABELAS[tabela].__table__.columns.keys())


def _escalar(dump: dict[str, Any], tabela: str) -> dict[str, Any]:
    cols = _colunas(tabela)
    return {k: v for k, v in dump.items() if k in cols}


def _entidade(
    tabela: str, linha: dict[str, Any], nivel: int, pk: tuple[str, ...] = ("id",)
) -> Unidade:
    filtro = tuple((col, linha[col]) for col in pk)
    return Unidade(tabela, tuple(v for _, v in filtro), ENTIDADE, nivel, filtro, (linha,))


def _grupo(
    tabela: str, filtro: dict[str, Any], linhas: list[dict[str, Any]], nivel: int
) -> Unidade:
    itens = tuple(filtro.items())
    return Unidade(tabela, tuple(v for _, v in itens), GRUPO, nivel, itens, tuple(linhas))


def unidades_do_estado(state: OrchestrationState) -> list[Unidade]:
    """Todas as unidades de gravação do agregado, exceto a própria orquestração e sequências."""
    oid = state.orchestration.id
    u: list[Unidade] = []

    def ent(tabela: str, dump: dict[str, Any], nivel: int, **extra: Any) -> None:
        u.append(_entidade(tabela, {**_escalar(dump, tabela), **extra}, nivel))

    # Nível 1 — board e plano (pais de cards e das junções).
    ent("boards", state.board.model_dump(mode="json"), 1)
    ent("execution_plans", state.plan.model_dump(mode="json"), 1)

    # Nível 2 — entidades que dependem de orquestração/board/plano.
    u.append(
        _entidade(
            "orchestrator_contexts",
            {
                "orchestration_id": oid,
                "version": state.context_version,
                "context_hash": "",
                "payload": state.context_payload,
            },
            2,
            pk=("orchestration_id",),
        )
    )
    u.append(
        _grupo(
            "board_columns",
            {"orchestration_id": oid, "board_id": state.board.id},
            [
                {
                    "board_id": state.board.id,
                    "orchestration_id": oid,
                    "key": col.key.value,
                    "position": col.order,
                    "wip_limit": col.wip_limit,
                }
                for col in state.board.columns
            ],
            2,
        )
    )
    u.append(
        _grupo(
            "planned_agents",
            {"orchestration_id": oid, "plan_id": state.plan.id},
            [
                {
                    "plan_id": state.plan.id,
                    "orchestration_id": oid,
                    "position": pos,
                    "agent": planned.agent,
                    "role": planned.role,
                    "reason": planned.reason,
                    "depends_on": list(planned.depends_on),
                }
                for pos, planned in enumerate(state.plan.agents)
            ],
            2,
        )
    )
    for pos, card in enumerate(state.cards):
        ent("kanban_cards", card.model_dump(mode="json"), 2, posicao=pos)
    for pos, evt in enumerate(state.card_events):
        ent("card_events", evt.model_dump(mode="json"), 2, orchestration_id=oid, posicao=pos)
    for adr in state.adrs:
        linha = _escalar(adr.model_dump(mode="json"), "adrs")
        u.append(_entidade("adrs", linha, 2, pk=("orchestration_id", "id")))
    colecoes: tuple[tuple[str, list[Any]], ...] = (
        ("snapshots", list(state.snapshots)),
        ("conflicts", list(state.conflicts)),
        ("quality_gate_results", list(state.gate_results)),
        ("human_approvals", list(state.approvals)),
        ("context_patches", list(state.patches)),
        ("pull_requests", list(state.pull_requests)),
        ("candidate_runs", list(state.candidate_runs)),
        ("slo_evaluations", list(state.slo_evaluations)),
        ("incidents", list(state.incidents)),
        ("bug_reports", list(state.bug_reports)),
        ("review_comments", list(state.review_comments)),
    )
    for tabela, itens in colecoes:
        for pos, item in enumerate(itens):
            ent(tabela, item.model_dump(mode="json"), 2, posicao=pos)

    def valores(owner_type: str, owner_id: str, rel: str, lista: list[str]) -> None:
        filtro = {
            "orchestration_id": oid,
            "owner_type": owner_type,
            "owner_id": owner_id,
            "rel": rel,
        }
        linhas = [{**filtro, "value": v, "position": pos} for pos, v in enumerate(lista)]
        u.append(_grupo("value_items", filtro, linhas, 2))

    valores("plan", state.plan.id, "success_criteria", list(state.plan.success_criteria))
    valores("context", oid, "frozen_sections", list(state.context_frozen))
    for snap in state.snapshots:
        valores("snapshot", snap.id, "frozen_sections", list(snap.frozen_sections))
        valores("snapshot", snap.id, "adrs", list(snap.adrs))
        valores("snapshot", snap.id, "cards", list(snap.cards))
    for conflict in state.conflicts:
        valores("conflict", conflict.id, "source_patch_ids", list(conflict.source_patch_ids))
    for gate in state.gate_results:
        valores("gate", gate.id, "blocking_issues", list(gate.blocking_issues))
        valores("gate", gate.id, "warnings", list(gate.warnings))
        valores("gate", gate.id, "required_actions", list(gate.required_actions))

    # Nível 3 — junções que dependem de cards/gates (e ADRs, por referência leve).
    for card in state.cards:
        u.append(
            _grupo(
                "card_links",
                {"orchestration_id": oid, "card_id": card.id},
                [
                    {
                        "card_id": card.id,
                        "orchestration_id": oid,
                        "rel": rel,
                        "value": value,
                        "position": pos,
                    }
                    for rel in CARD_RELS
                    for pos, value in enumerate(getattr(card, rel))
                ],
                3,
            )
        )
    for adr in state.adrs:
        u.append(
            _grupo(
                "adr_links",
                {"orchestration_id": oid, "adr_id": adr.id},
                [
                    {
                        "adr_id": adr.id,
                        "orchestration_id": oid,
                        "rel": rel,
                        "value": value,
                        "position": pos,
                    }
                    for rel in ADR_RELS
                    for pos, value in enumerate(getattr(adr, rel))
                ],
                3,
            )
        )
        u.append(
            _grupo(
                "adr_options",
                {"orchestration_id": oid, "adr_id": adr.id},
                [
                    {
                        "adr_id": adr.id,
                        "orchestration_id": oid,
                        "position": pos,
                        "name": str(opt.get("name", "")),
                        "pros": list(opt.get("pros", [])),
                        "cons": list(opt.get("cons", [])),
                    }
                    for pos, opt in enumerate(adr.options_considered)
                ],
                3,
            )
        )
    for gate in state.gate_results:
        u.append(
            _grupo(
                "gate_criteria",
                {"orchestration_id": oid, "gate_id": gate.id},
                [
                    {
                        "gate_id": gate.id,
                        "orchestration_id": oid,
                        "position": pos,
                        "name": crit.name,
                        "status": crit.status.value,
                        "failure_reason": crit.failure_reason,
                        "evidence": list(crit.evidence),
                        "duration_ms": crit.duration_ms,
                    }
                    for pos, crit in enumerate(gate.criteria)
                ],
                3,
            )
        )
    return u


def sequencias_do_estado(state: OrchestrationState) -> dict[str, list[dict[str, Any]]]:
    """Coleções que só crescem: gravadas pela cauda (nunca reescritas por inteiro)."""
    oid = state.orchestration.id
    return {
        "events": [
            {
                "orchestration_id": oid,
                "seq": seq,
                "type": event["type"],
                "payload": event.get("payload", {}),
                "created_at": event["created_at"],
            }
            for seq, event in enumerate(state.events)
        ],
        "context_history": [{"orchestration_id": oid, **entry} for entry in state.context_history],
    }


def prefixo_comum(anterior: list[str], atual: list[str]) -> int:
    n = 0
    for a, b in zip(anterior, atual, strict=False):
        if a != b:
            break
        n += 1
    return n
