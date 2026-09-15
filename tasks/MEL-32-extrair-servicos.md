# MEL-32 — Extrair serviços do `OrchestrationService` e dividir `app.py`

| Campo | Valor |
|---|---|
| Fase do roadmap | 3 — Robustez |
| Prioridade | P1 |
| Esforço | alto (incremental) |
| Status | Backlog |
| Depende de | MEL-10, MEL-11, MEL-12, MEL-13 (fechar P0 antes de mover código) |
| Origem | [feedback.md](../feedback.md) §3, §11, §13.3 problema 5 |
| Requer ADR | **Sim**: camada de aplicação por caso de uso (referencia ADR-0001, ADR-0006) |

## Problema

- [orchestration_service.py](../src/aso/control/orchestration_service.py): 7.046 linhas,
  cerca de 260 métodos, 12 subdomínios (criação, execução, PR/CI/review/merge, discovery,
  spec, documentos, deploy, QA/bugs, incidentes, catálogos, consultas, docs-first).
- [app.py](../src/aso/api/app.py): 2.669 linhas, 198 rotas, com regra de negócio
  (planejamento LLM e escolha de triagem no handler de criação).
- Disciplina de lock inconsistente entre métodos.

## Mudança proposta (sem reescrever)

Extração por passos, cada passo com a suíte verde e **sem mudar a API pública**. O
`OrchestrationService` vira uma façade que delega, até os chamadores migrarem.

| Passo | Novo serviço | Métodos que migram |
|---|---|---|
| 1 | `application/bundles.py` — `BundleStore` | `_bundle`, `_hydrate`, `_to_state`, `_persist`, `_lock_for` (fonte única de lock) |
| 2 | `application/queries.py` | listagens, dashboard, header, busca, auditoria, métricas de leitura |
| 3 | `application/delivery.py` | `open_pr`, `run_pr_ci`, `report_ci`, `run_review`, `report_review`, `_apply_review_verdict`, `merge_pr`, comentários |
| 4 | `application/execution.py` | `run_card`, `_build_task`, `_execute_isolated`, `_apply_execution`, `_route_failure`, freios de orçamento, controles em voo, `race_card` |
| 5 | `application/preparation.py` | discovery, spec, documentos, revisão documental, `_materialize_spec_cards` |
| 6 | `application/release.py` | deploy, pipeline, validação, rollback de deploy, incidentes |
| 7 | `application/workflow.py` | `run_phase`, `run_quality_gate`, `advance_phase`, aprovações, autopilot — **único lugar que muda fase** |
| 8 | `application/intake.py` | `create_orchestration`, `create_with_triage`, `populate_from_plan`, planejamento (sai do handler) |
| 9 | `application/catalogs.py` | projetos, executores, regras de roteamento, catálogo de agentes |
| 10 | `api/routers/*.py` | um `APIRouter` por recurso; `app.py` só compõe middleware e routers |

Regras da extração:
- Serviços recebem `BundleStore` e colaboradores por construtor (sem voltar à façade).
- Cada método que muta estado adquire o lock via `BundleStore`, nunca diretamente.
- Nenhum arquivo novo acima de ~800 linhas.

## Critérios de aceite

- [ ] `orchestration_service.py` reduzido a façade (< 500 linhas) ou removido.
- [ ] `app.py` < 300 linhas; rotas em routers por recurso.
- [ ] Nenhuma regra de negócio em handlers HTTP (planejamento LLM dentro de `intake`).
- [ ] Todo método mutador passa pelo lock do `BundleStore` (teste que inspeciona ou revisão documentada).
- [ ] Suíte completa verde a cada passo; nenhuma mudança de contrato HTTP (MEL-03 detecta).

## Arquivos prováveis

- `src/aso/application/` (novo pacote), `src/aso/api/routers/` (novo)
- `src/aso/control/orchestration_service.py`, `src/aso/api/app.py`, `src/aso/bootstrap.py`
- `docs/ARCHITECTURE.md`

## Riscos

- Alto volume de conflitos com trabalho paralelo: fazer um passo por incremento e congelar mudanças no arquivo durante cada passo.
