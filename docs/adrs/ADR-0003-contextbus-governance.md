# ADR-0003 — ContextBus como governança soberana do contexto

- **Status:** ACCEPTED
- **Fase:** F2
- **Criado por:** ArchitectureDesignAgent
- **Revisado por:** ReviewAgent · SecurityAgent
- **Data:** 2026-07-02

## Contexto

O princípio §8.3 estabelece que nenhum agente altera a verdade central diretamente: agentes produzem propostas/patches/evidências e o `ContextBus` valida e aplica. É a garantia central de consistência com múltiplos agentes concorrentes.

## Opções consideradas

### 1. Agentes escrevem direto no contexto
- **Prós:** simples.
- **Contras:** viola §8.3; conflitos e corrupção com concorrência; sem auditoria.

### 2. Event sourcing puro do contexto
- **Prós:** histórico completo; reconstrução por replay.
- **Contras:** complexidade alta para o MVP; consultas do estado atual exigem projeções.

### 3. Single-writer ContextBus com ContextPatch validado + histórico append-only
- **Prós:** um único ponto de escrita; pipeline de validação (§19: schema, permissão, conflito, snapshot lock, ADR, contrato, impacto em gate); histórico auditável; recuperável por snapshot.
- **Contras:** o ContextBus é caminho crítico — precisa ser confiável e performático.

## Decisão

Adotar o **ContextBus como único escritor** do `OrchestratorContext`. Agentes/skills retornam `ContextPatch`; o ContextBus executa o pipeline de validação de 7 etapas (§19). Aprovado → aplica, incrementa versão, registra evento, persiste histórico, atualiza cards. Reprovado → registra conflito, move card para Blocked/Waiting Human, aciona `ConflictResolutionAgent` quando necessário.

## Trade-offs

- Serializa escritas no contexto (contenção possível) em troca de consistência forte e auditabilidade. Mitigação: locks por `target_keys` e fila de conflitos.

## Consequências

- `governance` é o núcleo soberano do monolito modular (ADR-0001).
- Snapshots (O1–O7) congelam seções; escrita em seção congelada exige ADR de override (imutabilidade — protocolo de contexto).
- Toda mutação do contexto é rastreável (ator, agente, requisito, ADR, card, evidência).
