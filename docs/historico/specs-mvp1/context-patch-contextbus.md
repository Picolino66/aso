# SPEC — ContextPatch + ContextBus

- **Card:** TASK-09
- **Épico:** EPIC-6 (Governança)
- **Fase:** F5
- **ADRs:** ADR-0003
- **Requisitos:** §18, §19, §40 Task 9
- **Depende de:** TASK-03

## Objetivo

Implementar o `ContextBus`, o único componente autorizado a aplicar alterações no `OrchestratorContext` (§8.3, §19, ADR-0003), e o pipeline de validação de 7 etapas que todo `ContextPatch` (§18) atravessa antes de ser aplicado. Este é o coração da governança: garante que outputs de agentes só entrem no contexto após validação, mantendo a verdade central soberana.

Se o patch é aprovado, aplica-o, incrementa a versão do contexto, registra evento e atualiza cards; se reprovado, registra um `Conflict` e move o card para Blocked/WaitingHuman.

## Escopo

- Incluído:
  - Modelo `ContextPatch` (§18) e `Conflict` (§20).
  - Pipeline de 7 etapas (§19): 1) schema validation; 2) permission check; 3) conflict detection; 4) snapshot lock validation; 5) ADR consistency validation; 6) contract compatibility validation; 7) quality gate impact check.
  - Aplicação atômica: aplica patch → incrementa `version` (via serviço de contexto) → registra evento → persiste histórico → atualiza cards relacionados.
  - Fluxo de reprovação: cria `Conflict`, move card para Blocked/WaitingHuman.
  - Resposta do bus: `applied | rejected | queued_conflict`.
- Fora de escopo (MVP-1):
  - `ConflictResolutionAgent` automático (§15.15 — MVP-2); no MVP-1 conflito é registrado e escalado a humano.
  - Locks finos por `target_keys` e resolução de contenção concorrente avançada (TRISK-02 — MVP-2); validação básica de snapshot lock apenas.
  - Detecção sofisticada de todos os 13 tipos de conflito (§20); MVP-1 cobre os detectáveis por regra simples (schema, permissão, snapshot lock, ADR aceita, contrato congelado).

## Comportamento esperado

- `POST /v1/context-patches` nunca escreve direto: enfileira no ContextBus, que roda o pipeline e responde `applied | rejected | queued_conflict` (regra de contrato — api.md).
- Etapa 1 (schema): patch inválido é rejeitado imediatamente.
- Etapa 2 (permission): agente sem permissão para o `target_path`/ação → rejeição (TOOL_PERMISSION_CONFLICT).
- Etapa 3 (conflict): usa o ConflictDetector; conflito detectado → não aplica.
- Etapa 4 (snapshot lock): patch que altera seção congelada por snapshot é rejeitado sem ADR/approval (SNAPSHOT_LOCK_CONFLICT — ver [snapshot-engine.md](snapshot-engine.md)).
- Etapa 5 (ADR consistency): patch contra ADR aceita → conflito (ARCHITECTURE_CONFLICT).
- Etapa 6 (contract compatibility): patch incompatível com contrato aprovado → conflito (CONTRACT_CONFLICT).
- Etapa 7 (quality gate impact): registra impacto do patch nos gates.
- Aprovado → aplica atomicamente e incrementa versão do contexto (invariante: só o ContextBus escreve — ADR-0003); reprovado → cria `Conflict` e move card para Blocked (ou WaitingHuman se exigir humano).
- Todo desfecho gera evento (EventLog — ver [observability-basic.md](observability-basic.md)).

## Contratos / Interfaces

Módulo: `src/aso/governance/contextbus/`.

```python
# src/aso/governance/contextbus/context_bus.py
class PatchResult(str, Enum):
    applied = "applied"
    rejected = "rejected"
    queued_conflict = "queued_conflict"

class ContextBus:
    def __init__(self, ctx: OrchestratorContextService, validator: ContextPatchValidator,
                 detector: ConflictDetector, cards: CardService): ...
    async def submit(self, patch: ContextPatch) -> ContextBusResponse: ...

# src/aso/governance/contextbus/validator.py
class ContextPatchValidator:
    async def run_pipeline(self, patch: ContextPatch) -> ValidationReport: ...  # 7 etapas §19

# src/aso/governance/contextbus/conflict_detector.py
class ConflictDetector:
    async def detect(self, patch: ContextPatch) -> list[Conflict]: ...

class ContextBusResponse(BaseModel):
    result: PatchResult
    patch_id: UUID
    context_version: int | None = None
    conflict_ids: list[UUID] = []
```

- Endpoints: `POST /v1/context-patches`, `GET /v1/orchestrations/{id}/conflicts` (ver [api-minimal.md](api-minimal.md)).

## Critérios de aceite

- [ ] Patch validado nas 7 etapas do §19 (ordem preservada; falha em qualquer etapa impede aplicação).
- [ ] Patch aprovado é aplicado e incrementa a `version` do OrchestratorContext.
- [ ] Patch reprovado gera `Conflict` e move o card para Blocked/WaitingHuman.
- [ ] `POST /v1/context-patches` responde `applied | rejected | queued_conflict` e nunca escreve fora do bus.

## Rastreabilidade

§18/§19/§40 Task 9 → ADR-0003 → esta spec → TASK-09 → `src/aso/governance/contextbus/` (context_bus, validator, conflict_detector), tabelas `context_patches`, `conflicts` → `tests/unit/test_context_patch_validator.py`, `tests/integration/test_context_bus.py`
