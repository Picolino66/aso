# ADR-0013 — Tela de detalhe orientada a "próximo passo" + motor no runtime

- **Status:** ACCEPTED
- **Fase:** F5 (evolução pós-O5)
- **Data:** 2026-07-28
- **Relaciona-se com:** [ADR-0003](ADR-0003-contextbus-governance.md) (ContextBus soberano),
  [ADR-0009](ADR-0009-entrega-de-codigo-governada.md) (merge governado),
  [ADR-0010](ADR-0010-catalogo-multi-repo-governado.md) (catálogo multi-repo),
  [ADR-0012](ADR-0012-drift-check-docs-first.md) (drift de docs)

## Contexto

A [ADR-0010](ADR-0010-catalogo-multi-repo-governado.md) trouxe o catálogo multi-repo
(`/ui/` com projetos e kanban macro) e a navegação para `/ui/detalhe?id=…`. Só que a rota
servia o **console genérico** (`index.html`): ele nunca lia o `?id=`, exigia um segundo
clique na barra lateral e, ao abrir, repetia o formulário "Nova orquestração" e um kanban
de 12 colunas — quase todas vazias — sobre uma orquestração já escolhida.

O efeito prático é que a tela mostrava **onde** os cards estavam parados, mas nunca **por
que** nem **o que clicar**. As regras que decidem se a esteira anda existem e são
verificáveis, porém espalhadas pelo runtime: `start_autopilot` recusa sem
`validation_command`; `run_phase` só chega ao gate com os cards de F5/F6 mesclados;
`merge_pr` exige CI `passed` + review `approved`; gate reprovado bloqueia o avanço; o
autopilot pausa na aprovação humana. O operador precisava reconstruir isso de cabeça a
partir de contadores.

## Opções consideradas

1. **Corrigir só a navegação** — ler o `?id=` e abrir a orquestração direto no console
   atual. Rejeitada: resolve o clique duplo, mas mantém a tela respondendo à pergunta
   errada (estado bruto em vez de decisão).
2. **Tela nova com a lógica em JavaScript** — o console calcula os bloqueios lendo os
   endpoints existentes. Rejeitada: cria uma **segunda fonte de verdade** de governança,
   que envelhece em silêncio a cada regra nova no serviço e não entra na cobertura de
   testes.
3. **Motor de próximo passo no runtime + tela que só renderiza.** Escolhida.

## Decisão

Adotar a **opção 3**, em duas peças.

**(1) Motor.** Novo módulo `control/next_step.py` com `compute_next_step(NextStepInput)
→ NextStepReport`, **função pura** (sem I/O) sobre um retrato do estado governado. Ele
produz: a fase e seu rótulo, o `checklist` do ciclo da fase (workspace → docs-first →
validação → cards executados → entrega mesclada → gate → aprovação, com o item "atual"
marcado), a lista ordenada de `blockers` e a `primary_action`. Cada bloqueio carrega
`code`, `severity` (`bloqueia` > `aguardando_humano` > `acao_do_operador` >
`informativo`), texto explicativo e a rota da API v1 que o destrava — inclusive o papel
exigido (`admin` em merge, aprovação e sincronização de catálogo). A ordenação por
severidade é o que elege a ação primária.

Taxonomia coberta: `workspace_ausente`, `validacao_ausente`, `executor_indisponivel`,
`docs_first_pendente`, `aprovacao_pendente`, `pr_ci_pendente`, `pr_review_pendente`,
`pr_pronto_merge`, `conflitos_abertos`, `cards_bloqueados`, `cards_falhos`,
`cards_aguardando_humano`, `cards_prontos`, `cards_em_backlog`, `sem_cards_na_fase`,
`entrega_pendente`, `gate_pendente`, `gate_reprovado`, `drift_docs` (§ADR-0012),
`slo_em_risco`, `cancelada`. `OrchestrationService.next_step` coleta o estado e expõe o
resultado em `GET /v1/orchestrations/{id}/next-step`.

**(2) Tela.** `/ui/detalhe` passa a servir `static/detalhe.html`, dedicada a **uma**
orquestração: cabeçalho com breadcrumb do projeto, esteira F1→F7, o card **"Próximo
passo"** (manchete + checklist + botão primário), o funil **só da fase corrente**, as
pendências de governança com a ação de cada uma, atividade ao vivo (SSE) e um acordeão
"Detalhes técnicos". Some dali o formulário de criação (já existe em `/ui/nova`) e o
kanban de 12 colunas (já existe, com sentido, no macro `/ui/`). O console técnico
completo continua disponível em `/ui/console` para auditoria.

## Trade-offs

- **+** Fonte única de verdade: a regra de governança nasce no runtime, é testada em
  pytest e a UI não pode divergir dela.
- **+** O mesmo contrato serve a outras superfícies (CLI, card do projeto no macro) sem
  reimplementação.
- **+** *Progressive disclosure*: nada foi removido do console técnico; ele deixou de
  competir com a decisão do momento.
- **−** Uma regra nova de bloqueio precisa ser registrada em dois lugares (o serviço que a
  aplica e o motor que a anuncia) — mitigado por um teste por bloqueio.
- **−** `next-step` agrega várias leituras (cards, aprovações, PRs, gates, drift, SLO) por
  requisição; hoje isso é barato porque tudo vem do bundle e o drift é só leitura de disco.

## Consequências

- `GET /v1/orchestrations/{id}/next-step` passa a ser o contrato de "o que falta"; a tela
  de detalhe é um cliente burro dele.
- `/ui/detalhe?id=…` abre direto na orquestração escolhida — o clique duplo desaparece.
- `/ui/console` preserva as abas de auditoria (patches, snapshots, corridas, custos, SLO).
- Evolução natural: exibir o resumo de `next-step` no card de cada orquestração no kanban
  macro, para o operador priorizar entre projetos sem abrir cada uma.
