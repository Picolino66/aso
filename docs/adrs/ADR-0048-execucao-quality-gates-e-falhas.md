# ADR-0048 — Execução, quality gates e tratamento de falhas (Telas 15, 16 e 17)

- **Status:** ACCEPTED
- **Fase:** F4 (evolução pós-O5)
- **Data:** 2026-08-08
- **Relaciona-se com:** [ADR-0019](ADR-0019-roteamento-de-falha.md)
  (`control/failure.py` — `proximo_effort`/`proximo_executor`/`diagnosticar`,
  reaproveitados aqui tal como são, sem nenhuma mudança), [ADR-0022](ADR-0022-bateria-de-validacoes-e-effort-automatico.md)
  (`QualityGateEngine`), [ADR-0041](ADR-0041-detalhes-do-card-em-dez-abas.md)
  (`card-detalhe.html`, expandida aqui — mesmo padrão do FID-18/Discovery),
  [ADR-0044](ADR-0044-classificacao-editavel-e-recomendacao.md) (confiança
  categórica, mesmo raciocínio reaproveitado para o diagnóstico de falha),
  [`wiframe-fluxo.md`](../../wiframe-fluxo.md) §17 (Tela 15), §18 (Tela 16),
  §19 (Tela 17)

## Contexto

Numeração conferida sem divergência (§17=Tela 15, §18=Tela 16, §19=Tela 17).
O conteúdo das três telas é sobre **um card específico em execução**, não
sobre a demanda inteira — investigação prévia confirmou que o lugar correto é
expandir `card-detalhe.html` (FID-14/ADR-0041, já tem abas "Execuções" e
"Testes"), não criar página nova, mesmo padrão já usado no FID-18 para a aba
Discovery de `demanda-detalhe.html`. As seções fixas da sidebar `/ui/execucoes`
e `/ui/testes` (mapeadas para este card, `/ui/testes` compartilhada com o
FID-22) viram **listas agregadas por demanda**, com drill-down para
`card-detalhe.html` — mesmo padrão kanban macro vs. kanban por card do FID-20.

