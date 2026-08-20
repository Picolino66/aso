# ADR-0038 — Lista de demandas com filtros e ações (Tela 02)

- **Status:** ACCEPTED
- **Fase:** F4 (evolução pós-O5)
- **Data:** 2026-08-07
- **Relaciona-se com:** [ADR-0016](ADR-0016-ficha-da-demanda.md) (`DemandBrief`,
  fonte dos 4 filtros "caros"), [ADR-0037](ADR-0037-dashboard-operacional.md)
  (mesmo raciocínio "fato, não palpite" e precedente de status `waiting_human`/
  ausência de `blocked`), [ADR-0036](ADR-0036-sidebar-e-mapa-de-paginas.md)
  (placeholder que este card preenche), [`wiframe-fluxo.md`](../../wiframe-fluxo.md)
  §4 (requisito de origem)

## Contexto

O `wiframe-fluxo.md` §4 pede uma tabela de demandas com 11 filtros combináveis
(texto, projeto, tipo, prioridade, risco, complexidade, impacto, status,
agente responsável, data de criação, aprovação humana) e 11 ações por linha
(abrir, editar, duplicar, priorizar, bloquear, cancelar, histórico,
documentos, cards, reiniciar etapa, solicitar intervenção).

Investigação prévia encontrou, de novo (mesmo padrão do FID-10/ADR-0037), que
nem tudo tem suporte real:

- **"Prioridade" não existe como campo de demanda.** Só existe
  `KanbanCard.priority`, por card, sempre derivado do `risco` da
  `DemandBrief` via `prioridade_de()` — nunca atribuído manualmente. O
  wireframe trata "Prioridade" e "Risco" como dois filtros distintos, mas no
  runtime são o mesmo valor.
- **4 das 11 ações não têm nenhum endpoint hoje**: Editar (cadastro completo é
  o FID-12, ainda não feito), Duplicar (sem endpoint de clonagem),
  Priorizar (seguindo o ponto acima, não há o que priorizar em nível de
  demanda), Bloquear (não existe status `blocked` de orquestração — mesmo
  achado documentado pela ADR-0037 para "Bloqueadas" do dashboard).
- **O filtro "aprovação humana" é uma armadilha de performance.** A forma
  óbvia de calculá-lo — reaproveitar `list_all_approvals()` — hidrata o
  bundle de **toda** orquestração do sistema a cada chamada; ótimo para um
  agregado global chamado uma vez (dashboard, header), péssimo como filtro de
  uma tabela paginada, onde colidiria direto com o critério de aceite "tabela
  pagina sem travar com muitas demandas".
- **4 dos filtros (tipo, risco, complexidade, impacto) vivem dentro de
  `demand_brief`**, uma coluna JSON sem índice — não dá para filtrar em SQL
  puro sem introduzir um índice novo (fora do escopo deste card).
- **Não existe nenhum precedente de tabela paginada com filtros persistidos
  na URL** em nenhuma página do projeto — este card desenha o padrão do zero.

Duas decisões de escopo foram confirmadas com o usuário antes de codificar
(a terceira, "Prioridade" reaproveita `risco`, seguiu direto o precedente já
estabelecido pela ADR-0037, sem necessidade de nova pergunta).

## Decisão

**(1) Escopo das 11 ações: 7 reais, 3 desabilitadas com motivo explícito.**
Confirmado com o usuário. Abrir, Cancelar, Visualizar histórico/documentos/
cards, Reiniciar etapa e Solicitar intervenção usam endpoints que já
existiam (`GET/POST` já documentados em `docs/api.md`); **Duplicar** ganhou
endpoint novo (decisão 3, abaixo — segunda pergunta ao usuário, que também
confirmou implementá-la). Editar, Priorizar e Bloquear aparecem no menu de
ações **desabilitadas**, com `title`/tooltip explicando o motivo exato (ex.:
"Não existe status de bloqueio de demanda hoje") em vez de: (a) esconder a
ação (o critério de aceite pede "11 ações por linha"), ou (b) fingir uma
ação sem funcionalidade real por trás.

**(2) "Prioridade" e "Risco" convergem num único controle de filtro.** Os
dois nomes do wireframe (§4.2) mapeiam para o mesmo campo real
(`DemandBrief.risco`) — apresentar dois dropdowns independentes que sempre
concordam seria enganoso. O filtro único (`?risco=`) tem `title` explicando
a convergência. Contando os 11 controles de filtro renderizados (texto,
projeto, tipo, prioridade/risco, complexidade, impacto, status, agente,
criada-de, criada-até, aprovação humana), o total bate com os 11 do
wireframe — a "Prioridade" separada do wireframe § 4.2 não ganhou um
controle a mais porque não existe outro dado para alimentá-lo.

