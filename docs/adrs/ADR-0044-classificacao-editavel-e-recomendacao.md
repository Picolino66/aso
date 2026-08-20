# ADR-0044 — Classificação editável e painel de recomendação (Telas 05 e 13)

- **Status:** ACCEPTED
- **Fase:** F4 (evolução pós-O5)
- **Data:** 2026-08-07
- **Relaciona-se com:** [ADR-0028](ADR-0028-regras-de-roteamento.md) (motor
  `avaliar_regras`/`RoutingRule`, reaproveitado aqui na direção oposta ao
  FID-15), [ADR-0042](ADR-0042-editor-visual-de-regras-de-roteamento.md)
  (`POST /v1/routing-rules/preview`, precedente direto de "preview
  só-leitura reaproveitando o motor real"), [ADR-0043](ADR-0043-detalhes-da-demanda-em-onze-abas.md)
  (`demanda-detalhe.html`, onde as duas abas novas deste card entram),
  [ADR-0038](ADR-0038-lista-de-demandas.md)/[ADR-0039](ADR-0039-cadastro-de-demanda-completo.md)
  (convergência "Prioridade" = `brief.risco`, reafirmada aqui),
  [`wiframe-fluxo.md`](../../wiframe-fluxo.md) §7 (Tela 05) e §15 (Tela 13)

## Contexto

O card cobre duas seções do wireframe que descrevem a MESMA demanda em foco
(numeração conferida sem divergência: "Tela 05" = seção 7, "Tela 13" =
seção 15). Nenhuma das duas tem indício de tela cheia ou modal separado no
wireframe — a própria descrição do card já diz "a classificação **aparece
na ficha**", e de fato já aparecia, só-leitura, no cabeçalho e no painel de
responsáveis de `demanda-detalhe.html` (FID-16/ADR-0043). Investigação
prévia confirmou, com evidência direta: nenhuma das 11 abas já existentes
se chama "Classificação"/"Recomendação", e o padrão de página satélite
nova (usado no FID-15 para regras de roteamento) só se justifica quando o
conteúdo é **global**, sem amarração a uma demanda — não é o caso aqui.

Investigação também encontrou lacunas reais frente ao pedido do wireframe:
- **Sem PATCH parcial de classificação** — só existia reescrita completa via
  nova triagem por agente (`retriage_demand`/`set_demand_brief`).
- **Sem endpoint de "preview" da recomendação** — a decisão de agente/
  effort/aprovação só acontecia embutida em `create_orchestration`/
  `_apply_routing_rule`, sem forma de consultar "o que seria decidido" sem
  criar/mutar nada.
- **Sem conceito de "confiança" numérico** no motor — nem na heurística
  (`MultiAgentDecisionEngine`) nem no roteamento (`avaliar_regras`).
- **Sem "custo estimado"/"tempo estimado" prospectivos** — só existe
  histórico observado (`observability/aprendizado.py::desempenho_por_executor`,
  por EXECUTOR — não por "modelo" abstrato).
- **"Prioridade" de demanda não existe como conceito separado do risco**
  (mesma convergência já documentada nas ADR-0038/0039) — o wireframe pede
  os dois como campos distintos.
- Nomes de modelo do wireframe ("Sonnet/Opus/Luna/Terra/Sol") são fictícios,
  sem correspondência no catálogo real (`ExecutorCatalog`).

Duas decisões foram confirmadas explicitamente com o usuário.

## Decisão

**(1) Duas abas novas em `demanda-detalhe.html`** (`ABAS`/`TAB_LOADERS`):
"Classificação" (logo após "Visão geral") e "Recomendação" (logo depois) —
não uma página satélite nova. Reaproveita 100% a infraestrutura já existente
(header/sidebar/`.tabs`, cache por aba, SSE) da ADR-0043.

**(2) Novo endpoint `PATCH /v1/orchestrations/{id}/classification`** —
edição pontual (só os campos informados mudam: `tipo`/`risco`/
`complexidade`/`impactos`/`dominios`), **diferente** de `retriage_demand`
(que reroda o agente de triagem inteiro). Auditoria via `EventLog` com
`before`/`after`, mesmo padrão estrutural de `update_execution_settings`
(`"ExecutionSettingsUpdated"`) — aqui `"ClassificationUpdated"`. Sem
restrição de `status` (diferente de execution-settings): editar
classificação não muta plano/cards/executor, então não há o mesmo risco de
inconsistência que justifica travar depois que a execução começou. Nenhum
replanejamento automático é disparado — editar a ficha aqui é
deliberadamente **desacoplado** de recomputar o plano (isso já existe, sob
outra ação, em `retriage_demand`/`_replan_if_untouched`); misturar os dois
tornaria uma edição de campo simples numa operação com efeitos colaterais
amplos e surpreendentes.

**(3) Novo endpoint `GET /v1/orchestrations/{id}/recommendation`** (opção
recomendada, aprovada) — método novo e independente
(`preview_recommendation`), sem tocar `create_orchestration`/
`_apply_routing_rule` (caminho crítico já em produção). Reaproveita as
funções puras existentes: `avaliar_regras()` + `contexto_de_demand_brief()`
(mesmo par do FID-15) primeiro; se nenhuma regra bate, cai no fallback
`MultiAgentDecisionEngine.decide()` + `sugerir_effort()` — exatamente a
mesma sequência que o caminho real de criação já segue, só que **somente
leitura**, sem persistir nada (testado explicitamente:
`test_preview_recommendation_nao_persiste_nada`). Pequena duplicação da
"cola" de orquestração entre os dois lugares é o custo aceito por zero
risco de regressão num caminho crítico só para servir uma tela de UI.

**(4) "Confiança" é categórica, derivada do sinal real, nunca um percentual**
(opção recomendada, aprovada): `"alta"` quando uma regra de roteamento
específica bateu (decisão determinística e explícita do operador),
`"baixa"` quando caiu no fallback heurístico genérico. Nenhum número
inventado — o wireframe mostra "92%" só como exemplo ilustrativo, sem
fórmula.

**(5) "Custo estimado"/"Tempo estimado" derivados do histórico GLOBAL de
desempenho, categorizados em terços (baixo/médio/alto) pela posição
relativa do executor recomendado entre todos os executores com histórico**
(`get_learning_report_global()`, `desempenho_por_executor[].custo_por_entrega`/
`.tempo_medio_ms`) — só quando uma regra recomenda um `modelo` explícito
(a heurística não recomenda modelo, então não há o que comparar).
Sem regra casando ou sem amostra do executor recomendado, os dois campos
voltam `null`/`None` — omitidos honestamente, nunca um palpite.

**(6) "Prioridade" continua sendo o mesmo campo que `risco`** — reafirmação
da convergência já documentada nas ADR-0038/0039, não uma decisão nova.

**(7) "Número estimado de cards" e "Quality gates necessários" (§7.3) só
aparecem quando vêm de dado real**: quality gates é `RoutingAction.
quality_gates` da regra que bateu (lista vazia no fallback heurístico, que
não tem esse conceito); "número estimado de cards" é omitido por completo —
não existe hoje nenhum mecanismo que estime isso antes da criação real dos
cards (mesmo espírito da ADR-0037, que omitiu "variação" por não ter dado
real).

**(8) "Override humano da recomendação registrado" reaproveita o mecanismo
que já existia**: a aba "Recomendação" ganha um botão "Aplicar como
override manual" (visível só quando há `modelo` recomendado E a
orquestração está em `created`/`blocked`) que chama o já-existente `PATCH
.../execution-settings` — o mesmo endpoint que já gravava
`"ExecutionSettingsUpdated"` com `before`/`after` desde antes deste card.
Nenhum mecanismo de override novo foi inventado.

