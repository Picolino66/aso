# MEL-30 — Registro persistido de execuções (`agent_runs`) e IDs propagados

| Campo | Valor |
|---|---|
| Fase do roadmap | 3 — Robustez |
| Prioridade | P1 |
| Esforço | médio |
| Status | Backlog |
| Depende de | — (fica melhor após MEL-14) |
| Origem | [feedback.md](../feedback.md) §9 |
| Requer ADR | Sim: modelo de registro de execução de agente (referencia ADR-0015, ADR-0026, ADR-0051) |

## Problema

Não é possível reconstituir uma execução depois que ela acontece:

- o prompt (renderizado pelo wrapper ou pelo `PromptBuilder`) e a tarefa enviada não são persistidos;
- `AgentOutput.artifacts` (`stdout[-4000:]`, `raw` do LLM, diff) não é persistido;
- ferramentas chamadas só aparecem no `AgentLogBus`, em memória, perdidas no reinício;
- as perguntas de `perguntar_ao_agente` (triagem, discovery, spec, revisão, nomeação) não deixam registro próprio;
- `request_id` só existe nos logs do structlog; `execution_id` só nos `CardEvent`;
- decisões (roteamento de falha, effort sugerido, regra aplicada) estão espalhadas em eventos.

## Mudança proposta

1. Entidade `AgentRun` + tabela `agent_runs` (append-only, fora da reescrita do agregado):
   `id` (run_id), `orchestration_id`, `card_id`, `pr_id`, `attempt`, `kind` (execute/ask),
   `task_type`, papel, executor, modelo, effort, `prompt_version`, `prompt` (texto),
   `envelope` (JSON), `saida_resumo`, `stdout_cauda`, `exit_code`, `diff_lines`, `branch`,
   `inicio`, `fim`, `duracao_ms`, tokens (entrada/saída/cache), `custo_usd`, `uso_origem`,
   `erro`, `decisao` (JSON: ação do roteamento, motivo), `request_id`.
2. Repositório próprio (`AgentRunRepository`) com adapter em memória e SQLAlchemy.
3. Gravação em dois pontos: início (status `running`) e fim (resultado) — serve também de
   base para a fila de MEL-31.
4. Propagação de IDs: `request_id` da requisição → `run_id` → payload de `AgentExecuted`,
   `FailureRouted`, `CardEvent` e variável `ASO_RUN_ID` no ambiente do subprocess.
5. Endpoints `GET /v1/orchestrations/{id}/runs` e `GET /v1/runs/{run_id}`; aba no detalhe do card.
6. Retenção configurável do texto do prompt/stdout (`ASO_RUN_RETENCAO_DIAS`), mantendo os metadados.
7. Nunca gravar variáveis de ambiente nem chaves; filtrar padrões de segredo do stdout.

## Critérios de aceite

- [ ] Toda execução de card e toda pergunta a agente geram um `AgentRun` com prompt, envelope, duração e resultado.
- [ ] Uma falha roteada tem a decisão registrada no mesmo `AgentRun`.
- [ ] `run_id` aparece no `CardEvent` e no ambiente do processo do agente.
- [ ] Reiniciar a API não perde o registro.
- [ ] Teste garante que um valor com formato de chave (`sk-…`) não é persistido.
- [ ] Migration validada no Postgres.

## Testes obrigatórios

- Unit do repositório (memória e SQLite).
- Integração: `run_card` com CLI fake gera registro completo; pergunta de triagem gera registro `ask`.
- Unit do filtro de segredos.

## Arquivos prováveis

- `src/aso/agents/models.py` ou `src/aso/observability/agent_runs.py` (novo)
- `src/aso/persistence/ports.py`, `persistence/memory.py`, `db/models.py`, `db/repository.py`, `migrations/versions/`
- `src/aso/control/orchestration_service.py` (`_execute_isolated`, `_route_failure`), `src/aso/control/agent_ask.py`
- `src/aso/execution/cli_provider.py`, `src/aso/api/app.py`, console
