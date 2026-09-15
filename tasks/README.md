# tasks/ — Backlog de melhorias arquiteturais (MEL)

Tasks derivadas da revisão arquitetural registrada em [feedback.md](../feedback.md)
(base `main` @ `164c6ab`). Cada task referencia a seção do feedback que a motiva e
cita as evidências no código.

> O backlog histórico do MVP-1 (TASK-01…TASK-15) continua registrado em
> [`.aso/kanban/board.json`](../.aso/kanban/board.json).

## Convenções

- **ID:** `MEL-NN`. A dezena indica a fase do roadmap (0x clareza, 1x–2x correção,
  3x robustez, 4x inteligência, 5x escala e limpeza).
- **Status inicial:** todas as tasks nascem em `Backlog`. Só o operador humano as move.
- **Prioridade:** P0 (bloqueia a razão de existir do projeto) → P3 (oportunista).
- **Esforço:** baixo (≤ 1 dia) · médio (2–4 dias) · alto (≥ 1 semana, incremental).
- **Números de linha** citados são do commit `164c6ab`; prefira localizar pela função.

## Definition of Done comum (vale para toda task)

1. Bateria completa verde, na ordem do [CLAUDE.md](../CLAUDE.md):
   `ruff check` → `ruff format` → `mypy src` → `alembic upgrade head && alembic check`
   → `pytest -q -p no:cacheprovider --cov=src/aso --cov-fail-under=80`.
2. Mudança em persistência ou boot: validação também no Docker/Postgres
   (`docker compose down -v && up -d --build`, `/health` = 200, `./scripts/smoke.sh`).
3. Todo comportamento novo entra com teste; toda correção de bug entra com teste de
   regressão que falhava antes.
4. Decisão arquitetural relevante vira ADR em `docs/adrs/`, referenciando (ou
   supersedendo formalmente) as ADRs anteriores. A task indica quando é obrigatória.
5. Governança atualizada: card no `.aso/kanban/board.json` com `status: "Done"`,
   critérios e `evidence`; linha no `CHANGELOG.md`; docs afetadas sincronizadas.
6. Nenhum commit ou push feito por agente (regra 7).

## Índice

### Fase 1 — Clareza

| ID | Título | Prio | Esforço | Depende de |
|---|---|---|---|---|
| [MEL-01](MEL-01-mapa-regras-governanca.md) | Mapa regra inviolável → código → teste | P1 | baixo | — |
| [MEL-02](MEL-02-corrigir-docs-contraditorias.md) | Corrigir documentação contraditória e desatualizada | P1 | baixo | MEL-01 |
| [MEL-03](MEL-03-openapi-gerado.md) | OpenAPI gerado a partir do FastAPI, verificado no CI | P1 | baixo | — |
| [MEL-04](MEL-04-separar-meta-governanca.md) | Separar a meta-governança da construção do produto | P1 | baixo | — |
| [MEL-05](MEL-05-how-it-works-glossario.md) | `HOW_IT_WORKS.md` com fluxo real e glossário | P1 | baixo | MEL-02 |
| [MEL-06](MEL-06-referencias-secao-qualificadas.md) | Qualificar referências "§n" e remover referências mortas | P2 | médio | — |
| [MEL-07](MEL-07-reorganizar-documentacao.md) | Reorganizar a estrutura de documentação | P2 | médio | MEL-02, MEL-04, MEL-05 |

### Fase 2 — Correção

| ID | Título | Prio | Esforço | Depende de |
|---|---|---|---|---|
| [MEL-10](MEL-10-avanco-de-fase-exige-gate.md) | Avanço de fase exige gate aprovado e papel admin | **P0** | baixo | — |
| [MEL-11](MEL-11-aprovacao-estrategia-bloqueia.md) | Aprovação de estratégia pendente bloqueia a execução | **P0** | baixo | — |
| [MEL-12](MEL-12-ci-declarada-restrita.md) | Restringir a CI declarada manualmente | **P0** | baixo | — |
| [MEL-13](MEL-13-claim-atomico-de-card.md) | Claim atômico do card antes de executar | **P0** | médio | — |
| [MEL-14](MEL-14-contrato-wrapper-cli.md) | Contrato do wrapper CLI: perguntas × execução | **P0** | médio | — |
| [MEL-15](MEL-15-seguranca-por-padrao.md) | Segurança por padrão | **P0** | médio | — |
| [MEL-16](MEL-16-gate-escopado-por-fase.md) | Quality gate escopado por fase, sem aprovação vazia | P1 | médio | MEL-10 |
| [MEL-17](MEL-17-congelamento-de-snapshot.md) | Decidir e aplicar o congelamento de snapshots | P1 | médio | MEL-16 |
| [MEL-18](MEL-18-docs-first-via-pr.md) | Docs-first e self-heal via entrega governada | P1 | médio | MEL-12 |
| [MEL-19](MEL-19-context-builder.md) | ContextBuilder e injeção de contexto nos providers | P1 | médio | MEL-14 |
| [MEL-20](MEL-20-bugs-pontuais.md) | Correção de bugs pontuais encontrados na revisão | P1 | baixo | — |

