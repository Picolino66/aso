# MEL-02 — Corrigir documentação contraditória e desatualizada

| Campo | Valor |
|---|---|
| Fase do roadmap | 1 — Clareza |
| Prioridade | P1 |
| Esforço | baixo |
| Status | Backlog |
| Depende de | MEL-01 |
| Origem | [feedback.md](../feedback.md) §2 (itens 1–4, 11, 14–22, 24), §13.3 problema 9 |
| Requer ADR | Não |

## Problema

A documentação de núcleo descreve componentes e garantias que o código não tem. Regra do
projeto: `código executável > ADRs > docs` — então as docs devem ser corrigidas para refletir
o código (ou marcar a lacuna com link para a task).

## Correções

| Arquivo | Correção |
|---|---|
| [docs/context.md](../docs/context.md) | "7 etapas" → 8 funções, 2 sem efeito; remover "aciona ConflictResolutionAgent", "locks por target_keys (asyncio)" e "Idempotency-Key"; "todo agente recebe o contexto" → marcar como não implementado (MEL-19) |
| [src/aso/governance/contextbus.py](../src/aso/governance/contextbus.py) | Docstring "7 etapas" → descrição real |
| [docs/quality-gates.md](../docs/quality-gates.md) e [docs/snapshots.md](../docs/snapshots.md) | Remover a tabela de estado "F1–F4 PASSED, F5 pendente" (é do processo de construção, não do produto); descrever os critérios reais e a ausência de congelamento (MEL-17) |
| [docs/architecture.md](../docs/architecture.md) | Remover PhaseController, AgentRouter, DependencyGraph, HumanApprovalEngine, TerminalRuntime, AuditLog, ToolPermissionEngine; "workers asyncio" → handlers síncronos em threadpool, processo único; "UI diferida" → console atual; "sem ciclos" → ciclo control↔observability (MEL-36) |
| [docs/api.md](../docs/api.md) | Formato de erro real (`{"detail"}`), paginação por `X-Total-Count`, IDs `prefixo_hex`; remover `Idempotency-Key` |
| [docs/agents.md](../docs/agents.md) | Explicar papel × executor × função de agente; marcar os 6 papéis que nunca recebem card |
| [docs/index.md](../docs/index.md) | Índice completo das 55 ADRs (incluir 0007 e 0028–0055); remover "estado da orquestração" do processo de construção |
| [README.md](../README.md) | Remover contagem de testes/cobertura fixa (vai para o CI); aviso de que agentes CLI não rodam na imagem Docker atual |
| `agents/README.md`, `skills/README.md` (se ainda existirem) | Remover `.aso/providers.yaml`, `SkillResolver` e `ExternalSkillResolver`, ou mover para histórico (MEL-04) |

## Critérios de aceite

- [ ] Cada linha da tabela acima aplicada.
- [ ] Nenhuma menção restante a componentes inexistentes (verificável por `grep` dos nomes listados).
- [ ] Onde a garantia ainda não existe, a doc diz isso e aponta a task.

## Arquivos prováveis

Os listados na tabela.
