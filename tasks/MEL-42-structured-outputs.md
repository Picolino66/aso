# MEL-42 — Structured outputs com JSON Schema

| Campo | Valor |
|---|---|
| Fase do roadmap | 4 — Inteligência |
| Prioridade | P2 |
| Esforço | médio |
| Status | Backlog |
| Depende de | MEL-14 |
| Origem | [feedback.md](../feedback.md) §4 (structured output / JSON Schema) |
| Requer ADR | Sim, curta: schemas gerados dos modelos Pydantic como contrato das funções de agente |

## Problema

- Os formatos de resposta estão escritos à mão dentro dos prompts de sistema (triagem,
  discovery, spec, revisão, revisão documental, planejamento, nomeação) e podem divergir
  dos modelos Pydantic que os leem.
- `parse_llm_json` remove cercas de código e, em último caso, pega o trecho entre o
  primeiro `{` e o último `}` — frágil.
- Cada serviço tem um `_sanear` manual extenso para compensar respostas fora do formato.

## Mudança proposta

1. Um modelo Pydantic de resposta por função de agente (alguns já existem:
   `DemandBrief`, `DiscoveryReport`, `SpecDocument`, `ReviewVerdict`, `ProjectPlan`).
2. `output_schema = Modelo.model_json_schema()` enviado no `TaskEnvelope` (MEL-14) e usado
   para gerar o trecho de formato do prompt (fim do texto duplicado).
3. Adapters de API usam o recurso nativo do provider quando disponível (modo de saída
   estruturada / tool use com schema); caso contrário, prompt + validação.
4. Validação por `Modelo.model_validate`; erro de validação registrado com o campo exato
   e uma única tentativa de correção com o erro no prompt.
5. `_sanear` reduzido a regras de negócio (vocabulário fechado), não a parsing.

## Critérios de aceite

- [ ] Nenhum prompt de sistema contém o formato JSON escrito à mão.
- [ ] Resposta inválida gera erro com o campo faltante e no máximo uma tentativa de correção.
- [ ] Fallbacks determinísticos continuam funcionando quando o agente falha.
- [ ] Testes de snapshot garantem que o schema enviado corresponde ao modelo.
