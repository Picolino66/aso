# Design system — tema claro e componentes reutilizáveis (wf §2.1)

Fonte única visual das páginas em `/ui/*`. Ver [ADR-0034](adrs/ADR-0034-design-system-wireframe.md)
(tokens/componentes CSS) e [ADR-0035](adrs/ADR-0035-header-compartilhado.md)
(header de 9 elementos) para o raciocínio arquitetural.

## Arquivos

- [`src/aso/api/static/tokens.css`](../src/aso/api/static/tokens.css) — variáveis
  CSS (`:root`): paleta de cor, espaçamento, raio, fontes. **Sempre** carregado
  antes de `components.css`.
- [`src/aso/api/static/components.css`](../src/aso/api/static/components.css) —
  biblioteca de componentes reutilizáveis, construída a partir do vocabulário que
  já existia (duplicado) nas 4 páginas.
- [`src/aso/api/static/header.js`](../src/aso/api/static/header.js) — header
  compartilhado de 9 elementos (wf §2.3). Primeiro JS compartilhado do projeto
  (ADR-0035) — as 4 páginas continuam com seu próprio `<script>` autocontido
  para tudo o mais.

Toda página de `/ui/*` carrega os dois arquivos no `<head>`, nesta ordem:

```html
<link rel="stylesheet" href="/ui/tokens.css">
<link rel="stylesheet" href="/ui/components.css">
<style>/* só o que é específico desta página */</style>
```

O `<style>` de cada página vem **depois** dos `<link>`, então uma regra local com o
mesmo seletor de `components.css` a sobrescreve de propósito (ex.: o `.card` do
Kanban macro, que é visualmente um mini-card clicável, não o card-container padrão).

## Paleta (wf §2.1: fundo claro, tons neutros, bordas visíveis)

| Token | Valor | Uso |
|---|---|---|
| `--bg` | `#f8fafc` | fundo da página |
| `--panel` | `#ffffff` | cards, painéis, cabeçalho |
| `--panel-2` | `#f1f5f9` | fundo secundário — inputs, hover, linhas de destaque |
| `--border` | `#cbd5e1` | bordas visíveis (o wireframe pede borda em vez de sombra) |
| `--muted` | `#64748b` | texto secundário |
| `--fg` | `#0f172a` | texto principal |
| `--accent` | `#0284c7` | cor de destaque (links, botão primário, item ativo) |
| `--ok` / `--warn` / `--err` / `--info` | verde/âmbar/vermelho/índigo (600) | estados semânticos |
| `--on-*` | branco | cor de texto sobre um fundo `--accent`/`--ok`/`--warn`/`--err`/`--info` |
| `--radius` | `10px` | raio padrão de cards/modais |
| `--gap` | `14px` | espaçamento padrão entre blocos |
| `--font` / `--mono` | sans-serif / monoespaçada | tipografia legível (wf §2.1) |

## Componentes

Cada componente abaixo cita a seção do `wiframe-fluxo.md` que o descreve.

### Card de indicador / painel (`.card`, wf §3.3)

```html
<div class="card">
  <h2>Título da seção</h2>
  ... conteúdo ...
</div>
```
`.card > h2` já vem estilizado como rótulo pequeno em maiúsculas. Variante de
mini-card clicável (kanban): ver `.kcard` abaixo.

### Botão (`button` ou `.btn`)

Duas formas convivem por herança histórica das páginas — ambas têm a mesma
linguagem visual e os mesmos modificadores:

```html
<button class="ok">Confirmar</button>
<button class="ghost">Cancelar</button>
<button class="err">Remover</button>
<button class="sm">Pequeno</button>

<button class="btn ok">Confirmar</button>
<button class="btn ghost" disabled>Cancelar</button>
```
Modificadores: `.ghost` (neutro), `.ok` (verde), `.err` (vermelho), `.info`
(índigo, só na forma `button`), `.sm`/`.big` (tamanho). `[disabled]`/`:disabled`
já ficam com opacidade reduzida automaticamente.

### Pill de status

```html
<span class="pill ok">Aprovado</span>
<span class="pill err">Reprovado</span>
<span class="pill warn">Pendente</span>
<span class="pill info">Em revisão</span>
<span class="pill accent">Em destaque</span>
```
Sem modificador, `.pill` usa o tom neutro (`--border`/`--fg`).

### Tabela filtrável (wf §4)

```html
<table>
  <thead><tr><th>Código</th><th>Título</th><th>Status</th></tr></thead>
  <tbody><tr><td>ASO-101</td><td>…</td><td><span class="pill ok">Aprovado</span></td></tr></tbody>
</table>
```
Os filtros em si (busca, selects) usam os componentes de formulário padrão
(`input`, `select`) dentro de um `.row`.

### Checklist (wf §9.2)

```html
<ul class="checklist">
  <li class="ok"><span class="ico">✓</span> Item concluído</li>
  <li class="atual"><span class="ico">▶</span> Item atual <span class="aqui">você está aqui</span></li>
  <li class="falha"><span class="ico">✕</span> Item com falha</li>
  <li><span class="ico">○</span> Item futuro</li>
</ul>
```

### Árvore (wf §12, "Estrutura da demanda")

```html
<ul class="tree">
  <li><span class="node">Épico: Autenticação OAuth</span>
    <ul>
      <li><span class="node">História: Login</span>
        <ul><li><span class="node">ASO-101</span> <span class="meta">Done</span></li></ul>
      </li>
    </ul>
  </li>
</ul>
```
Novo nesta ADR — nenhuma tela hoje o consome ainda; existe para a Tela 10
(estrutura da demanda), fora do escopo deste card.

