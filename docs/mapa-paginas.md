# Mapa de páginas — rotas `/ui/*` (wf §2.4, §40.1/§40.3)

Entregável exigido pelo `wiframe-fluxo.md` §40 ("1. Mapa das páginas", "3.
Estrutura de rotas"). Ver [ADR-0036](adrs/ADR-0036-sidebar-e-mapa-de-paginas.md)
para o raciocínio arquitetural (por que 16 arquivos/rotas explícitas) e
[ADR-0078](adrs/ADR-0078-consolidacao-do-console.md) para a consolidação das
páginas legadas (MEL-55).

## Rotas legadas (redirecionam — ADR-0078)

As quatro páginas da primeira geração foram **removidas**: todo o conteúdo delas
vive hoje numa seção da sidebar, e as rotas antigas respondem `307` preservando a
query string (link salvo e marcador continuam funcionando).

| Rota legada | Redireciona para | Onde o conteúdo foi |
|---|---|---|
| `GET /ui/` | `/ui/dashboard` | kanban macro → Dashboard; projetos (criar/arquivar/restaurar, histórico, navegador de pastas) → `/ui/configuracoes` |
| `GET /ui/nova` | `/ui/demanda-nova` | cadastro completo; a pré-análise da pasta (`fs/analyze/stream`) virou um passo do formulário |
| `GET /ui/detalhe` | `/ui/esteira` | a sala de controle inteira (esteira F1→F7, próximo passo, pendências, painel ao vivo, autopilot, spec, gate, implantação) é a seção Esteira |
| `GET /ui/console` | `/ui/demanda-detalhe` | auditoria técnica nas abas da demanda (aba **Governança**: patches, conflitos, snapshots/diff/restauração, SLO, worktrees; aba Execuções: tempo e custo por card); catálogo de executores → `/ui/modelos` |

## Páginas satélite (novas, com sidebar, fora da lista de 16 seções)

| Rota | Arquivo | Conteúdo |
|---|---|---|
| `GET /ui/demanda-nova` | `demanda-nova.html` | Tela 03 — cadastro completo de demanda (wf §5.2, [ADR-0039](adrs/ADR-0039-cadastro-de-demanda-completo.md)); acessada pelo botão "+ Nova demanda" em `/ui/demandas` |
| `GET /ui/demanda-estrutura?id=` | `demanda-estrutura.html` | Tela 10 — estrutura da demanda em árvore (wf §12, [ADR-0040](adrs/ADR-0040-estrutura-da-demanda-em-arvore.md)); acessada pela ação "Visualizar cards" em `/ui/demandas` |
| `GET /ui/card-detalhe?id=&card=` | `card-detalhe.html` | Tela 12 — detalhes do card em 11 abas (10 do wf §14 + Falhas do wf §17/§19, [ADR-0048](adrs/ADR-0048-execucao-quality-gates-e-falhas.md)); aba Review expandida com resumo/checklist de 12 eixos/comentários completos (wf §20) e aba Testes expandida com plano de teste manual e registro de bug (wf §22/§23, [ADR-0049](adrs/ADR-0049-code-review-testes-manuais-e-bugs.md)); acessada pelo clique num nó de `/ui/demanda-estrutura` |
| `GET /ui/regras-roteamento` | `regras-roteamento.html` | Tela 31 — editor visual de regras de roteamento (wf §33, [ADR-0042](adrs/ADR-0042-editor-visual-de-regras-de-roteamento.md)); sem `?id=` (regras são globais, não de uma demanda); acessada a partir de `/ui/console` |
| `GET /ui/demanda-detalhe?id=&aba=` | `demanda-detalhe.html` | Tela 04 — detalhes da demanda em 14 abas (11 do wf §6 + Classificação/Recomendação do wf §7/§15, [ADR-0044](adrs/ADR-0044-classificacao-editavel-e-recomendacao.md), + Encerramento do wf §29, [ADR-0050](adrs/ADR-0050-implantacao-validacao-rollback-aceite-encerramento.md)), progresso e responsáveis (wf §6, [ADR-0043](adrs/ADR-0043-detalhes-da-demanda-em-onze-abas.md)); aba Discovery expandida com painel de execução, log e aprovação (wf §8/§9, [ADR-0045](adrs/ADR-0045-discovery-tecnico-e-aprovacao.md)); aba Deploys expandida com pipeline visual, checklist de aprovação, saúde pós-implantação e rollback (wf §24-§27, [ADR-0050](adrs/ADR-0050-implantacao-validacao-rollback-aceite-encerramento.md)); aba Incidentes com timeline e investigar/resolver; `detalhe.html` (sala de controle) permanece intocada; acessada por "Visualizar histórico"/"Visualizar documentos" em `/ui/demandas` |

## As 16 seções da sidebar (wf §2.4)

Todas as rotas abaixo existem, respondem `200` e têm **conteúdo real** — desde a
ADR-0078 não há mais placeholder na sidebar, e toda página do console monta a
mesma navegação. Um teste varre os arquivos e falha se alguma página voltar a
dizer "ainda não foi implementada", deixar de montar a sidebar ou linkar para uma
rota legada
([`test_consolidacao_ui.py`](../tests/integration/test_consolidacao_ui.py)).

| # | Rota | Seção | Card(s) FID | Status | Conteúdo parcial hoje |
|---|---|---|---|---|---|
| 1 | `/ui/dashboard` | Dashboard | FID-10 | **Done** | conteúdo real — ver [ADR-0037](adrs/ADR-0037-dashboard-operacional.md) |
| 2 | `/ui/demandas` | Demandas | FID-11 (**Done**), FID-12 (**Done**), FID-13 (**Done**), FID-14 (**Done**), FID-16 (**Done**), FID-17 (**Done**), FID-18 (**Done**), FID-21 (**Done**), FID-22 (**Done**), FID-23 (**Done**) | FID-11/12/13/14/16/17/18/21/22/23 done | lista com filtros/ações ([ADR-0038](adrs/ADR-0038-lista-de-demandas.md)) + cadastro completo em `/ui/demanda-nova` ([ADR-0039](adrs/ADR-0039-cadastro-de-demanda-completo.md)) + estrutura em árvore em `/ui/demanda-estrutura` ([ADR-0040](adrs/ADR-0040-estrutura-da-demanda-em-arvore.md)) + detalhes do card em 11 abas em `/ui/card-detalhe` ([ADR-0041](adrs/ADR-0041-detalhes-do-card-em-dez-abas.md)/[ADR-0048](adrs/ADR-0048-execucao-quality-gates-e-falhas.md)/[ADR-0049](adrs/ADR-0049-code-review-testes-manuais-e-bugs.md)) + detalhes da demanda em 14 abas em `/ui/demanda-detalhe` ([ADR-0043](adrs/ADR-0043-detalhes-da-demanda-em-onze-abas.md)/[ADR-0044](adrs/ADR-0044-classificacao-editavel-e-recomendacao.md)/[ADR-0045](adrs/ADR-0045-discovery-tecnico-e-aprovacao.md)/[ADR-0050](adrs/ADR-0050-implantacao-validacao-rollback-aceite-encerramento.md)) |
| 3 | `/ui/esteira?id=` | Esteira | MEL-55 | **Done** | sala de controle de UMA demanda (ADR-0078): esteira F1→F7 com o agente de cada etapa, próximo passo, pendências, painel "o que o agente está fazendo", discovery/spec/gate/implantação e autopilot; sem `id`, seletor de demanda |
| 4 | `/ui/kanban?id=` | Kanban | FID-20 | **Done** | conteúdo real — ver [ADR-0047](adrs/ADR-0047-kanban-operacional-completo.md); sem `id`, mostra seletor de demanda; `/ui/` (kanban macro, cross-demanda) continua existindo à parte |
| 5 | `/ui/agentes` | Agentes | FID-26 | **Done** | conteúdo real — ver [ADR-0053](adrs/ADR-0053-catalogo-de-agentes.md); catálogo persistente de 13 campos, fonte de verdade real das permissões do `ContextBus` (não espelho), 14 exemplos pré-provisionados (11 vinculados a papéis reais do `AgentRegistry`, 3 sem contraparte documentados honestamente) |
| 6 | `/ui/modelos` | Modelos | FID-25, MEL-55 | **Done** | catálogo único de executores (ADR-0076/ADR-0078): perfis CLI/LLM, streaming, permissão de escrita, candidatos da corrida e sincronização do Codex |
| 7 | `/ui/documentos?id=` | Documentos | FID-19 | **Done** | conteúdo real — ver [ADR-0046](adrs/ADR-0046-documentos-e-revisao-documental.md); sem `id`, mostra seletor de demanda |
| 8 | `/ui/aprovacoes` | Aprovações | FID-23 | **Done** | conteúdo real — ver [ADR-0050](adrs/ADR-0050-implantacao-validacao-rollback-aceite-encerramento.md); inbox cross-demanda real (`GET /v1/approvals`), sem picker (exceção deliberada ao padrão das outras páginas agregadas) |
| 9 | `/ui/execucoes?id=` | Execuções | FID-21 | **Done** | lista agregada por demanda com drill-down para `/ui/card-detalhe` ([ADR-0048](adrs/ADR-0048-execucao-quality-gates-e-falhas.md)) |
| 10 | `/ui/testes?id=` | Testes | FID-21 (**Done**), FID-22 (**Done**) | FID-21/22 done | quality gates + QA por card + plano de teste manual + bugs registrados ([ADR-0048](adrs/ADR-0048-execucao-quality-gates-e-falhas.md)/[ADR-0049](adrs/ADR-0049-code-review-testes-manuais-e-bugs.md)) |
| 11 | `/ui/code-reviews` | Code Reviews | FID-22 | **Done** | conteúdo real — ver [ADR-0049](adrs/ADR-0049-code-review-testes-manuais-e-bugs.md) |
| 12 | `/ui/implantacoes` | Implantações | FID-23 | **Done** | conteúdo real — ver [ADR-0050](adrs/ADR-0050-implantacao-validacao-rollback-aceite-encerramento.md); sem `id`, mostra seletor de demanda; pipeline/checklist/saúde/rollback completos ficam na aba Deploys de `/ui/demanda-detalhe` |
| 13 | `/ui/incidentes` | Incidentes | FID-05, MEL-55 | **Done** | lista cross-demanda por `GET /v1/incidents` (ADR-0078) com filtro de status/projeto; timeline completa + investigar/resolver continuam na aba Incidentes de `/ui/demanda-detalhe` (wf §27, [ADR-0050](adrs/ADR-0050-implantacao-validacao-rollback-aceite-encerramento.md)) |
| 14 | `/ui/auditoria` | Auditoria | FID-24 | **Done** | conteúdo real — ver [ADR-0051](adrs/ADR-0051-auditoria-com-filtros.md); página única cross-demanda (não picker+drilldown, a auditoria já é naturalmente global) com os 6 filtros do wf §30.3 e export CSV |
| 15 | `/ui/metricas` | Métricas | FID-25 | **Done** | conteúdo real — ver [ADR-0052](adrs/ADR-0052-metricas-e-aprendizado.md); página única cross-demanda (mesmo padrão de `/ui/auditoria`) com 15 indicadores, comparação de modelos e 8 recomendações estruturadas (6 reais, 2 desabilitadas) |
| 16 | `/ui/configuracoes` | Configurações | FID-15, FID-26, MEL-55 | **Done** | hub de ajustes (ADR-0078): atalhos para modelos/agentes/regras/contrato, **projetos** (criar, arquivar, restaurar, histórico e navegador de pastas) e estado do runtime (`/health`, `/v1/me`) |

Quatro seções (Esteira, Agentes, Modelos, Incidentes) não têm uma tela numerada
própria no `wiframe-fluxo.md`. Até a MEL-55 o conteúdo delas vivia espalhado nas
páginas legadas; com a ADR-0078 cada uma passou a ser a casa daquele assunto
(sala de controle, papéis de agente, catálogo de executores e incidentes
cross-demanda).

## Arquivos estáticos compartilhados usados por todas as 21 páginas

- [`tokens.css`](../src/aso/api/static/tokens.css) / [`components.css`](../src/aso/api/static/components.css) — [ADR-0034](adrs/ADR-0034-design-system-wireframe.md)
- [`header.js`](../src/aso/api/static/header.js) — [ADR-0035](adrs/ADR-0035-header-compartilhado.md)
- [`sidebar.js`](../src/aso/api/static/sidebar.js) — [ADR-0036](adrs/ADR-0036-sidebar-e-mapa-de-paginas.md) (todas as páginas, desde a ADR-0078)
- [`aso-api.js`](../src/aso/api/static/aso-api.js) — [ADR-0078](adrs/ADR-0078-consolidacao-do-console.md): `ASOApi.api/token/esc`, mensagens de 401/403/404/409 e o polling do 202 da fila (ADR-0067). `jobs.js` é um shim que delega para ele.

`/ui/dashboard` (FID-10) carrega, além dos três acima, `mermaid.js` via CDN
(`cdn.jsdelivr.net`) para renderizar o diagrama do fluxo geral da esteira —
**primeira dependência externa do frontend**, exceção deliberada ao
precedente "zero dependência externa" das ADR-0034/0035/0036, decidida em
[ADR-0037](adrs/ADR-0037-dashboard-operacional.md). Nenhuma outra página
carrega essa lib.

## Requisitos de UX obrigatórios (wf §39) — FID-27, card de encerramento

[ADR-0054](adrs/ADR-0054-requisitos-ux-transversais.md) — varredura dos 12
requisitos transversais de wf §39 contra todas as páginas acima. 9 lacunas
reais fechadas (confirmação + critérios em `aprovacoes.html`, coluna Modelo
em `execucoes.html`, navegação de volta em `auditoria.html`, pill de risco
crítico em `demanda-detalhe.html`/`card-detalhe.html`, indicador de retorno
de fluxo e reexibição de `next_action` em `card-detalhe.html`, histórico
enriquecido em `demanda-detalhe.html`), travadas por
[`tests/integration/test_ux_transversal_wf39.py`](../tests/integration/test_ux_transversal_wf39.py).
Com este card, os 137 cards do board (`FID-01`…`FID-27` + `TASK-01`…`TASK-110`)
estão 100% `Done`.