**(3) `POST /v1/orchestrations/{id}/duplicate` — novo, implementado de
verdade.** Confirmado com o usuário (segunda pergunta, escolha explícita).
Cria uma orquestração **nova**, re-triada do zero a partir do
`user_request`/`project_id`/`target_path`/`execution_mode`/executor/effort/
`validation_command` da origem, pelo mesmo caminho de `create_with_triage`
("o único caminho correto de criação", ADR-0017) — **não** é uma cópia de
estado: cards, histórico e `demand_brief` não são clonados, a duplicata
começa do zero como qualquer orquestração nova. É uma ação barata e sem
ambiguidade, ao contrário de Editar/Priorizar/Bloquear, que exigiriam
conceitos novos de domínio.

**(4) Filtros baratos em SQL, filtros caros em memória sobre o resultado já
filtrado — nunca sobre todas as orquestrações do sistema.**
`project_id`/`status`/`q` (`LIKE`/`ILIKE` em `user_request`)/`executor`
(`selected_executor`)/`created_from`/`created_to` (`created_at`, string
ISO-8601, comparável lexicograficamente) são colunas reais, filtráveis
direto em SQL (`SqlAlchemyOrchestrationRepository.list_orchestrations`
estendido). `tipo`/`risco`/`complexidade`/`impacto` (dentro de
`demand_brief`) e `aprovacao_humana` rodam em `OrchestrationService`, **sobre
os candidatos já reduzidos pelos filtros baratos** — nunca escaneiam o
sistema inteiro. `aprovacao_humana` usa uma query nova e direta,
`orchestration_ids_with_pending_approval()` (`SELECT DISTINCT
orchestration_id FROM human_approvals WHERE status='pending'`, sobre o
índice `ix_approvals_orch_status` já existente) — deliberadamente **não**
`list_all_approvals()`, que hidrataria bundles desnecessariamente. Quando
nenhum filtro caro é usado (o caso comum), a paginação continua 100% em SQL,
sem nenhuma mudança de comportamento/custo em relação ao que já existia.

**(5) `GET /v1/orchestrations` sem `page` continua devolvendo tudo (contrato
preservado).** O gatilho de paginação continua sendo exclusivamente a
presença do parâmetro `page` — adicionar filtros não muda esse contrato
(testado explicitamente: `?q=x` sem `page` devolve todos os resultados que
batem, não só os primeiros 50).

**(6) Tabela paginada com filtros na URL — padrão novo, primeiro do
projeto.** `history.replaceState` (não `pushState`, para não poluir o
histórico do navegador a cada filtro) mantém a URL sincronizada com os
filtros e a página atual; ao carregar a página, o estado inicial vem da
própria URL — permite favoritar/compartilhar uma lista já filtrada. Página
de 20 itens (`PAGE_SIZE`), navegação anterior/próxima usando `X-Total-Count`
(já emitido pelo backend). Menu de ações por linha é um "⋮" com dropdown
(reaproveita `.hdr-dropdown`/`.hdr-dropdown-item`, introduzidos pelo header
no FID-08 — 11 botões por linha lado a lado não caberiam numa tabela).

**(7) "Solicitar intervenção humana" usa `prompt()`/`confirm()` nativos, não
um modal novo.** Simplificação deliberada de escopo: o campo único
necessário (motivo) não justifica construir um modal dedicado neste card já
grande — `.overlay`/`.modal` (ADR-0034) seguem disponíveis para um card
futuro que precise de um formulário mais rico aqui.

## Consequências

**Positivas**
- Os 11 filtros e as 11 ações existem na UI, cada ação com o comportamento
  real que tem hoje — nenhuma finge funcionar.
- O filtro "aprovação humana" não reintroduz o risco de performance que o
  próprio código já documentava como aceitável só para agregados globais.
- `POST .../duplicate` é reaproveitável por qualquer tela futura (FID-14,
  FID-20) que precise da mesma ação.
- Primeiro padrão de tabela paginada + filtros na URL do projeto — path
  trilhado para FID-14/FID-20/FID-21, que também vão precisar disso.

**Negativas / riscos aceitos**
- Editar/Priorizar/Bloquear ficam sem funcionalidade nesta entrega — quem
  clicar vê o motivo exato, não um erro genérico, mas a ação não acontece.
- "Prioridade" e "Risco" do wireframe, apresentados como dois filtros no
  §4.2, viram um só na UI real — documentado no `title` do controle.
- `prompt()`/`confirm()` nativos são visualmente inconsistentes com o design
  system (não usam `.modal`) — aceito pela simplicidade, candidato a
  melhoria futura sem mudança de contrato de API.
