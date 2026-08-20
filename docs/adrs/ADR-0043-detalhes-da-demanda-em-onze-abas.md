# ADR-0043 — Detalhes da demanda em 11 abas (Tela 04)

- **Status:** ACCEPTED
- **Fase:** F4 (evolução pós-O5)
- **Data:** 2026-08-07
- **Relaciona-se com:** [ADR-0036](ADR-0036-sidebar-e-mapa-de-paginas.md)
  (previa explicitamente que FID-10…FID-26 "absorveriam" o conteúdo das
  páginas legadas — este card é essa absorção, não uma exceção a ela),
  [ADR-0041](ADR-0041-detalhes-do-card-em-dez-abas.md) (mesmo padrão de
  página satélite com abas, mesmo componente `.tabs`/`.tab`),
  [ADR-0034](ADR-0034-design-system-wireframe.md) (`.progressbar`/`.tl`,
  ambos comentados como "wf §6"/"wf §8" desde a origem, nunca usados até
  agora), [`wiframe-fluxo.md`](../../wiframe-fluxo.md) §6 (requisito de
  origem — "Tela 04", seção 6, sem divergência de numeração)

## Contexto

`detalhe.html` é a "sala de controle" legada (rota `/ui/detalhe?id=`) —
esteira F1→F7, próximo passo, pendências, ao vivo via SSE. A ADR-0036
(FID-09) já a excluiu deliberadamente da sidebar por "misturar conteúdo de
várias seções ao mesmo tempo — não há uma seção ativa única e honesta", mas
registrou explicitamente que essa era uma inconsistência **temporária**: "as
páginas legadas continuam acessíveis até que os cards FID-10…FID-26
substituam seu conteúdo pela seção correspondente." `docs/mapa-paginas.md`
já marcava a linha "Demandas" com "detalhe DA DEMANDA com abas (FID-16)
ainda pendente" — a lacuna que este card fecha.

O wireframe §6 lista 11 campos de cabeçalho e 11 abas, mas **não especifica
a fórmula do percentual de progresso** nem distingue "agente" de "modelo" no
painel de responsáveis (mistura os dois no mesmo rótulo textual do exemplo
ilustrativo). Duas decisões foram confirmadas explicitamente com o usuário.

Investigação prévia confirmou, com evidência direta (não inferência): (1)
nenhum outro card FID-17…FID-27 depende de `detalhe.html` permanecer como
está; (2) o padrão já estabelecido para "uma tela nova de abas substitui uma
responsabilidade antes espalhada em `detalhe.html`" é **página satélite
nova + redirecionamento dos pontos de entrada**, não editar a página legada
no lugar — precedente direto do FID-14/ADR-0041 (`card-detalhe.html`
nasceu do mesmo jeito, e `demanda-estrutura.html` teve seu link de saída
redirecionado para lá).

## Decisão

