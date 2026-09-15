# MEL-56 — Suporte a múltiplos processos (só se necessário)

| Campo | Valor |
|---|---|
| Fase do roadmap | 5 — Escala |
| Prioridade | P3 |
| Esforço | alto |
| Status | Backlog |
| Depende de | MEL-31, MEL-33 |
| Origem | [feedback.md](../feedback.md) §3 (escalabilidade), §12 Fase 5 |
| Requer ADR | **Sim**: coordenação entre processos |

## Gatilho

**Não iniciar** sem evidência de necessidade: fila de execução com espera persistente
mesmo com workers ajustados, ou requisito de alta disponibilidade. Registrar a medição que
justifica o início.

## Problema

Hoje o runtime pressupõe um único processo:

- locks por orquestração são `threading.RLock` em memória;
- `EventBroker` (SSE) e `AgentLogBus` (log ao vivo) são em memória;
- cache de agregados local ao processo;
- workers da fila (MEL-31) no mesmo processo da API.

## Mudança proposta (esboço, detalhar na ADR)

1. Lock por orquestração com advisory lock do Postgres (`pg_advisory_xact_lock`) no `BundleStore`.
2. Fila de `agent_runs` consumida com `SELECT … FOR UPDATE SKIP LOCKED`.
3. Workers em processo separado (`aso worker`).
4. SSE e log ao vivo via Postgres `LISTEN/NOTIFY` (evitar nova infraestrutura) ou broker externo se o volume exigir.
5. Invalidação de cache por versão otimista (MEL-33).

## Critérios de aceite

- [ ] Duas réplicas da API + dois workers sem execução duplicada nem perda de gravação (teste de integração no Docker).
- [ ] SSE e log ao vivo funcionam com o cliente conectado a uma réplica diferente da que executa.
