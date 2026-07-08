# SPEC — Observabilidade básica + docs

- **Card:** TASK-15
- **Épico:** EPIC-8 (Observabilidade & Docs)
- **Fase:** F5
- **ADRs:** —
- **Requisitos:** §33, §38, §40 Task 15
- **Depende de:** TASK-13

## Objetivo

Entregar a observabilidade básica do runtime (F2 §9): logs estruturados com correlation IDs, um `EventLog` append-only de eventos de domínio e uma timeline exibível da orquestração (§33). Também atualizar a documentação `/docs` (§38) para refletir o MVP-1 implementado.

Isto torna a execução rastreável (§8.4, §39.10) e permite responder às perguntas do §33 (por que um agente foi chamado, qual gate aprovou uma fase, qual conflito bloqueou a entrega). Executado em conjunto por DevOpsAgent + DocumentationAgent (card multi_agent).

## Escopo

- Incluído:
  - Logging estruturado (JSON) com correlation IDs `orchestration_id`/`card_id`/`agent_run_id` (F2 §9).
  - `EventLog` append-only para eventos de domínio: card movido, patch aplicado/rejeitado, gate executado, snapshot gerado, ADR criada, agente executado, aprovação solicitada/decidida.
  - `AuditEvent` (§domain-model): `actor, agent, action, payload` por evento sensível.
  - Timeline da orquestração agregando eventos em ordem cronológica → `GET /v1/orchestrations/{id}/timeline`.
  - Atualização de `/docs` (§38): `kanban.md`, `context.md`, `quality-gates.md`, `snapshots.md`, `agents.md`, `api.md`, `mvp/mvp-1.md` refletindo o entregue.
- Fora de escopo (MVP-1):
  - `CostTracker`/`TokenUsageTracker` reais (§26A.11 — sem execução LLM real; campos podem ficar nulos/stub).
  - Tracing distribuído OpenTelemetry pleno (previsto; instrumentação plena em F7 — F2 §9).
  - Dashboards/UI de observabilidade (diferido).

## Comportamento esperado

- Todo log emitido inclui os correlation IDs disponíveis no contexto da operação (formato JSON estruturado).
- Cada evento de domínio relevante gera uma entrada append-only no `EventLog` com `type`, `actor`, `payload`, `created_at` e as chaves de correlação.
- `GET /v1/orchestrations/{id}/timeline` retorna os eventos da orquestração em ordem cronológica (base para `aso status`/`aso board` e para responder às perguntas do §33).
- Eventos são imutáveis (append-only); nada é sobrescrito.
- Ações sensíveis (aprovações, override de snapshot, resolução de conflito) geram `AuditEvent`.
- A documentação `/docs` é atualizada de forma consistente com o código do MVP-1 (§42 DoD: "documentação atualizada").

## Contratos / Interfaces

Módulo: `src/aso/observability/`.

```python
# src/aso/observability/logging.py
def configure_logging() -> None: ...      # JSON logs + injeção de correlation IDs
def bind_context(orchestration_id=None, card_id=None, agent_run_id=None): ...  # contextvars

# src/aso/observability/event_log.py
class EventLog:
    async def record(self, event: DomainEvent) -> None: ...   # append-only
    async def timeline(self, orchestration_id: UUID) -> list[DomainEvent]: ...

# src/aso/observability/audit.py
class AuditLog:
    async def record(self, actor: str, agent: str | None, action: str, payload: dict,
                     orchestration_id: UUID) -> AuditEvent: ...

class DomainEvent(BaseModel):
    id: UUID
    orchestration_id: UUID
    card_id: UUID | None = None
    type: str                 # card_moved | patch_applied | gate_run | snapshot_created | adr_created | ...
    actor: str
    payload: dict = {}
    created_at: datetime
```

- Endpoint: `GET /v1/orchestrations/{id}/timeline` (ver [api-minimal.md](api-minimal.md)).
- Docs atualizados sob `/docs` (§38).

## Critérios de aceite

- [ ] Logs estruturados incluem correlation IDs (`orchestration_id`/`card_id`/`agent_run_id`).
- [ ] Timeline da orquestração é exibível (`GET /v1/orchestrations/{id}/timeline`) e ordenada cronologicamente.
- [ ] Eventos de domínio são registrados append-only no `EventLog`; ações sensíveis geram `AuditEvent`.
- [ ] `/docs` atualizado (kanban, context, quality-gates, snapshots, agents, api, mvp-1) coerente com o MVP-1.

## Rastreabilidade

§33/§38/§40 Task 15 → (sem ADR) → esta spec → TASK-15 → `src/aso/observability/` (logging, event_log, audit), tabelas `audit_events`, `card_events` (timeline), `/docs/*` → `tests/unit/test_event_log.py`, `tests/integration/test_timeline.py`
