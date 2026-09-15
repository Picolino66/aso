# MEL-18 — Docs-first e self-heal via entrega governada

| Campo | Valor |
|---|---|
| Fase do roadmap | 2 — Correção |
| Prioridade | P1 |
| Esforço | médio |
| Status | Backlog |
| Depende de | MEL-12 |
| Origem | [feedback.md](../feedback.md) §2 item 10 |
| Regras invioláveis | 5 (nunca operar na branch principal) e 6 (merge governado) |
| Requer ADR | **Sim**: supersede o trecho da ADR-0008 ("docs = baixo risco, sem aprovação") e ajusta ADR-0012 |

## Problema

- `analyze_folder` ([orchestration_service.py:6524](../src/aso/control/orchestration_service.py#L6524)):
  - em pasta vazia, faz `ws.commit_all(root, …)` direto na branch atual do repositório-alvo;
  - com agente, faz `WorktreeManager(root).merge(branch)` direto, **sem PR, CI ou revisão**,
    e engole falha com `except WorktreeError: pass` ([:6585](../src/aso/control/orchestration_service.py#L6585)).
- `heal_docs` repete o padrão ([:6797](../src/aso/control/orchestration_service.py#L6797)).
- `_maybe_autoheal_docs` ([:6850](../src/aso/control/orchestration_service.py#L6850)) roda
  automaticamente no fim de F5/F6, então agentes alteram a branch base sem nenhum humano ver.
- `start_autopilot` chama `analyze_folder` antes de qualquer outra etapa, e `ensure_git`
  pode inicializar git na pasta do usuário.

## Mudança proposta

1. Documentação gerada por agente vira **card do tipo `Documentation`** com branch e PR
   interna, seguindo o mesmo fluxo de qualquer card: `ci/run` (quando houver bateria) →
   revisão → merge admin.
2. Scaffold determinístico em pasta vazia: permitido commitar direto **somente** quando o
   repositório foi inicializado pelo próprio ASO nesta chamada (sem histórico prévio);
   caso contrário, também vira PR.
3. Falha de merge nunca é silenciosa: registrar `DocsMergeFailed` com o erro e manter o card aberto.
4. `_maybe_autoheal_docs` passa a **abrir o card** de healing em vez de aplicar o merge.
5. `ensure_git` em pasta sem git exige confirmação explícita no fluxo de criação (flag na
   requisição), com evento registrado.

## Fora de escopo

- Mudar o conteúdo do scaffold ou o algoritmo de drift (ADR-0012 permanece).

## Critérios de aceite

- [ ] `analyze_folder` em projeto existente cria um card `Documentation` com PR aberta e **não** altera a branch base.
- [ ] O merge da documentação exige as mesmas condições de `merge_pr`.
- [ ] Simular conflito de merge gera `DocsMergeFailed` e o card não é marcado como entregue.
- [ ] O autoheal ao fim de F5/F6 cria card, sem commit na branch base.
- [ ] Nenhum `except WorktreeError: pass` restante no serviço.

## Testes obrigatórios

- Integração com git real em `tmp_path`: HEAD da branch base inalterado após `analyze_folder` e `heal_docs`.
- Integração: merge da PR de docs exige CI + review.
- Regressão de `test_workspace_docs.py`, `test_docs_drift_flow.py`, `test_workspace_preanalysis.py`.

## Arquivos prováveis

- `src/aso/control/orchestration_service.py` (`analyze_folder`, `heal_docs`, `_maybe_autoheal_docs`, `start_autopilot`)
- `src/aso/execution/workspace.py`
- `src/aso/control/next_step.py`
- ADR nova; `docs/adrs/ADR-0008-workspace-por-orquestracao.md` (marcar trecho superseded)

## Riscos

- O smoke (`scripts/smoke.sh`) espera `has_aso_docs: true` logo após `analyze-folder`: ajustar para o novo fluxo.
