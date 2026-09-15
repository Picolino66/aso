# MEL-55 — Consolidar a UI legada e as páginas novas

| Campo | Valor |
|---|---|
| Fase do roadmap | 5 — Limpeza |
| Prioridade | P2 |
| Esforço | médio |
| Status | Backlog |
| Depende de | — (fica mais simples após MEL-31) |
| Origem | [feedback.md](../feedback.md) §3 (duplicação), §7 |
| Requer ADR | Sim, curta: supersede a decisão de manter páginas legadas intocadas (ADR-0036) |

## Problema

O console tem 29 páginas em duas gerações que se sobrepõem ([mapa-paginas.md](../docs/mapa-paginas.md)):

- legadas: `macro.html` (`/ui/`), `nova.html`, `detalhe.html` (1.481 linhas), `index.html` (console técnico, 999 linhas);
- novas com sidebar: `demandas`, `demanda-nova`, `demanda-detalhe`, `kanban`, `card-detalhe` etc.;
- 4 seções da sidebar são placeholders: `esteira`, `modelos`, `incidentes`, `configuracoes`.

Pares redundantes: `nova` × `demanda-nova`, `detalhe` × `demanda-detalhe`, `macro` × `demandas`/`kanban`.
Os testes de HTML verificam textos no arquivo, então duplicar lógica JS custa manutenção dobrada.

## Mudança proposta

1. Inventário por funcionalidade: onde cada ação existe hoje (legada, nova ou ambas).
2. Migrar para as páginas novas o que só existe na legada (ex.: painel ao vivo do agente,
   corrida de candidatos, snapshots/diff, patches).
3. Rotas legadas passam a redirecionar para a página nova equivalente por uma versão; depois, remover os arquivos.
4. Placeholders: implementar com conteúdo mínimo real (`modelos` = catálogo de executores,
   `configuracoes` = links já existentes, `incidentes` = lista cross-demanda, `esteira` =
   visão de fases) ou remover da sidebar.
5. Extrair JS repetido (chamadas de API, tratamento de erro 403/409, polling de runs) para um módulo compartilhado.

## Critérios de aceite

- [ ] Nenhuma funcionalidade exclusiva de página legada (inventário marcado como migrado).
- [ ] Rotas legadas redirecionam; a sidebar não tem placeholders.
- [ ] Testes de HTML atualizados para as páginas finais.
- [ ] Smoke do Docker adaptado.
