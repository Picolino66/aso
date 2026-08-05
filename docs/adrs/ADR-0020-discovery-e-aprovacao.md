# ADR-0020 — Discovery e aprovação

- **Status:** ACCEPTED
- **Fase:** F1 (evolução pós-O5)
- **Data:** 2026-07-31
- **Relaciona-se com:** [ADR-0016](ADR-0016-ficha-da-demanda.md) (`DemandBrief` como
  base do fallback), [ADR-0017](ADR-0017-revisao-independente-de-codigo.md) (mesmo
  padrão de veredito auto-contido), [ADR-0019](ADR-0019-roteamento-de-falha.md),
  [`fluxo.md`](../../fluxo.md) §3/§4

## Contexto

`plano3.md` §10 lista o Incremento D ("artefatos por fase", `fluxo.md` §3–§6) como a
maior lacuna restante — sem plano detalhado como incrementos anteriores tiveram. O
"D" completo cobre quatro seções de tamanho comparável a incrementos inteiros: §3
(discovery), §4 (aprovação do discovery), §5 (especificação) e §6 (revisão
documental). Ficou combinado quebrar em duas entregas — **esta ADR cobre só D1:
discovery + aprovação (§3/§4)**. D2 (especificação + revisão documental, §5/§6) fica
para depois, com seu próprio plano.

Dois precedentes quase perfeitos já existiam no `control/`, e D1 é a combinação dos
dois:

- **`TriageService`/`DemandBrief`** (ADR-0016) para a metade "produzir o documento":
  agente (LLM ou CLI, via `ExecutorCatalog`) que responde em JSON saneado, com
  **fallback determinístico que nunca falha**. `TriageService` já importa
  `_SENSITIVE_IMPACTS`/`_APPROVAL_IMPACTS`/`_DOMAIN_AGENT` diretamente de
  `decision_engine.py` — confirma que reaproveitar constantes entre módulos de
  `control/` é prática aceita no repo.
- **`ReviewService`/`PullRequest.review_status`** (ADR-0017) para a metade "decidir
  com comentários": um veredito com estado guardado como dict JSONB direto na
  entidade dona, sem passar pelo mecanismo genérico `HumanApproval`.

## Decisão

**(1) Sem tabela nova.** `Orchestration.discovery_report: dict[str, Any] = {}` —
coluna JSONB em `orchestrations`, mesmo padrão de `demand_brief`/`agent_assignments`
(pequeno, sempre lido junto da orquestração). Dict vazio = "discovery nunca rodado".

**(2) `DiscoveryReport` é auto-contido, não usa `HumanApproval`.** Segue
`PullRequest.review_status`: `situacao_atual`, `problema`, `componentes_afetados`,
`restricoes`, `riscos`, `alternativas`, `recomendacao_tecnica`, `pontos_decisao`,
`confianca` (`alta`/`media`/`baixa`), `status`
(`rascunho`/`aguardando_aprovacao`/`aprovado`/`reprovado`), `revisao_comentarios`,
`origem` (executor ou `"heuristica"`), `fallback_reason`.

