# MEL-19 — ContextBuilder e injeção de contexto nos providers

| Campo | Valor |
|---|---|
| Fase do roadmap | 2 — Correção |
| Prioridade | P1 |
| Esforço | médio |
| Status | Backlog |
| Depende de | MEL-14 |
| Origem | [feedback.md](../feedback.md) §1 (contexto), §4 (contexto insuficiente) |
| Requer ADR | **Sim**: papel do `OrchestratorContext` e contexto por tipo de tarefa (referencia ADR-0003, ADR-0007) |

## Problema

- `LlmExecutionProvider` aceita `context_provider`, mas nenhuma construção o passa
  ([bootstrap.py:46](../src/aso/bootstrap.py#L46), [catalog.py:188](../src/aso/execution/catalog.py#L188)).
  Nenhum agente lê o `OrchestratorContext`.
- `PromptBuilder.build_messages` ([prompt_builder.py:38](../src/aso/agents/prompt_builder.py#L38))
  usa só `request` (demanda global) e a fase; ignora título, descrição, critérios de
  aceite, correções e contexto adicional do card.
- Quando há contexto, ele é cortado em 6.000 caracteres do JSON serializado, podendo
  quebrar no meio.
- `_build_task` grava `target_path = f"{section}.mock_{agent.role}"` ([:5564](../src/aso/control/orchestration_service.py#L5564)),
  sobrescrevendo a mesma chave a cada execução do mesmo papel.
- Saídas das fases F1–F4 via LLM não chegam às fases seguintes.

## Mudança proposta

1. `src/aso/agents/context_builder.py`: função pura
   `construir_contexto(bundle, card, task_type) -> ContextoDaTarefa`, com orçamento de
   caracteres e ordem de prioridade:
   1. card: título, descrição, critérios, correções, contexto adicional;
   2. item de especificação de origem (quando o card nasceu da spec);
   3. resumo do discovery aprovado e da ficha da demanda;
   4. ADRs aceitas relacionadas (por fase ou referência no card);
   5. saídas anteriores relevantes do ledger (`engineering`, `architecture`, `contracts`), resumidas por seção.
   Itens que não cabem são omitidos inteiros (nunca cortados no meio) e listados em `omitidos`.
2. `_build_task` inclui o contexto no `TaskEnvelope` (MEL-14); o wrapper e o
   `PromptBuilder` renderizam a partir dele.
3. `target_path` passa a ser `f"{section}.{card.id}"`, sem o prefixo `mock_`.
4. Registrar no evento `AgentExecuted` o tamanho do contexto e os itens omitidos.

## Fora de escopo

- Leitura do repositório pelo agente (MEL-40) e índice de código (MEL-44).
- Compressão por LLM.

## Critérios de aceite

- [ ] Prompt LLM de um card contém título, critérios e correções do card.
- [ ] Card nascido da spec recebe o resumo do discovery e o item de origem.
- [ ] Contexto acima do orçamento omite itens inteiros de menor prioridade e registra a omissão.
- [ ] Dois cards do mesmo papel não sobrescrevem a mesma chave do ledger.
- [ ] A ADR define o `OrchestratorContext` como memória de trabalho consumida via ContextBuilder.

## Testes obrigatórios

- Unit do `context_builder`: prioridade, orçamento, omissão inteira.
- Unit do `PromptBuilder` com `FakeLlmClient` inspecionando o prompt recebido.
- Integração: card F5 recebe saída de card F2 aplicada ao ledger.

## Arquivos prováveis

- `src/aso/agents/context_builder.py` (novo), `src/aso/agents/prompt_builder.py`
- `src/aso/execution/llm_provider.py`, `src/aso/execution/catalog.py`, `src/aso/bootstrap.py`
- `src/aso/control/orchestration_service.py` (`_build_task`)
- `docs/context.md`

## Riscos

- Mais tokens por chamada: acompanhar custo com MEL-41; orçamento configurável por tipo de tarefa.
