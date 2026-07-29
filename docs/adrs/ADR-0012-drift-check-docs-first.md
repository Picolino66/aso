# ADR-0012 — Drift-check contínuo de docs-first + self-heal (F5/F6)

- **Status:** ACCEPTED
- **Fase:** F5 (evolução pós-O5)
- **Data:** 2026-07-09
- **Relaciona-se com:** [ADR-0003](ADR-0003-contextbus-governance.md) (ContextBus soberano),
  [ADR-0008](ADR-0008-workspace-por-orquestracao.md) (workspace + docs-first),
  skill `ai-docs-self-healing`

## Contexto

A [ADR-0008](ADR-0008-workspace-por-orquestracao.md) trouxe a documentação **docs-first**
gerada na criação da orquestração. Mas, à medida que o código evolui em F5/F6, a doc
**envelhece**: surgem módulos sem doc, docs de módulos removidos (órfãs), links internos
quebrados e features ainda em placeholder (`_A preencher._`). A skill `ai-docs-self-healing`
exige que `/docs` permaneça em sincronia com o código. Faltava um mecanismo que **detecte**
esse drift ao longo da esteira e permita **sincronizar** (self-heal).

## Opções consideradas

1. **Gate bloqueante de docs** — reprovar F5/F6 quando há drift. Rejeitada: trava a esteira
   por um sinal de baixo risco e ainda ruidoso (placeholders logo após o scaffold).
2. **Aviso não-bloqueante + ação de self-heal sob demanda** — o gate F5/F6 emite um
   *warning* quando há drift (sem reprovar) e o operador dispara a sincronização. Escolhida.
3. **Só heurística de IA** — deixar o agente decidir tudo. Rejeitada: não-determinística,
   sem sinal objetivo para a UI/gate e cara.

## Decisão

Adotar a **opção 2**. Novo módulo determinístico `execution/docs_drift.py` com
`check_drift(path) → DocsDriftReport` (só leitura): detecta `undocumented_modules`,
`orphan_module_docs` (excluindo o módulo neutro `projeto`), `broken_links` e
`unfilled_features`. O `run_quality_gate` registra, para F5/F6, um critério
**não-bloqueante** `docs_in_sync` — drift vira *warning* no `QualityGateResult`, nunca
`blocking_issue` (a esteira segue e o snapshot é gerado normalmente).

O self-heal (`OrchestrationService.heal_docs`) resolve o drift em duas camadas: (1)
**determinística** — cria `docs/modules/<módulo>/` para módulos de código sem doc via
`write_scaffold`; (2) **agente** (se houver executor real) — preenche placeholders e
conserta links num worktree isolado, com o diff mesclado (governado). Registra evento
`DocsHealed` + `ContextPatch` em `engineering.docs_drift` pelo ContextBus
([ADR-0003](ADR-0003-contextbus-governance.md)), **sem** aprovação humana (baixo risco).
Endpoints `GET /v1/orchestrations/{id}/docs-drift` (relatório) e `POST .../docs-heal`; no
console, um indicador de drift e o botão **"Sincronizar docs"**.

## Trade-offs

- **+** A esteira nunca trava por doc desatualizada, mas o drift fica **visível** no gate/UI.
- **+** Sinal **determinístico** (testável, barato) + heal em duas camadas (funciona offline
  para módulos novos; usa o agente quando disponível para o conteúdo).
- **+** Governança preservada: worktree isolado, diff, patch validado, rastreabilidade.
- **−** `unfilled_features` marca placeholders recém-criados como drift — é intencional
  (a doc ainda não reflete o código), mas gera aviso logo após o scaffold.
- **−** A qualidade do preenchimento depende do agente CLI selecionado.

## Consequências

- F5/F6 passam a sinalizar continuamente a saúde da documentação docs-first.
- O drift-check contínuo previsto como evolução na
  [ADR-0008](ADR-0008-workspace-por-orquestracao.md) fica entregue.
- **Self-heal automático no autopilot:** ao fim de F5/F6, o `run_phase` chama o self-heal
  automaticamente quando há pasta, docs geradas e drift real (best-effort — nunca derruba a
  esteira), retornando o resultado em `docs_autoheal`. Controlável por `ASO_AUTOHEAL_DOCS=0`.
  Além disso, permanece disponível como ação explícita (botão "Sincronizar docs").
