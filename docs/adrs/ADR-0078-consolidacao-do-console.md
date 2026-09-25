# ADR-0078 — Consolidação do console: uma geração de páginas, uma navegação

- **Status:** ACCEPTED
- **Fase:** F5 (limpeza — MEL-55, origem `feedback.md` §3 e §7)
- **Data:** 2026-09-25
- **Supersede:** a decisão da [ADR-0036](ADR-0036-sidebar-e-mapa-de-paginas.md) de manter as quatro
  páginas legadas **intocadas e fora da sidebar** ("nenhuma delas corresponde 1:1 a uma seção")
- **Relaciona-se com:** [ADR-0034](ADR-0034-design-system-wireframe.md) (design system),
  [ADR-0035](ADR-0035-header-compartilhado.md) (header compartilhado),
  [ADR-0067](ADR-0067-execucao-assincrona-com-fila.md) (202 da fila),
  [ADR-0076](ADR-0076-catalogo-unico-de-executores.md) (catálogo de executores),
  [ADR-0061](ADR-0061-congelamento-de-snapshot.md) (restauração de seção)

## Contexto

O console tinha **duas gerações** de páginas se sobrepondo: quatro legadas (`macro.html` em
`/ui/`, `nova.html`, `detalhe.html` com 1.500 linhas e `index.html`, o console técnico) e dezesseis
seções com sidebar. Quatro seções eram **placeholder** (`esteira`, `modelos`, `incidentes`,
`configuracoes`) e apontavam "o conteúdo já existe, parcialmente, numa página legada" — o operador
precisava saber em qual geração cada coisa vivia. Pior: funções centrais só existiam nas legadas.

Inventário por rota de API exclusiva (o que mediu a sobreposição de verdade):

| Página legada | Só existia lá |
|---|---|
| `index.html` (console) | catálogo de executores (CRUD + sync), snapshots (lista/diff/restauração de seção), patches, conflitos, SLO + histórico + avaliar, worktrees + prune, `execution-timeline` (custo por card) |
| `detalhe.html` (sala de controle) | `next-step`, atribuição por etapa (`agents/{etapa}`), autopilot, `quality-gates/run`, spec (rodar/revisar/aprovar), `validation-checks/suggest`, `deploy/config`, `/v1/phases` |
| `macro.html` (kanban macro) | criar/arquivar/restaurar projeto, histórico do projeto, navegador de pastas (`fs/dirs`) |
| `nova.html` | pré-análise da pasta (`fs/analyze/stream`) |

Cada página também repetia `token()`, `api()`, `esc()` e, em seis delas, o polling do 202 —
cópias que **já divergiam** em como tratavam 403/409.

## Decisão

1. **Uma geração só.** As quatro páginas legadas foram removidas; suas rotas
   (`/ui/`, `/ui/nova`, `/ui/detalhe`, `/ui/console`) respondem `307` para a seção equivalente,
   preservando a query string (`?id=` continua abrindo a mesma demanda). Temporário de propósito:
   um `301` ficaria no cache do navegador mesmo depois de a rota sair.
2. **Nada de funcionalidade perdida** — cada item do inventário foi para uma seção:
   - **`/ui/esteira?id=`** é a sala de controle (o conteúdo de `detalhe.html`, agora dentro do
     shell com sidebar): esteira F1→F7 com o agente de cada etapa, próximo passo, pendências,
     painel "o que o agente está fazendo", discovery/spec/gate/implantação e autopilot. Sem `?id=`,
     mostra o seletor de demanda (mesmo padrão de `kanban`/`documentos`).
   - **`/ui/modelos`** é o catálogo de executores (ADR-0076), com os campos `streaming`,
     `permissao_escrita` e `candidato` em vez de flags digitadas no comando.
   - **`/ui/configuracoes`** reúne os ajustes: atalhos (modelos, agentes, regras de roteamento,
     contrato), **projetos** (criar/arquivar/restaurar, histórico e navegador de pastas, vindos do
     kanban macro) e o estado do runtime (`/health`, `/v1/me`).
   - **`/ui/incidentes`** lista incidentes de todas as demandas, com filtro de status e projeto,
     pela rota nova `GET /v1/incidents` (consulta no repositório, sem hidratar agregado — MEL-52);
     investigar/resolver continuam na aba da demanda, uma fonte só.
   - **Aba "Governança" de `/ui/demanda-detalhe`**: patches, conflitos (+resolver), snapshots
     (+diff +restaurar seção com dry-run, ADR-0061), orçamento de erro (+avaliar +histórico) e
     worktrees (+prune). A aba "Execuções" ganhou tempo/custo por card (`execution-timeline`).
   - **`/ui/demanda-nova`** ganhou a pré-análise da pasta do projeto (SSE, sem alterar arquivo).
3. **Um módulo de acesso à API:** `static/aso-api.js` (`ASOApi`) com `token`, `api`, `esc`,
   mensagens padronizadas de 401/403/404/409 e o polling do 202 da fila (ADR-0067) resolvido
   automaticamente. Todas as páginas passaram a usá-lo; `jobs.js` virou um shim que delega, para
   não haver duas implementações do mesmo polling.
4. **A sidebar não tem mais placeholder**, e toda página do console monta a mesma navegação — um
   teste varre os arquivos e falha se aparecer "ainda não foi implementada", se alguma página não
   montar a sidebar, ou se algum link interno apontar para uma rota legada.

### Alternativas descartadas

- **Manter as legadas e só implementar os placeholders:** era o estado atual, e ele obrigava o
  operador a saber em qual geração cada função vivia; os testes de HTML também passariam a cobrir
  duas cópias da mesma lógica.
- **Redirecionar sem migrar** (apontar `/ui/console` para a demanda e aceitar a perda): tiraria do
  runtime a única interface de patches, conflitos, snapshots, SLO e worktrees — governança visível
  é requisito, não conveniência.
- **Reescrever a sala de controle dentro de `demanda-detalhe`** (como uma 15ª aba): a sala de
  controle é uma página de **ação** com estado próprio (SSE, painel ao vivo, matriz de etapas), e
  empilhá-la numa aba de leitura misturaria dois modos de uso. `esteira` já era o nome da seção.
- **Manter `jobs.js` como implementação:** duas cópias do polling voltariam a divergir; o shim
  existe só enquanto algum consumidor externo o referenciar.

## Consequências

- O operador tem **uma** navegação: 16 seções, nenhuma placeholder, e as rotas antigas continuam
  funcionando por redirecionamento (marcador e link salvo não quebram).
- `detalhe.html`, `index.html`, `macro.html` e `nova.html` saíram do repositório (−3.800 linhas de
  HTML/JS, incluindo a duplicação dos helpers).
- Erros de governança ficaram legíveis em todas as telas: 403 vira "requer papel com permissão" e
  409 traz o `detail` da recusa (gate reprovado, estratégia pendente, versão concorrente).
- `GET /v1/incidents` é rota nova no contrato (cross-demanda, com filtros na consulta).
- O smoke do Docker agora segue os redirecionamentos e verifica as quatro seções que deixaram de
  ser placeholder.
- Risco assumido: os testes de HTML verificam o conteúdo servido, não o comportamento no
  navegador. A validação de sintaxe dos scripts inline (`node --check`) e o smoke cobrem o básico;
  interação continua sendo verificada à mão no Docker, como antes desta ADR.
