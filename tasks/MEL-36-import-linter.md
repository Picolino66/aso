# MEL-36 — Regra de dependência verificada (import-linter)

| Campo | Valor |
|---|---|
| Fase do roadmap | 3 — Robustez |
| Prioridade | P2 |
| Esforço | baixo |
| Status | Backlog |
| Depende de | — (revisar após MEL-32) |
| Origem | [feedback.md](../feedback.md) §2 item 17, §3 (dependências) |
| Requer ADR | Não (aplica ADR-0001) |

## Problema

A arquitetura afirma que a regra de dependência é "verificável por lint de imports" e
"sem ciclos", mas não há verificação. O grafo real mostra:

- ciclo `control` ↔ `observability`: [metrics.py:13](../src/aso/observability/metrics.py#L13) importa `OrchestrationService`;
- `api/app.py` importa 7 pacotes além de `control`;
- `db`, `persistence` e `bootstrap` não aparecem no `module_map` declarado;
- `persistence` depende de modelos de `control`, `governance`, `kanban` e `agents`.

## Mudança proposta

1. Adicionar `import-linter` ao extra `dev` e contratos em `pyproject.toml` (`[tool.importlinter]`):
   - camadas: `api | cli` → `bootstrap` → `control/application` → `agents | execution | kanban | governance | observability` → `shared`;
   - `governance`, `kanban` e `shared` sem dependência de `control`;
   - `observability` não importa `control`.
2. Quebrar o ciclo: `MetricsService` recebe uma porta de leitura (protocolo) em vez de `OrchestrationService`.
3. Atualizar o `module_map` na documentação para o grafo real permitido.
4. Rodar `lint-imports` no CI, antes dos testes.

## Critérios de aceite

- [ ] `lint-imports` passa no CI.
- [ ] Nenhum ciclo entre pacotes.
- [ ] Documentação e contratos do import-linter descrevem o mesmo grafo.
