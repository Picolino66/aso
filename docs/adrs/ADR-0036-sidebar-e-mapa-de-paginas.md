# ADR-0036 — Sidebar de 16 seções e mapa de páginas

- **Status:** ACCEPTED
- **Fase:** F4 (evolução pós-O5)
- **Data:** 2026-08-06
- **Relaciona-se com:** [ADR-0034](ADR-0034-design-system-wireframe.md) (tokens/
  componentes CSS, zero bundler), [ADR-0035](ADR-0035-header-compartilhado.md)
  (primeiro JS compartilhado — `header.js`, mesmo raciocínio de contenção de
  escopo aplicado aqui), [`wiframe-fluxo.md`](../../wiframe-fluxo.md) §2.4 e §40
  (requisito de origem), [docs/mapa-paginas.md](../mapa-paginas.md) (entregável)

## Contexto

O `wiframe-fluxo.md` §2.4 pede uma navegação lateral com 16 seções (lista
plana, sem hierarquia): Dashboard, Demandas, Esteira, Kanban, Agentes,
Modelos, Documentos, Aprovações, Execuções, Testes, Code Reviews,
Implantações, Incidentes, Auditoria, Métricas, Configurações. O §40 exige,
como entregável, um "Mapa das páginas" (item 1) e uma "Estrutura de rotas"
(item 3).

Este é o **último card da Trilha B** (shell da interface) — todos os 17
cards de tela seguintes (FID-10 a FID-26, cobrindo as ~62 telas numeradas do
wireframe) dependem dele no `board.json`, e nenhum ainda começou (todos em
`Backlog`). Investigação prévia (cruzando as 16 seções com as telas
numeradas e com o backlog) confirmou um ponto decisivo: **nenhuma das 16
seções tem hoje um card que implemente seu conteúdo completo** — construir
as 16 telas de verdade aqui duplicaria integralmente o trabalho de FID-10 a
FID-26. O escopo deste card é, portanto, **infraestrutura de navegação**
(rotas + sidebar + mapa), não conteúdo.

Duas perguntas de arquitetura precisavam de resposta antes de codificar:

1. **16 páginas novas ou uma "shell" única com roteamento client-side?**
2. **As 4 páginas legadas (`/ui/`, `/ui/nova`, `/ui/detalhe`, `/ui/console`)
   ganham a sidebar também, ou ficam como estão?**

## Opções consideradas

