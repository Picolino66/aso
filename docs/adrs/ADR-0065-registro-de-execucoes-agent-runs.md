# ADR-0065 — Registro persistido de execuções de agente (`agent_runs`)

- **Status:** ACCEPTED
- **Fase:** F5/F7 (robustez — MEL-30, origem `feedback.md` §9)
- **Data:** 2026-09-15
- **Relaciona-se com:** [ADR-0015](ADR-0015-observabilidade-ao-vivo-da-execucao.md) (log ao vivo em
  memória), [ADR-0026](ADR-0026-custo-real-e-orcamento.md) (uso e custo do agente),
  [ADR-0051](ADR-0051-auditoria-com-filtros.md) (`execution_id` nos `CardEvent`),
  [ADR-0058](ADR-0058-claim-de-execucao-do-card.md) (claim por tentativa), regra inviolável 9

## Contexto

Não dava para reconstituir uma execução depois que ela acontecia: prompt e tarefa não eram
persistidos; `artifacts` (stdout, `raw`, diff) eram descartados; ferramentas chamadas só
existiam no `AgentLogBus` em memória; perguntas a agentes (triagem, discovery, spec, revisão,
nomeação) não deixavam registro; `request_id` só no log e `execution_id` só no `CardEvent`.

## Decisão

- Entidade `AgentRun` (`observability/agent_runs.py`) e tabela `agent_runs`, **append-only e fora
  da reescrita do agregado** (sem FK para `orchestrations`: sobrevive ao `save` por níveis e às
  perguntas feitas antes de a orquestração existir). Repositório próprio
  (`AgentRunRepository`: memória e `SqlAlchemyAgentRunRepository`, upsert por `id`).
- Campos: ids (run, orquestração, card, PR), tentativa, `kind` (`execute`|`ask`), `task_type`,
  papel, executor, modelo, effort, `prompt_version`, prompt renderizado, envelope, status,
  resumo, cauda do stdout, exit code, linhas de diff, branch, início/fim/duração, tokens, custo,
  origem do uso, erro, `decisao` do roteamento e `request_id`.
- **`run_id` = `execution_id` da tentativa**: já está no `CardEvent`; vai também em
  `AgentExecuted`, `FailureRouted`, `task["run_id"]` e na variável `ASO_RUN_ID` do subprocess
  do agente (execução e pergunta via CLI).
- Gravação em dois pontos: início (`running`, em `_execute_isolated`) e fim (resultado); a
  decisão do roteamento de falha é gravada no **mesmo** registro (`run_card`/`run_plan`).
- Perguntas: `control/agent_ask.py` registra `kind=ask` quando há `contexto_de_run` ativo
  (`ContextVar`); `OrchestrationService` abre esse contexto em triagem, discovery,
  especificação, revisões e nomeação.
- **Segredos:** `mascarar_segredos` substitui padrões de chave (`sk-…`, `gh*_…`, `AKIA…`,
  `Bearer …`, `api_key=…`) e valores de variáveis de ambiente com nome sensível antes de
  persistir prompt, envelope, stdout, resumo, erro e decisão.
- **Retenção:** `ASO_RUN_RETENCAO_DIAS` limpa prompt, stdout e envelope de registros mais antigos
  (metadados permanecem).
- API: `GET /v1/orchestrations/{id}/runs[?card_id=]` e `GET /v1/runs/{run_id}`. Falha ao
  gravar o registro nunca derruba a execução (log `agent_run_nao_registrado`).

## Consequências

- Uma execução pode ser reconstituída depois de reinícios: o que o agente recebeu, o que
  devolveu, quanto custou e o que o runtime decidiu.
- Corridas de candidatos (`race_card`) ainda não geram `AgentRun` (o `CandidateRunner` chama os
  providers diretamente) — lacuna registrada.
- Base da fila de execução (MEL-31) e do custo para todos os executores (MEL-41).
- Saída de agente em eventos/`block_reason` continua sem máscara (DISCOVERED-03, parcialmente
  resolvida: o que vai para `agent_runs` é mascarado).
- Console (aba de execuções no card) fica para a MEL-55.
