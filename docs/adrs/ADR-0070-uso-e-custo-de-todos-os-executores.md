# ADR-0070 — Uso e custo de todos os executores (fontes e tabela de preços)

- **Status:** ACCEPTED
- **Fase:** F5 (inteligência — MEL-41, origem `feedback.md` §2 item 25, §9)
- **Data:** 2026-09-15
- **Atualiza:** [ADR-0026](ADR-0026-custo-real-e-orcamento.md) (custo real e orçamento) — fontes
  de uso e cálculo de custo; o freio de orçamento e seus limiares continuam os mesmos
- **Relaciona-se com:** [ADR-0065](ADR-0065-registro-de-execucoes-agent-runs.md) (`agent_runs`),
  [ADR-0053](ADR-0053-catalogo-de-agentes.md) (limite por agente)

## Contexto

Uso e custo só vinham do envelope `result` do Claude Code. `OpenAICompatibleClient` e
`AnthropicClient` descartavam `usage`; Codex e as perguntas via `perguntar_ao_agente` não
registravam nada. Para essas fontes o custo ficava indisponível: o freio de orçamento e o limite
por agente nunca disparavam e o relatório de aprendizado subestimava o gasto.

## Decisão

1. **Origem do uso explícita** (`shared/agent_usage.py`): `agente` (o executor informou custo),
   `tabela` (custo calculado), `tokens` (tokens sem preço — custo indisponível) e `indisponivel`.
   Só `agente` e `tabela` contam como custo conhecido; as demais somam em
   `execucoes_sem_custo`.
2. **Clientes LLM:** novo `completar() -> RespostaLlm(texto, uso)` nos adapters (OpenAI:
   `prompt_tokens` menos `cached_tokens`, `completion_tokens`; Anthropic: `input_tokens`,
   `output_tokens`, cache de leitura e escrita). `complete()` continua devolvendo só o texto —
   planejamento e demais chamadores não mudam. A função `completar(client, ...)` aceita clientes
   antigos (uso indisponível).
3. **Tabela de preços** `ASO_PRECOS_MODELOS` (`execution/precos.py`): USD por milhão de tokens de
   entrada/saída/cache por modelo. `precificar` é idempotente e só age sobre origem `tokens`.
   Sem preço: tokens registrados, custo indisponível — nunca zero inventado.
4. **Codex:** `turn.completed.usage.{input_tokens, cached_input_tokens, output_tokens}` vira
   tokens (o modelo vem do perfil do executor). Os nomes foram confirmados nas strings do binário
   `codex-cli 0.144.6` instalado; não houve execução real (custaria uma chamada à conta do
   operador) — confirmar numa execução real antes de confiar em números.
5. **Perguntas:** `perguntar_ao_agente` grava tokens, custo, modelo e origem no `AgentRun`.
   O **gasto da orquestração** soma execuções de card (`card.uso`) e o custo das perguntas lido de
   `agent_runs` (`custo_de_perguntas`). *Por que não também no agregado:* o registro de execuções
   já é a fonte append-only das perguntas; duplicar em `orchestrations` criaria dois números para o
   mesmo gasto (a task sugeria os dois).
6. **Relatório:** `proporcao_sem_custo` por executor, exibida no console ao lado de
   `execucoes_sem_custo`.

## Consequências

- Com preço configurado, LLM via API e Codex passam a frear orçamento e limite por agente.
- O limite de custo **por agente** (ADR-0053) continua olhando só os cards do papel; perguntas não
  têm papel e ficam só no orçamento da orquestração.
- Preços mudam: a tabela é configuração do operador, não constante do código.
