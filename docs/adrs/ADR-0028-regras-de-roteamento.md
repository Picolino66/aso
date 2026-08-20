# ADR-0028 — Regras de roteamento (RoutingRule)

- **Status:** ACCEPTED
- **Fase:** F2 (decisão de estratégia/execução)
- **Data:** 2026-08-06
- **Relaciona-se com:** [ADR-0016](ADR-0016-ficha-da-demanda.md) (`DemandBrief`,
  fonte de `tipo`/`complexidade`), [ADR-0019](ADR-0019-roteamento-de-falha.md)
  (padrão de política pura e determinística, sem I/O), [ADR-0022](ADR-0022-bateria-de-validacoes-e-effort-automatico.md)
  (declina formalmente automatizar a escolha de agente/modelo por aprendizado —
  ver seção "Por que isto não contradiz a ADR-0022" abaixo), [`fluxo.md`](../../fluxo.md)
  §9, [`wiframe-fluxo.md`](../../wiframe-fluxo.md) §32.1/§33/§36.3/§36.4

## Contexto

`docs/plano-fidelidade-fluxo.md` aponta a maior lacuna funcional das duas specs:
o `MultiAgentDecisionEngine` (`control/decision_engine.py`) decide agente/estratégia
só por heurística compilada (`_DOMAIN_AGENT`, sinais de risco/domínio/impacto) e
`control/selecao.py` decide o effort por uma tabela fixa complexidade×risco. O
operador não tem como declarar uma política própria — o exemplo do wireframe §33.1:

> *"SE tipo=Segurança E risco for Alto ou Crítico E complexidade for Complexa ou
> Estratégica ENTÃO Utilizar Claude Opus, Effort Máximo, exigir revisão humana,
> exigir scan de vulnerabilidades, exigir code review por agente diferente, limitar
> a 3 tentativas automáticas."*

Duas lacunas de dado bloqueavam isto antes de qualquer motor de regras poder
existir: `DecisionInput` (entrada do decision engine) não carrega `tipo`/
`complexidade` — só `risk_level`/`domains`/`impacts` — e `DemandBrief.to_decision_input`
descartava os dois campos na tradução, mesmo já coletando-os desde a ADR-0016.

## Decisão

### 1. `control/routing_rules.py` — avaliador puro, sem I/O

Mesmo princípio de `control/failure.py`/`control/selecao.py`: dado o mesmo
conjunto de regras e o mesmo contexto, o resultado é sempre o mesmo. Nenhum LLM
decide roteamento — decisão de governança é regra declarada pelo operador, não
palpite.

**`RoutingRule`**: `nome`, `descricao`, `ativa`, `precedencia` (menor = avaliada
primeiro; empate mantém ordem de entrada — `sorted` é stable), `condicoes`
(lista de `RoutingCondition`, combinadas por **E**), `acao` (`RoutingAction`).

