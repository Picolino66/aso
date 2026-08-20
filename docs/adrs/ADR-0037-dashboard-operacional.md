# ADR-0037 — Dashboard operacional (Tela 01)

- **Status:** ACCEPTED
- **Fase:** F4 (evolução pós-O5)
- **Data:** 2026-08-06
- **Relaciona-se com:** [ADR-0034](ADR-0034-design-system-wireframe.md) (tokens/
  componentes), [ADR-0035](ADR-0035-header-compartilhado.md) (header, mesmo
  raciocínio "fato, não palpite" para os 4 itens sem especificação),
  [ADR-0036](ADR-0036-sidebar-e-mapa-de-paginas.md) (sidebar/mapa de páginas —
  este card preenche o primeiro dos 16 placeholders que ela criou),
  [`wiframe-fluxo.md`](../../wiframe-fluxo.md) §3 (requisito de origem)

## Contexto

O `wiframe-fluxo.md` §3 pede o primeiro conteúdo real de uma das 16 seções da
sidebar (ADR-0036): 4 cards de indicador (demandas ativas, em execução,
bloqueadas, falhas abertas — cada um com "Título; Valor atual; Variação;
Indicador visual; Link para detalhamento", §3.3), um diagrama do fluxo geral
da esteira (§3.3 traz um bloco `mermaid` pronto, 14 nós), "cards por status",
"aprovações pendentes por tipo" (4 tipos citados no mock: Discovery,
Arquitetura, Deploy, Aceite final) e "atividades recentes" (horário + ator).

A investigação prévia (antes de qualquer código) encontrou que **a maior
parte desses dados não tem fonte real hoje**:

- Não existe contagem de orquestrações "ativas" nem "bloqueadas" — só
  `execucoes_ativas` (status `running`, já usado no header do FID-08).
- **Não existe nenhuma série temporal dos indicadores globais** — o único
  histórico com timestamp do sistema é `SloEvaluation`, e é (a) por
  orquestração, (b) sobre burn-rate de SLO, não sobre essas contagens, (c) só
  gravado sob demanda explícita, nunca automaticamente. "Variação" (o `+12%`
  do mock) não tem de onde vir.
- `HumanApproval.action` é texto livre — não existe o enum de 4 tipos do
  wireframe (Discovery/Arquitetura/Deploy/Aceite final). Os 3 pontos reais do
  código que criam aprovação automática (execução de estratégia, aplicação de
  patch, avanço de fase) não mapeiam 1:1 para esses 4 rótulos.
- Só existe timeline **por orquestração** (`GET .../timeline`) — nenhum
  endpoint agrega atividade de todas as orquestrações.
- Nenhuma página carrega uma lib de renderização de diagrama hoje — as ADR-
  0034/0035/0036 mantiveram deliberadamente "zero bundler, zero dependência
  externa" no frontend.

Cada uma dessas lacunas exigiu uma decisão explícita, tomada com o usuário
antes de escrever código (duas foram perguntas diretas; as demais seguem o
mesmo raciocínio "fato, não palpite" já aplicado nas ADRs anteriores).

## Decisão

**(1) "Variação" fica de fora — sem número fabricado.** Confirmado com o
usuário: como não existe série temporal real, cada card de indicador mostra
só **título, valor e link** (3 dos 5 atributos do wireframe). Inventar uma
porcentagem ou introduzir um mecanismo de snapshot periódico novo (uma
segunda peça de arquitetura, fora do escopo deste card) foram as duas
alternativas descartadas — a primeira por princípio, a segunda por escopo.

**(2) "Bloqueadas" reaproveita o status real `waiting_human`.** Não existe (e
este ADR não cria) nenhum status `blocked` de orquestração — o único
candidato próximo no código é uma checagem defensiva morta
(`orchestration_service.py`, guarda que testa `status in {"created",
"blocked"}` mas nenhum caminho jamais atribui `"blocked"`). Uma orquestração
`waiting_human` — parada esperando decisão humana — é, de fato, uma demanda
bloqueada; é o mapeamento mais honesto disponível no vocabulário que já
existe, sem inventar um status novo nem redefinir `ColumnKey.BLOCKED` (que é
de **card**, não de demanda) para um uso que não é o dele.

**(3) `dashboard_summary()` — quatro contagens de orquestração + passagem de
`cards_por_status` + agrupamento de aprovações.** `demandas_ativas` = status
não-terminal (`not in {completed, cancelled}`); `em_execucao` = `running`
(mesma definição já usada por `header_summary`, ADR-0035); `bloqueadas` =
`waiting_human`; `falhas_abertas` = `cards_por_status["Failed"]`.
`cards_por_status` reaproveita `aggregate_metrics()` inteiro quando global
(uma query já pronta) ou soma `count_cards_by_status(oid)` por orquestração
quando escopado a um projeto (mesmo padrão N+1 bounded já estabelecido por
`header_summary`/`search`, ADR-0035).

**(4) `HumanApproval.tipo` — campo novo, com os 3 tipos REAIS do código, não
os 4 do wireframe.** Migration `8f4b6d1c9a2e` adiciona `tipo: str =
"manual"`. Os 3 pontos que criam aprovação automaticamente ganham seu tipo
verdadeiro: `"estrategia"` (execução de plano de alto risco),
`"patch"` (patch de contexto pendente), `"fase_gate"` (avanço de fase após
gate). Aprovações criadas via `POST .../approvals` (a rota genérica, operador
decide o texto de `action` livremente) recebem `"manual"` — não é um dos três
automáticos. **Deliberadamente não** os rótulos Discovery/Arquitetura/
Deploy/Aceite final do wireframe: nenhum desses quatro existe como conceito
distinto no runtime hoje (F1-F7 do backend não mapeia 1:1 para eles, ver
investigação), e forçar essa tradução seria inventar categorias que não
refletem o sistema real. `aprovacoes_por_tipo` no `dashboard_summary` agrupa
pelas pendentes por esse campo.

**(5) Atividade global — nova query, não um novo mecanismo.** `EventRow` já
tem `created_at`/`orchestration_id`/`type`/`payload`; só faltava uma consulta
sem filtro de orquestração. `recent_events(limit)` (novo, nos dois
repositórios) faz um único `ORDER BY created_at DESC LIMIT N` — nenhuma
iteração por orquestração, ao contrário de `header_summary`/`search`/
`list_all_approvals` (que precisam do bundle hidratado; um evento já é uma
linha plana, não precisa). `ator` é melhor esforço a partir do `payload`
(`actor` ou `agent`, caindo em `"sistema"`) — nem todo evento tem um
responsável humano, e inventar um seria pior que admitir a ausência.

**(6) Diagrama do fluxo — mermaid.js via CDN, escolha explícita do usuário.**
Ofereci as duas opções (desenhar o fluxo à mão em HTML/CSS, seguindo o
precedente "zero dependência externa", vs. carregar mermaid.js e renderizar o
bloco que o `wiframe-fluxo.md` §3.3 já traz pronto) e o usuário escolheu a
segunda. **Isto é a primeira dependência externa do frontend** — rompe,
conscientemente, o precedente que as ADR-0034/0035/0036 mantiveram. Só
`dashboard.html` carrega `mermaid.min.js` (via `cdn.jsdelivr.net`); as
outras 19 páginas não são afetadas. Risco aceito: o diagrama não renderiza
sem rede (offline/CDN bloqueado) — degrada para o texto-fonte do mermaid
visível (dentro de um `<pre>`), não para um erro.

## Consequências

**Positivas**
- Nenhum número exibido é inventado — todo valor no dashboard vem de uma
  consulta real, e as lacunas genuínas (variação) ficam ausentes, não
  fabricadas.
- `HumanApproval.tipo` é reaproveitável por qualquer tela futura que precise
  distinguir a origem de uma aprovação (ex.: FID-18/23, que tratam aprovação
  de discovery/deploy).
- `recent_events`/`dashboard_summary` seguem os padrões já estabelecidos
  (N+1 bounded quando precisa hidratar bundle, query única quando não
  precisa) — nenhuma abordagem nova de acesso a dado.
- O primeiro dos 16 placeholders da ADR-0036 agora tem conteúdo real,
  confirmando que o padrão desenhado ali (header+sidebar+`<main>`) funciona
  para uma tela de verdade, não só para placeholders.

**Negativas / riscos aceitos**
- Mermaid via CDN é uma dependência de rede nova, only nesta página — offline
  ou CDN bloqueado degrada para o texto-fonte visível, não quebra a página,
  mas o "diagrama renderizado" não aparece.
- "Aprovações pendentes por tipo" usa 3 categorias reais, não as 4 do
  wireframe — quem espera ver literalmente "Discovery/Arquitetura/Deploy/
  Aceite final" não vai encontrar esses rótulos. Documentado aqui e no
  próprio dashboard (rótulos são os valores reais de `tipo`).
- "Bloqueadas" mede orquestrações `waiting_human`, que é um conceito mais
  amplo que "bloqueio" no sentido estrito (também cobre aprovações pendentes
  não-críticas) — aceito como a leitura mais honesta disponível no
  vocabulário atual do runtime.
