# Quality Gates — ASO Runtime

> Explica o `QualityGateEngine` (§22) e lista os gates por fase.
> **Resultados materializados em:** [`.aso/quality-gates/`](../.aso/quality-gates/).
> Requisito: [`requerimentos.md` §22](../requerimentos.md).

## 1. QualityGateEngine (§22)

Cada fase F1–F7 tem um **quality gate** que valida critérios verificáveis antes de permitir o avanço. Regras:

- **Gate falho bloqueia o avanço** de fase. Imposto em `advance_phase` (MEL-10): só
  avança quando o **último** `QualityGateResult` da fase atual é `PASSED` ou `SKIPPED`
  (fase sem nada bloqueante a verificar, ADR-0060) — gate nunca
  executado, `FAILED` ou `PASSED` antigo seguido de `FAILED` recusam com 409, gravam o
  evento `PhaseAdvanceRefused` e mantêm `current_phase`. O autopilot usa o mesmo caminho.
- Gate falho pode gerar cards automáticos e acionar o agente responsável.
- Gate crítico pode exigir aprovação humana.
- **Fase aprovada gera um snapshot** (ver [`snapshots.md`](snapshots.md)).

Cada resultado (`QualityGateResult`) registra: `phase`, `status` (`PASSED`/`FAILED`/`WARNING`/`SKIPPED`), lista de `criteria` (com `evidence` e `failure_reason`), `blocking_issues`, `warnings`, `required_actions`, `approved_by` e se exigiu aprovação humana.

### Bateria de validações nomeada (§12, ADR-0022)

Nas fases F5/F6, o critério que roda os testes/lint do repositório deixou de ser um
comando único (`tests_pass`): `Orchestration.validation_checks` guarda uma lista de
`ValidationCheck` (`nome`, `comando`, `categoria`, `bloqueante`), e
`run_quality_gate` cria **um `Criterion` por verificação** — todas rodam até o fim,
sem parar na primeira falha, cada uma com sua própria evidência. Uma verificação
`bloqueante: false` que falha entra em `warnings`, não em `blocking_issues` (mesmo
tratamento que `docs_in_sync` já tinha). Sem bateria configurada,
`checks_efetivos` faz o `validation_command` legado (um comando só) virar uma
verificação sintética `"testes"` — compatibilidade total com orquestrações
anteriores a este incremento. Gerencie a bateria em
`GET/PUT /v1/orchestrations/{id}/validation-checks` e peça uma sugestão
determinística por stack em `GET .../validation-checks/suggest`
([`docs/api.md`](api.md)). Ver
[ADR-0022](adrs/ADR-0022-bateria-de-validacoes-e-effort-automatico.md).

### Critérios do runtime por fase (ADR-0060)

Declarados em [`src/aso/governance/gate_definitions.py`](../src/aso/governance/gate_definitions.py);
a tabela abaixo é **gerada** das definições (`tabela_markdown()`) e um teste falha se ela
divergir do código. Gate sem nenhum critério bloqueante aplicável fica `SKIPPED`: não gera
snapshot nem aprovação humana; `advance_phase` o aceita como `PASSED`; o autopilot registra
`PhaseSkipped` e segue para a próxima fase.

<!-- gate-definitions:inicio -->
| Critério | Fases | Bloqueia | Regra |
|---|---|---|---|
| `cards_da_fase_entregues` | todas | sim | Todo card da fase (fora Cancelled/Archived) está Done, ou Testing sem branch. |
| `output_da_fase_aplicado` | todas | sim | Ao menos um ContextPatch aplicado com a fase igual à do gate (quando há cards). |
| `discovery_aprovado` | F1 | sim | Último relatório de discovery aprovado (só se o discovery foi rodado). |
| `deploy_aprovado` | F6 | sim | Implantação aceita / pipeline completo (só se houve implantação). |
| `bateria de validações (1 critério por verificação)` | F5, F6 | sim | Cada verificação configurada roda na pasta de trabalho (bloqueia conforme a verificação). |
| `cards_entregues` | F5, F6 | sim | Com validação configurada e cards na fase: todos mesclados (Done). |
| `docs_in_sync` | F5, F6 | não | Documentação docs-first sem drift em relação ao código (aviso, não bloqueia). |
| _(nenhum critério bloqueante aplicável)_ | todas | — | Gate `SKIPPED`: sem snapshot e sem aprovação humana de fase vazia. |
<!-- gate-definitions:fim -->

## 2. Estado do processo de construção do ASO

As tabelas "F1–F4 PASSED / F5 pendente" que existiam aqui descreviam o **processo de
construção do próprio ASO** (artefatos mantidos à mão em `.aso/quality-gates/`), não o
estado de uma orquestração do runtime. O estado real de cada orquestração vem de
`GET /v1/orchestrations/{id}/quality-gates`. A separação dos artefatos de construção é a
MEL-04 (aguardando decisão do operador).

## Referências

- Snapshots: [`snapshots.md`](snapshots.md)
- Governança de contexto: [`context.md`](context.md)
- Requisitos: [`requerimentos.md` §22](../requerimentos.md)
