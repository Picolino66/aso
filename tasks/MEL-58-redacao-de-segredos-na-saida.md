# MEL-58 — Redação de segredos em toda saída de agente persistida

| Campo | Valor |
|---|---|
| Fase do roadmap | 1 — Clareza (governança) |
| Prioridade | P1 |
| Esforço | médio |
| Status | Backlog |
| Depende de | MEL-30 (`agent_runs` já mascarado) |
| Origem | DISCOVERED-03 (registrada na MEL-10), regra 9 de governança |
| Requer ADR | Sim, curta: redação como invariante do estado governado |

## Problema

A regra 9 diz que **secrets só existem em variável de ambiente, nunca no repo** — mas nada impede
que a *saída do agente* carregue o valor de um segredo para dentro do estado governado. A MEL-30
fechou apenas `agent_runs` (`mascarar_segredos` em prompt, envelope, `saida_resumo`, `stdout_cauda`)
e a MEL-31 fechou o resultado do job. Continuam **sem redação**:

- `EventLog` — `payload` de `AgentExecuted`, `AgentFailed`, `FailureRouted`, `CIExecuted` etc.
  carrega mensagem de erro e trechos de saída do agente, e o log é persistido e servido em
  `GET …/timeline`, `/audit` e no SSE;
- `KanbanCard.block_reason` e o ring `failures[]` (`mensagem`, `saida`, `comando`) — persistidos e
  exibidos no console;
- `AgentLogBus` — as linhas ao vivo do CLI, servidas em `GET …/agent-log`.

Um agente que imprima `echo $ASO_LLM_API_KEY` (ou qualquer log que inclua um token) grava o segredo
no banco e o expõe na API. Evidência: `mascarar_segredos` só é chamado em `agent_runs.py` e em
`api/execucao_assincrona.py`.

## Mudança proposta

1. Mover a redação para `shared/segredos.py` (a camada que `events`, `kanban` e `observability`
   podem importar), mantendo `observability/agent_runs.py` reexportando para não quebrar quem usa.
2. Aplicar no **ponto de entrada do estado governado**, não em cada chamador:
   `EventLog.append`, `AgentLogBus._append`, `FailureRecord` e o motivo de bloqueio/movimentação do
   card.
3. Teste negativo de governança: agente que imprime um segredo real (variável de ambiente com nome
   sensível) não deixa o valor em evento, card, log ao vivo, `agent_runs` nem em resposta da API.

## Critérios de aceite

- [ ] Nenhum valor de variável de ambiente com nome sensível aparece em evento, card, log ao vivo ou
      resposta da API depois de uma execução que o imprimiu.
- [ ] A redação é aplicada no ponto de entrada (um teste falha se um caminho novo escrever sem ela).
- [ ] Padrões conhecidos (`sk-…`, `ghp_…`, `AKIA…`, `Bearer …`, `api_key=…`) continuam cobertos.
- [ ] Nenhuma mudança de comportamento além da redação (suíte verde).
