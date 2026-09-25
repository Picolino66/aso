# ADR-0063 — OrchestratorContext como memória de trabalho via ContextBuilder

- **Status:** ACCEPTED
- **Fase:** F5 (correção — MEL-19, origem `feedback.md` §1 e §4)
- **Data:** 2026-09-15
- **Relaciona-se com:** [ADR-0003](ADR-0003-contextbus-governance.md) (ContextBus como único
  escritor — continua valendo para a escrita), [ADR-0007](ADR-0007-llm-provider-and-autopilot.md)
  (provider LLM e autopilot), [ADR-0059](ADR-0059-contrato-task-envelope.md) (TaskEnvelope),
  [ADR-0061](ADR-0061-congelamento-de-snapshot.md) (seções congeladas que o contexto expõe)

## Contexto

A documentação diz que "todo agente recebe o contexto atualizado", mas:

- `LlmExecutionProvider` aceitava `context_provider` e nenhuma construção o passava;
- `PromptBuilder` usava só a demanda global e a fase, ignorando título, descrição,
  critérios, correções e contexto adicional do card; quando havia contexto, cortava o JSON
  em 6.000 caracteres (podendo quebrar no meio);
- o wrapper CLI não recebia contexto nenhum;
- `_build_task` gravava `target_path = "<seção>.mock_<papel>"`: dois cards do mesmo papel
  sobrescreviam a mesma chave do ledger;
- saídas de F1–F4 nunca chegavam a F5.

## Opções consideradas

1. **Passar o payload inteiro do contexto.** Explode tokens e mistura o irrelevante.
2. **Ligar o `context_provider` existente.** Só dá o JSON cru por seção, sem card, spec ou
   discovery, e não chega ao wrapper CLI.
3. **ContextBuilder puro + contexto no `TaskEnvelope`.** Adotada.

## Decisão

- O `OrchestratorContext` é a **memória de trabalho** da orquestração: escrito só pelo
  ContextBus (ADR-0003) e **lido pelos agentes via ContextBuilder**.
- `agents/context_builder.py` (puro; recebe `FontesDoContexto` extraídas pelo serviço) monta
  `ContextoDaTarefa` em **prioridade estrita**: card (sempre) → item de especificação de
  origem (casado por título na versão atual da spec) → resumo do discovery aprovado → ficha
  da demanda → ADRs aceitas da fase do card ou referenciadas por ele → vizinhança no código
  dos arquivos citados (índice estrutural, [ADR-0077](ADR-0077-indice-estrutural-por-commit.md))
  → saídas anteriores do ledger (`architecture`, `contracts`, `engineering`), por seção.
- **Orçamento** em caracteres (`ASO_CONTEXTO_MAX_CHARS`, padrão 12.000): o primeiro item que
  não cabe é omitido **inteiro**, junto com todos os de menor prioridade; as chaves omitidas
  ficam em `omitidos`. Nada é cortado no meio.
- `_build_task` coloca o contexto em `TaskEnvelope.contexto` (campo aditivo; `schema_version`
  segue `"1"`). `PromptBuilder` (LLM) e `render_prompt.py` (wrapper CLI) renderizam o mesmo
  bloco — um teste garante que os dois textos são idênticos. O `context_provider` antigo fica
  como fallback sem envelope.
- `target_path` da execução passa a ser `"<seção>.<card.id>"`.
- `AgentExecuted` registra `contexto_chars` e `contexto_omitidos`.

## Consequências

- Agentes de F5 recebem o que F2/F3 produziram, a spec de origem e o discovery aprovado.
- Mais tokens por chamada; o orçamento é configurável e a omissão é auditável no evento
  (custo acompanhado na MEL-41).
- O congelamento de seções (ADR-0061) passa a proteger informação que de fato é consumida.
- Leitura do repositório pelo agente (MEL-40) e índice de código (MEL-44) ficam fora.

## Adendo (ADR-0077, MEL-44)

Entrou o item `codigo`: uma linha por arquivo citado pelo trabalho (símbolos com linha, pontos de
entrada, quem importa, testes que cobrem), tirada do índice estrutural por commit. "Arquivos
citados" = `linked_files` do card + `componentes_afetados` do discovery aprovado (já validados
contra o índice), no máximo 5. Sem arquivo citado o índice nem é construído, e o item respeita o
orçamento como qualquer outro.
