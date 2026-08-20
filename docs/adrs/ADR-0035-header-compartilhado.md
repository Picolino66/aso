# ADR-0035 — Header compartilhado com os 9 elementos da spec

- **Status:** ACCEPTED
- **Fase:** F4 (evolução pós-O5)
- **Data:** 2026-08-06
- **Relaciona-se com:** [ADR-0034](ADR-0034-design-system-wireframe.md) (design
  system — este ADR estende a infraestrutura CSS dela, mas introduz o primeiro
  JS compartilhado do projeto), [ADR-0013](ADR-0013-tela-de-detalhe-por-proximo-passo.md)
  (precedente "tela burra" — não revisitado aqui: o header consome dados já
  prontos da API, não recalcula governança), [`wiframe-fluxo.md`](../../wiframe-fluxo.md)
  §2.3 (requisito de origem), [docs/design-system.md](../design-system.md)
  (documentação do componente)

## Contexto

O `wiframe-fluxo.md` §2.3 pede 9 elementos no header: logo, nome do projeto
atual, seletor de ambiente, indicador de execução ativa, indicador de falhas,
indicador de aprovações pendentes, campo de busca, central de notificações e
perfil do usuário — com um mock de uma linha (`ASO │ Projeto: SID3 ▼ │
Ambiente: Produção ▼ │ Execuções: 4 │ Alertas: 2 │ Buscar... │ 🔔 │ Usuário`).

Duas lacunas descobertas na investigação, antes de qualquer código:

1. **O wireframe não detalha 4 dos 9 itens.** Não há seção sobre o que a
   central de notificações lista, o que a busca global varre, o que
   "selecionar" um ambiente faz, nem se o perfil do usuário tem um menu. Fora
   da lista de bullets e do mock, essas quatro peças não têm especificação —
   decidir o comportamento delas é trabalho desta ADR, não uma leitura literal
   de outra seção.
2. **A maior parte dos "dados reais da API" que os indicadores exigem não
   existia.** Não havia `GET /v1/me` (o frontend não tinha como saber "quem
   sou eu" além de "existe um token salvo" — a identidade é só token→papel via
   `ASO_API_KEYS`, sem usuário nomeado), não havia busca de texto livre, e os
   agregados existentes (`GET /v1/metrics`, `GET /v1/approvals`) eram sempre
   globais, sem filtro por projeto — mas o mock do wireframe (`Projeto: SID3 ▼`
   ao lado de `Execuções: 4`) sugere números escopados ao projeto selecionado.

Diferente da ADR-0034 (puro reskin, zero mudança de `<script>`), este card é
**funcionalidade nova com dados ao vivo** — 9 elementos duplicados em 4 páginas
seria pior duplicação que a de CSS que a ADR-0034 resolveu. Não dá para
implementar sem tocar JS.

## Opções consideradas

1. **Duplicar o markup/lógica dos 9 elementos nas 4 páginas**, no mesmo
   espírito "cada página autocontida" da ADR-0034. Rejeitada: ao contrário do
   CSS (onde duplicar era só recolorir), aqui cada cópia precisaria de sua
   própria lógica de polling, busca e dropdown — 4x mais superfície para
   divergir, exatamente o problema que a ADR-0034 acabou de fechar para o CSS.
2. **Indicadores sempre globais, sem escopo por projeto.** Rejeitada (com
   opção oferecida e não escolhida): o mock do wireframe deixa claro que os
   números aparecem ao lado do projeto selecionado — tratá-los como globais
   contradiria a leitura mais direta do §2.3.
3. **Inventar comportamento para os 4 itens sem especificação** (menu de
   usuário, ação de "trocar ambiente", central de notificações com tipos
   próprios). Rejeitada: o projeto segue "fato, não palpite" — decisão abaixo
   é reaproveitar dado que já existe (aprovações pendentes, falhas) em vez de
   construir um subsistema novo sem pedido explícito.
4. **`header.js` compartilhado + 4 endpoints novos/estendidos no backend,
   dados reaproveitados sempre que possível.** Aceita — ver Decisão.

## Decisão

**(1) Backend — quatro peças novas, todas GET, todas dev-scale (sem índice
dedicado).**
- `GET /v1/me` (`app.py`): devolve `{actor, role}` do `request.state.principal`
  já autenticado pelo middleware `gateway` — não há usuário nomeado no
  runtime, só isso.
- `GET /v1/header-summary?project_id=` (`OrchestrationService.header_summary`):
  `{execucoes_ativas, falhas, aprovacoes_pendentes}`. Itera
  `list_all(project_id=...)` (já existia, filtrável) e soma
  `count_cards_by_status(oid)["Failed"]` + aprovações `pending` de
  `list_all_approvals()` filtradas ao conjunto de ids do escopo. Mesmo padrão
  N+1 que `list_all_approvals` já usa hoje (itera todas as orquestrações do
  escopo a cada chamada) — consistente com a filosofia "dev-scale, não
  hyperscale" já aplicada a rings de 5, bundles em memória, etc.; não criei
  agregação SQL nova para não introduzir uma segunda forma de contar as mesmas
  coisas que `aggregate_metrics` já conta globalmente.
- `GET /v1/search?q=&project_id=` (`control/search.py::buscar` + `svc.search`):
  varre demanda (`user_request`), card (`title`) e ADR (`title`) por substring
  case-insensitive, bounded a 100 orquestrações por chamada
  (`list_orchestrations_page`). `buscar` é uma função pura (substring +
  limite) — o serviço faz todo o I/O de coleta, o mesmo padrão de
  separação já usado por `control/failure.py`/`control/selecao.py`.
