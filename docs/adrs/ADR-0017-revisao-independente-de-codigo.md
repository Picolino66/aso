# ADR-0017 — Revisão independente de código (§14/§15)

- **Status:** ACCEPTED
- **Fase:** F5 (evolução pós-O5)
- **Data:** 2026-07-30
- **Relaciona-se com:** [ADR-0009](ADR-0009-entrega-de-codigo-governada.md) (entrega governada,
  CI + revisão como pré-requisito de merge), [ADR-0014](ADR-0014-agente-por-etapa-e-nomes-semanticos.md)
  (mecanismo de agente por etapa, de onde vem a seleção do revisor),
  [ADR-0016](ADR-0016-ficha-da-demanda.md) (ficha da demanda, reaproveitada para a
  aprovação automática por risco), [`fluxo.md`](../../fluxo.md) §14/§15 (requisito de
  origem)

## Contexto

O `fluxo.md` §14 é categórico: *"Depois que os testes passam, um agente diferente
realiza o code review. (...) O agente que implementou o código não deve ser o único
responsável pela aprovação."* Esse é o argumento de qualidade da esteira inteira, e
não existia em lugar nenhum do runtime:

- `report_review` gravava uma `str` sem checar quem revisou, sem conteúdo de revisão e
  sem exigir que alguém tivesse olhado o diff.
- A UI oferecia "Aprovar revisão" como um clique com `body={"status": "approved"}` — um
  botão que dizia que houve revisão sem que ela tivesse acontecido.
- O `ReviewAgent` já entrava na equipe multiagente (`MultiAgentDecisionEngine`), mas
  rodava pelo `_build_task` genérico, que **não passa diff nenhum**: ele "revisava" sem
  ver código.
- `ReviewRequestedChanges` levava o card de volta para `Review`, indistinguível de um
  card ainda não revisado — o `fluxo.md` §15 pede uma coluna própria
  ("Aguardando correção") com os comentários virando ações objetivas.

Consequência prática: o merge governado (`merge_pr`, que já exige `ci_status ==
"passed"` **e** `review_status == "approved"`) tinha uma das duas travas oca. A CI é
real (roda `subprocess` em worktree destacado); a revisão era um campo de texto.

## Opções consideradas

1. **Revisor com acesso ao worktree/branch completos.** Rejeitada: exigiria abrir mais
   um worktree por revisão (custo e complexidade de concorrência) e daria ao revisor
   capacidade de escrever código — o oposto de "independente". Aceita a limitação: o
   revisor vê só o diff, não o código ao redor (documentado abaixo).
2. **Fallback determinístico "aprovado" quando o revisor falha**, no mesmo molde de
   `NamingService`/`TriageService`. Rejeitada: **não existe revisão de código
   determinística**. Naming cai num slug e triagem cai numa heurística por
   palavra-chave — ambos continuam corretos sem agente. Aprovar código sem ninguém
   (nem heurística) tê-lo revisado é o oposto exato do que o §14 pede. O fallback deste
   serviço é sempre `necessita_humano`.
3. **Aprovação automática sempre que o agente aprova**, delegando 100% ao revisor.
   Rejeitada: risco alto ou impacto sensível (`security`, `database`, `deploy`) não pode
   fechar sozinho mesmo com o agente aprovando — é o §4 do `fluxo.md` (aprovação
   automática vs. humana) aplicado ao code review.
4. **Tabela filha para o veredito da revisão.** Rejeitada pelo mesmo motivo de
   `demand_brief`/`agent_assignments`: mapa pequeno, sempre lido junto da PR — colunas
   novas em `pull_requests`, não tabela nova.

## Decisão