**(3) Regra de aprovação automática vs. humana (§4), função pura.**
`exige_aprovacao_discovery(report, brief)` em `control/discovery.py`, reaproveitando
`_SENSITIVE_IMPACTS` de `decision_engine.py` (architecture/contract/security/
database/deploy — cobre "altera arquitetura"/"afeta segurança"/"risco de perda de
dados" do §4 quase literalmente):

```python
report.confianca == "baixa" or brief.risco in (HIGH, CRITICAL) or
bool(set(brief.impactos) & _SENSITIVE_IMPACTS)
```

Espelha `exige_confirmacao_humana` (ADR-0017) na forma. `confianca` é sempre
`"baixa"` no fallback heurístico (sem agente real, o relatório é só um resumo do que
a triagem e o scan de workspace já enxergavam) — logo, **sem agente de discovery
configurado, toda demanda cai no caminho de aprovação humana**. Isto é intencional:
"baixa confiança na recomendação" (§4) é exatamente o estado de quem não teve uma
investigação de verdade.

**(4) `DiscoveryService`, mesma estrutura de `TriageService`.**
`investigar(assignment, *, user_request, demand_brief, workspace_report,
comentarios_anteriores) -> DiscoveryReport`: com agente configurado, monta um prompt
(system fixo em pt-BR, JSON saneado) e roda via `catalog.llm_client`/
`catalog.cli_command` (cwd temporário — discovery não altera código, sem worktree).
Qualquer falha (JSON inválido, executor fora do catálogo, exit≠0, timeout) cai no
fallback heurístico construído a partir do `WorkspaceReport` (scan estrutural já
existente, `execution/workspace.py`) + `DemandBrief` já triada — nunca lança.
`comentarios_anteriores` (do relatório reprovado anterior, se houver) entra no
prompt para o agente ajustar o documento (§4: "o agente ajusta o documento e o
submete novamente").

**(5) Onde a decisão é aplicada — `OrchestrationService`.**
`run_discovery` exige `target_path` (`ValueError` → `409` senão); resolve o executor
pela etapa `DISCOVERY_KEY` (mesmo regime de `TRIAGE_KEY`/`REVIEW_KEY`: não é fase da
esteira, sempre editável); roda `WorkspaceAnalyzer`; chama `DiscoveryService`;
aplica `exige_aprovacao_discovery` para decidir o `status`; persiste. `decide_discovery`
só aceita quando `status == "aguardando_aprovacao"` (`ValueError` → `409` senão);
grava `status`/`revisao_comentarios`.

**(6) Gate de F1, não-regressivo.** Em `run_quality_gate`, quando
`target_phase == Phase.F1` **e** `orchestration.discovery_report` não está vazio,
acrescenta `Criterion("discovery_aprovado", ...)` checando `status == "aprovado"`.
Vazio (discovery nunca rodado) = critério nem entra — vacuamente ok, zero mudança
de comportamento para qualquer orquestração que não chamar `/discovery/run`
(inclusive todo `CODE_EXECUTION`, que já pula F1–F4 inteiro). Validado manualmente
em Postgres: uma orquestração sem discovery passa o gate de F1 só com
`context_has_output`, exatamente como antes desta ADR.

**(7) API.**
```
POST /v1/orchestrations/{id}/discovery/run     body: {executor?, effort?}
GET  /v1/orchestrations/{id}/discovery
POST /v1/orchestrations/{id}/discovery/decide  body: {approved, comentario?}
```
`decide` é ação crítica (regra 4 do `CLAUDE.md`) — `/discovery/decide` entra no
grupo que `required_role` já resolve para `admin` (mesmo tratamento de
`/approve`/`/reject`/`/merge`).

**(8) `next_step.py`.** Item de checklist `discovery` só entra em F1 quando
`status != "rascunho"` (discovery já foi iniciado). `_discovery_blocker`:
`reprovado` → `SEVERITY_OPERATOR` (o agente reajusta e resubmete, ação aponta para
`/discovery/run`); `aguardando_aprovacao` → `SEVERITY_HUMAN` (ação aponta para
`/discovery/decide`, `role="admin"`). `rascunho`/`aprovado` não bloqueiam nada.

**(9) UI.** Painel "Discovery" em `detalhe.html`, mesmo esqueleto condicional de
"Revisão de código" (visível só quando há relatório): situação atual, problema,
componentes afetados, riscos, alternativas, recomendação técnica, pontos de decisão,
pill de status/confiança/origem; botão "Rodar discovery"; quando
`aguardando_aprovacao`, botões "Aprovar"/"Reprovar" (com comentário).

## Consequências

**Positivas**
- `fluxo.md` §3/§4 deixam de ser só requisito documentado — a esteira agora produz e
  governa um relatório de discovery de verdade antes de avançar de F1.
- Zero migração de comportamento para o que já existia: toda a suíte pré-existente
  (549 testes) passou sem alteração, e o roteiro manual confirmou o gate vacuamente
  aprovado em Postgres para uma orquestração que nunca chama `/discovery/run`.
- Reaproveita dois padrões já maduros do repositório (`TriageService`,
  `PullRequest.review_status`) em vez de inventar um terceiro mecanismo de aprovação.

**Negativas / riscos aceitos**
- Sem agente de discovery configurado, toda demanda cai em `aguardando_aprovacao`
  (confiança sempre baixa no fallback) — mais trabalho manual do que o desejável até
  alguém configurar a etapa `discovery`. Aceito: mesmo trade-off que `ReviewService`
  já faz (fallback pessimista em vez de aprovar por omissão).
- `DiscoveryReport` não é versionado — reexecutar depois de uma reprovação
  **substitui** o relatório anterior; o comentário da reprovação sobrevive só porque
  entra no prompt da próxima tentativa, não como histórico consultável. Aceito como
  simplificação desta entrega.
- **Especificação (§5) e revisão documental (§6) ficam explicitamente fora** — D2,
  com seu próprio plano.

## Emenda (2026-07-31, ADR-0021)

O risco aceito do não-versionamento foi resolvido na
[ADR-0021](ADR-0021-especificacao-e-revisao-documental.md) (D2, §4.2):
`Orchestration.discovery_report: dict` (singular) virou `discovery_reports:
list[dict]` — um ring de até 5 versões (`control/documentos.py`), com migração de
dados do formato antigo (`c1a3e7f92b4d`). `run_discovery` acrescenta uma versão
nova a cada rodada; `decide_discovery` atualiza a última no lugar (decidir não é
produzir um documento novo). `get_discovery_report` continua devolvendo a versão
corrente (comportamento externo inalterado para quem só lê o estado atual); o
histórico completo passou a ser exposto em `GET .../discovery/history`. D2
(especificação + revisão documental, §5/§6) saiu na mesma ADR-0021.
