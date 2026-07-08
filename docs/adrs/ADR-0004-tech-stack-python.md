# ADR-0004 — Stack de implementação: Python

- **Status:** ACCEPTED
- **Fase:** F2
- **Criado por:** technology-stack-selector / ArchitectureDesignAgent
- **Revisado por:** ReviewAgent
- **Data:** 2026-07-02
- **Supersedes:** sugestão do §37 do `requerimentos.md` (monorepo TypeScript)

## Contexto

O §37 do requisito sugeria um monorepo TypeScript (`apps/api|web|cli`, `packages/*`). O responsável pelo projeto **decidiu explicitamente por Python** como stack de implementação do ASO Runtime. Como a decisão diverge de uma recomendação registrada no requisito, ela é formalizada aqui (regra: nenhuma decisão contraditória sem ADR).

## Opções consideradas

### 1. TypeScript monorepo (sugestão §37)
- **Prós:** alinhado às referências (AgentWrapper, OpenAI Agents SDK); UI e backend na mesma linguagem.
- **Contras:** não foi a escolha do responsável.

### 2. Python (escolhido)
- **Prós:** ecossistema forte para orquestração de agentes e SDKs de LLM; Pydantic v2 ideal para contexto/patches/contratos fortemente tipados; FastAPI para API contrato-first; produtividade em domínio data/agent.
- **Contras:** UI web fica como projeto separado (não same-language); alguns CLI agents são JS-cêntricos (mitigado pela abstração `AgentAdapter`).

### 3. .NET
- **Prós:** robustez e tipagem forte.
- **Contras:** referências e tooling de CLI agents são JS/Python-cêntricos; menor aderência ao ecossistema agentic.

## Decisão

Adotar **Python 3.12+** com: FastAPI + Uvicorn (API), Pydantic v2 (modelos/validação), SQLAlchemy 2.x + Alembic + PostgreSQL 16 com JSONB (persistência), Typer (CLI), httpx e SDK Anthropic (LLM providers), subprocess/PTY (CLI agents), pytest (testes), ruff + mypy (qualidade). UI web **diferida** para MVP posterior, consumindo a API.

## Trade-offs

- Ganha-se aderência ao ecossistema agentic/LLM e validação tipada (Pydantic) ao custo de a UI não compartilhar linguagem com o backend.

## Consequências

- A estrutura de repositório do §37 é substituída pela estrutura Python de [ADR-0001](ADR-0001-runtime-architecture.md) / F2 §4.
- Contratos de API e schemas (F3) serão gerados a partir de Pydantic/OpenAPI (contrato-first).
- Qualquer contribuinte deve tratar o §37 como histórico; esta ADR é a referência de stack.