Investigação prévia contra os 8 controles em voo do wf §17.2 encontrou: 3 já
reais (Cancelar, Transferir agente, Marcar bloqueado); 2 só automáticos
dentro do roteamento de falha (Aumentar effort, Trocar modelo — funções
puras reutilizáveis, sem endpoint manual); 2 sem nenhum suporte (Pausar,
Adicionar contexto); 1 com mecanismo adjacente não idêntico (Solicitar
ajuda ~ `HumanApproval`). Contra as "7 decisões do orquestrador" do wf
§19.2, só 5 ações existem no código (`ACAO_MESMO_AGENTE`,
`ACAO_AUMENTAR_EFFORT`, `ACAO_TROCAR_EXECUTOR`, `ACAO_ESCALAR_HUMANO`,
`ACAO_BLOQUEAR`) — faltam "Trocar modelo" (hoje embutido em "trocar
executor") e "Criar investigação separada" (não existe). Duração por
critério de quality gate não existia em lugar nenhum da cadeia de
execução. "Diagnóstico"/"confiança" de falha não eram campos persistidos —
só calculados sob demanda (`diagnosticar`), sem confiança nenhuma.

Duas decisões foram confirmadas com o usuário.

## Decisão

**(1) `card-detalhe.html` ganha uma 11ª aba ("Falhas") e as abas "Execuções"/
"Testes" são expandidas** (opção recomendada, aprovada) — não páginas
satélite novas. `/ui/execucoes?id=` e `/ui/testes?id=` (opção recomendada)
viram listas agregadas (todos os cards da demanda) com link para o card
específico, mesmo padrão de `/ui/kanban` (FID-20) e `/ui/documentos`
(FID-19).

**(2) 6 dos 8 controles em voo ganham funcionalidade real** (opção
recomendada, aprovada):
- **Cancelar/Transferir agente/Marcar bloqueado**: reaproveitados como
  estão (`cancel_card`/`assign_agent`/`block_card`, já existiam).
- **Aumentar effort/Trocar modelo**: dois métodos novos
  (`increase_card_effort`/`transfer_card_model`) que reaproveitam **as
  mesmas funções puras** do roteamento automático de falha
  (`proximo_effort`/`proximo_executor`, ADR-0019) — zero lógica de decisão
  duplicada, só um novo caminho manual de acioná-las. Efeito real: gravam
  `card.effort_override`/`card.executor_override`, dois campos novos que
  **vencem a resolução normal de etapa na próxima execução** (`run_card`
  passa a considerá-los com a mesma prioridade de um parâmetro explícito de
  chamada).
- **Adicionar contexto**: novo campo `card.contexto_adicional: list[str]`,
  que passa a entrar no próximo prompt do agente (`_build_task`), ao lado
  de `correction_actions`.
- **Solicitar ajuda**: reaproveita `request_approval` (já genérico, já
  aceita `card_id`), com a ação rotulada `"solicitar_ajuda"` — nenhum
  mecanismo de aprovação novo.
- **Pausar**: reinterpretação honesta e restrita — `card.pausado: bool`
  impede a **próxima** execução (`run_card` recusa com 409 se `pausado`),
  não interrompe um processo em andamento (nada no runtime hoje suporta
  isso — a chamada ao CLI, mesmo quando streaming como em
  `cli_provider.py`, não tem um mecanismo de cancelamento a meio caminho
  exposto). `/retry` já absorve esse novo `ValueError` silenciosamente
  (mesmo tratamento que já dava a qualquer outra rejeição de `run_card`),
  sem precisar de nenhuma mudança lá.

**(3) Das 7 decisões do orquestrador (wf §19.2), 6 mapeiam para ações reais
já existentes ou construídas neste card** — Manter mesmo agente (reexecutar,
`POST .../run`), Trocar agente (`assign_agent`), Trocar modelo
(`transfer_card_model`, novo), Aumentar effort (`increase_card_effort`,
novo), Solicitar revisão humana (`request_card_help`, novo), Bloquear
(`block_card` — **bloqueia o card**, não "a demanda" como o rótulo do
wireframe sugere; não existe bloqueio de demanda inteira no runtime,
rotulado honestamente na UI). **"Criar investigação separada" fica
desabilitada com tooltip** — não existe nenhum mecanismo de investigação
separada da demanda principal hoje; construir um exigiria decisão de
produto própria (o que seria uma "investigação"? um card? uma nova
orquestração?), fora do escopo deste card.

**(4) Diagnóstico e confiança calculados NA LEITURA, nunca persistidos como
palpite.** Novo método `get_card_failure_diagnostics` aplica `diagnosticar()`
(já existia) e a nova função pura `confianca_diagnostico()` a cada
`FailureRecord` do ring — `"alta"` quando a falha veio de uma verificação
nomeada da bateria (`categoria` preenchida, fato), `"baixa"` quando caiu na
heurística por palavra-chave. Categórica, nunca um percentual — mesmo
raciocínio já usado para a confiança da recomendação de roteamento
(ADR-0044).

**(5) Duração real por critério de quality gate.** `QualityGateEngine.run`
mede `time.monotonic()` em volta de cada predicado (linha única de mudança,
cobre TODOS os critérios uniformemente — comando externo ou em memória).
Novo campo `GateCriterionResult.duration_ms`, com migration nova em
`gate_criteria` (tabela normalizada) — testado end-to-end no Postgres real
via Docker.

**(6) "Arquivos alterados" via novo `WorktreeManager.changed_files`**
(`git diff --name-only`, mesma comparação de `branch_diff` já existente, só
os caminhos) — lista vazia quando o card nunca teve branch, honesto, não
fabricado.

**(7) "Logs da execução" são um fetch único, filtrado por `card_id` no
cliente** — `GET .../agent-log` já existia (global da orquestração, com
`card_id` por linha); a novidade é só o filtro. Não é streaming ao vivo:
`card-detalhe.html` nunca teve polling (diferente de `detalhe.html`), e
adicionar isso só para esta aba quebraria a consistência do resto da
página — mesmo raciocínio de escopo já usado no FID-18 para os logs de
discovery.

**(8) "Plano passo a passo" do wf §17.1 não virou um checklist fictício.**
Investigação confirmou que nenhum mecanismo rastreia progresso granular
tipo "Implementar repositório" (✓/→/○) — só o `preparation_checklist` (5
itens fixos de passagem de contexto, já mostrado na aba Plano) e os
`CardEvent` de movimentação de coluna (granularidade de Kanban). Não
duplicado nem fabricado aqui — a aba Execuções aponta implicitamente para
a aba Plano já existente, sem inventar uma terceira fonte de verdade.

## Consequências

**Positivas**
- 4 dos novos controles (Aumentar effort, Trocar modelo, diagnóstico,
  confiança) reaproveitam 100% funções puras já existentes e testadas do
  roteamento automático de falha — zero lógica de decisão nova ou
  duplicada.
- `run_card` ganha os overrides do card na MESMA ordem de prioridade que já
  usava para parâmetros explícitos — sem introduzir um segundo mecanismo de
  resolução paralelo.
- Migrations novas validadas em Postgres real via Docker, não só SQLite.

**Negativas / riscos aceitos**
- "Pausar" não interrompe execução em andamento — só a próxima. Documentado
  como reinterpretação restrita, não a semântica literal do wireframe.
- "Bloquear demanda" (wf §19.2) na prática bloqueia o card — rotulado
  honestamente na UI (`"Bloquear (card)"`), não escondido.
- "Criar investigação separada" fica permanentemente desabilitada — 1 das
  7 decisões sem suporte real.
- Logs da execução são um retrato do momento do carregamento da página, não
  ao vivo — mesma limitação já aceita para o discovery no FID-18.
- Quality gates no painel do card mostram o resultado da FASE do card, não
  um resultado por-card (gates não têm essa granularidade no domínio) —
  rotulado explicitamente como "quality gates da fase X", não inventando
  uma correspondência 1:1 card↔gate que não existe.
