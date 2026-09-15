# MEL-33 — Persistência append-only, versão otimista e cache com descarte

| Campo | Valor |
|---|---|
| Fase do roadmap | 3 — Robustez |
| Prioridade | P1 |
| Esforço | alto |
| Status | Backlog |
| Depende de | MEL-32 (passo 1, `BundleStore`) |
| Origem | [feedback.md](../feedback.md) §3 (escalabilidade), §13.3 problema 7 |
| Requer ADR | **Sim**: supersede o modelo de gravação da ADR-0006 |

## Problema

- `SqlAlchemyOrchestrationRepository.save` apaga todas as tabelas filhas da orquestração e
  reinsere o agregado inteiro (eventos, patches, histórico do contexto, card events…) a cada
  `_persist`. O custo cresce com o tamanho do histórico; o "log append-only" é regravado.
- `_bundles` ([:731](../src/aso/control/orchestration_service.py#L731)) nunca descarta
  entradas: toda orquestração lida fica em memória.
- Locks são só do processo. API e CLI (`aso`) sobre o mesmo banco sobrescrevem um ao outro
  (última gravação vence) [H]. Multi-worker do uvicorn é inviável e não documentado.
- `create_all` roda no boot além do Alembic (`create_schema=True` por padrão, [repository.py:158](../src/aso/db/repository.py#L158)).

## Mudança proposta

1. **Append-only real** para `events`, `card_events`, `context_patches`, `context_history`,
   `conflicts`, `gate_results`: `save` insere só os itens novos (rastrear "persistido até" por coleção).
2. **Upsert** para entidades mutáveis (orquestração, cards, PRs, aprovações, incidentes…),
   sem apagar tabelas.
3. **Versão otimista:** `orchestrations.version` incrementada a cada gravação;
   `UPDATE … WHERE version = :esperada`; conflito → recarregar o bundle e levantar
   `ConcurrentModificationError` (409 na API).
4. **Cache com descarte:** LRU com limite (`ASO_BUNDLE_CACHE_MAX`), invalidado quando a versão no banco muda.
5. `create_schema=False` no `bootstrap`; `create_all` só em testes.
6. Documentar em OPERATIONS a restrição de processo único até MEL-56.

## Critérios de aceite

- [ ] Gravar após N eventos insere só os novos (teste conta INSERTs/DELETEs).
- [ ] Duas instâncias do serviço sobre o mesmo banco: a segunda gravação concorrente recebe conflito em vez de perder dados.
- [ ] Cache respeita o limite configurado.
- [ ] Boot em produção não chama `create_all`.
- [ ] Ordem de FK validada no Postgres (docker compose + smoke), incluindo exclusões.

## Testes obrigatórios

- Integração SQLite e **Postgres**: gravações incrementais, reidratação idêntica ao estado anterior.
- Teste de concorrência entre dois `OrchestrationService` com o mesmo URL.
- Regressão de `test_persistence*.py`, `test_normalization.py`, `test_race_stress.py`.

## Arquivos prováveis

- `src/aso/db/repository.py`, `src/aso/db/models.py`, `migrations/versions/`
- `src/aso/persistence/ports.py`, `persistence/memory.py`, `persistence/state.py`
- `src/aso/application/bundles.py` (MEL-32), `src/aso/bootstrap.py`
- `docs/ARCHITECTURE.md`, `docs/OPERATIONS.md`

## Riscos

- Armadilha conhecida de ordem de INSERT/DELETE por FK no Postgres (ver CLAUDE.md): validar sempre no Docker.
