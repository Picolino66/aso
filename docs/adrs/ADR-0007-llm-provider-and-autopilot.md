# ADR-0007 — Provedor LLM injetável e planejamento por LLM (autopilot)

- **Status:** ACCEPTED
- **Fase:** F5 (evolução pós-O5)
- **Data:** 2026-07-09
- **Relaciona-se com:** [ADR-0001](ADR-0001-runtime-architecture.md) (Hexagonal),
  [ADR-0003](ADR-0003-contextbus-governance.md) (ContextBus soberano),
  [ADR-0004](ADR-0004-tech-stack-python.md) (stack)

## Contexto

O runtime já governa a esteira (ContextBus, gates, snapshots, worktrees, PR/merge),
mas não tinha o "cérebro": não havia como um LLM ler uma ideia e produzir plano,
arquitetura e código. O objetivo do **autopilot** é: dada uma ideia, rodar F1→F7
com o mínimo de intervenção humana (aprovação por fase). Este ADR cobre a primeira
fatia (M1 — cérebro; M2 — planejamento).

## Opções consideradas

1. **Depender de um SDK específico (anthropic/openai)** — acopla o núcleo a um
   fornecedor e a uma dependência pesada; dificulta testes offline.
2. **Porta `LlmClient` própria + adapters (stdlib urllib)** — sem dependência
   extra, com `FakeLlmClient` para testes determinísticos e adapters para
   OpenAI-compatible (DeepSeek/OpenAI) e Anthropic.
3. **Somente via CLI (wrapper de `claude`/`codex`)** — funciona para código, mas
   não cobre planejamento por API (DeepSeek) nem prompt estruturado.

## Decisão

Adotar a **opção 2** como base e **rotear por fase** (decisão do usuário):
DeepSeek/OpenAI-compatible para planejar (F1–F4) e agentes CLI para codar (F5),
convivendo com a opção 3. O `LlmClient` é injetável (Ports & Adapters, ADR-0001);
as chaves vêm **apenas de variáveis de ambiente** (`ASO_LLM_*`). Toda saída do LLM
vira **`ContextPatch`** submetido ao ContextBus (ADR-0003) — o LLM nunca escreve o
contexto diretamente. O planejamento (`PlanningService`) produz um `ProjectPlan`
**validado por Pydantic** e o `OrchestrationService.populate_from_plan` materializa
cards+ADRs governados.

## Trade-offs

- **+** Sem dependência nova; testável offline; independente de fornecedor.
- **+** Governança preservada: patches validados, ADRs de rastreabilidade.
- **−** `urllib` é mais verboso que um SDK; streaming não suportado (não é preciso
  para planejamento). Se necessário, um adapter httpx pode ser somado depois.

## Consequências

- Destrava usar a **API do DeepSeek** diretamente e planejar o produto de verdade.
- Prepara M3/M4 (PhaseRunner + loop de autopilot com aprovação por fase) e M5
  (execução de código real em F5/F6 com gate rodando testes).
- Aprovação humana continua obrigatória nos portões de fase (§8.6/§24).
