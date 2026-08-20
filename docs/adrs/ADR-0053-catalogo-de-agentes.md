# ADR-0053 — Catálogo de agentes como fonte de verdade de permissões (Tela 30)

- **Status:** ACCEPTED
- **Fase:** F4 (evolução pós-O5)
- **Data:** 2026-08-09
- **Relaciona-se com:** [ADR-0028](ADR-0028-regras-de-roteamento.md)
  (`RoutingRuleRepository`/`RoutingRuleService`/`SqlAlchemyRoutingRuleRepository`/
  `InMemoryRoutingRuleRepository`, template exato replicado para
  `AgentDefinitionRepository`/`AgentCatalogService`), regra de governança #2 do
  [CLAUDE.md](../../CLAUDE.md) (deny-by-default nas permissões — diretamente
  afetada por esta ADR), [`fluxo.md`](../../fluxo.md) princípio central
  (rastreabilidade e permissões reais, nunca simuladas),
  [`wiframe-fluxo.md`](../../wiframe-fluxo.md) §32 (Tela 30)

## Contexto

Numeração conferida sem divergência (§32 = Tela 30, um único card, FID-26).
Investigação prévia encontrou **duas estruturas pré-existentes e distintas**
que a Tela 30 poderia ter confundido:

1. `AgentSpec`/`AgentRegistry` (`agents/models.py`/`registry.py`) — 16 papéis
   hardcoded em `_DEFAULT_AGENTS`, cujo `permission_map()` alimenta
   `PermissionPolicy` no `ContextBus`. **Este é o mecanismo real de
   deny-by-default** (regra #2 do CLAUDE.md) — hoje travado no código-fonte,
   sem nenhuma superfície administrativa.
2. `ExecutorCatalog`/`ExecutorProfile` (`execution/catalog.py`) — catálogo de
   *modelos/executores* já persistente, um conceito totalmente diferente
   (qual modelo roda, não o que um papel pode escrever).

A Tela 30 pede um catálogo de "agentes" com 13 campos (nome, tipo, função,
plataforma, papel, modelos permitidos, efforts permitidos, ferramentas,
permissões, projetos, categorias de tarefa, limite de custo, limite de
tentativas, exige supervisão) e 14 agentes de exemplo. Nenhuma dessas duas
estruturas cobria isso: `AgentRegistry` não é persistente nem editável em
runtime; `ExecutorCatalog` não modela papel/permissão nenhum.

Duas decisões foram confirmadas com o usuário — a primeira delas com
consequência de segurança direta, por isso levada explicitamente à escolha
do usuário em vez de assumida.

## Decisão

**(1) O catálogo novo é a FONTE DE VERDADE das permissões reais** (opção
**não recomendada**, escolhida deliberadamente pelo usuário sobre "espelho
somente leitura"). `AgentRegistry.seed_from_catalog(definicoes)` substitui
`seed_defaults()` nos dois pontos de construção do registry
(`create_orchestration` e `_hydrate`): primeiro semeia a base seed_defaults()
segura, depois — para cada `AgentDefinition` ativa com `role` preenchido e
correspondente a um papel real — sobrescreve `allowed_tools`/`context_sections`
daquele papel com `ferramentas`/`permissoes` da definição. Ou seja: editar uma
definição vinculada a um `role` real **muda de fato** o que aquele agente pode
escrever via `ContextBus` na próxima orquestração criada/hidratada.

Isso torna a Tela 30 uma superfície administrativa de segurança real, não um
mock. Três salvaguardas foram construídas para tornar isso seguro:

- **Baseline sempre semeada primeiro**: `seed_from_catalog([])` (catálogo
  vazio) produz `permission_map()` byte-idêntico a `seed_defaults()` sozinho —
  um catálogo vazio ou mal configurado nunca produz um agente com zero
  permissões.
- **Seed dos 14 exemplos é não-destrutivo**: os `ferramentas`/`permissoes`
  dos 11 exemplos com `role` real foram copiados VERBATIM dos valores
  hardcoded em `_DEFAULT_AGENTS` — confirmado por comparação direta
  (`pos_seed == antes`) que o `permission_map()` resultante do primeiro boot
  é idêntico ao baseline pré-ADR.
- **Unicidade de `role` entre definições ativas**: `AgentCatalogService`
  recusa (`AgentDefinitionError`, HTTP 400) criar ou ativar uma segunda
  definição para um `role` já ocupado por outra definição ativa. Sem isso, a
  ordem de iteração alfabética por `nome` em `seed_from_catalog` decidiria
  "a última values ganha" silenciosamente — um bug real encontrado ao vivo
  durante a implementação (duas definições para `BackendDevelopmentAgent`
  produziram uma sobrescrita silenciosa das ferramentas). Desativar uma
  definição libera o `role` para outra.
- **`role` validado contra a lista real do `AgentRegistry`** — nunca aceito
  um papel inventado; `_ROLES_VALIDOS` é derivado de uma instância fresca de
  `AgentRegistry().seed_defaults()`, não de uma lista duplicada à mão (uma
  primeira tentativa hardcoded esqueceu `RequirementsAgent` e quebrou em
  runtime — corrigido eliminando a duplicação estrutural, não só o sintoma).
- **Escrita exige papel `admin`** — `auth.py`: qualquer método != GET em
  `/agent-definitions` exige admin, mesmo nível crítico das rotas de
  aprovação/merge (regra #4 do CLAUDE.md), documentado no código como "nível
  crítico máximo" por controlar permissão real do ContextBus.

**(2) 14 exemplos do wireframe mapeados para papéis reais onde existe
contraparte** (opção recomendada, aprovada) — **11 de 14** têm `role`
vinculado a um `AgentSpec` real do `AgentRegistry` (Orquestrador, Arquiteto,
Analista de requisitos, Desenvolvedor backend, Desenvolvedor frontend,
Especialista em banco, Especialista em infraestrutura, QA, Code reviewer,
Segurança, Documentação). **3 ficam sem `role`, honestamente**: Discovery
técnico, Deploy e Incidentes — nenhum papel dedicado existe hoje no
`AgentRegistry` para esses três (Deploy é hoje coberto de fato por
`DevOpsAgent`/"Especialista em infraestrutura", documentado no `funcao` do
exemplo em vez de fingir um papel próprio). Nenhum `role` foi fabricado só
para preencher a lista de 14.

**(3) Limite de custo e de tentativas por agente é um TERCEIRO freio
independente**, novo, aditivo — `_recusar_se_limite_do_agente_estourado`
(chamado em `run_card` logo após a checagem de `card.pausado` já existente)
recusa a execução se `card.tentativa_atual >= definicao.limite_tentativas`
ou se o custo acumulado **filtrado por `card.assignee == role`**
(`_gasto_usd_por_agente`) atinge `definicao.limite_custo_usd`. Isso não
modifica nem substitui os dois freios já existentes: orçamento por
orquestração (ADR-0026, `orcamento_usd`) e limite de tentativas por card
(ADR-0031, `max_tentativas`) — os três operam em paralelo, em escopos
diferentes (orquestração / card / agente).

**(4) `AgentDefinitionRepository`/`AgentCatalogService` seguem o template
exato de `RoutingRuleRepository`/`RoutingRuleService`** (ADR-0028) —
`SqlAlchemyAgentDefinitionRepository`/`InMemoryAgentDefinitionRepository`
com a mesma concorrência otimista (`before_updated_at`), mesma tabela global
não escopada por `orchestration_id` (`agent_definitions`, precedente
`routing_rules`), mesma disciplina de `_verificar_role_unico` análoga a
validações de unicidade já usadas alhures.

## Consequências

**Positivas**
- A Tela 30 deixa de ser decorativa: é a primeira superfície administrativa
  real sobre o mecanismo de deny-by-default do `ContextBus` — antes só
  editável no código-fonte.
- Segurança verificada, não assumida: não-destrutividade do primeiro boot
  confirmada por comparação direta de `permission_map()`, não só por
  inspeção de código.
- Um bug real de concorrência de `role` (last-write-wins silencioso) foi
  encontrado e corrigido ANTES de chegar a produção, graças à disciplina de
  escrever o teste de verificação de permissão real
  (`test_definicao_muda_permissao_real_via_bundle`) em vez de só testar CRUD
  superficial.
- Nenhum papel foi fabricado: 3 dos 14 exemplos do wireframe permanecem sem
  `role`, com a lacuna documentada no próprio campo `funcao` em vez de
  escondida.

**Negativas / riscos aceitos**
- O catálogo agora é um mecanismo de segurança editável em runtime por
  `admin` — um erro operacional (ex.: um admin removendo `ferramentas`
  críticas de um papel em produção) tem efeito real na próxima orquestração
  criada/hidratada. Mitigado por exigir papel `admin` e por não afetar
  orquestrações já em memória (`AgentRegistry` é reconstruído por
  orquestração, não global).
- `role` só pode ser reaproveitado por padrão (1 definição ativa por role) —
  operadores que queiram "esconder temporariamente" um agente precisam
  desativá-lo explicitamente (`ativo: false`) em vez de simplesmente criar
  outro com o mesmo papel.
- 3 papéis do wireframe (Discovery técnico, Deploy, Incidentes) continuam
  sem contraparte real no `AgentRegistry` — a Tela 30 não tenta disfarçar
  essa lacuna; corrigir isso exigiria adicionar novos `AgentSpec`s ao
  registry, fora do escopo deste card.
