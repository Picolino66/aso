# ADR-0001 — Arquitetura do runtime: Modular Monolith + Hexagonal

- **Status:** ACCEPTED
- **Fase:** F2
- **Criado por:** ArchitectureDesignAgent
- **Revisado por:** ReviewAgent
- **Data:** 2026-07-02

## Contexto

O ASO Runtime precisa coordenar 6 planes (Control, Kanban, Agent, Execution, Governance, Observability) com forte necessidade de consistência do contexto canônico e rastreabilidade. É um produto local-first, para uso individual/equipe pequena no MVP, com escopo amplo mas roadmap incremental.

## Opções consideradas

### 1. Microsserviços (um serviço por plane)
- **Prós:** escala independente; isolamento forte.
- **Contras:** complexidade distribuída prematura; consistência do contexto vira problema distribuído; overhead operacional incompatível com MVP local-first.

### 2. Modular Monolith + Hexagonal (Ports & Adapters) + DDD
- **Prós:** consistência forte simples (um DB); planes como bounded contexts com fronteiras explícitas; extração futura para serviços possível; baixo custo operacional.
- **Contras:** disciplina de fronteiras precisa ser imposta (risco de acoplamento).

### 3. Serverless / funções
- **Prós:** custo sob demanda.
- **Contras:** execução de agentes de longa duração e worktrees locais não combinam com FaaS; estado do contexto difícil.

## Decisão

Adotar **Modular Monolith com Clean/Hexagonal Architecture e DDD**, mapeando cada plane como um módulo de domínio (bounded context). `governance` é o núcleo soberano; api/cli/db/providers são adapters.

## Trade-offs

- Ganha-se simplicidade e consistência ao custo de exigir disciplina de fronteiras entre módulos.
- Escala horizontal por serviço fica adiada — aceitável (validação de gargalos em F7 via `performance-and-scale-engine`).

## Consequências

- Estrutura `src/aso/{control,kanban,agents,execution,governance,observability,shared,api,cli,db}`.
- Comunicação entre módulos por interfaces/eventos, nunca por escrita direta no contexto.
- Fronteiras verificáveis por lint de imports (regra de dependência apontando para dentro).
