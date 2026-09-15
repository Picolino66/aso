# ADR-0072 — Respostas das funções de agente com JSON Schema gerado dos modelos

- **Status:** ACCEPTED
- **Fase:** F5 (inteligência — MEL-42, origem `feedback.md` §4)
- **Data:** 2026-09-15
- **Relaciona-se com:** [ADR-0059](ADR-0059-contrato-task-envelope.md) (`output_schema` no
  TaskEnvelope), [ADR-0016](ADR-0016-ficha-da-demanda.md) (ficha da demanda),
  [ADR-0017](ADR-0017-revisao-independente-de-codigo.md) (revisão),
  [ADR-0070](ADR-0070-uso-e-custo-de-todos-os-executores.md) (clientes LLM com `completar`)

## Contexto

O formato de resposta de cada função de agente (nomeação, triagem, discovery, especificação,
revisão de código, revisão documental, planejamento) estava escrito à mão no prompt de sistema,
com as listas de valores aceitos em texto — e podia divergir do modelo que lia a resposta. O
parsing era frouxo (`parse_llm_json` cata o trecho entre `{` e `}`) e cada serviço compensava
com um `_sanear` extenso.

## Decisão

1. **Um modelo Pydantic de resposta por função** (`RespostaNomeacao`, `RespostaTriagem`,
   `RespostaDiscovery`, `RespostaEspecificacao`, `RespostaRevisao`, `RespostaRevisaoDocumental`;
   o planejamento usa `ProjectPlan`), ao lado do prompt. Vocabulários fechados entram no schema
   como `enum` (`respostas_estruturadas.vocabulario`), mas o campo é texto: **o que fazer com um
   valor fora do vocabulário continua regra de negócio do `_sanear`** — os fallbacks não mudam.
2. **Formato gerado do schema:** `instrucao_de_formato(modelo)` monta o trecho do prompt a partir
   de `model_json_schema()`; os prompts de sistema não trazem mais JSON nem listas de valores.
   O `TaskEnvelope` leva o schema em `output_schema` (o renderizador do wrapper acrescenta ao
   prompt); a tarefa no formato antigo leva o formato no `system`.
3. **Saída estruturada nativa:** OpenAI com `response_format: json_schema` (não estrito),
   DeepSeek com `json_object`, Anthropic com ferramenta forçada (`tool_choice`) cujo
   `input_schema` é o schema. `ASO_LLM_SAIDA_ESTRUTURADA=0` desliga para servidores compatíveis
   que recusem o parâmetro.
4. **Validação com uma correção:** `perguntar_ao_agente(modelo_resposta=...)` valida a resposta;
   fora do schema, o agente recebe **uma** nova tentativa com os campos exatos que falharam
   (`campo: motivo`). Falhou de novo → `RespostaInvalida` (um `ValueError`), que cai no fallback do
   serviço como qualquer erro de agente. Campos obrigatórios: `branch`/`commit` na nomeação e
   `veredito` nas revisões; o resto é opcional para não trocar fallback por correção.
5. **Snapshots** dos schemas em `tests/snapshots/schemas/`: mudar um modelo de resposta muda o
   contrato com os agentes e só passa regerando o snapshot de propósito.

## Consequências

- Resposta fora do formato custa no máximo uma pergunta extra, e o motivo registrado aponta o campo.
- O prompt fica maior (o schema completo vai junto); o ganho é não haver duas fontes do formato.
- Os parâmetros nativos de saída estruturada não foram exercitados contra as APIs reais (testes com
  HTTP simulado); a flag de desligamento existe para o caso de recusa.
