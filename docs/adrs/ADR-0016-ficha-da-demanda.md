# ADR-0016 — Ficha da demanda (triagem) alimentando o motor de decisão

- **Status:** ACCEPTED
- **Fase:** F5 (evolução pós-O5)
- **Data:** 2026-07-30
- **Relaciona-se com:** [ADR-0014](ADR-0014-agente-por-etapa-e-nomes-semanticos.md)
  (mecanismo de agente por etapa/`agent_assignments`, de onde vem a seleção do agente
  de triagem), [`fluxo.md`](../../fluxo.md) §1/§2 (requisito de origem)

## Contexto

Uma auditoria etapa a etapa da esteira-alvo descrita em `fluxo.md` (24 etapas) apontou
aderência de ~35–40%, concentrada no miolo (demanda → cards → execução em worktree →
CI → merge governado). As pontas — entrada/classificação da demanda (§1/§2) e o
encerramento documental/operacional (§3–§6, §19–§22) — são rótulo.

O achado de maior alavancagem: `OrchestrationService.create_orchestration` **já aceita**
o parâmetro `decision_input`, mas **nenhum caller o preenche**. Em vez disso:

```python
din = decision_input or DecisionInput(user_request=user_request, domains=["backend"])
```

O `MultiAgentDecisionEngine` — que classifica estratégia, risco, composição de equipe e
necessidade de aprovação humana — decide sempre sobre a mesma constante:
`domains=["backend"]`, `risk_level=LOW`, `impacts=[]`. Consequências observáveis:
toda orquestração vira `SINGLE_AGENT`; `requires_human_approval` nunca dispara;
`ReviewAgent` nunca entra na equipe; `card.priority` é sempre `MEDIUM` (o argumento
`priority=` sequer era passado na criação do card).

Este incremento **não constrói um motor de decisão novo — ele liga um motor
existente**, interpretando a demanda em texto livre antes de montá-la em
`DecisionInput`.

## Opções consideradas

1. **Formulário estruturado no front-end** (o operador preenche tipo/domínio/risco
   manualmente antes de criar a orquestração). Rejeitada: contraria o modo de operação
   do runtime — a demanda entra como texto livre e a IA interpreta; um formulário
   obrigatório empurraria trabalho de volta para o humano exatamente onde a automação
   tem mais alavancagem.

2. **`DemandBrief` só por agente (LLM/CLI), sem fallback.** Rejeitada: acopla a criação
   de toda orquestração à disponibilidade de um agente configurado. Contraria a regra 3
   do `CLAUDE.md` (nunca avance sem fallback determinístico) e o precedente já
   estabelecido pelo `NamingService` (ADR-0014): uma etapa auxiliar não pode ser ponto
   único de falha do caminho principal.

3. **Tabela filha `demand_briefs`.** Rejeitada pelo mesmo motivo que `agent_assignments`
   na ADR-0014: é um mapa pequeno, sempre lido junto da orquestração, nunca consultado
   isoladamente. Uma tabela filha entraria na dança de delete+reinsert do repositório e
   é onde vivem os bugs de ordem de INSERT que só aparecem no Postgres.

4. **`DemandBrief` com fallback heurístico determinístico + JSONB na orquestração +
   agente selecionável pelo mesmo mecanismo da ADR-0014.** Escolhida.

## Decisão

**(1) `TriageService` (`src/aso/control/triage.py`), espelhando `NamingService`.**
Mesma filosofia de fallback: **triar nunca pode impedir a criação de uma
orquestração.** Qualquer falha do agente (timeout, JSON inválido, executor fora do
catálogo, sandbox sem permissão, resposta sem campo utilizável) cai no caminho
heurístico determinístico (classificação por palavra-chave, sem I/O) e registra
`fallback_reason`. Sem nenhum sinal no texto, a heurística produz `dominios=["backend"]`
e `risco=LOW` — exatamente o comportamento anterior, o que garante que a mudança não
regride nenhuma orquestração hoje classificada como simples.

**(2) `DemandBrief` usa o vocabulário fechado do `MultiAgentDecisionEngine`.** Os campos
`dominios` e `impactos` são saneados contra `_DOMAIN_AGENT` e
`_SENSITIVE_IMPACTS`/`_APPROVAL_IMPACTS` de `decision_engine.py`: um rótulo fora desse
conjunto é **descartado**, nunca propagado — do contrário `_DOMAIN_AGENT.get(domain,
"BackendDevelopmentAgent")` montaria equipe errada silenciosamente.
`DemandBrief.to_decision_input()` deriva `parallelizable` e `needs_independent_review`
no runtime (não pergunta ao agente): são decisões de estratégia de execução, não fatos
sobre a demanda.

