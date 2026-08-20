# ADR-0034 — Design system wireframe: tokens, tema claro e componentes reutilizáveis

- **Status:** ACCEPTED
- **Fase:** F4 (evolução pós-O5)
- **Data:** 2026-08-06
- **Relaciona-se com:** [ADR-0013](ADR-0013-tela-de-detalhe-por-proximo-passo.md)
  (precedente "tela burra": lógica de governança no backend, JS só renderiza —
  este ADR não o revisita), [`wiframe-fluxo.md`](../../wiframe-fluxo.md) §2.1–§2.4
  (requisito de origem), [docs/design-system.md](../design-system.md) (catálogo
  completo dos componentes)

## Contexto

O `wiframe-fluxo.md` §2.1 pede um estilo visual específico para a interface:

> "Fundo claro; Componentes em tons neutros; Bordas visíveis; Ícones simples;
> Tipografia legível; Hierarquia clara; Pouca ornamentação; Foco em estrutura,
> navegação e funcionalidade; Layout responsivo; Componentes reutilizáveis."

A UI hoje (`src/aso/api/static/{macro,nova,detalhe,index}.html`) é um tema
escuro slate/ciano (`--bg:#0f172a`, `--accent:#38bdf8`) — o oposto do pedido. Além
disso, cada uma das 4 páginas tem seu **próprio** bloco `<style>` inline, com uma
cópia quase idêntica dos tokens de cor (inclusive uma inconsistência de nome:
`--panel2` em três arquivos, `--panel-2` no quarto) e do vocabulário de
componentes (`.card`, `.pill`, `.tabs`, `.progressbar`/`.progress`/`.progresso`,
`.tl`, `.kcard`, `.board`/`.col`/`.column`, tabela, `.checklist`, `.overlay`/
`.modal`) — sem nenhuma fonte única. Não existe build step, bundler, nem sistema
de módulos JS: cada página é um HTML autocontido com um único `<script>` inline
que já implementa toda a lógica de fetch/renderização daquela tela (precedente
fixado pela ADR-0013: a lógica de governança vive no backend; a tela só
renderiza o que a API devolve).

Este card (FID-07) é o primeiro da "Trilha B" do plano de fidelidade e bloqueia
os cards seguintes de shell (header de 9 elementos, sidebar de 16 seções) e,
por consequência, todas as telas novas do wireframe — que vão precisar deste
vocabulário de componentes para não reinventar CSS a cada tela nova.

## Opções consideradas

1. **Reescrever as 4 páginas do zero com um framework de UI** (React/Vue + build
   step). Rejeitada: introduziria uma segunda arquitetura de frontend só para
   trocar de tema, um risco desproporcional ao problema, e contradiz a
   simplicidade deliberada do projeto (zero dependência de build hoje). Nenhum
   critério de aceite deste card pede isso.
2. **Recolorir cada página no próprio `<style>` inline, sem extrair nada
   compartilhado.** Rejeitada: perpetua a duplicação de 4 cópias dos mesmos
   tokens/componentes (a raiz do problema, incluindo a inconsistência
   `--panel2`/`--panel-2`) e não entrega o critério de aceite "biblioteca de
   componentes reutilizáveis documentada" — só trocaria a cor, não criaria uma
   fonte única.
3. **Dois arquivos CSS estáticos compartilhados (`tokens.css` + `components.css`),
   servidos pelo `StaticFiles` já montado em `/ui`, sem tocar nenhum `<script>`.**
   Aceita — ver Decisão.

## Decisão

**(1) `tokens.css` + `components.css` em `src/aso/api/static/`, sem build step.**
O `app.py` já monta `StaticFiles(directory=_STATIC_DIR)` em `/ui` (depois das 4
rotas explícitas `/ui/`, `/ui/nova`, `/ui/detalhe`, `/ui/console`) — os dois
arquivos novos são servidos automaticamente, sem mudar `app.py`. Cada página
troca seu `:root{...}`/CSS duplicado por dois `<link>` no `<head>`, nesta ordem
(tokens antes de components, que consome as variáveis).

**(2) Extração literal, não redesenho.** Cada regra movida para
`components.css` é a mesma regra que já existia (mesmo seletor, mesma
propriedade), só recolorida com os novos tokens — nenhuma classe, nenhum
seletor, nenhum atributo de markup mudou. Onde duas páginas usam nomes de
classe históricos diferentes para o mesmo componente (`.col` vs `.column`,
`.progress`/`.progresso` vs `.progressbar`, `button` vs `.btn`), o arquivo
compartilhado declara **as duas formas**, lado a lado, em vez de forçar uma
migração de markup — o JS de nenhuma página precisou mudar uma linha.

