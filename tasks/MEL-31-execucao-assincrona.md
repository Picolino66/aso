# MEL-31 — Execução assíncrona com fila e workers

| Campo | Valor |
|---|---|
| Fase do roadmap | 3 — Robustez |
| Prioridade | P1 |
| Esforço | alto |
| Status | Backlog |
| Depende de | MEL-13, MEL-30 |
| Origem | [feedback.md](../feedback.md) §1 (retry), §3 (tolerância a falhas), §13.3 problema 3 |
| Requer ADR | **Sim**: modelo de execução assíncrona (supersede a premissa de execução síncrona de ADR-0007/M3–M4; referencia ADR-0027) |

## Problema

- `run_card`, `run_phase`, `start_autopilot` e `race_card` rodam dentro da requisição HTTP
  (handlers síncronos em threadpool). Com timeout de 1.800 s por tentativa e retries
  aninhados, uma requisição pode durar horas [H].
- `decide_approval` de uma `fase_gate` chama `_advance_after_phase_gate` → `run_phase` da
  próxima fase **dentro da requisição de aprovação** ([:2847](../src/aso/control/orchestration_service.py#L2847)).
- Cliente que fecha a conexão não cancela nada; reinício da API perde o trabalho em andamento.

## Mudança proposta

1. **Fila persistida** usando `agent_runs` (MEL-30) com status `queued → running → done/failed/cancelled`.
2. **Workers** no mesmo processo (pool de threads, `ASO_WORKERS`, padrão 2) que:
   pegam o próximo job, fazem o claim do card (MEL-13), executam e gravam o resultado.
3. **Rotas** de execução respondem `202 Accepted` com `run_id` (ou `job_ids`):
   `POST …/cards/{cid}/run`, `…/run-phase`, `…/autopilot`, `…/race`, `…/run-plan`,
   `…/discovery/run`, `…/spec/run`, `…/pulls/{pr}/review/run`, `…/analyze-folder`.
4. Aprovar `fase_gate` **enfileira** a próxima fase e retorna imediatamente.
5. `run_phase` vira um coordenador que enfileira os cards e, quando todos terminam,
   enfileira o gate — sem bloquear thread.
6. Cancelamento: `POST /v1/runs/{run_id}/cancel` mata o subprocess e marca `cancelled`.
7. Boot: jobs `running` sem worker vivo → `failed` com motivo "interrompido por reinício"; `queued` continuam.
8. Console: polling de `GET /v1/runs/{id}` + SSE existente para atualizar.

## Fora de escopo

- Múltiplos processos/réplicas (MEL-56).
- Paralelismo por onda com limite por orquestração (MEL-50) — aqui os workers só consomem a fila.

## Critérios de aceite

- [ ] Nenhuma rota de execução mantém a requisição aberta durante a execução do agente (tempo de resposta < 1 s com provider lento).
- [ ] Aprovar `fase_gate` retorna rapidamente e a próxima fase aparece na fila.
- [ ] Cancelar um run em andamento encerra o subprocess e libera o card.
- [ ] Reiniciar com job `running` o marca `failed`; `queued` executa após o boot.
- [ ] O fluxo do autopilot de ponta a ponta continua funcionando (teste de integração com provider fake).
- [ ] Smoke do Docker adaptado e verde.

## Testes obrigatórios

- Integração com provider lento: 202 imediato, conclusão observada por polling.
- Unit do worker: claim, execução, gravação, liberação em exceção.
- Integração de cancelamento com CLI fake que dorme.
- Integração de recuperação no boot.
- Adaptar `test_autopilot_loop.py`, `test_llm_autopilot.py`, `test_candidates_api.py`.

## Arquivos prováveis

- `src/aso/execution/jobs.py` (novo)
- `src/aso/control/orchestration_service.py` (ou serviço extraído em MEL-32)
- `src/aso/api/app.py`, `src/aso/bootstrap.py`
- `src/aso/api/static/detalhe.html`, `card-detalhe.html`, `demanda-detalhe.html`
- `scripts/smoke.sh`, `scripts/e2e_candidates.sh`

## Riscos

- Mudança grande na semântica da API e da UI: fazer atrás de flag `ASO_EXECUCAO_ASSINCRONA`
  durante a transição, com os dois caminhos testados, e remover o síncrono depois.