**(1) Nova página satélite `/ui/demanda-detalhe?id=`**, mesmo padrão das
quatro já entregues: header+sidebar (`active: 'demandas'`), componente
`.tabs`/`.tab` (já usado no FID-14). `detalhe.html` **permanece intocada**
— continua sendo a "sala de controle" de ação (próximo passo, configurações,
esteira F1→F7 operável), acessível via "Abrir" em `demandas.html`. A Tela 04
é uma tela de **centralização de informação** (§6.1: "centralizar todas as
informações"), não um console de ação — mutações continuam vivendo nas
páginas onde já existem (`/ui/detalhe`, `/ui/console`).

**(2) Percentual de progresso = cards Done / total de cards da demanda**
(opção recomendada, aprovada) — calculado no cliente a partir de `GET
.../cards` (já teria que ser buscado para a aba Cards). Mesma lógica já
usada para o progresso da FASE atual (`next_step.py`, `cards_done/
cards_total`), só que somando TODOS os cards da orquestração em vez de só
os da fase corrente. Reaproveita o componente `.progressbar`/`.progress`
(`components.css`, comentado desde a origem como "wf §6.4", nunca
consumido até agora).

**(3) SSE mantido ao vivo** (opção recomendada, aprovada) — primeira página
satélite do projeto com `EventSource`. Reaproveita o mesmo endpoint que
`detalhe.html` já usa (`GET .../events/stream?token=`). Diferente de
`detalhe.html` (que recarrega a página inteira a cada evento), aqui cada
mensagem: (a) limpa o cache de abas já carregadas (`TAB_CACHE`), (b)
recarrega o núcleo (cabeçalho/progresso/responsáveis), (c) recarrega só a
aba **ativa**. Abas não visitadas não são buscadas até o clique — carregamento
tardio (lazy), não um `Promise.all` de ~17 endpoints no load.

**(4) Painel de responsáveis usa o dado real por etapa técnica** (F1-F7 +
`naming`/`triagem`/`revisao`, via `Orchestration.agent_assignments`), não os
4 papéis ilustrativos do exemplo do wireframe ("Orquestrador/Arquiteto/
Implementação/Review", que não correspondem a nenhuma chave real). Para
cada etapa atribuída, mostra `executor` (nome real), `effort` e o `model`
correspondente, resolvido cruzando o nome do executor com o catálogo (`GET
/v1/executors`) — o wireframe mistura "agente" e "modelo" num único rótulo;
aqui os dois aparecem como campos reais separados, já que ambos existem
como dado.

**(5) Cabeçalho: "Prioridade" e "Risco" seguem o mesmo campo único**
(`brief.risco`, rotulado "Prioridade / risco") — mesma convergência já
documentada nas ADR-0038/ADR-0039 (não existe prioridade de demanda separada
do risco no domínio hoje; repetir os dois rótulos apontando pro mesmo valor
seria redundância visual, não um segundo dado).

**(6) As 11 abas consomem 100% endpoints já existentes** — nenhum endpoint
novo foi criado para este card (única exceção entre os satélites com abas
até agora). Mapeamento: Visão geral (`/brief`), Discovery (`/discovery`),
Documentos (`/spec` + `/adrs`), Cards (`/cards`, link para
`/ui/demanda-estrutura` e `/ui/card-detalhe`), Execuções
(`/execution-metrics` + `/candidate-runs`), Testes (`/validation-checks` +
`/quality-gates`), Reviews (`/pulls`), Deploys (`/deploy` +
`/deploy/history`), Incidentes (`/incidents`), Histórico (`/timeline`,
paginado, `newest_first=true`), Métricas (`/metrics` + `/learning`, versão
**por orquestração**, não a global que alimenta o Dashboard/FID-10).
"Documentos" agrega Discovery+Spec+ADRs já existentes — a lista completa de
tipos de documento do wf §10 (Tela 08) não existe como entidade no runtime
hoje; é escopo do FID-19, não deste card.

**(7) `demandas.html`: "Visualizar histórico"/"Visualizar documentos" agora
apontam para `/ui/demanda-detalhe?id=...&aba=Histórico`/`...&aba=Documentos`**
(deep-link direto à aba certa, via novo suporte a `?aba=` na página nova).
"Abrir" continua indo para `/ui/detalhe?id=...` — é a única ação que de fato
pertence à sala de controle (próximo passo acionável), não à centralização
de informação.

## Consequências

**Positivas**
- Zero endpoint novo — todos os 17 endpoints consumidos já existiam, criados
  por cards anteriores (FID-01…FID-15) para outros fins.
- `detalhe.html` não regride nem muda de comportamento — zero risco à sala
  de controle em uso.
- `.progressbar` e `.tl`, comentados desde a origem como "wf §6"/"wf §8" e
  nunca consumidos, finalmente têm uso real.
- Carregamento tardio por aba evita uma janela de ~17 requisições
  simultâneas no load — só o núcleo (4 chamadas) é obrigatório de início.

**Negativas / riscos aceitos**
- "Linha do tempo" (marcos macro do wireframe, ex. "Demanda → Discovery →
  Documentação → Cards → Desenvolvimento") não tem representação visual
  própria — a aba "Histórico" mostra a lista cronológica completa de
  eventos (`EventLog`/`timeline`), não um breadcrumb de marcos agregados.
  Nenhum componente CSS pronto existe para essa segunda visualização;
  tratado como a mesma fonte de dado servindo um propósito só (log
  detalhado), não dois.
- Painel de responsáveis mostra até 10 etapas técnicas (F1-F7 + 3 papéis),
  não os 4 papéis ilustrativos do wireframe — divergência documentada, não
  escondida (ver decisão 4).
- SSE recarregando a aba ativa a cada evento pode refazer a mesma chamada
  repetidamente em uma execução com muitos eventos seguidos — aceitável no
  volume dev-scale do projeto; sem debounce nesta entrega.
