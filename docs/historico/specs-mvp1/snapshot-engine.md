# SPEC — SnapshotEngine básico

- **Card:** TASK-12
- **Épico:** EPIC-6 (Governança)
- **Fase:** F5
- **ADRs:** ADR-0003
- **Requisitos:** §23, §40 Task 12
- **Depende de:** TASK-11

## Objetivo

Implementar o `SnapshotEngine` que gera um `Snapshot` (§23) do `OrchestratorContext` após um quality gate aprovado, congelando as seções da fase concluída. Snapshots são versões imutáveis (O1..O7, um por fase) que garantem que decisões congeladas não sejam alteradas sem ADR/aprovação, sustentando a governança soberana (ADR-0003).

Entrega criação de snapshot, congelamento de seções (feed para a etapa 4 do ContextBus — SNAPSHOT_LOCK_CONFLICT) e restauração (restore).

## Escopo

- Incluído:
  - Modelo `Snapshot` (§23): `snapshot_version` (O0..O7), `phase`, `context_hash`, `frozen_sections[]`, `quality_gate_result_id`, `adrs[]`, `cards[]`.
  - Geração de snapshot após gate `PASSED` (congela seções relevantes da fase).
  - Congelamento: seções em `frozen_sections` não podem ser alteradas por patch sem ADR/approval (validado pelo ContextBus — §19 etapa 4).
  - Restauração de um snapshot (restore) para uma versão do contexto.
  - `context_hash` referencia a versão exata do contexto congelada (ver [orchestrator-context.md](orchestrator-context.md)).
- Fora de escopo (MVP-1):
  - Diff estrutural entre snapshots (`GET /v1/snapshots/{a}/diff/{b}` — implementação plena em MVP-5; MVP-1 pode retornar diff textual simples ou 501).
  - Rollback de orquestração completo com geração de ADR de rollback (§api.md — orquestração via `POST /rollback` é MVP-2; snapshot restore é o núcleo aqui).
  - Snapshots parciais/incrementais (MVP-5).

## Comportamento esperado

- `create(orchestration_id, phase, quality_gate_result_id)` só gera snapshot se o gate referenciado for `PASSED` (§22/§23); caso contrário, recusa.
- O snapshot captura `context_hash` da versão corrente do contexto, a lista de `frozen_sections`, `adrs[]` e `cards[]` da fase.
- `snapshot_version` segue o mapeamento fase→versão: O1 após F1, ..., O7 após F7 (§23).
- Seções congeladas: tentativa de alterá-las via ContextPatch é bloqueada pelo ContextBus (SNAPSHOT_LOCK_CONFLICT) a menos que haja ADR/approval.
- `restore(snapshot_id)` restaura o contexto para o estado congelado (cria nova versão do contexto igual ao snapshot, mantendo append-only) — operação sensível.
- Snapshot é imutável após criado.

## Contratos / Interfaces

Módulo: `src/aso/governance/snapshots/`.

```python
# src/aso/governance/snapshots/snapshot_engine.py
class SnapshotEngine:
    def __init__(self, ctx: OrchestratorContextService, gates: QualityGateEngine): ...
    async def create(self, orchestration_id: UUID, phase: PhaseCode,
                     quality_gate_result_id: UUID) -> Snapshot: ...
    async def get(self, snapshot_id: UUID) -> Snapshot: ...
    async def list(self, orchestration_id: UUID) -> list[Snapshot]: ...
    async def restore(self, snapshot_id: UUID) -> OrchestratorContext: ...
    def is_section_frozen(self, orchestration_id: UUID, section: str) -> bool: ...

class Snapshot(BaseModel):
    id: UUID
    orchestration_id: UUID
    snapshot_version: SnapshotVersion   # O0..O7
    phase: PhaseCode
    context_hash: str
    frozen_sections: list[str]
    quality_gate_result_id: UUID
    adrs: list[str] = []
    cards: list[UUID] = []
    created_at: datetime
```

- Endpoints: `GET/POST /v1/orchestrations/{id}/snapshots`, `GET /v1/snapshots/{id}`, `POST /v1/snapshots/{id}/restore`, `GET /v1/snapshots/{a}/diff/{b}` (ver [api-minimal.md](api-minimal.md)).

## Critérios de aceite

- [ ] Snapshot é gerado após gate `PASSED` (recusa se o gate não passou).
- [ ] Seções ficam congeladas (`frozen_sections`) e bloqueiam patches sem ADR/approval no ContextBus.
- [ ] `restore` é funcional e restaura o contexto para o estado congelado.
- [ ] `snapshot_version` segue o mapeamento fase→O-version (§23).

## Rastreabilidade

§23/§40 Task 12 → ADR-0003 → esta spec → TASK-12 → `src/aso/governance/snapshots/snapshot_engine.py`, tabela `snapshots` → `tests/unit/test_snapshot_engine.py`, `tests/integration/test_snapshot_restore.py`
