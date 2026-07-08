# ADR-0002 — Kanban como plano de execução

- **Status:** ACCEPTED
- **Fase:** F2
- **Criado por:** ArchitectureDesignAgent
- **Revisado por:** ReviewAgent
- **Data:** 2026-07-02

## Contexto

O requisito (§8.7, §16) determina que o Kanban não é apenas visual — ele é o mecanismo de controle operacional das tarefas. Cada card representa uma unidade de trabalho rastreável executada por humano, agente ou grupo de agentes.

## Opções consideradas

### 1. Kanban puramente visual + fila de tarefas separada
- **Prós:** separação clara entre visualização e execução.
- **Contras:** duplica estado (fila vs board); risco de board divergir da execução real; contraria §16.6 ("Kanban deve refletir o estado real").

### 2. Kanban como plano de execução (card = unidade de trabalho com máquina de estados)
- **Prós:** fonte única de verdade operacional; automação por eventos (§16.7); rastreabilidade card ↔ agente ↔ PR ↔ gate.
- **Contras:** máquina de estados do card precisa ser robusta e dirigida por eventos.

## Decisão

O **Kanban é o plano de execução**. O `Card` é a unidade de trabalho com máquina de estados (colunas §16.2) movida por eventos do runtime (§16.7). Movimentos automáticos: agent started → In Progress; needs input → Waiting Human; PR opened → Review; CI failed → Failed/Blocked; gate passed → Done; gate failed → Blocked.

## Trade-offs

- Board sempre reflete a execução real, ao custo de acoplar a lógica de execução à máquina de estados do card (mitigado por eventos de domínio desacoplados).

## Consequências

- Todo trabalho executável vira card com fase (§16.6).
- Cards vinculam requisitos, ADRs, contratos, arquivos, branch/worktree, PR e resultado de gate.
- `CardEventService` publica eventos; automação de colunas consome esses eventos.
