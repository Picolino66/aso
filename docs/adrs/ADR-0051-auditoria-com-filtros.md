# ADR-0051 — Auditoria cross-demanda com filtros (Tela 28)

- **Status:** ACCEPTED
- **Fase:** F4 (evolução pós-O5)
- **Data:** 2026-08-09
- **Relaciona-se com:** [ADR-0019](ADR-0019-roteamento-de-falha.md) (`CardEvent`,
  motivo/resultado/evidências/próxima ação por movimentação — a base que este
  card estende), [ADR-0038](ADR-0038-lista-de-demandas.md) (`list_orchestrations`,
  precedente direto do padrão de query SQL filtrada e paginada reaproveitado
  aqui), [ADR-0037](ADR-0037-dashboard-operacional.md) (`recent_events`, único
  precedente de query cross-orquestração antes desta ADR),
  [`wiframe-fluxo.md`](../../wiframe-fluxo.md) §30 (Tela 28)

## Contexto

Numeração conferida sem divergência (§30 = Tela 28). Investigação prévia (via
subagente Explore) encontrou que "a aba audit existe sem filtros" (texto do
card) descreve `index.html` (console legado, `renderAudit`) com precisão: só
mostra contadores agregados e uma tabela de patches filtrável por status —
zero filtro sobre os 14 campos do wf §30.2, zero registro individual visível.

A investigação também encontrou que este card é bem maior do que "adicionar
filtros a uma consulta existente": dois armazenamentos duráveis e
append-only já existem (`EventLog`/`EventRow` e `CardEvent`/`CardEventRow`),
mas **nenhum dos dois tem consulta cross-orquestração filtrável** hoje —
`timeline`/`svc.audit` são por-orquestração; `/v1/activity` é a única query
global, e é um "peek" plano de 20-100 linhas sem filtro nenhum. Pior: 5 dos
14 campos do wireframe (Projeto, Modelo, Effort, Etapa-como-Fase,
Identificador da execução) não tinham fonte durável nenhuma — os únicos
lugares onde `modelo`/`effort`/`fase` existem no código são os RINGS
limitados (`card.tentativas`, capado em 10; `card.failures`, capado em 5),
que violam ativamente o critério de aceite "Registro nunca sobrescrito" se
reaproveitados como fonte.

Duas decisões foram confirmadas com o usuário.

## Decisão

**(1) Estender `CardEvent`/`CardEventRow` de verdade** (opção recomendada,
aprovada) — `CardEvent` já é append-only e nunca truncado (ao contrário dos
rings), então ganhou 4 campos novos, opcionais: `model`, `effort`, `phase`
(a fase F1-F7 da esteira, distinta de `from_status`/`to_status`, que são
COLUNA do Kanban) e `execution_id`. Preenchidos **daqui pra frente**, nos
pontos de escrita já existentes que têm essa informação à mão
(`_apply_execution`/`_route_failure`, chamados de `run_card`/`run_plan`) —
eventos antigos e movimentação manual/automação de coluna ficam
honestamente `None` nesses 4 campos, nunca fabricados retroativamente.
`execution_id` é gerado (`gen_id("exec")`) uma vez por tentativa de execução
do agente (`run_card`'s laço de retry, ou por job do wave de `run_plan`) e
propagado a todo `CardEvent` que nasce daquela mesma execução — validado
manualmente: os eventos "AgentStarted"→"TestsPassed" de uma execução real
carregam o MESMO `execution_id`.

**(2) Nova query SQL real e paginada, não o padrão N+1 de `/v1/approvals`**
(opção recomendada, aprovada) — `SqlAlchemyOrchestrationRepository.audit_page`
segue o mesmo desenho de `list_orchestrations` (ADR-0038): filtros viram
`WHERE` sobre colunas reais/indexadas (`created_at`, `actor`, `phase` via
`__table_args__` novo em `CardEventRow`), com `JOIN` em `OrchestrationRow`
para "Projeto"/"Demanda" e um segundo lookup em lote (`IN`) para os títulos
de card — nunca N+1 por linha. `list_all_approvals`
(hidrata toda orquestração do sistema em Python) foi explicitamente
rejeitado como padrão aqui: auditoria cresce sem limite (é o próprio ponto
de "nunca sobrescrito"), então a versão que escala em SQL foi a escolha
certa, mesmo custando mais código novo. Implementado nos dois adapters
(`SqlAlchemyOrchestrationRepository` e `InMemoryOrchestrationRepository`,
usado em testes/dev), mantendo o contrato `OrchestrationRepository`
(`persistence/ports.py`) simétrico.

**(3) `CardEvent` como fonte primária, `EventLog` não usado.** Dos 14 campos
do wf §30.2, 9 já mapeavam diretamente para `CardEvent` (Data, Card, Ação,
Motivo, Resultado, Evidências, Próxima ação, Agente, Demanda via
`orchestration_id`); os 4 novos cobrem os restantes exceto "Projeto"
(resolvido via `JOIN`). Nenhum campo do wireframe foi fabricado: "Resultado"
continua texto livre (não um enum limpo como o mock do wireframe sugere —
mesma disciplina de não forçar vocabulário que o domínio não tem).

**(4) Exportação em CSV, não markdown.** Primeiro export CSV do projeto
(o único precedente, `closure/export` da ADR-0050, é markdown — adequado a
um relatório narrativo, não a uma tabela de auditoria). CSV é o formato
natural para revisão em planilha, que é o uso esperado de um export de
auditoria. Mesmos 14 campos, mesma ordem do wf §30.2, filtros idênticos ao
`GET /v1/audit`. Teto defensivo de 5000 linhas (`_AUDIT_EXPORT_LIMITE`) —
auditoria cresce sem limite; exportar milhões de linhas sem teto arriscaria
esgotar memória. Documentado explicitamente no código, não escondido.

**(5) `/ui/auditoria` deixou de ser placeholder** — página única (não
picker+drilldown como `/ui/execucoes`/`/ui/implantacoes`, já que a auditoria
É naturalmente cross-demanda) com os 6 filtros do wf §30.3 (Data de/até,
Projeto, Demanda, Agente, Etapa, Resultado), lista paginada e link de
exportação que carrega os MESMOS filtros aplicados. Projeto/Demanda usam
`<select>` populado a partir de `/v1/projects`/`/v1/orchestrations` reais
(não texto livre) — Etapa usa os 7 valores fixos de `Phase` (F1-F7).

## Consequências

**Positivas**
- `audit_page` escala em SQL real (índices em `created_at`/`actor`/`phase`),
  não em memória — segue o precedente correto (`list_orchestrations`) para
  uma tabela que só cresce.
- `execution_id` compartilhado entre os eventos de uma mesma execução é um
  fato novo e real, útil além da auditoria (ex.: agrupar toda a atividade de
  uma tentativa específica).
- Nenhum mecanismo paralelo aos rings (`tentativas`/`failures`) foi criado —
  os 4 campos novos vivem no MESMO `CardEvent` que já era a fonte de
  motivo/resultado/evidências, sem duplicar conceito.

**Negativas / riscos aceitos**
- Eventos gravados antes desta ADR (e toda movimentação manual/automação de
  coluna, mesmo depois) ficam com `model`/`effort`/`phase`/`execution_id`
  em branco — auditoria histórica é honestamente incompleta, não
  retroativamente inventada.
- "Resultado" continua texto livre — o filtro correspondente é `ILIKE`
  substring, não uma seleção de valores fixos como o mock do wireframe
  sugere.
- Export tem teto de 5000 linhas — filtros mais estreitos são necessários
  para recortes maiores que isso.