### Fase 3 — Robustez

| ID | Título | Prio | Esforço | Depende de |
|---|---|---|---|---|
| [MEL-30](MEL-30-registro-agent-runs.md) | Registro persistido de execuções (`agent_runs`) e IDs propagados | P1 | médio | — |
| [MEL-31](MEL-31-execucao-assincrona.md) | Execução assíncrona com fila e workers | P1 | alto | MEL-13, MEL-30 |
| [MEL-32](MEL-32-extrair-servicos.md) | Extrair serviços do `OrchestrationService` e dividir `app.py` | P1 | alto | MEL-10…MEL-13 |
| [MEL-33](MEL-33-persistencia-incremental.md) | Persistência append-only, versão otimista e cache com descarte | P1 | alto | MEL-32 |
| [MEL-34](MEL-34-testes-negativos-governanca.md) | Suíte de testes negativos de governança via API | P1 | médio | MEL-10…MEL-15 |
| [MEL-35](MEL-35-retry-unico.md) | Retry único via roteamento de falha | P2 | baixo | — |
| [MEL-36](MEL-36-import-linter.md) | Regra de dependência verificada (import-linter) | P2 | baixo | — |

### Fase 4 — Inteligência

| ID | Título | Prio | Esforço | Depende de |
|---|---|---|---|---|
| [MEL-40](MEL-40-discovery-review-com-repo.md) | Discovery e revisão com leitura do repositório | P1 | médio | MEL-14 |
| [MEL-41](MEL-41-custo-todos-executores.md) | Uso e custo para todos os executores | P1 | médio | MEL-30 |
| [MEL-42](MEL-42-structured-outputs.md) | Structured outputs com JSON Schema | P2 | médio | MEL-14 |
| [MEL-43](MEL-43-effort-por-provider.md) | Effort como campo do contrato, mapeado por provider | P2 | médio | MEL-14 |
| [MEL-44](MEL-44-indice-estrutural-workspace.md) | Índice estrutural do workspace por commit | P2 | alto | MEL-19 |
| [MEL-45](MEL-45-similaridade-demandas.md) | Recomendações por similaridade de demandas | P3 | médio | MEL-30 |

### Fase 5 — Escala e limpeza

| ID | Título | Prio | Esforço | Depende de |
|---|---|---|---|---|
| [MEL-50](MEL-50-paralelismo-por-onda.md) | Paralelismo por onda na fila de execução | P2 | médio | MEL-31 |
| [MEL-51](MEL-51-lock-git-por-repositorio.md) | Lock git por repositório | P2 | baixo | — |
| [MEL-52](MEL-52-read-models.md) | Consultas sem hidratar agregados | P2 | médio | MEL-32 |
| [MEL-53](MEL-53-remover-codigo-morto.md) | Remover código morto e abstrações vazias | P2 | médio | MEL-17 |
| [MEL-54](MEL-54-catalogo-unico-executores.md) | Catálogo único de executores | P2 | médio | MEL-14 |
| [MEL-55](MEL-55-consolidar-ui.md) | Consolidar a UI legada e as páginas novas | P2 | médio | — |
| [MEL-56](MEL-56-multiprocesso.md) | Suporte a múltiplos processos (só se necessário) | P3 | alto | MEL-31, MEL-33 |
| [MEL-57](MEL-57-cache-por-commit.md) | Cache de discovery e índice por commit | P3 | médio | MEL-44 |

## Ordem sugerida

```
MEL-10 · MEL-11 · MEL-12 · MEL-15   (P0 baratos, independentes — podem ir juntos)
   └─ MEL-13 → MEL-14 → MEL-34
MEL-01 → MEL-02 → MEL-05   ·   MEL-03   ·   MEL-04
MEL-16 → MEL-17 · MEL-18 · MEL-19 · MEL-20
MEL-30 → MEL-32 → MEL-31 → MEL-33
MEL-40 · MEL-41 · MEL-42 · MEL-43 → MEL-44
MEL-5x conforme necessidade
```