- `GET /v1/approvals` ganha filtros opcionais `status`/`project_id` (só no
  handler do `app.py` — `list_all_approvals()` do serviço não muda).

Todos os quatro são `GET`, então caem em `viewer` por `required_role` sem
precisar tocar `api/auth.py`.

**(2) `header.js` — primeiro JS compartilhado do projeto, deliberadamente
pequeno.** Cada página troca `<header>...</header>` (markup completo,
duplicado) por `<header id="app-header"></header>` e chama
`ASOHeader.mount(container, opts)` uma vez, síncrono, antes de qualquer
`getElementById` de que o resto do script da página precise (login, botões
extras) — `mount` escreve via `innerHTML`, então a ordem de execução garante
que os elementos existem quando o script da página os procura depois.
`opts.extraHtml` é uma string HTML crua que a página fornece para os botões
que só fazem sentido naquela tela (ex.: "📁 Novo projeto"/"＋ Nova
orquestração" em `macro.html`, "⚙ Configurações" em `detalhe.html`) — cada
página mantém o `id`/`addEventListener` exatamente como já tinha, só a
CRIAÇÃO do elemento migrou para dentro do `extraHtml`.

**(3) O login continua por `localStorage['aso_token']`, agora com
`location.reload()` em vez de callback por página.** Antes, cada página tinha
seu próprio handler de "Entrar" (`saveTok()` em `index.html`, listener `#login`
em `macro.html`/`detalhe.html`, chaves de input inconsistentes `#tok` vs.
`#token`). `header.js` unifica isso: um único campo/botão, grava no mesmo
`localStorage['aso_token']` de sempre (nenhuma migração de dado necessária) e
recarrega a página — mais simples e mais robusto que os handlers antigos
(`detalhe.html`, por exemplo, também precisava fechar manualmente a conexão
SSE antes de recarregar; um reload completo faz isso de graça). Cada página
mantém sua própria função `token()` local para as chamadas de API que já
fazia — `header.js` não a substitui, só para de duplicar a UI de login.

**(4) Reaproveitamento em vez de subsistema novo.** "Central de notificações"
lista as aprovações pendentes (`GET /v1/approvals?status=pending`) — a mesma
fonte do indicador 6, sem inventar tipo de notificação novo. "Seletor de
ambiente" mostra `orchestration.deploy_environment` como texto informativo,
**sem** ação de trocar (não existe no resto do sistema o conceito de "ambiente
de visualização do console" — "Ambiente" em toda outra seção do wireframe já
significa o ambiente de deploy/teste de uma orquestração específica). "Perfil
do usuário" mostra `actor`/`role` sem menu (não há conceito de usuário além
disso). Cada uma dessas decisões está documentada em
`docs/design-system.md` sob "O que NÃO existe hoje", para não ser reinventada
por engano num card futuro.

**(5) Indicadores por polling (20s), não SSE novo.** O único stream do runtime
é por orquestração (`.../events/stream`); um stream global de métricas seria
proporcional a um problema que ainda não apareceu (indicadores levemente
desatualizados por até 20s é aceitável para um dashboard operacional). Fica
para um incremento futuro se a cadência atual se mostrar insuficiente.

**(6) `detalhe.html` ganhou um `.orquestracao-banner` novo**, fora do
`<header>`: os breadcrumbs/título/fatos daquela orquestração específica não
são parte do header persistente do app (item de conteúdo da página, não de
navegação) — separá-los do `<header>` é o que permite o header de 9 elementos
ficar genérico e igual nas 4 páginas.

## Consequências

**Positivas**
- Os 9 elementos existem e são alimentados por dados reais — nenhum número
  é mockado no cliente.
- Um único lugar (`header.js`) concentra a lógica do header; a inconsistência
  `#tok`/`#token`/`saveTok()`/listener desaparece por construção.
- Busca global funciona de fato (varre demanda/card/documento), mesmo que hoje
  só navegue até o nível da orquestração (ver limitação abaixo).
- Zero regressão: os 3 testes de integração que travam texto literal das
  páginas continuam passando sem alteração — as âncoras (`"ASO Runtime"` no
  `<title>`, `"Esteira F1 → F7"`, `"Nova orquestração"`, ausência de `"NOVA
  ORQUESTRAÇÃO"`) não viviam no `<header>` que mudou.

**Negativas / riscos aceitos**
- Este é o primeiro JS compartilhado do projeto — quebra a garantia "cada
  página é 100% autocontida" que a ADR-0034 preservou deliberadamente. Aceito
  porque a alternativa (duplicar 9 elementos com estado vivo 4 vezes) é pior.
- Busca navega só até `/ui/detalhe?id=` da orquestração — não há âncora para
  um card ou ADR específico dentro daquela página ainda (não existe página
  dedicada a card/documento hoje). Documentado, não escondido.
- "Seletor de ambiente" é só leitura — um operador que espera trocar de
  ambiente pelo header vai precisar ir a `PUT .../deploy/config`. Aceito: o
  wireframe não define nenhuma ação para esse controle, e inventar uma seria
  o oposto da disciplina "fato, não palpite" do projeto.
- Polling de 20s, não tempo real — aceitável para indicadores operacionais,
  reavaliar se a expectativa de "ao vivo" for mais estrita que isso.
