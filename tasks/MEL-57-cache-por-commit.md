# MEL-57 — Cache de discovery e índice por commit

| Campo | Valor |
|---|---|
| Fase do roadmap | 5 — Escala |
| Prioridade | P3 |
| Esforço | médio |
| Status | Backlog |
| Depende de | MEL-44 (e MEL-40) |
| Origem | [feedback.md](../feedback.md) §12 Fase 5 |
| Requer ADR | Não (complementa a ADR de MEL-44) |

## Problema

Discovery com leitura do repositório (MEL-40) e o índice estrutural (MEL-44) custam tempo e
tokens. Demandas diferentes sobre o mesmo repositório, no mesmo commit, repetem a mesma
investigação estrutural.

## Mudança proposta

1. Chave de cache: `(repositório, commit da base, versão do prompt/schema)`.
2. Reaproveitar o índice estrutural sempre que a chave coincidir.
3. Para o discovery, reaproveitar só a parte estrutural (mapa de componentes, dependências
   externas, testes existentes); a análise específica da demanda continua sendo gerada.
4. Invalidação automática quando o commit da base muda; limite de tamanho e idade configuráveis.
5. Registrar no `agent_runs` quando um resultado veio do cache.

## Critérios de aceite

- [ ] Segunda demanda no mesmo commit não recalcula o índice e reduz o tempo do discovery (medição registrada).
- [ ] Mudança de commit invalida o cache.
- [ ] O relatório indica quais partes vieram do cache.