**(3) Agente de triagem selecionável como as demais etapas.** `TRIAGE_KEY = "triagem"`
entra em `_validate_assignment_key` ao lado de `NAMING_KEY`: sempre editável (não é
fase da esteira), pelos mesmos endpoints `PUT`/`DELETE /v1/orchestrations/{id}/agents/{key}`
e pela mesma matriz de configuração da UI (ADR-0014) — nenhum componente novo.

**(4) `demand_brief: dict[str, Any]` (JSONB) em `Orchestration`/`OrchestrationRow`.**
Mesmo raciocínio de `agent_assignments`: mapa pequeno, sempre lido junto da
orquestração, evita a dança de delete+reinsert de tabela filha. Migration
`40812903e932` acrescenta a coluna com `server_default='{}'` (linhas existentes não
quebram o `NOT NULL`).

**(5) A triagem roda antes de `create_orchestration`.** O `DecisionInput` que ela
produz é consumido dentro do próprio `create_orchestration` — não dá para inverter a
ordem. Como a orquestração ainda não existe nesse ponto, não há
`agent_assignments["triagem"]` a consultar: o agente de triagem na criação resolve por
`body.executor` explícito → default do catálogo → heurística (`None`). Depois de
criada, o `POST .../brief` (re-triagem) já pode olhar `agent_assignments["triagem"]`.

**(6) `card.priority` deriva do risco da ficha** via `prioridade_de(brief) ->
RiskLevel`, um helper único usado em `create_orchestration` e `populate_from_plan` — os
dois pontos onde cards nascem.

**(7) Perguntas em aberto não travam a esteira.** `DemandBrief.perguntas_abertas` vira
um `NextStepBlocker` com `severity=SEVERITY_HUMAN` — abaixo de `SEVERITY_BLOCKS` na
ordenação de `next_step.py`, então aparece com destaque no "Próximo passo" sem impedir
nenhum avanço. É a leitura literal do §1 do `fluxo.md`: o orquestrador *poderá* pedir
mais informação, não *deverá* parar.

**(8) Efeito visual, não automático, sobre o effort.** A complexidade da ficha sugere um
effort (`simples→low`, `intermediaria→medium`, `complexa→high`, `estrategica→high`) só
como rótulo informativo na tela de detalhe — o executor/effort efetivos continuam sendo
decisão do operador, resolvidos pela cadeia de precedência da ADR-0014.

## Consequências

**Positivas**
- O `MultiAgentDecisionEngine`, já bem construído, passa a decidir sobre sinal real:
  demandas multi-domínio/alto risco deixam de cair sempre em `SINGLE_AGENT`, e a revisão
  independente (`ReviewAgent`) entra automaticamente quando o risco pede.
- Impactos sensíveis (`deploy`, `secrets`, `database_reset`, `branch_main`) passam a
  abrir `HumanApproval` pendente na própria criação, não só depois.
- `card.priority` reflete o risco em vez de uma constante.
- Nenhum ponto único de falha novo: a garantia de fallback do `NamingService` se repete
  aqui, com o mesmo nível de cobertura de teste (cada exceção de `_perguntar` mapeada).

**Negativas / riscos aceitos**
- A heurística por palavra-chave é rasa comparada a um agente real; ela existe para
  nunca falhar, não para triar com profundidade — a triagem por agente continua sendo o
  caminho de qualidade.
- `demand_brief` em JSONB não é consultável por SQL relacional, mesma aceitação já feita
  para `agent_assignments` na ADR-0014.
- A ordem de resolução do agente de triagem na criação (explícito → default do catálogo
  → heurística) é ligeiramente diferente da do nomeador (que nunca usa o default do
  catálogo automaticamente); documentado em código porque não havia
  `agent_assignments` para consultar antes da orquestração existir.

**Emenda (2026-07-30, avaliação do Incremento B)** — dois pontos não previstos aqui:
- **CLI sem triagem.** `cli/main.py` chamava `create_orchestration` direto, sem passar
  por triagem — orquestrações nascidas pela CLI tinham `demand_brief` vazio e
  `priority=low` fixo (a mesma classe de bug que esta ADR resolveu para a API). Causa
  raiz: a sequência triagem→criação só existia em `app.py`.
- **Re-triagem sem re-plano.** `retriage_demand` atualizava a ficha, mas o
  `ExecutionPlan` calculado na criação nunca era recomputado — o operador respondia
  `perguntas_abertas`, ganhava uma ficha melhor e continuava com a mesma equipe.

Ambos resolvidos em [ADR-0017](ADR-0017-revisao-independente-de-codigo.md)
(`create_with_triage` como ponto único de entrada; `retriage_demand` recomputa o plano
enquanto nada saiu de `Ready`).