### Abas (wf §6.3)

```html
<div class="tabs">
  <div class="tab active">Visão geral</div>
  <div class="tab">Documentos</div>
</div>
```

### Painel de logs / timeline (wf §8)

```html
<div class="tl">
  <div>14:02 — Projeto carregado</div>
  <div>14:04 — Módulo authentication identificado</div>
</div>
```
Variante rica (usada em `detalhe.html`, painel ao vivo do agente): `.feed` com
linhas `.l` tipadas (`.texto`/`.ferramenta`/`.resultado`/`.marco`/`.bruto`/`.err`).

### Barra de progresso (wf §6.4)

```html
<div class="progressbar"><div style="width:72%"></div></div>
```
`.progress`/`.progresso` são aliases históricos do mesmo componente (páginas
diferentes nomeavam a classe de forma diferente antes desta ADR); todos os três
nomes de classe continuam funcionando.

### Kanban (board + card)

```html
<div class="board">
  <div class="col"><h3>Backlog</h3>
    <div class="kcard"><strong>Título do card</strong><small>meta</small></div>
  </div>
</div>
```
`.col`/`.column` são o mesmo componente (nomes históricos diferentes por
página); ambos continuam funcionando.

## Grid responsivo

`components.css` define dois pontos de quebra compartilhados:
- `max-width:900px` — colapsa qualquer `main` de duas colunas para uma coluna.
- `max-width:720px` — reduz o padding do header e esconde `header .spacer`.

Cada página pode acrescentar seus próprios ajustes finos (ex.: `nova.html`
empilha o indicador de etapas em telas muito estreitas).

## O que NÃO mudou (tokens/componentes, ADR-0034)

Nenhum arquivo `.js` foi tocado — a lógica de cada página (fetch de API,
renderização, estado) continua exatamente onde estava, no `<script>` inline de
cada HTML (ver [ADR-0013](adrs/ADR-0013-tela-de-detalhe-por-proximo-passo.md):
a lógica de governança vive no backend, a tela só renderiza). Este design system
é puramente visual: os mesmos seletores de classe, os mesmos elementos, a mesma
estrutura de markup — só a cor e a origem do CSS mudaram.

## Header (`header.js`, wf §2.3, ADR-0035)

Cada página troca seu antigo `<header>...</header>` por um contêiner vazio:

```html
<header id="app-header"></header>
```

E, no início do próprio `<script>`, chama `ASOHeader.mount(...)` **antes** de
qualquer `getElementById` que dependa de um elemento do header (login, botões
extras):

```html
<script src="/ui/header.js"></script>
<script>
  ASOHeader.mount(document.getElementById('app-header'), {
    subtitulo: 'texto ao lado do logo',       // opcional
    orchestrationId: ID,                       // opcional — mostra Projeto/Ambiente
    projectId: projeto && projeto.id,          // opcional — escopa os indicadores
    extraHtml: '<button id="x">Botão da página</button>', // opcional
  });
  // resto do script da página, incluindo listeners para os IDs do extraHtml
</script>
```

`mount` escreve o HTML de forma síncrona (`innerHTML`), então qualquer
`getElementById` do `extraHtml` que o resto do script da página fizer depois
da chamada encontra o elemento normalmente.

### Os 9 elementos (wf §2.3)

| # | Elemento | Fonte |
|---|---|---|
| 1 | Logo do ASO | fixo (`⚙️ ASO Runtime`) |
| 2 | Nome do projeto atual | `GET /v1/projects/{id}`, só quando `orchestrationId` é passado |
| 3 | Seletor de ambiente | `orchestration.deploy_environment` — texto informativo, **não editável** aqui (o wireframe não define nenhuma ação para "trocar" o ambiente do header; editar de fato é `PUT .../deploy/config`) |
| 4 | Indicador de execução ativa | `GET /v1/header-summary` (`execucoes_ativas`) |
| 5 | Indicador de falhas | idem (`falhas`) |
| 6 | Indicador de aprovações pendentes | idem (`aprovacoes_pendentes`) |
| 7 | Campo de busca | `GET /v1/search?q=` — demanda, card ou documento; resultado navega para `/ui/detalhe?id=` |
| 8 | Central de notificações | `GET /v1/approvals?status=pending` — mesma fonte do indicador 6, listada |
| 9 | Perfil do usuário | `GET /v1/me` (`actor`/`role`) — mais o campo/botão de login (token Bearer) |

Os indicadores 4–6 fazem polling a cada 20s enquanto a página está aberta —
não há stream global (o único SSE do runtime é por orquestração,
`.../events/stream`); um stream global fica para um incremento futuro se a
frequência de 20s se mostrar insuficiente.

### O que NÃO existe hoje (documentado para não ser "reinventado" por engano)

- Não há endpoint de configuração de ambiente pelo header — o item 3 é só
  leitura.
- Não há menu no "Perfil do usuário" (não existe conceito de usuário nomeado
  no runtime — só token → papel via `ASO_API_KEYS`, ver `api/auth.py`).
- A busca (item 7) não abre em uma página de resultados dedicada — cada
  resultado navega direto para `/ui/detalhe?id=` da orquestração; não há
  âncora para um card ou ADR específico dentro daquela página ainda.
