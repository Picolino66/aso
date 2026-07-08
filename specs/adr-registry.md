# SPEC — ADRRegistry

- **Card:** TASK-10
- **Épico:** EPIC-6 (Governança)
- **Fase:** F5
- **ADRs:** —
- **Requisitos:** §21, §40 Task 10
- **Depende de:** TASK-02

## Objetivo

Implementar o `ADRRegistry`: criação, numeração sequencial e listagem de Architecture Decision Records (§21). Toda decisão arquitetural relevante deve gerar uma ADR (§8.4, §39.11), e o registro é a fonte que o ContextBus consulta para validar consistência de patches contra decisões aceitas (etapa 5 do pipeline — §19).

Entrega o CRUD mínimo de ADRs com suporte a `superseded` (uma ADR pode substituir outra), sustentando a rastreabilidade requisito → ADR → task.

## Escopo

- Incluído:
  - Modelo `ADR` (§21) com `id` `ADR-XXXX` sequencial, `status` (proposed|accepted|superseded|rejected|deprecated), `context`, `options_considered[]`, `decision`, `rationale`, `tradeoffs[]`, `consequences[]`, `phase`, `created_by_agent`, `reviewed_by_agent`, `supersedes`/`superseded_by`, `linked_cards[]`, `linked_requirements[]`.
  - Numeração sequencial automática (`ADR-0001`, `ADR-0002`, ...) por orquestração/projeto.
  - Criar, obter, listar e atualizar (patch de status).
  - Suporte a supersede: marcar ADR antiga como `superseded` e nova com `supersedes`.
- Fora de escopo (MVP-1):
  - Geração automática de ADR por agente/LLM (o mock pode propor via ContextPatch, mas a redação automática é MVP-2).
  - Renderização em arquivos `docs/adrs/*.md` sincronizados (as ADRs vivem no banco; docs manuais).
  - Fluxo de review formal multiagente (§13.7 — MVP-2).

## Comportamento esperado

- `create` gera o próximo `ADR-XXXX` sequencial (sem lacunas/duplicatas) e status inicial `proposed` (ou o informado).
- `list` retorna ADRs da orquestração ordenadas por número.
- Ao supersedir: a nova ADR referencia `supersedes=ADR-XXXX`; a antiga tem `status=superseded` e `superseded_by` preenchido — operação consistente (atômica).
- ADR aceita (`accepted`) é insumo da validação de consistência do ContextBus (§19 etapa 5); alterar uma ADR aceita é ação sensível (§24 — pode exigir aprovação humana).
- IDs de ADR são `ADR-XXXX` (não UUID), conforme domain-model.
- `linked_cards`/`linked_requirements` permitem rastreabilidade bidirecional.

## Contratos / Interfaces

Módulo: `src/aso/governance/adrs/`.

```python
# src/aso/governance/adrs/adr_registry.py
class ADRRegistry:
    async def create(self, orchestration_id: UUID, data: ADRCreate) -> ADR: ...
    async def get(self, adr_id: str) -> ADR: ...
    async def list(self, orchestration_id: UUID) -> list[ADR]: ...
    async def update(self, adr_id: str, patch: ADRPatch) -> ADR: ...
    async def supersede(self, old_id: str, new: ADRCreate) -> tuple[ADR, ADR]: ...
    def _next_number(self, orchestration_id: UUID) -> str: ...  # ADR-XXXX sequencial
```

- Endpoints: `GET/POST /v1/orchestrations/{id}/adrs`, `GET/PATCH /v1/adrs/{id}` (ver [api-minimal.md](api-minimal.md)).

## Critérios de aceite

- [ ] ADR é criada e listada por orquestração.
- [ ] Numeração é sequencial (`ADR-XXXX`) sem lacunas nem duplicatas.
- [ ] `superseded` é suportado: antiga marcada `superseded`/`superseded_by`, nova com `supersedes`.
- [ ] Status transiciona (proposed → accepted → superseded/deprecated/rejected).

## Rastreabilidade

§21/§40 Task 10 → (sem ADR) → esta spec → TASK-10 → `src/aso/governance/adrs/adr_registry.py`, tabela `adrs` → `tests/unit/test_adr_registry.py`