**(1) `ReviewService` (`src/aso/control/review.py`)**, no molde de `triage.py`: prompt
de sistema constante, duplo caminho `kind == "llm"`/`kind == "cli"`, `parse_llm_json`,
saneamento contra vocabulário fechado (`veredito`, `categoria`, `severidade` fora do
vocabulário caem no padrão mais conservador, nunca são descartados por completo).
`ReviewVerdict` traz os cinco desfechos do §14 (`aprovado`, `aprovado_com_sugestoes`,
`alteracoes_obrigatorias`, `reprovado`, `necessita_humano`), a lista de `acoes`
(`ReviewAction`: descrição + categoria + severidade `obrigatoria`/`sugestao`) e
`pontos_verificados`, que existem para o veredito ser auditável contra os doze eixos do
§14. Diff acima de `DIFF_MAX` (60 000 caracteres) é truncado com aviso no prompt e um
item automático em `pontos_verificados` — um revisor que viu metade do diff e aprova
sem ressalva é pior que nenhum revisor.

**(2) O fallback nunca é `aprovado` — é sempre `necessita_humano`.** Diferença crítica
em relação a `naming`/`triage`: qualquer indisponibilidade do agente (timeout, JSON
inválido, executor removido do catálogo, sandbox sem permissão, resposta sem veredito
utilizável) escala para revisão humana. Coberto pelos seis caminhos de falha em
`tests/unit/test_review_service.py`.

**(3) Independência real, três peças:**
- `REVIEW_KEY = "revisao"` ao lado de `NAMING_KEY`/`TRIAGE_KEY` em
  `_validate_assignment_key`: sempre editável (não é fase), herda de graça
  `PUT`/`DELETE /v1/orchestrations/{id}/agents/revisao` e a matriz de configuração da
  UI (ADR-0014) — nenhum componente novo.
- `KanbanCard.executor: str | None` — distinto de `assignee` (o **papel** planejado,
  ex. `BackendDevelopmentAgent`): guarda o **perfil de executor** que de fato rodou o
  card, gravado em `_apply_execution`. Sem isto não havia como exigir revisor diferente
  do implementador. Serve também ao §23/§24 (modelos utilizados/melhor desempenho).
- Resolução do revisor: `agent_assignments["revisao"]` → default do catálogo → nenhum
  — **desde que diferente de `card.executor`**. Se o único candidato disponível for o
  próprio implementador, `_resolve_reviewer` recusa com motivo
  (`fallback_reason="revisor seria o mesmo executor do card"`) em vez de aprovar por
  omissão.

**(4) `report_review` governado.** Nova assinatura com `actor`/`justificativa`.
`status == "approved"` só é aceito quando **(i)** já existe `pr.review_verdict` com
veredito `aprovado`/`aprovado_com_sugestoes` — o clique humano confirma o que o agente
já disse — **ou (ii)** vem com `justificativa` não vazia, e a rota exige papel `admin`
nesse caso (checagem fina no handler, já que `required_role` só enxerga método+rota).
Sem nenhum dos dois, `ValueError` (`409`). O antigo `pr_review_pendente` de um clique
com `body={"status": "approved"}` não existe mais no `next_step.py`.

**(5) Aprovação automática conforme o risco da ficha (§4.3).**
`exige_confirmacao_humana(brief)` — `risco in (high, critical)` ou impacto em
`{security, database, deploy}` — decide se um veredito `aprovado`/
`aprovado_com_sugestoes` fecha `review_status="approved"` sozinho ou fica `pending`
aguardando confirmação. Reaproveita a `DemandBrief` da ADR-0016; o merge continua
exigindo aprovação humana separada (regra 4 do `CLAUDE.md`) — o humano deixa de
precisar fingir que revisou, não deixa de ser o último portão.

