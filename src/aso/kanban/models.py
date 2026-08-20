"""Modelos do Kanban Plane (§16.5)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from aso.shared.ids import gen_id, now_iso
from aso.shared.types import AssigneeType, CardType, ColumnKey, Phase, RiskLevel


class BoardColumn(BaseModel):
    key: ColumnKey
    order: int
    wip_limit: int | None = None


class KanbanCard(BaseModel):
    """Unidade de trabalho rastreável (§16.5)."""

    id: str = Field(default_factory=lambda: gen_id("card"))
    board_id: str
    orchestration_id: str
    phase: Phase
    type: CardType
    title: str
    description: str = ""
    status: ColumnKey = ColumnKey.BACKLOG
    priority: RiskLevel = RiskLevel.MEDIUM
    assignee_type: AssigneeType = AssigneeType.AGENT
    assignee: str | None = None
    # Papel planejado (ex.: "BackendDevelopmentAgent") continua em `assignee`; este
    # campo guarda o PERFIL de executor que de fato rodou (ex.: "codex-gpt-5-high"),
    # gravado em `_apply_execution` — sem ele não há como exigir revisor diferente
    # do implementador (§14, ADR-0017). Serve também ao §23/§24 (modelos utilizados).
    executor: str | None = None
    agents: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    blocked_by: list[str] = Field(default_factory=list)
    # Hierarquia épico → história → subtarefa (§7 do fluxo.md, ADR-0025). Nulo (o
    # estado de todo card anterior a esta ADR) continua válido — a hierarquia é
    # opcional, não obrigatória. Profundidade máxima 3 e ausência de ciclo são
    # validadas em `BoardService.add_card`, não aqui (Pydantic não valida contra
    # outros cards).
    parent_id: str | None = None
    acceptance_criteria: list[str] = Field(default_factory=list)
    # Ações objetivas de uma revisão reprovada (§15, ADR-0017): só as de severidade
    # `obrigatoria` — chegam ao agente na re-execução via `_build_task`. Limpo quando
    # o veredito volta a ser aprovado.
    correction_actions: list[str] = Field(default_factory=list)
    # Ring das últimas 5 falhas (§13 do fluxo.md, ADR-0019) — cada item é um
    # `FailureRecord.model_dump()` (control/failure.py). Fica em `kanban/` como dict
    # solto (não o tipo Pydantic) para não inverter a dependência: `control` importa
    # `kanban`, não o contrário.
    failures: list[dict[str, Any]] = Field(default_factory=list)
    # Contador AUTORITATIVO de tentativas (§36.4 do wiframe, ADR-0031) — nunca
    # truncado (diferente de `len(failures)`, que é o tamanho do ring, travado em
    # 5). Incrementado a cada execução real, sucesso ou falha. Usado para exibição
    # ("tentativa N") e para o teto por agente (ADR-0053) — NÃO para a escalação de
    # falha (ver `tentativa_falha_atual`).
    tentativa_atual: int = 0
    # Contador de FALHAS CONSECUTIVAS (§13 do fluxo.md, ADR-0019) — diferente de
    # `tentativa_atual`: zera a cada sucesso, incrementa só em falha (execução ou
    # QA). É este que `decidir()` deve receber para escalar após N falhas seguidas;
    # revisão de código encontrou `tentativa_atual` (que soma sucesso) sendo usado
    # ali por engano, disparando escalação prematura na 1ª falha real após
    # sucessos anteriores. Também uncapped, ao contrário de `len(failures)` (ring
    # travado em 5, ADR-0031) — não reintroduz o bug que motivou `tentativa_atual`.
    tentativa_falha_atual: int = 0
    # `None` = usa o limite global do processo (`ASO_MAX_ESCALONAMENTOS`) —
    # preserva o comportamento de toda orquestração anterior a esta ADR. Um
    # inteiro aqui sobrepõe o global só para este card (ex.: herdado de
    # `RoutingRule.acao.limite_tentativas`, ADR-0028/ADR-0031).
    max_tentativas: int | None = None
    # Ring das últimas 10 tentativas (§36.4, ADR-0031) — sucesso OU falha, cada
    # item um `TentativaRegistro.model_dump()` (control/attempts.py). Diferente de
    # `failures` (só falha): é o "modelo/effort/resultado" por tentativa que o
    # wiframe pede, incluindo a tentativa que finalmente teve sucesso.
    tentativas: list[dict[str, Any]] = Field(default_factory=list)
    # Ring das últimas 10 verificações de QA manual (§16/§17 do fluxo.md, ADR-0025) —
    # cada item é um `QaCheck.model_dump()` (control/qa.py). Mesmo raciocínio de
    # `failures`: dict solto para não inverter a dependência `control` → `kanban`.
    qa_checks: list[dict[str, Any]] = Field(default_factory=list)
    # Consumo acumulado do agente neste card (§1.1/§1.4, ADR-0026) — soma reexecuções
    # (`aso.shared.agent_usage.acumular_uso`). Dict solto (não `UsoDoAgente`) pelo
    # mesmo motivo de `failures`/`qa_checks`: `kanban` não importa `control`, e o tipo
    # já pertence a `shared`, mais neutro que qualquer um dos dois.
    uso: dict[str, Any] = Field(default_factory=dict)
    # Ficha de encerramento (§23 do fluxo.md, ADR-0021) — preenchida em `merge_pr`,
    # o ponto em que o card chega a Done. Vazio = card ainda não encerrado (ou
    # encerrado antes desta ADR). Só registra o que o runtime tem à mão: campos do
    # §23 sem dado disponível (data de implantação, commits individuais) ficam de
    # fora — ficha com campo inventado é pior que ficha curta.
    closure: dict[str, Any] = Field(default_factory=dict)
    linked_requirements: list[str] = Field(default_factory=list)
    linked_adrs: list[str] = Field(default_factory=list)
    linked_contracts: list[str] = Field(default_factory=list)
    linked_files: list[str] = Field(default_factory=list)
    linked_prs: list[str] = Field(default_factory=list)
    worktree: str | None = None
    branch: str | None = None
    block_reason: str | None = None
    # Checklist de preparação (§10 do fluxo.md, ADR-0030) — cada item é um
    # `PreparationChecklistItem.model_dump()` (control/preparation.py). Dict solto
    # pelo mesmo motivo de `failures`/`qa_checks`: `kanban` não importa `control`.
    # Estado, não log — no máximo 8 itens, um por rótulo do §10.
    preparation_checklist: list[dict[str, Any]] = Field(default_factory=list)
    # Card de acompanhamento criado automaticamente na primeira vez que este card
    # bloqueia por dependência pendente (§10, ADR-0030) — `None` = nunca bloqueou
    # (ou já foi desbloqueado e o ponteiro foi limpo). Evita duplicar a tarefa em
    # tentativas repetidas do mesmo bloqueio.
    dependency_task_id: str | None = None
    # Controles em voo (Tela 15, wf §17.2, ADR-0048) — `None`/vazio/`False` = nenhum
    # override manual, comportamento idêntico a toda orquestração anterior a esta
    # ADR. `effort_override`/`executor_override` vencem a resolução normal de
    # etapa (`_effective_effort`/`_effective_executor`) na próxima execução deste
    # card, sem mudar o comportamento de nenhum outro card.
    effort_override: str | None = None
    executor_override: str | None = None
    # "Pausar" (wf §17.2) não interrompe um processo em andamento (nada no runtime
    # hoje suporta isso) — impede a PRÓXIMA execução manual/automática deste card
    # até ser desmarcado. Reinterpretação honesta e restrita, documentada na ADR.
    pausado: bool = False
    # "Adicionar contexto" (wf §17.2) — instruções extras do operador, entram no
    # próximo prompt do agente (`_build_task`) junto de `correction_actions`.
    contexto_adicional: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class Board(BaseModel):
    id: str = Field(default_factory=lambda: gen_id("board"))
    orchestration_id: str
    project_id: str | None = None
    name: str
    scope: str = "orchestration"
    columns: list[BoardColumn] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)


class CardEvent(BaseModel):
    """Movimentação de um card (§8 do fluxo.md): cada uma registra motivo, resultado,
    evidências e próxima ação — não só data e ator (ADR-0019).

    `model`/`effort`/`phase`/`execution_id` (Tela 28, wf §30, ADR-0051) são
    preenchidos só quando o evento nasce de uma execução de agente real
    (`run_card`/`run_plan`) — movimentação manual/automação de coluna deixa os
    quatro em branco, honesto (nenhum agente rodou, não há o que registrar).
    Eventos gravados ANTES desta ADR também ficam em branco nesses campos —
    não há como reconstruir histórico que nunca foi capturado.
    """

    id: str = Field(default_factory=lambda: gen_id("cardevt"))
    card_id: str
    type: str
    from_status: ColumnKey | None = None
    to_status: ColumnKey | None = None
    actor: str = "system"
    reason: str = ""
    result: str = ""
    evidence: list[str] = Field(default_factory=list)
    next_action: str = ""
    model: str | None = None
    effort: str | None = None
    # Fase da esteira (F1-F7) no momento do evento — distinta de `from_status`/
    # `to_status` (coluna do Kanban); wf §30.2 pede "Etapa" separado de "Ação".
    phase: str | None = None
    execution_id: str | None = None
    created_at: str = Field(default_factory=now_iso)
