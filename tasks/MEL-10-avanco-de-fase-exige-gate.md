# MEL-10 — Avanço de fase exige gate aprovado e papel admin

| Campo | Valor |
|---|---|
| Fase do roadmap | 2 — Correção |
| Prioridade | **P0** |
| Esforço | baixo |
| Status | Backlog |
| Depende de | — |
| Origem | [feedback.md](../feedback.md) §2 item 5, §13.3 problema 1, §14 experimento 1 |
| Regra inviolável | 3 — não avançar de fase com quality gate reprovado |
| Requer ADR | Não (aplica regra já aceita) |

## Problema

`OrchestrationService.advance_phase` ([orchestration_service.py:7036](../src/aso/control/orchestration_service.py#L7036))
muda `current_phase` sem consultar nenhum resultado de gate. A rota
`POST /v1/orchestrations/{id}/advance-phase` ([app.py:1853](../src/aso/api/app.py#L1853))
cai no papel padrão `operator` em `required_role` ([auth.py:59](../src/aso/api/auth.py#L59)).

Evidência executada: 6 chamadas seguidas levaram a orquestração de F1 a F7 com 0 gates rodados.

## Mudança proposta

1. `advance_phase` só avança quando o **último** `QualityGateResult` da fase atual
   (`b.gate_results`, filtrado por `phase`) tem `status == PASSED`. Caso contrário,
   levanta `ValueError` com mensagem em pt-BR citando o status encontrado
   ("gate de F3 não aprovado: FAILED" / "gate de F3 nunca executado").
2. Adquirir `_lock_for` já existe; manter a verificação dentro do lock (check-then-act).
3. Registrar evento `PhaseAdvanceRefused` com fase e motivo quando recusar.
4. `required_role`: incluir o sufixo `/advance-phase` na lista de admin.
5. `_advance_after_phase_gate` (auto-avanço do autopilot) passa pelo mesmo caminho
   e continua funcionando, porque só é chamado após gate PASSED + aprovação.

## Fora de escopo

- Tornar o gate escopado por fase e acabar com a aprovação vazia (MEL-16).
- Mudar o fluxo de aprovação `fase_gate`.

## Critérios de aceite

- [ ] Chamar `advance_phase` sem gate executado na fase atual devolve erro e não altera `current_phase`.
- [ ] Com o último gate da fase `FAILED` (mesmo havendo um PASSED anterior), o avanço é recusado.
- [ ] Com o último gate `PASSED`, o avanço ocorre como antes.
- [ ] A rota responde 409 quando recusa e 403 para token `operator`.
- [ ] O autopilot (aprovar `fase_gate`) continua avançando e rodando a próxima fase.
- [ ] Evento `PhaseAdvanceRefused` aparece na timeline quando há recusa.

## Testes obrigatórios

- Unit: `advance_phase` sem gate, com gate FAILED, com PASSED seguido de FAILED, com PASSED.
- Integração API: 409 sem gate; 403 com papel operator (usar `AuthService` com chaves).
- Regressão: testes existentes do autopilot (`test_autopilot_loop.py`, `test_phase_runner.py`)
  continuam verdes; ajustar os que chamavam `advance_phase` sem gate.

## Arquivos prováveis

- `src/aso/control/orchestration_service.py` (`advance_phase`)
- `src/aso/api/auth.py` (`required_role`)
- `tests/unit/`, `tests/integration/test_governance_endpoints.py`

## Riscos

- Testes e scripts que usam `advance-phase` como atalho vão quebrar — é o efeito desejado;
  ajustar para rodar o gate antes.
- O console (`detalhe.html`/`index.html`) pode ter botão de avanço manual: exibir a mensagem de recusa.
