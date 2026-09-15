# ADR-0056 — CI executada × CI declarada

- **Status:** ACCEPTED
- **Fase:** F5/F6 (correção de governança — MEL-12, origem `feedback.md` §2 item 9)
- **Data:** 2026-09-15
- **Relaciona-se com:** [ADR-0009](ADR-0009-entrega-de-codigo-governada.md) (merge
  governado exige CI `passed` + review `approved`), [ADR-0017](ADR-0017-revisao-independente-de-codigo.md)
  (mesmo padrão aplicado à revisão: aprovação sem veredito exige justificativa de admin)

## Contexto

A regra inviolável 6 diz que o merge só ocorre com CI `passed` e review `approved`.
`merge_pr` confia em `PullRequest.ci_status`, mas havia dois caminhos para preenchê-lo:

- `POST .../pulls/{pr}/ci/run` (`run_pr_ci`) — executa a validação configurada na branch;
- `POST .../pulls/{pr}/ci` (`report_ci`) — grava o status informado **sem executar nada**,
  aberto a qualquer `operator`.

Na prática a exigência de CI aprovada podia ser satisfeita por declaração, e a ficha de
encerramento não distinguia uma da outra. A ADR-0017 já havia fechado a mesma brecha na
revisão (aprovar sem veredito exige justificativa + admin); a CI ficou para trás.

## Opções consideradas

1. **Remover a CI declarada.** Mais rígido, mas quebra o uso legítimo de CI externa
   (GitHub Actions/GitLab) enquanto não há integração — fora do escopo.
2. **Manter a declaração, mas crítica e rastreada.** `passed` declarado exige admin +
   justificativa e fica marcado como declarado; `failed` continua livre (só bloqueia).
3. **Só registrar a origem, sem restringir.** Não fecha a burla; apenas a documenta.

## Decisão

Opção 2.

- `PullRequest.ci_origem ∈ {"", "executada", "declarada", "desconhecida"}`:
  `""` = CI ainda não reportada; `executada` = gravada por `run_pr_ci`; `declarada` =
  gravada por `report_ci`; `desconhecida` = PR legada com CI já reportada antes desta
  distinção (a migration não inventa origem: afirmar "executada" para dados antigos
  seria evidência falsa).
- `report_ci(status="passed")` exige `justificativa` não vazia (409 sem ela) e registra
  evento `CIDeclared {pr_id, status, actor, justificativa}`.
- A rota `POST .../pulls/{pr}/ci` exige papel **admin** quando `status == "passed"`
  (403 para operator). Como `required_role` não lê o corpo, a checagem fica no handler
  — mesmo padrão de `report_review` (ADR-0017). `failed` segue aberto a operator.
- A ficha de encerramento do card (`card.closure`) ganha `ci_origem` e a evidência
  passa a ser `CI: passed (declarada|executada|desconhecida)`.
- `merge_pr` **não** passa a recusar CI declarada: a declaração de admin com
  justificativa é uma decisão humana legítima (regra 4); o que muda é que ela deixa de
  ser anônima e indistinguível.

## Consequências

- Declarar CI aprovada deixa de ser atalho de operator; testes e o
  `scripts/e2e_candidates.sh` passam a enviar justificativa (o e2e roda com token admin).
- Auditoria consegue separar merges liberados por execução real dos liberados por
  declaração (evento + ficha).
- Integração com CI externa, quando existir, deve gravar `executada` (ou uma origem
  própria) em vez de reutilizar `report_ci`.
