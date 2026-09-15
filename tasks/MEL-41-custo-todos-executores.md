# MEL-41 — Uso e custo para todos os executores

| Campo | Valor |
|---|---|
| Fase do roadmap | 4 — Inteligência |
| Prioridade | P1 |
| Esforço | médio |
| Status | Backlog |
| Depende de | MEL-30 |
| Origem | [feedback.md](../feedback.md) §2 item 25, §9 (tokens/custo) |
| Requer ADR | Sim, curta: atualiza ADR-0026 (fontes de uso e tabela de preços) |

## Problema

- Uso e custo só são extraídos do envelope `result` do `claude --output-format stream-json`
  (`extrair_uso` em [agent_stream.py](../src/aso/execution/agent_stream.py)).
- `OpenAICompatibleClient` e `AnthropicClient` ([llm_client.py](../src/aso/execution/llm_client.py))
  descartam o campo `usage` da resposta.
- Codex e perguntas via `perguntar_ao_agente` não registram uso.
- Consequência: para essas fontes, `custo_usd` fica "indisponível", o freio de orçamento
  (`_recusar_se_orcamento_estourado`) e o limite por agente nunca disparam, e o relatório
  de aprendizado subestima custo.

## Mudança proposta

1. `LlmClient.complete` passa a retornar `RespostaLlm(texto, uso)`; os adapters leem
   `usage` (OpenAI: `prompt_tokens`/`completion_tokens`; Anthropic: `input_tokens`/`output_tokens`).
2. Tabela de preços configurável (`ASO_PRECOS_MODELOS`, JSON por modelo: USD por milhão
   de tokens de entrada/saída/cache) para calcular custo quando o provider só informa tokens.
   Sem preço configurado: tokens registrados, custo "indisponível" (nunca zero inventado).
3. Parser de uso para Codex `exec --json` quando o envelope trouxer tokens (confirmar contra saída real).
4. `perguntar_ao_agente` devolve o uso e o grava em `agent_runs` e no agregado da orquestração.
5. Orçamento soma custo de execuções de card **e** perguntas.
6. Painel de métricas mostra a proporção de execuções sem custo conhecido por executor.

## Critérios de aceite

- [ ] Execução via LLM (fake com `usage`) acumula tokens e custo no card.
- [ ] Perguntas (triagem, revisão…) contam para o orçamento da orquestração.
- [ ] Com orçamento pequeno e LLM com preço configurado, o freio recusa nova execução.
- [ ] Sem preço configurado, tokens aparecem e custo fica "indisponível".

## Arquivos prováveis

- `src/aso/execution/llm_client.py`, `llm_provider.py`, `agent_stream.py`
- `src/aso/control/agent_ask.py`, `src/aso/control/orcamento.py`
- `src/aso/shared/agent_usage.py`, `src/aso/observability/aprendizado.py`
