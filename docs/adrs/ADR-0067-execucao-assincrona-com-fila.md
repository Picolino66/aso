# ADR-0067 — Execução assíncrona: fila persistida de jobs e workers no processo

- **Status:** ACCEPTED
- **Fase:** F5 (robustez — MEL-31, origem `feedback.md` §1, §3, §13.3 problema 3)
- **Data:** 2026-09-15
- **Supersede (em parte):** a premissa de execução **dentro da requisição** do autopilot de
  [ADR-0007](ADR-0007-llm-provider-and-autopilot.md) (M3–M4: `run_phase`/aprovação rodando a
  fase no handler)
- **Relaciona-se com:** [ADR-0027](ADR-0027-sobrevivencia-a-crash.md) (sobrevivência a crash),
  [ADR-0058](ADR-0058-claim-de-execucao-do-card.md) (claim do card),
  [ADR-0065](ADR-0065-registro-de-execucoes-agent-runs.md) (`agent_runs`),
  [ADR-0066](ADR-0066-camada-de-aplicacao.md) (camada de aplicação)

## Contexto

`run_card`, `run_phase`, o autopilot, a corrida de candidatos, discovery, spec, revisão e o
docs-first rodavam dentro da requisição HTTP (handlers síncronos no threadpool). Com timeout de
1.800 s por tentativa e retries, uma requisição podia durar horas; aprovar um `fase_gate` rodava a
fase seguinte inteira dentro da requisição de aprovação; fechar a conexão não cancelava nada; e
reiniciar a API perdia o trabalho em andamento sem rastro.

## Decisão

1. **Fila persistida em tabela própria `jobs`** (`execution/jobs.py::Job`, migration
   `ffabdb4f1996`; em memória sem `ASO_DATABASE_URL`). Estados: `queued → running → done |
   failed | cancelled`, com `parametros`, `resultado` (JSON), `erro` + `erro_status` (o código
   HTTP que a rota síncrona daria), `ator`, `dono` (instância) e horários.
   *Por que não em `agent_runs`* (a task sugeria): um job gera **vários** `AgentRun` (tentativas,
   perguntas, cards de uma fase) e carrega parâmetros e resultado da operação; a ADR-0065 define
   `agent_runs` como registro append-only por invocação de agente. Misturar os dois tornaria o
   `GET /v1/runs/{id}` ambíguo.
2. **Workers no mesmo processo** (`FilaDeJobs`, `ASO_WORKERS`, padrão 2): threads que pegam o job
   mais antigo, marcam `running` e chamam o **mesmo método do serviço** que a rota síncrona chama —
   claim do card (ADR-0058), governança e registro de execução não mudam.
3. **Rotas 202:** com `ASO_EXECUCAO_ASSINCRONA=1`, `POST …/cards/{id}/run`, `…/race`, `…/run-plan`,
   `…/run-phase`, `…/autopilot`, `…/discovery/run`, `…/spec/run`, `…/spec/review`,
   `…/pulls/{pr}/review/run`, `…/analyze-folder` e `…/docs-heal` respondem `202 {job_id, status,
   operacao, acompanhar}`. Acompanhamento: `GET /v1/jobs/{id}`, `GET /v1/orchestrations/{id}/jobs`;
   cancelamento: `POST /v1/jobs/{id}/cancel` (operator). O console trata o 202 por polling
   (`static/jobs.js`) e o SSE existente avisa o fim do job.
4. **Aprovar `fase_gate` enfileira a próxima fase** (`WorkflowService.definir_agendador_de_fase`;
   evento `PhaseScheduled`) e a aprovação responde na hora. Pular fases vazias (`SKIPPED`)
   continua dentro do job que já está rodando.
5. **Cancelamento cooperativo:** o job corrente fica num `ContextVar` (copiado para as threads dos
   `ThreadPoolExecutor` de ondas e candidatos); o executor CLI registra o subprocess e o
   cancelamento o mata; `run_card` (antes de cada tentativa), `run_plan` (entre ondas) e
   `run_phase` (entre cards) consultam `verificar_cancelamento()`. `JobCancelado` deriva de
   `BaseException` para atravessar os `except Exception` por card; os `finally` liberam o claim.
6. **Boot:** o lifespan da API recupera a fila — `running` de outra instância vira `failed`
   ("interrompido por reinício do runtime"); `queued` volta a ser consumido.
7. **Transição por flag:** o padrão do código é síncrono (a suíte e a CLI seguem iguais; os dois
   caminhos têm teste). `docker-compose.yml` e `scripts/manager.sh` ligam a flag. O caminho
   síncrono das rotas sai numa MEL posterior, quando o console e os scripts só usarem o modo
   assíncrono.

### Alternativas descartadas

- **`run_phase` como coordenador de sub-jobs por card:** com pool pequeno, o coordenador ocupa um
  worker esperando cards que precisam de worker (deadlock). A fase roda os cards dentro do próprio
  job; paralelismo por onda com limite por orquestração é a MEL-50.
- **Broker externo / processo separado de workers:** fora de escopo (MEL-56); a fila em tabela já
  permite migrar o consumidor sem mudar o contrato HTTP.
- **Cancelar por `thread.interrupt`:** Python não interrompe threads; matar o subprocess e checar
  entre passos é o que dá garantia de parada sem corromper estado.

## Consequências

- Nenhuma rota de execução segura a requisição com a flag ligada (teste com provider lento:
  resposta < 1 s; conclusão por polling).
- Rotas de comando no host que não acionam agente (`ci/run`, `deploy/run`,
  `quality-gates/run`) continuam síncronas.
- Erro de governança (estratégia pendente, dependência, orçamento) aparece no job
  (`status=failed`, `erro_status=409`) em vez de na resposta imediata.
- Processo único continua sendo premissa: a reivindicação de job usa a condição da fila, não
  `SELECT … FOR UPDATE` (múltiplas réplicas: MEL-56).