**(3) `<style>` de cada página só guarda o que é realmente específico dela**
(ex.: `.esteira`/`.fase`/`.feed` de `detalhe.html`, `.diffgrid`/`.diffcol` de
`index.html`, `.steps` de `nova.html`, `.project`/`.fs-list` de `macro.html`) —
e vem **depois** dos `<link>` no `<head>`, então pode sobrescrever uma regra
compartilhada de propósito quando o mesmo nome de classe tem um significado
local diferente. Caso real: `.card` em `macro.html` é o mini-card clicável de
uma coluna do kanban (padding pequeno, cursor pointer, hover de borda), bem
diferente do card-container das outras 3 páginas — a página sobrescreve
`components.css` legitimamente via cascata (mesma especificidade, ordem de
declaração posterior vence), sem precisar de um nome de classe novo.

**(4) Paleta clara concreta** (o wireframe não define valores hex, só
princípios): `--bg:#f8fafc`, `--panel:#ffffff`, `--panel-2:#f1f5f9`,
`--border:#cbd5e1`, `--muted:#64748b`, `--fg:#0f172a`, `--accent:#0284c7`
(mais escuro que o `#38bdf8` do tema antigo — necessário para manter contraste
adequado de texto branco sobre fundo colorido agora que o fundo geral é claro),
`--ok:#16a34a`/`--warn:#d97706`/`--err:#dc2626`/`--info:#4f46e5` (tons 600,
mais escuros que os 500 do tema antigo, pelo mesmo motivo de contraste). Novos
tokens `--on-accent`/`--on-ok`/`--on-warn`/`--on-err`/`--on-info` (todos
brancos) substituem as cores de texto de botão que antes eram hardcoded
(`#08131f`, `#fff`) — nomeados por *intenção* (cor de texto sobre aquele fundo),
não pelo valor, para a próxima mudança de paleta não precisar caçar hex
espalhado.

**(5) Um componente novo: `.tree`** (wf §12, "Estrutura da demanda") — nenhuma
tela hoje o usa; existe para a Tela 10 (fora do escopo deste card, mas listada
entre os componentes exigidos pela descrição do card FID-07), evitando que o
card daquela tela precise inventar CSS de árvore do zero.

**(6) Painel "ao vivo do agente" (`.feed`) deixou de ser um terminal escuro
fixo.** O `.feed` de `detalhe.html` tinha fundo hardcoded `#0a1220`
independente do tema — no tema escuro isso já era quase invisível (mesma
paleta), mas manteria um retângulo escuro incongruente dentro de uma página
clara. Como o critério de aceite exige o tema claro em **todas** as páginas,
sem exceção, o `.feed` passou a usar `--panel-2` como qualquer outro painel —
as cores semânticas por tipo de linha (`--accent`/`--info`/`--ok`/`--muted`/
`--warn`) já foram escolhidas para funcionar em fundo claro, então a legibilidade
não piora.

**(7) `--panel2`/`--panel-2` unificados em `--panel-2`** — a inconsistência de
nome (3 páginas vs. 1) desaparece porque agora há uma única declaração da
variável. Nenhum código JS referenciava a variável diretamente (confirmado por
busca — os únicos usos de `var(--panel-2)` em `<script>` já estavam em
`index.html`, que já usava o nome com hífen), então a unificação não quebra
nada em execução.

**(8) `docs/design-system.md`** documenta cada componente (propósito, seção do
wireframe, markup de exemplo) — o critério de aceite "biblioteca documentada".

## Consequências

**Positivas**
- Fonte única de tokens/componentes — a próxima tela nova (Trilha B em diante)
  reaproveita `.card`/`.pill`/`.tabs`/`.checklist`/`.tree`/etc. sem duplicar CSS.
- Zero mudança de `<script>`/markup — todo o comportamento (fetch, filtros,
  drag-and-drop do kanban, painel ao vivo via SSE) continua idêntico; só a cor
  mudou. Os 3 testes de integração existentes que travam texto literal das
  páginas (`test_extra_endpoints.py`, `test_auth.py`,
  `test_next_step_api.py::test_ui_detalhe_e_dedicada_a_uma_orquestracao`)
  continuam passando sem alteração.
- A inconsistência `--panel2`/`--panel-2` desaparece por construção.
- Nenhuma dependência nova (sem bundler, sem framework) — mantém a arquitetura
  frontend atual (HTML autocontido, CSS/JS inline por página) intacta, só
  adiciona dois arquivos estáticos.

**Negativas / riscos aceitos**
- Este card **não** inclui header de 9 elementos nem sidebar de 16 seções (isso
  é FID-08/FID-09, que dependem deste) — é reskin + biblioteca, não navegação.
  Uma tela aberta hoje continua com a mesma navegação de antes (link simples de
  volta ao catálogo, sem sidebar).
- Pequenas variações de valor entre o que cada página tinha antes e o valor
  agora compartilhado (ex.: opacidade de fundo de `.pill`, padding de `.empty`)
  foram niveladas para o valor do `components.css` — são ajustes cosméticos de
  poucos pixels/pontos percentuais de opacidade, não mudanças de comportamento.
