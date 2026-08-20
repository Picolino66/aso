# ADR-0042 — Editor visual de regras de roteamento (Tela 31)

- **Status:** ACCEPTED
- **Fase:** F4 (evolução pós-O5)
- **Data:** 2026-08-07
- **Relaciona-se com:** [ADR-0028](ADR-0028-regras-de-roteamento.md) (motor
  `avaliar_regras`/`RoutingRule`/`RoutingRuleService`, FID-01 — este card é
  puramente a camada de UI sobre esse motor, sem trabalho novo de backend
  além do estritamente necessário para a pré-visualização e a reordenação),
  [ADR-0035](ADR-0035-header-compartilhado.md) (precedente "dev-scale,
  varredura completa aceitável" de `header_summary`/`search`),
  [ADR-0041](ADR-0041-detalhes-do-card-em-dez-abas.md) (mesmo cuidado de
  ordenação de rotas Starlette, reaplicado aqui a `routing-rules/reorder`),
  [`wiframe-fluxo.md`](../../wiframe-fluxo.md) §33 (requisito de origem —
  "Tela 31" no título da tela, "33" no número da seção do documento)

## Contexto

O `wiframe-fluxo.md` §33 descreve o editor SE/ENTÃO (campo/operador/valor →
agente/modelo/effort/aprovação humana/quality gates) mas **não menciona em
nenhum lugar** pré-visualização de demandas nem ordem de precedência
editável — os dois últimos critérios de aceite do card são extrapolações do
board sobre a spec original, não citação literal do wireframe. Investigação
prévia confirmou que ambos são, ainda assim, bem suportados pelo modelo já
existente:

- `RoutingCondition`/`RoutingAction`/`RoutingRule` (`control/routing_rules.py`,
  ADR-0028) já implementam exatamente a DSL do wireframe — nenhum campo
  citado no §33.2 falta no modelo.
- `RoutingRule.precedencia: int` já é um campo explícito, gravável via `PUT`
  — só faltava UI para editá-lo.
- `avaliar_regras()` já é uma função pura, isolada, que recebe uma lista de
  regras + um contexto genérico — reutilizável para simular uma regra ainda
  não salva contra demandas já existentes, sem duplicar a lógica de match.
- "Escrita restrita a admin" **já estava implementado** desde o FID-01
  (`auth.py::required_role`, checagem por prefixo de path `/routing-rules`)
  — nenhum trabalho novo de RBAC foi necessário.
- Regras são configuração **global** do runtime (`RoutingRuleRow` sem FK
  para `orchestrations`), não por orquestração — reforça que esta é uma
  página satélite única, não parametrizada por `?id=`.

Duas decisões foram confirmadas explicitamente com o usuário entre opções
oferecidas.

## Decisão

**(1) Pré-visualização via novo endpoint `POST /v1/routing-rules/preview`**
(opção recomendada, aprovada). Recebe `condicoes`/`acao` de uma regra ainda
não salva, monta uma `RoutingRule` temporária (`nome="__preview__"`), valida
com `validar_regra` (mesma validação da escrita real) e roda
`avaliar_regras([regra], contexto)` contra o `demand_brief` de **cada
orquestração já existente no sistema** (`OrchestrationService.list_all()`,
sem filtro — leitura leve, sem hidratar bundle). Devolve as que bateriam
(`orchestration_id`, `user_request`, `tipo`, `risco`, `complexidade`).
Reaproveita 100% o motor do FID-01 — zero lógica de match duplicada em
JavaScript. Nova função pura `contexto_de_demand_brief(brief)` em
`routing_rules.py`, espelhando `contexto_de_decision_input` já existente
(mesmos 5 campos: `tipo`/`risco`/`complexidade`/`dominios`/`impactos`).
Varredura completa por chamada é aceita conscientemente — mesma filosofia
"dev-scale, não hyperscale" já documentada na ADR-0035 para
`header_summary`/`search`.

**(2) Reordenação por arrastar-e-soltar via novo endpoint `PUT
/v1/routing-rules/reorder`** (opção NÃO recomendada, escolhida explicitamente
pelo usuário sobre a alternativa mais simples — campo numérico de precedência
por linha). Recebe `{"ordem": [id, id, ...]}` e reatribui `precedencia`
sequencialmente (10, 20, 30…) na ordem recebida — passo de 10, não 1, para
deixar espaço a ajustes futuros sem precisar renumerar tudo de novo.
`RoutingRuleService.reorder()` novo, reaproveitando a mesma concorrência
otimista (`before_updated_at`) que `update()`/`delete()` já usam. Um id fora
da lista atual gera `404` — mesma checagem de `update`/`delete`. **Cuidado
de roteamento**: `PUT .../reorder` foi registrada ANTES de `PUT
.../{rule_id}` (rota já existente) — como ambas são de um segmento sob
`routing-rules/`, registrá-la depois faria `reorder` ser interceptado como
`rule_id="reorder"` (Starlette casa por ordem de registro; mesma classe de
bug evitada em `cards/{card_id}` na ADR-0041). Testado explicitamente
(`test_reorder_nao_e_interceptado_por_put_de_id`).

**(3) Nova página satélite `/ui/regras-roteamento`**, sem `?id=` (regras são
globais, não de uma demanda específica) — primeira página satélite do
projeto sem parâmetro de escopo. `active: 'configuracoes'` na sidebar (seção
mais próxima conceitualmente das 16 fixas — nenhuma delas cobre "roteamento"
hoje; `docs/mapa-paginas.md` já registrava essa lacuna). Linkada a partir de
`/ui/console` (que já hospeda a configuração de executores) até que FID-26
(`/ui/configuracoes`) exista — mesmo raciocínio de "acessada a partir de"
usado pelas satélites anteriores.

**(4) Gate de escrita também no frontend, além do 403 do backend.** A página
consulta `GET /v1/me`; quando `role !== 'admin'`, oculta "+ Nova regra",
"Editar"/"Excluir" por linha e desliga o `draggable` das linhas (sem alça de
arraste ativa) — evita o usuário tentar uma ação que o backend recusaria,
com uma nota explícita explicando o motivo. O 403 do backend continua sendo
a garantia real; a UI é só melhoria de UX sobre uma regra que já existia.

**(5) Campos "Agente"/"Effort" seguem texto livre; "Modelo" vira `<select>`
populado por `GET /v1/executors`.** Não existe um catálogo global de nomes
de agente (o registro é por bundle de orquestração) nem de valores de
effort — texto livre evita inventar um vocabulário fechado que o runtime não
tem. `RoutingAction.modelo` de fato sobrescreve `selected_executor` (não
"modelo" no sentido LLM) — `GET /v1/executors` já lista os nomes reais
usáveis nesse campo, dado real disponível sem endpoint novo.

## Consequências

**Positivas**
- Zero endpoint novo de CRUD — reaproveita `GET/POST/PUT/DELETE
  /v1/routing-rules` (FID-01) integralmente; só 2 endpoints novos, ambos
  aditivos (`preview`, `reorder`).
- Pré-visualização é dado real (demandas já existentes no sistema), nunca
  simulado/fabricado.
- RBAC não precisou de nenhuma mudança — já cobria `/routing-rules` por
  inteiro (incluindo os dois sub-paths novos, por prefixo de path).

**Negativas / riscos aceitos**
- `preview`, embora conceitualmente só leitura, herda a exigência de `admin`
  do middleware por casar em `/routing-rules` (guard atual é por
  path+método, não por endpoint individual) — um operator não-admin não
  consegue pré-visualizar antes de pedir a um admin para criar a regra.
  Aceito para não introduzir uma exceção pontual num middleware central que
  hoje é 100% previsível por padrão de path.
- Reordenação em lote (`reorder`) é mais complexa que a alternativa de campo
  numérico por linha — decisão explícita do usuário, não a recomendação.
- Varredura completa de `list_all()` a cada preview é O(n) no total de
  orquestrações do sistema — aceitável hoje (dev-scale), mesmo trade-off já
  aceito noutros lugares do projeto.
