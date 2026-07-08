# Kanban — ASO Runtime

> Fase F4. O Kanban é o **plano de execução** (ADR-0002), não apenas visual. Board inicial em [`.aso/kanban/board.json`](../.aso/kanban/board.json).

## Colunas (§16.2)

`Backlog → Ready → Planning → In Progress → Waiting Agent → Waiting Human → Review → Testing → Blocked → Failed → Done → Archived`

## Swimlanes (§16.3)

Por fase (F1–F7), por agente, por épico, por prioridade, por tipo de trabalho, por release. Board MVP-1 usa swimlane por **épico**.

## Tipos de card (§16.4)

`Epic, Feature, Task, Bug, TechDebt, ADRTask, Research, Review, Test, Documentation, Deploy, Incident, Improvement`

## Automação por eventos (§16.7)

| Evento | Transição |
|---|---|
| Agent started | → In Progress |
| Agent needs input | → Waiting Human |
| PR opened | → Review |
| CI failed | → Failed / Blocked |
| Review requested changes | → Review |
| Tests passed | → Testing / Done |
| Quality gate passed | → Done |
| Quality gate failed | → Blocked |

## Regras (§16.6)

Todo trabalho executável vira card com fase; card técnico tem critério de aceite; card de agente registra agente; card que altera arquitetura vincula ADR; card que altera API vincula contrato; card de código vincula branch/worktree/PR; card bloqueado registra motivo; card finalizado tem evidência.
