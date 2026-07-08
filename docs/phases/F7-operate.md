# F7 — Operate & Evolve — ASO Runtime

> Fase F7 (ciclo). Depende de O6. Estado: **F7 concluída — snapshot O7 gerado** (pipeline F1–F7 fechado).

## 1. Observabilidade & métricas (observability-engine)

`MetricsService` ([observability/metrics.py](../../src/aso/observability/metrics.py)) calcula métricas a partir das consultas indexadas e da timeline:

- **Por orquestração:** fase, snapshot, cards por status, totais de ADRs/snapshots, conflitos abertos, eventos.
- **Global:** total de orquestrações, agregação de cards por status, ADRs, snapshots, conflitos abertos.

Exposto em `GET /v1/metrics`, `GET /v1/orchestrations/{id}/metrics` e `aso metrics <id>`.

## 2. SLOs (baseados em sintomas)

| SLO | Alvo | Fonte |
|---|---|---|
| `sem_conflitos_abertos` | 0 conflitos abertos | ConflictDetector/ContextBus |
| `sem_cards_bloqueados` | 0 cards em Blocked/Failed | Kanban |
| `snapshot_da_fase_gerado` | snapshot ≠ O0 | SnapshotEngine |

`GET /v1/orchestrations/{id}/slo` retorna avaliação + `breaches`.

## 3. Alertas (baseados em sintomas)

Regras derivadas dos SLOs (entrega de alerta — e-mail/webhook — é infra futura):

| Alerta | Condição | Severidade |
|---|---|---|
| Conflito aberto | `sem_conflitos_abertos` em breach | high |
| Card bloqueado | `sem_cards_bloqueados` em breach | medium |
| Fase sem snapshot | `snapshot_da_fase_gerado` em breach | low |

## 4. Feedback → backlog (user-feedback-engine)

`POST /v1/orchestrations/{id}/feedback` e `aso feedback <id> "<texto>"` convertem feedback
em card `Improvement` no Backlog, com evento `FeedbackReceived` — fechando o loop de evolução.

## 5. Loop de evolução

O pipeline retorna a **F2** (evolução arquitetural) ou **F4** (novas features) conforme gatilhos.
Feedbacks viram cards priorizáveis; ADRs de evolução são criadas quando a decisão afeta arquitetura.

## 6. Quality Gate F7 (loop)

| Critério | Status | Evidência |
|---|---|---|
| SLOs definidos p/ itens críticos | ✅ PASSED | 3 SLOs (seção 2); endpoint /slo |
| Alertas ativos e testados | ⚠️ PARCIAL | Regras definidas (seção 3); entrega de alerta é infra futura |
| Feedback loop operacional | ✅ PASSED | add_feedback → card Improvement + evento |
| Primeiro incident review | ⚠️ N/A | Sem produção real (§7); runbook de incidente em operations.md |
| Próxima evolução documentada | ✅ PASSED | roadmap/próximos passos + loop F2/F4 |

**Resultado: PASSED (2 avisos: entrega de alerta e incident review dependem de produção real, §7) → snapshot O7. Pipeline F1–F7 fechado.**