## Consequências

**Positivas**
- Zero mudança no caminho crítico de criação/roteamento — `preview_recommendation`
  é aditivo e só-leitura.
- Auditoria de classificação segue o mesmo padrão estrutural já usado e
  testado em `update_execution_settings` — sem inventar um novo tipo de
  evento estruturalmente diferente.
- "Override registrado" reaproveita 100% um mecanismo pré-existente, em vez
  de duplicar auditoria.

**Negativas / riscos aceitos**
- `preview_recommendation` duplica, em glue-code (não em regra de negócio),
  a sequência "regra vence, senão heurística" que já existe dentro de
  `create_orchestration`/`_apply_routing_rule` — se o caminho real mudar de
  comportamento no futuro, o preview pode divergir silenciosamente até
  alguém lembrar de atualizar os dois lugares. Risco aceito conscientemente
  em troca de zero chance de regressão no caminho crítico.
- Sem regra casando, "Modelo/plataforma" fica sem recomendação nenhuma
  (`null`) — o painel comunica isso explicitamente ("nenhuma regra de
  roteamento bateu"), mas o operador não tem hoje uma heurística automática
  de modelo, só de agente/effort/aprovação — lacuna real do motor, não
  desta tela.
- Editar classificação não recomputa automaticamente o plano — um operador
  pode mudar `risco` e não perceber que o plano/effort já atribuído não
  reflete a nova classificação até rodar uma nova triagem manualmente.
  Documentado como escolha deliberada (decisão 2), não descoberto tarde.