**`RoutingCondition`**: `campo` (vocabulário fechado —
`tipo`/`risco`/`complexidade`/`dominios`/`impactos`) `operador`
(`igual`/`diferente`/`em`/`contem`/`maior_ou_igual`) `valor`. `maior_ou_igual` só
vale para `risco`/`complexidade` (comparação ordinal contra uma tabela própria,
copiada dos vocabulários existentes pelo mesmo motivo que `triage.py` copia
`_DOMAIN_AGENT`: um valor fora do vocabulário nunca deve comparar como "menor que
tudo" silenciosamente).

**`RoutingAction`**: `agente`, `modelo`, `effort`, `aprovacao_humana`,
`quality_gates`, `limite_tentativas` — cada campo `None`/vazio significa "sem
opinião, não sobrescreve" (nunca um valor mágico que force um estado).

**`avaliar_regras(regras, contexto) -> RoutingRuleResult | None`**: primeira regra
**ativa**, em ordem de precedência, cujas condições batem todas. `None` = nenhuma
regra casou (nenhuma configurada, ou nenhuma condição bateu) → quem chama cai na
heurística existente, sem exceção, sem regressão. Regra sem condições nunca casa
(`_regra_bate` recusa explicitamente) — não é um catch-all silencioso, mesma
postura defensiva de `validar_regra` na escrita.

**`validar_regra`** recusa, na escrita (não na avaliação): nome vazio, regra sem
condição, campo/operador fora do vocabulário, `maior_ou_igual` num campo não
ordinal. Levanta `RoutingRuleError(ValueError)` — mesmo padrão de
`GateCommandError` (`execution/gate_validation.py`).

### 2. `DecisionInput` ganha `tipo`/`complexidade`

`control/models.py::DecisionInput` ganha dois campos `str = ""` (default vazio —
nenhuma orquestração anterior a esta ADR os preenchia, e o `MultiAgentDecisionEngine`
continua ignorando os dois: só `contexto_de_decision_input` os lê).
`DemandBrief.to_decision_input` (`control/triage.py`) passa a propagar
`tipo=self.tipo, complexidade=self.complexidade` — antes descartados na tradução.

### 3. Persistência: tabela própria, não `ContextBus`

`RoutingRule` é configuração do runtime, não estado de uma orquestração — mesmo
raciocínio do catálogo de projetos (ADR-0010): `ContextBus`/`ContextPatch` são
sempre escopados a `orchestration_id`, e `RoutingRule` precisa ser global e
sobreviver entre orquestrações. Diferente de `ExecutorCatalog` (arquivo JSON via
`ExecutorSettingsStore`), o critério de aceite deste card exige migration Alembic
— e o volume/necessidade de auditoria de regras justifica uma tabela real em vez
de um arquivo. Segue o precedente mais próximo: `ProjectRepository`/
`SqlAlchemyProjectRepository` (Ports & Adapters, ADR-0001/0006).

`persistence/ports.py::RoutingRuleRepository` (Protocol) +
`persistence/memory.py::InMemoryRoutingRuleRepository` (default, concorrência
otimista por `updated_at`) + `db/repository.py::SqlAlchemyRoutingRuleRepository`
(`ASO_DATABASE_URL` configurado, via `bootstrap.py`). `db/models.py::RoutingRuleRow`
— tabela `routing_rules`, sem FK para `orchestrations` (é global). `condicoes`/
`acao` em JSONB (`_JSONB`, sem `astext_type=Text()` — mitigação da armadilha de
import documentada no `CLAUDE.md`, mesmo padrão das migrations de 2026-07/08).

`control/routing_rule_service.py::RoutingRuleService` é o único ponto de I/O:
CRUD + `validar_regra` na escrita + concorrência otimista (`before_updated_at`).
Espelha `control/project_service.py` na estrutura.

### 4. Integração no `OrchestrationService` — fallback, nunca substituição

`OrchestrationService._apply_routing_rule(orchestration, din, plan, *,
executor_explicito, effort_explicito)`: avalia as regras ativas contra
`contexto_de_decision_input(din)` **depois** que `MultiAgentDecisionEngine.decide`
já produziu `plan` (a heurística sempre roda primeiro, nunca é pulada). Regra
casando:

- `acao.agente` sobrescreve `plan.agents[0].agent` (o agente primário/líder —
  não a equipe inteira: o próprio editor do wireframe §33.2 só expõe um campo
  "Agente" por regra, não uma lista, então este é o alcance correto do recurso,
  não uma limitação de implementação);
- `acao.aprovacao_humana` só **adiciona** exigência (`plan.requires_human_approval
  or acao.aprovacao_humana`) — uma regra nunca reduz uma aprovação que a
  heurística (ex.: risco crítico) já exigia;
- `acao.modelo`/`acao.effort` viram `orchestration.selected_executor`/
  `selected_effort`, **só quando o operador não escolheu explicitamente** na
  chamada (`executor_explicito`/`effort_explicito is None`) — a regra entra no
  degrau "padrão da orquestração" da cadeia de precedência já documentada na
  ADR-0022 (explícito → etapa → padrão da orquestração → sugestão automática →
  default do perfil), sem inventar um degrau novo nem tocar `_effective_effort`;
- `quality_gates`/`limite_tentativas` **não são aplicados** neste incremento —
  ficam no `RoutingRuleResult` persistido (ver §5) para a FID-04 (limite de
  tentativas por card, que depende deste card) e a FID-02 (pipeline de ambientes)
  consumirem. Aplicá-los agora exigiria campos novos em `KanbanCard` que já estão
  no escopo declarado de outro card — não duplicar o trabalho aqui.

Chamado em dois pontos: `create_orchestration` (logo após `planner.plan`, antes
de registrar a ADR de estratégia — cuja `rationale` passa a citar o nome da regra
quando uma casou) e `_replan_if_untouched` (retriagem, §2 herdado da ADR-0016),
com `executor_explicito`/`effort_explicito` vindos do que já está gravado na
orquestração — uma regra reaplicada no replan nunca sobrescreve uma escolha
humana anterior nem uma regra já aplicada.

### 5. `Orchestration.routing_rule_applied` — rastro, não novo mecanismo

Campo novo `dict[str, Any] | None = None` (`RoutingRuleResult.model_dump()`).
`None` = nenhuma regra casou (ou nenhuma existe) — comportamento de toda
orquestração anterior a este incremento, preservado byte a byte. Mesma migration
que cria `routing_rules` adiciona a coluna (`orchestrations.routing_rule_applied`,
JSONB nullable) — precedente de migration única com duas operações (ADR-0025:
`parent_id` + `qa_checks` na mesma migration).

### 6. API — RBAC crítico, mesmo nível de `/executors`

```
GET    /v1/routing-rules              # viewer
POST   /v1/routing-rules              # admin
PUT    /v1/routing-rules/{id}         # admin
DELETE /v1/routing-rules/{id}         # admin
```

`api/auth.py::required_role`: `method != "GET" and "/routing-rules" in path ->
"admin"`, ao lado da regra equivalente de `/executors` — escrever uma regra muda
a política de decisão de **toda** orquestração futura, mesmo nível crítico.

## Por que isto não contradiz a ADR-0022

A emenda final da ADR-0022 (2026-07-31) **declinou formalmente** automatizar a
escolha de agente/modelo: *"sem dado sobre desempenho por executor, a automação
seria adivinhação — reavaliar quando houver massa de várias demandas reais."*
Isto continua verdadeiro e não é revertido aqui: `RoutingRule` não é automação
por aprendizado/estatística sobre desempenho passado — é uma **política
declarada explicitamente pelo operador**, auditável, com precedência e
justificativa por nome de regra em cada `ContextPatch`/ADR de estratégia. São
dois mecanismos distintos: um extrapola dado histórico (declinado, continua
declinado), o outro executa uma decisão humana já tomada (isto). Quando
`desempenho_por_executor` (ADR-0025, `observability/aprendizado.py`) tiver massa
suficiente, ele pode alimentar a *criação* de regras sugeridas — não é este
incremento.

## Consequências

**Positivas**
- Fecha a maior lacuna funcional apontada em `docs/plano-fidelidade-fluxo.md`: o
  operador declara política SE/ENTÃO sem precisar alterar código.
- Avaliação determinística e testável isoladamente (`routing_rules.py` não tem
  I/O) — mesma garantia de auditabilidade de `control/failure.py`.
- Nenhuma orquestração existente regride: sem regra ativa configurada (ou
  nenhuma condição batendo), o comportamento é idêntico ao de antes desta ADR —
  provado por teste de regressão explícito.
- Abre a extensão natural para FID-02 (`quality_gates` por regra), FID-04
  (`limite_tentativas` por regra) e FID-15 (editor visual, tela 31) sem
  retrabalho no motor de avaliação.

**Negativas / riscos aceitos**
- `acao.agente` só sobrescreve o agente primário/líder do plano, não a equipe
  inteira em estratégias multiagente — aceito porque o próprio editor do
  wireframe (§33.2) só expõe um campo "Agente" por regra.
- `quality_gates`/`limite_tentativas` da ação ficam persistidos mas não
  aplicados a nenhum gate/card neste incremento — é o formato de dado que a
  FID-02/FID-04 (dependentes deste card) precisam consumir, não uma
  funcionalidade completa hoje.
- `RoutingRule` é global (não por-orquestração/por-projeto) — uma regra afeta
  todo o runtime. Escopo por projeto, se necessário, é extensão futura sem
  quebra de contrato (campo novo opcional na condição).
- Duas regras com a mesma `precedencia` resolvem por ordem de entrada, não por
  um critério de negócio — aceito por simplicidade; a UI (FID-15) pode expor a
  ordem explicitamente para o operador evitar ambiguidade.
