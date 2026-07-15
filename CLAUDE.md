# CLAUDE.md

Guia para agentes de IA (Claude Code e afins) trabalhando neste repositório.
Leia antes de editar código. **Tudo em pt-BR: docs, textos de UI e comentários.**

## O que é este projeto

**ASO Runtime** — runtime de orquestração multiagente para engenharia de software
autônoma (fases F1–F7). Visão geral e comandos em [README.md](README.md);
requisitos originais em [requerimentos.md](requerimentos.md).

## Regras invioláveis de governança

Estas regras são a razão de existir do projeto — não as contorne:

1. **O ContextBus é o único escritor do contexto canônico.** Nunca mute o estado
   de governança fora dele. Toda mudança é um `ContextPatch` que passa pelo
   pipeline de validação de 8 etapas em
   [src/aso/governance/contextbus.py](src/aso/governance/contextbus.py).
2. **Deny-by-default nas permissões.** Um agente só escreve nas chaves que sua
   `PermissionPolicy` autoriza.
3. **Não avance de fase com quality gate reprovado.**
4. **Ações críticas exigem aprovação humana** (merge, rollback, aprovações). Os
   endpoints correspondentes exigem papel `admin`.
5. **Agentes que alteram código rodam em worktree git isolado**
   ([src/aso/execution/worktree.py](src/aso/execution/worktree.py)); nunca opere
   na branch principal. Colete o diff antes de qualquer merge.
6. **Merge é governado**: só ocorre com CI `passed` + review `approved`.
7. **Nunca faça commit ou push.** Agentes podem preparar mudanças e apresentar
   diffs, mas a criação de commits e qualquer envio para repositórios remotos
   ficam reservados ao operador humano.
8. **Rastreabilidade**: requisito → ADR → spec → card → implementação → teste →
   gate → snapshot. Toda decisão arquitetural relevante vira ADR.
9. **Secrets só por variável de ambiente** (`ASO_API_KEYS` etc.), nunca no repo.

## Fluxo de trabalho obrigatório ao terminar um incremento

Este projeto é construído de forma incremental e **cada incremento só é
considerado pronto após validação integral**. Sempre, ao final de uma mudança:

```bash
. .venv/bin/activate
ruff check src tests            # 1. lint (falha rápido)
ruff format src tests           # 2. formatação (aplica)
mypy src                        # 3. tipagem estrita
alembic upgrade head && alembic check   # 4. migrations em dia + sem diffs
pytest -q -p no:cacheprovider --cov=src/aso --cov-fail-under=80   # 5. testes + cobertura
```

Para mudanças que tocam persistência ou o boot, **valide também no Docker/Postgres**
(o SQLite dos testes não impõe FKs — bugs de ordem de INSERT só aparecem no
Postgres):

```bash
docker compose down -v && docker compose up -d --build
# aguarde /health = 200, rode ./scripts/smoke.sh, depois docker compose down -v
```

## Ao concluir, atualize a governança (não pule)

O estado do runtime é versionado em arquivos que precisam refletir a realidade:

- [.aso/context/orchestrator-context.json](.aso/context/orchestrator-context.json)
  — `coverage_report` (nº de testes, cobertura, escopo), `cards_done`,
  `increments_post_o5`.
- [.aso/kanban/board.json](.aso/kanban/board.json) — adicione o(s) card(s) do
  incremento com `status: "Done"`, critérios de aceite e `evidence`.
- [CHANGELOG.md](CHANGELOG.md) — uma linha por entrega, em pt-BR.

Mantenha `docs/` sincronizado quando a mudança afetar arquitetura, contratos ou
operação; registre decisões arquiteturais em `docs/adrs/` referenciando ADRs
anteriores (nunca contrarie uma ADR aceita sem supersedê-la).

## Convenções de código

- Python 3.12, **Pydantic v2** para modelos, tipagem completa (`mypy --strict`).
- Comentários e docstrings em **pt-BR**, explicando o *porquê* de governança.
- Siga o estilo do arquivo vizinho; a regra de dependência aponta para dentro
  (Clean Architecture) — veja `module_map` no orchestrator-context.
- Rode `ruff check` **antes** de `ruff format` (o check falha rápido em erros
  reais; o format só reformata). Linhas ≤ 100 colunas.
- Testes ficam em `tests/unit/` e `tests/integration/`; toda feature nova entra
  com teste. Integrações de execução usam git real em `tmp_path`.

## Estrutura (onde mexer)

```
src/aso/control/       # OrchestrationService (glue), decision engine, planner, run_plan, aprovações
src/aso/governance/    # ContextBus, ContextPatch, ConflictDetector, ADR, QualityGate, Snapshot
src/aso/execution/     # WorktreeManager, CliAgentExecutionProvider, CandidateRunner, PR/merge
src/aso/kanban/        # Board, cards, automação por eventos
src/aso/agents/        # AgentRegistry, AgentSupervisor, ExecutionProvider
src/aso/observability/ # logging, ratelimit, tracing, metrics, broker (SSE)
src/aso/api/           # FastAPI (app.py, auth.py, static/index.html = console)
src/aso/cli/           # Typer
src/aso/db/            # ORM normalizado + repository
migrations/            # Alembic
```

O ponto de entrada que amarra tudo é
[src/aso/control/orchestration_service.py](src/aso/control/orchestration_service.py).

## Armadilhas conhecidas

- **FKs no Postgres**: o `save` insere em níveis (orchestration → board/plan →
  filhos → tabelas de junção) e deleta em ordem FK-safe. Não reordene sem testar
  no Postgres.
- **PK composta de `adrs`** é `(orchestration_id, id)` — ids de ADR são
  sequenciais por orquestração; não trate `adr_id` como global.
- **Migrations autogeradas** com JSONB podem gerar `Text()` sem import — confira
  `from sqlalchemy import Text`.
- **SSE**: testes só cobrem o `EventBroker`; o streaming é validado ao vivo no
  Docker (não escreva testes que consomem o gerador infinito no TestClient).
- **Volume Postgres velho** após teardown falho causa "Can't locate revision" —
  resolva com `docker compose down -v` e suba de novo.

## Estilo de interação (este projeto)

O desenvolvimento é conduzido por um menu incremental: ao concluir um incremento,
apresente opções **(a)/(b)/(c)/(d)** de próximos passos e aguarde a seleção do
usuário (por letra). Não avance para o próximo incremento sem seleção.
