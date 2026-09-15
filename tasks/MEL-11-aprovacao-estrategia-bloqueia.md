# MEL-11 — Aprovação de estratégia pendente bloqueia a execução

| Campo | Valor |
|---|---|
| Fase do roadmap | 2 — Correção |
| Prioridade | **P0** |
| Esforço | baixo |
| Status | Backlog |
| Depende de | — |
| Origem | [feedback.md](../feedback.md) §2 item 8, §14 experimento 8 |
| Regra inviolável | 4 — ações críticas exigem aprovação humana |
| Requer ADR | Não |

## Problema

`create_orchestration` cria uma `HumanApproval` de `tipo="estrategia"` quando
`plan.requires_human_approval` é verdadeiro ([orchestration_service.py:979](../src/aso/control/orchestration_service.py#L979)),
mas nada consulta essa aprovação antes de executar. `run_card`, `run_phase`,
`run_plan`, `race_card` e `start_autopilot` executam normalmente.

Evidência executada: demanda com risco CRITICAL e impacto `database_reset` gerou a
aprovação pendente e o `DatabaseAgent` executou mesmo assim.

Além disso, rejeitar essa aprovação (`decide_approval(approved=False)`) só muda o
status: a orquestração segue executável.

## Mudança proposta

1. Criar um guard único `_recusar_se_estrategia_pendente(b)` que levanta `ValueError`
   quando existe aprovação `tipo == "estrategia"` com `status == "pending"`.
2. Chamar o guard na entrada de `run_card`, `run_phase`, `run_plan`, `race_card`,
   `start_autopilot` e `analyze_folder` (esta executa agente).
3. Em `decide_approval`, quando a aprovação rejeitada for `tipo == "estrategia"`,
   marcar a orquestração como `cancelled` e registrar `StrategyRejected`.
4. `next_step` deve apresentar a aprovação pendente como bloqueio acionável
   (verificar se já aparece; se não, incluir).

## Fora de escopo

- Replanejar automaticamente após rejeição.
- Aprovação por card (já existe via `approval.card_id`).

## Critérios de aceite

- [ ] Com aprovação de estratégia pendente, os seis pontos de entrada recusam com mensagem em pt-BR e nenhum agente é chamado.
- [ ] Após aprovar, a execução segue normalmente.
- [ ] Após rejeitar, a orquestração fica `cancelled` e continua recusando execução.
- [ ] Orquestrações sem aprovação de estratégia não mudam de comportamento.
- [ ] A API devolve 409 nas rotas de execução enquanto houver pendência.

## Testes obrigatórios

- Unit com provider que conta chamadas: 0 chamadas com pendência; ≥ 1 após aprovar.
- Unit: rejeição cancela e bloqueia.
- Integração API: `POST .../autopilot` e `POST .../cards/{cid}/run` → 409 com pendência.

## Arquivos prováveis

- `src/aso/control/orchestration_service.py`
- `src/aso/control/next_step.py`
- `tests/unit/`, `tests/integration/`

## Riscos

- Fluxos de teste que criam demandas de alto risco e executam direto vão falhar; ajustar
  aprovando antes.