**(6) Ciclo de correção (§15).** `ColumnKey.NEEDS_FIX` ("Aguardando correção") entra
após `Review` na ordem canônica; `ReviewRequestedChanges` passa a levar o card para lá
em vez de de volta a `Review`. As ações de severidade `obrigatoria` do veredito viram
`card.correction_actions` (coleção plana, mesmo caminho de `acceptance_criteria` — sem
migration) e chegam ao agente na re-execução via `_build_task`/
`scripts/aso-agent-wrapper.sh` ("Correções obrigatórias apontadas pela revisão
independente"). `pr.review_rounds` incrementa a cada rodada; aprovação posterior limpa
`correction_actions`.

**(7) `next_step` — o botão que mentia sai.** `_pr_blocker` passa a checar CI → revisão
→ merge, com três bloqueios novos: `pr_review_nao_executada` (ação do operador, roda o
agente), `pr_alteracoes_obrigatorias` (bloqueia, mostra as 3 primeiras ações), e
`pr_review_humana` (aguardando humano — cobre `necessita_humano`, indisponibilidade e
o caso "aprovado mas risco exige confirmação").

**(8) Persistência — colunas em tabelas existentes, sem tabela nova.**
`pull_requests` ganha `review_verdict` (JSONB), `reviewed_by`, `review_rounds`;
`kanban_cards` ganha `executor`. Migration `b6e2f4a91c53`, `down_revision =
40812903e932`.

## Dois pontos herdados da ADR-0016 (avaliação do Incremento A)

A avaliação do incremento anterior identificou duas pendências não registradas nas
Consequências da ADR-0016, resolvidas aqui:

- **CLI sem triagem.** `cli/main.py` chamava `create_orchestration` direto —
  orquestrações criadas pela CLI nasciam com `demand_brief` vazio e `priority=low`
  fixo. A causa raiz era duplicação: a sequência triagem→criação só existia em
  `app.py`. Corrigido com um único ponto de entrada, `create_with_triage`, usado por
  `app.py` e por `cli/main.py`; `create_orchestration` permanece como está (usada em
  dezenas de testes).
- **Re-triagem sem re-plano.** `retriage_demand` atualizava a ficha e fazia o bloqueio
  `demanda_incompleta` sumir, mas o `ExecutionPlan` continuava o da triagem original —
  o mecanismo que a ADR-0016 existe para ligar ficava desligado no caminho de correção.
  Corrigido: `retriage_demand` recomputa o `ExecutionPlan` e a prioridade dos cards
  **enquanto nenhum card saiu de `Ready`**; depois de executado, replanejar mentiria
  sobre o trabalho já feito (mesma razão de `_validate_assignment_key` recusar
  reconfigurar uma fase que já passou) — o plano é preservado e o motivo (`
  ReplanSkipped`) é devolvido na resposta de `POST .../brief`.

## Consequências

**Positivas**
- Nenhum caminho aprova uma PR sem veredito registrado ou justificativa humana — o
  merge governado (ADR-0009) tem as duas travas reais agora.
- O revisor é sempre diferente do executor que implementou o card (ou a revisão recusa
  com motivo explícito).
- Risco alto ou impacto sensível não fecha revisão sozinho, mesmo com o agente
  aprovando.
- Card reprovado tem destino próprio (`NeedsFix`) e ações objetivas que chegam ao
  agente na re-execução — fecha o §15.
- CLI e API criam orquestrações pelo mesmo caminho (`create_with_triage`); re-triagem
  antes da execução recalcula a equipe de verdade.

**Negativas / riscos aceitos**
- O revisor vê só o diff, não o código ao redor — erro de integração pode passar. É a
  limitação aceita explicitamente na decisão (1); mitigação futura ficaria para um
  incremento de revisão com contexto mais amplo, fora de escopo aqui.
- A aprovação automática por risco depende da qualidade da triagem (ADR-0016): uma
  ficha que não capturou um impacto sensível não aciona `exige_confirmacao_humana`.
- O fallback deliberadamente pessimista (`necessita_humano`) significa que qualquer
  instabilidade do agente revisor aumenta a fila de aprovação humana — trade-off aceito
  em troca de nunca aprovar por omissão.

## Emenda (2026-07-30, ADR-0019)

**Bug encontrado na avaliação deste incremento:** `report_review("approved")` só
checava se havia um veredito aprovado, nunca se o **risco da demanda** exigia
confirmação humana (`exige_confirmacao_humana`). Em demanda de alto risco, o agente
aprovando bastava para fechar a revisão — a "confirmação humana" da decisão (3) virava
um clique de `operator` sem justificativa, mesmo com o `next_step` anunciando
`role="admin"` no bloqueio `pr_review_humana`. Corrigido na
[ADR-0019](ADR-0019-roteamento-de-falha.md) §4.7: `report_review` agora exige
justificativa também quando `exige_confirmacao_humana(brief)` é verdadeiro, mesmo com
veredito aprovado.
