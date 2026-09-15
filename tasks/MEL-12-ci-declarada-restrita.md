# MEL-12 — Restringir a CI declarada manualmente

| Campo | Valor |
|---|---|
| Fase do roadmap | 2 — Correção |
| Prioridade | **P0** |
| Esforço | baixo |
| Status | Backlog |
| Depende de | — |
| Origem | [feedback.md](../feedback.md) §2 item 9, §14 experimento 6 |
| Regra inviolável | 6 — merge só com CI `passed` + review `approved` |
| Requer ADR | Sim, curta: define "CI executada" × "CI declarada" (referencia ADR-0009/ADR-0017) |

## Problema

`POST /v1/orchestrations/{id}/pulls/{pr_id}/ci` ([app.py:2148](../src/aso/api/app.py#L2148))
aceita `{"status": "passed"}` de qualquer `operator` e `report_ci`
([orchestration_service.py:1826](../src/aso/control/orchestration_service.py#L1826))
grava `pr.ci_status = "passed"` sem executar nada. Como `merge_pr` confia nesse campo,
a exigência de CI aprovada pode ser satisfeita por declaração.

A execução real existe em `run_pr_ci` (`POST …/ci/run`).

## Mudança proposta

1. Distinguir origem da CI em `PullRequest`: `ci_origem ∈ {"executada", "declarada"}`
   (migration nova com default `"executada"` para PRs antigas… ou `"desconhecida"` —
   decidir na ADR).
2. `report_ci` com `status == "passed"` passa a exigir `justificativa` não vazia e
   `actor`; registra `ci_origem = "declarada"` e evento `CIDeclared` com quem e por quê.
3. `required_role`: `…/pulls/{pr}/ci` com status `passed` exige admin. Como
   `required_role` não lê corpo, fazer a checagem fina no handler (mesmo padrão de
   `report_review`).
4. `status == "failed"` continua permitido a operator (reprovar é seguro).
5. `merge_pr` exibe/registra a origem da CI na ficha de encerramento do card.

## Fora de escopo

- Integração com CI externa (GitHub Actions etc.).

## Critérios de aceite

- [ ] Operator não consegue declarar CI `passed` (403).
- [ ] Admin sem justificativa recebe 409; com justificativa, a PR fica `passed` com `ci_origem = "declarada"`.
- [ ] `ci/run` grava `ci_origem = "executada"`.
- [ ] A ficha de encerramento (`card.closure`) mostra a origem da CI.
- [ ] Migration aplicada e `alembic check` sem diff.

## Testes obrigatórios

- Integração API: operator → 403; admin sem justificativa → 409; admin com justificativa → 200.
- Unit: `run_pr_ci` grava origem executada; `merge_pr` inclui origem na ficha.
- Validação no Postgres (migration).

## Arquivos prováveis

- `src/aso/governance/models.py` (`PullRequest`)
- `src/aso/db/models.py`, `migrations/versions/`
- `src/aso/control/orchestration_service.py` (`report_ci`, `run_pr_ci`, `_build_card_closure`)
- `src/aso/api/app.py`
- `docs/adrs/ADR-00NN-ci-executada-e-declarada.md`

## Riscos

- `scripts/e2e_candidates.sh` e testes podem usar CI declarada como atalho; ajustar para admin + justificativa ou `ci/run`.
