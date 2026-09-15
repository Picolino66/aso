# MEL-52 — Consultas sem hidratar agregados

| Campo | Valor |
|---|---|
| Fase do roadmap | 5 — Escala |
| Prioridade | P2 |
| Esforço | médio |
| Status | Backlog |
| Depende de | MEL-32 (passo 2, `queries`) |
| Origem | [feedback.md](../feedback.md) §3 (escalabilidade) |
| Requer ADR | Não |

## Problema

Várias leituras carregam agregados inteiros para memória (e, com o cache sem descarte,
ali permanecem):

- `_find_approval` e `list_all_approvals` percorrem **todas** as orquestrações ([:2915](../src/aso/control/orchestration_service.py#L2915));
- `/metrics` calcula `slo_report` para cada orquestração (tratado em MEL-15, mas o restante do `MetricsService` também usa `timeline` completa);
- `get_learning_report_global` hidrata o sistema quando não há `project_id`;
- `execution_metrics`, `slo_report` e `execution-timeline` leem o `EventLog` inteiro por orquestração.

## Mudança proposta

1. Consultas SQL diretas no repositório para: aprovação por id, aprovações pendentes globais,
   contagem de execuções/falhas por orquestração, amostras para aprendizado.
2. `GET /v1/approvals/{id}` e `POST /v1/approvals/{id}/approve` localizam a orquestração por
   consulta, não por varredura.
3. Métricas de execução a partir de `agent_runs` (MEL-30) em vez do `EventLog`.
4. Teste com repositório espião garantindo que essas rotas não chamam `load()` de agregados não envolvidos.

## Critérios de aceite

- [ ] Aprovar uma aprovação carrega no máximo uma orquestração.
- [ ] Listagem global de aprovações não hidrata agregados.
- [ ] Relatório de aprendizado global usa consultas agregadas.
- [ ] Resultados idênticos aos atuais em testes comparativos.
