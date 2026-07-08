# SPEC — API mínima (FastAPI)

- **Card:** TASK-13
- **Épico:** EPIC-7 (Interfaces API/CLI)
- **Fase:** F5
- **ADRs:** ADR-0005
- **Requisitos:** §28, §40 Task 13
- **Depende de:** TASK-09, TASK-11, TASK-12

## Objetivo

Expor o núcleo de governança do ASO Runtime como API HTTP (FastAPI), driving adapter da arquitetura hexagonal (F2 §2). Entrega os endpoints do §28 aderentes ao contrato de máquina `contracts/openapi.yaml`, permitindo criar orquestrações, operar o Kanban, submeter patches ao ContextBus, rodar gates, gerar snapshots e registrar ADRs.

Segue as convenções de ADR-0005: prefixo `/v1`, erros RFC 7807-like, idempotência por `Idempotency-Key` em criações, paginação e IDs UUID (exceto ADR).

## Escopo

- Incluído (núcleo §28, conforme api.md):
  - Orchestrations: `POST/GET /v1/orchestrations`, `GET /v1/orchestrations/{id}`, `.../context`, `.../plan`, `.../timeline`, `POST .../resume|cancel|rollback|retry`.
  - Kanban: `GET/POST /v1/boards`, `GET /v1/boards/{id}`, `GET/POST /v1/boards/{id}/cards`, `PATCH /v1/cards/{id}`, `POST /v1/cards/{id}/move|assign-agent|run|block|unblock`.
  - Agents: `GET /v1/agents`, `GET /v1/agents/{id}`, `GET /v1/agents/{id}/runs`, `POST /v1/agents/{id}/run`, `POST /v1/agent-runs/{id}/cancel|nudge`.
  - Governança: quality-gates (`GET`, `POST .../run`, `GET /v1/quality-gates/{id}`), ADRs (`GET/POST`, `GET/PATCH /v1/adrs/{id}`), snapshots (`GET/POST`, `GET /v1/snapshots/{id}`, `POST .../restore`, `GET .../diff/...`), approvals (`GET`, `POST .../approve|reject`), context-patches (`POST /v1/context-patches`), conflicts (`GET /v1/orchestrations/{id}/conflicts`).
  - Convenções: erros RFC7807-like, `Idempotency-Key`, paginação `{items,total,page,page_size}`.
- Fora de escopo (MVP-1):
  - Endpoints de providers/cli-agents/agent-role-bindings/agent-router (§26A.8 — MVP posterior).
  - Autenticação/autorização de API (local-first; sem authz no MVP-1).
  - WebSocket/streaming de timeline (polling apenas).

## Comportamento esperado

- Todos os endpoints sob `/v1`; respostas e erros no formato padronizado (ADR-0005).
- `POST /v1/context-patches` delega ao ContextBus e responde `applied | rejected | queued_conflict` — nunca escreve direto no contexto (regra de contrato — api.md).
- `POST /v1/cards/{id}/run` só executa se as dependências (`depends_on`) estiverem `Done` e as permissões de tool forem satisfeitas (senão `409/422`).
- `POST /v1/orchestrations/{id}/rollback` exige `to_snapshot` existente e aprovado; gera ADR de rollback (comportamento delegado ao SnapshotEngine/ADRRegistry — pode ser parcial no MVP-1).
- Ações críticas (§24) retornam `202 Accepted` e criam `HumanApproval` pendente em vez de executar.
- `Idempotency-Key` em `POST` de criação (orchestrations, cards, adrs, approvals) evita duplicação.
- A API é aderente ao `contracts/openapi.yaml` (contrato-first); divergência é conflito de contrato.
- Cada request carrega/gera correlation IDs (`orchestration_id`/`card_id`) para logs (ver [observability-basic.md](observability-basic.md)).

## Contratos / Interfaces

Módulo: `src/aso/api/`. App FastAPI em `src/aso/api/main.py`; routers por recurso em `src/aso/api/routers/`.

```python
# src/aso/api/main.py
app = FastAPI(title="ASO Runtime API", version="1.0.0")
app.include_router(orchestrations.router, prefix="/v1")
app.include_router(boards.router, prefix="/v1")
app.include_router(cards.router, prefix="/v1")
app.include_router(agents.router, prefix="/v1")
app.include_router(governance.router, prefix="/v1")  # gates, adrs, snapshots, approvals, context-patches, conflicts

# exemplo de handler
@router.post("/context-patches")
async def submit_patch(patch: ContextPatchCreate, bus: ContextBus = Depends(...)) -> ContextBusResponse: ...
```

- DTOs de entrada/saída = schemas Pydantic de [domain-models.md](domain-models.md).
- Handler de erro global mapeia exceções de domínio para o formato RFC7807-like.

## Critérios de aceite

- [ ] Endpoints de orchestrations/boards/cards/context/gates/snapshots/adrs disponíveis sob `/v1`.
- [ ] Aderente ao `contracts/openapi.yaml` (schema OpenAPI gerado bate com o contrato).
- [ ] `POST /v1/context-patches` responde `applied|rejected|queued_conflict` via ContextBus.
- [ ] Ações críticas retornam `202` + criam `HumanApproval`; `Idempotency-Key` respeitado em criações.

## Rastreabilidade

§28/§40 Task 13 → ADR-0005, `contracts/openapi.yaml` → esta spec → TASK-13 → `src/aso/api/main.py`, `src/aso/api/routers/*` → `tests/integration/test_api_orchestrations.py`, `tests/integration/test_api_governance.py`
