# MEL-45 — Recomendações por similaridade de demandas

| Campo | Valor |
|---|---|
| Fase do roadmap | 4 — Inteligência |
| Prioridade | P3 |
| Esforço | médio |
| Status | Backlog |
| Depende de | MEL-30 |
| Origem | [feedback.md](../feedback.md) §4 (RAG, BM25, busca híbrida) |
| Requer ADR | Não (a menos que se adote embeddings — então sim) |

## Problema

O relatório de aprendizado (`observability/aprendizado.py`, ADR-0052) e o painel de
recomendação (ADR-0044) agregam por faixas de complexidade e risco, mas não conseguem
responder "demandas parecidas com esta falharam onde, com qual executor e a que custo?".

## Mudança proposta

1. Busca textual primeiro: índice full-text (Postgres `tsvector`; SQLite FTS5 nos testes)
   sobre demanda, ficha, títulos de cards e motivos de falha.
2. `recomendar_por_similares(demanda)`: top N demandas parecidas com executor usado,
   tentativas, custo, desfecho da revisão e diagnósticos de falha mais frequentes.
3. Exibir no painel de recomendação da criação da demanda, marcado como "baseado em N demandas".
4. Embeddings só se a busca textual se mostrar insuficiente numa avaliação com exemplos reais (registrar a medição).

## Critérios de aceite

- [ ] Demanda nova com texto parecido a demandas anteriores recebe as recomendações com a fonte citada.
- [ ] Sem histórico suficiente, o painel diz isso em vez de inventar recomendação.
- [ ] Funciona em SQLite (testes) e Postgres (validação no Docker).
