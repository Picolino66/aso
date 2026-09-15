# MEL-13 — Claim atômico do card antes de executar

| Campo | Valor |
|---|---|
| Fase do roadmap | 2 — Correção |
| Prioridade | **P0** |
| Esforço | médio |
| Status | Backlog |
| Depende de | — |
| Origem | [feedback.md](../feedback.md) §3 (tolerância a falhas, concorrência), §14 experimento 7 |
| Requer ADR | Sim: modelo de claim/lease de execução (referencia ADR-0018, ADR-0027) |

## Problema

- `run_card` ([orchestration_service.py:5941](../src/aso/control/orchestration_service.py#L5941))
  não adquire `_lock_for` e não verifica se o card já está em execução.
- O evento `AgentStarted` (→ InProgress) só é aplicado **depois** que o agente termina,
  dentro de `_apply_execution` ([:5868](../src/aso/control/orchestration_service.py#L5868)).
- Resultado executado: duas threads chamando `run_card` no mesmo card geraram 2
  execuções do agente; durante a execução o card aparecia como `Ready`.
- Um crash no meio da execução deixa o card em `Ready`, sem registro de que estava rodando.

## Mudança proposta

1. **Claim** sob `_lock_for(orchestration_id)`, antes de chamar o provider:
   - recusar se o card já estiver `IN_PROGRESS` (ou com `em_execucao_desde` preenchido);
   - mover para `IN_PROGRESS` via `apply_event("AgentStarted", execution_id=…)`;
   - gravar `card.em_execucao_desde = now_iso()` e `card.execution_id`;
   - `_persist(b)` imediatamente (o estado "rodando" precisa sobreviver a crash).
2. Executar o agente **fora** do lock (execução longa não pode segurar o lock).
3. **Release** sob lock em `_apply_execution`: limpar `em_execucao_desde`, aplicar resultado.
   Remover a aplicação tardia de `AgentStarted`.
4. Aplicar o mesmo claim em `run_plan`, `race_card` e no laço de retry de `run_card`
   (o retry mantém o claim; não solta e re-adquire).
5. Boot: cards com `em_execucao_desde` definido e sem processo vivo são marcados
   `Failed` com motivo "execução interrompida (reinício do runtime)" — ponto de
   integração com o prune de worktrees da ADR-0027.

## Fora de escopo

- Fila persistida e workers (MEL-31). Este claim é o pré-requisito dela.

## Critérios de aceite

- [ ] Duas chamadas concorrentes a `run_card` no mesmo card resultam em exatamente 1 execução do agente; a segunda recebe erro "card já em execução" (409 na API).
- [ ] Durante a execução, `GET …/cards/{cid}` mostra `InProgress`.
- [ ] Após sucesso ou falha, `em_execucao_desde` volta a vazio.
- [ ] Reiniciar o serviço com card em execução marca o card como `Failed` com o motivo registrado.
- [ ] Migration do novo campo validada no Postgres.

## Testes obrigatórios

- Unit com provider lento (`time.sleep`) e 2 threads: contador de chamadas == 1.
- Unit: status observado durante a execução == `InProgress`.
- Unit: exceção inesperada no provider libera o claim.
- Integração: reidratação com card "em execução" → `Failed` no boot.
- `test_race_stress.py` e `test_supervisor_concurrency.py` continuam verdes.

## Arquivos prováveis

- `src/aso/control/orchestration_service.py` (`run_card`, `_apply_execution`, `run_plan`, `race_card`)
- `src/aso/kanban/models.py`, `src/aso/kanban/board_service.py`
- `src/aso/db/models.py`, `migrations/versions/`
- `src/aso/bootstrap.py` (recuperação no boot)

## Riscos

- Persistir no claim adiciona uma gravação por execução (aceitável; MEL-33 reduz o custo).
- Transições manuais (`move_card_validado`) não devem permitir tirar um card de `InProgress` enquanto há claim ativo.