1. **Roteamento client-side numa página "shell" única** (querystring/hash
   trocando o conteúdo de `<main>` via JS, sem round-trip ao servidor por
   seção). Rejeitada: romperia o precedente que as ADR-0034/0035 fixaram
   deliberadamente ("cada página é HTML autocontido, zero sistema de módulos,
   zero bundler") — introduziria um roteador client-side que hoje não existe
   em nenhuma linha do projeto (confirmado: zero uso de `history.pushState`/
   `hashchange`), com todo o estado extra que isso implica (deep-linking,
   back/forward, refresh preservando seção). É uma mudança de paradigma maior
   que o problema pede.
2. **16 arquivos HTML + 16 rotas explícitas**, mesmo padrão das 4 páginas já
   existentes. Aceita — ver Decisão (1).
3. **Retrofit da sidebar nas 4 páginas legadas.** Rejeitada (oferecida ao
   usuário e não escolhida): cada uma mistura conteúdo de várias seções da
   sidebar ao mesmo tempo (`detalhe.html`, por exemplo, resume Execuções,
   Testes, Code Reviews e Implantações numa página só) — não há uma "seção
   ativa" única e honesta para destacar nelas. Forçar isso agora criaria uma
   sidebar que mente sobre onde o operador está.
4. **Construir o conteúdo real de uma ou mais das 16 seções já aqui**
   (aproveitando que a infraestrutura estaria pronta). Rejeitada: duplicaria
   o trabalho já planejado e atribuído a FID-10…FID-26 — este card entrega a
   estrutura, não o conteúdo.

## Decisão

**(1) 16 arquivos HTML novos + 16 rotas explícitas**, gerados uma única vez
por um script (não é build step em runtime — o resultado são 16 arquivos
estáticos comuns, versionados como se tivessem sido escritos à mão; rodar o
script de novo só reescreve os mesmos 16 arquivos). Rotas registradas em
`app.py` via um laço sobre `_SIDEBAR_SECOES` chamando `app.add_api_route`
(equivalente a `@app.get`, só chamável programaticamente) com uma fábrica de
handler por arquivo — evita tanto copiar 16 funções quase idênticas quanto a
armadilha clássica de closure em `for` (mesmo cuidado já documentado em
`_check_predicate`, `orchestration_service.py`). **Deliberadamente não** um
path curinga (`/ui/{secao}`): um catch-all interceptaria
`/ui/tokens.css`/`components.css`/`header.js`/`sidebar.js` antes deles
chegarem ao `StaticFiles` mount — quebraria os assets compartilhados do
FID-07/08 silenciosamente.

**(2) Páginas legadas não ganham a sidebar.** `/ui/`, `/ui/nova`,
`/ui/detalhe`, `/ui/console` continuam exatamente como o FID-08 as deixou —
só o header. A sidebar é a porta de entrada nova para as 16 seções; as
páginas legadas continuam acessíveis (inclusive linkadas a partir dos
placeholders, ver decisão 4) até que os cards FID-10…FID-26 substituam seu
conteúdo pela seção correspondente.

**(3) `sidebar.js` — segundo JS compartilhado do projeto**, mesmo molde do
`header.js`: `ASOSidebar.mount(container, opts)`, HTML síncrono via
`innerHTML`. A seção ativa é calculada a partir de `location.pathname` (sem
estado adicional no cliente — cada carregamento de página descobre sozinho
"onde estou" pela própria URL, satisfazendo "seção ativa destacada" sem
inventar um mecanismo de persistência de estado que a navegação por URL já
resolve de graça). Em telas estreitas (`max-width:860px`), a sidebar vira um
painel deslizante com um botão `☰` fixo — mesmo espírito responsivo dos
breakpoints já definidos em `components.css` pela ADR-0034.

**(4) Cada uma das 16 páginas é um placeholder honesto**, não uma tela
fingindo estar pronta: título da seção, aviso "ainda não implementada —
acompanhe o card FID-XX", e um link para a página legada que hoje cobre
parcialmente aquele conteúdo, quando existe uma (ex.: "Demandas" aponta para
`/ui/nova`; "Kanban" aponta para `/ui/`). Quatro seções (Esteira, Agentes,
Modelos, Incidentes) não têm nenhum card de tela dedicado — o placeholder
delas diz isso explicitamente, para não ser esquecido nem duplicado por
engano num card futuro (registrado também em `docs/mapa-paginas.md`).

**(5) `docs/mapa-paginas.md` novo**, satisfazendo §40.1/§40.3: tabela
rota↔seção↔card(s) FID↔status↔conteúdo-parcial-hoje, mais a lista das 4
rotas legadas preservadas. Linkado em `docs/index.md` (que também não linkava
`design-system.md` até agora — corrigido de passagem).

## Consequências

**Positivas**
- Os 4 critérios de aceite são satisfeitos: 16 rotas existem e respondem
  `200`, seção ativa destacada via URL (sem estado extra), mapa documentado,
  rotas antigas intocadas.
- Nenhum trabalho de FID-10…FID-26 foi antecipado nem duplicado — cada um
  desses cards agora só precisa **preencher** sua página, não criar rota,
  navegação, header ou tema do zero.
- `/ui/tokens.css`, `/ui/components.css`, `/ui/header.js` seguem sendo
  servidos normalmente — o risco de um catch-all interceptá-los foi
  identificado e evitado antes de virar bug.
- O placeholder linkando para a página legada equivalente significa que
  nenhum operador fica "preso" numa seção vazia sem saber onde encontrar
  aquele conteúdo hoje.

**Negativas / riscos aceitos**
- 16 arquivos HTML quase idênticos (só título/seção mudam) — aceito porque é
  gerado uma vez por script, não mantido à mão, e seguir divergindo desses 16
  templates conforme cada FID-10…FID-26 roda é esperado (cada um vai
  substituir o conteúdo do seu placeholder por uma tela real).
- Sidebar e header não compartilham exatamente a mesma superfície de todas as
  20 páginas (as 4 legadas não têm sidebar) — uma inconsistência visual
  deliberada e temporária, que desaparece à medida que FID-10…FID-26 forem
  absorvendo o conteúdo das páginas legadas para dentro das seções novas.
- Quatro seções (Esteira, Agentes, Modelos, Incidentes) ficam sem card de
  tela dedicado — decisão consciente de não inventar um card novo fora do
  escopo desta ADR; registrado como lacuna explícita no mapa de páginas para
  decisão futura do backlog.
