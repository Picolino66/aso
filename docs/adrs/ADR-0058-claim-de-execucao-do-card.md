# ADR-0058 — Claim atômico (lease) de execução do card

- **Status:** ACCEPTED
- **Fase:** F5 (correção de concorrência — MEL-13, origem `feedback.md` §3 e §14 experimento 7)
- **Data:** 2026-09-15
- **Relaciona-se com:** [ADR-0018](ADR-0018-kanban-fiel-colunas-e-dependencias.md) (colunas e
  dependências do card), [ADR-0027](ADR-0027-sobrevivencia-a-crash.md) (card órfão após crash —
  complementada aqui), [ADR-0019](ADR-0019-roteamento-de-falha.md) (laço de retry de `run_card`),
  [ADR-0051](ADR-0051-auditoria-com-filtros.md) (`execution_id` nos `CardEvent`)

## Contexto

`run_card` não adquiria `_lock_for` nem verificava se o card já estava rodando, e o
evento `AgentStarted` (→ `InProgress`) só era aplicado **depois** que o agente
terminava, dentro de `_apply_execution`. Consequências observadas:

- duas threads chamando `run_card` no mesmo card executavam o agente duas vezes;
- durante toda a execução o card aparecia `Ready`;
- um crash no meio deixava o card `Ready`, sem registro de que estava rodando.

`run_plan` e `race_card` tinham a mesma lacuna. A ADR-0027 tratou o card órfão só por
heurística de tempo (`updated_at` parado há mais que `ASO_AGENT_TIMEOUT`), porque não
havia sinal de "quem está executando".

## Opções consideradas

1. **Segurar `_lock_for` durante a execução inteira.** Simples, mas serializa toda a
   orquestração por minutos (agentes CLI) e bloqueia leituras que pegam o lock.
2. **Só mudar a coluna para `InProgress` antes de executar.** Não é atômico sem lock e
   confunde estado de exibição (movível manualmente) com posse da execução.
3. **Claim/lease explícito no card, adquirido e liberado sob lock, execução fora do
   lock.** Adotada.

## Decisão

- `KanbanCard` ganha `em_execucao_desde`, `execution_id` (tentativa corrente) e
  `execucao_dono` (id da instância do `OrchestrationService`, `gen_id("runtime")`),
  persistidos em `kanban_cards` (colunas nulas; NULL = livre).
- **Claim** (`_reivindicar_card`, chamador detém `_lock_for`): recusa com
  `ValueError("… já em execução …")` (409 na API) se `em_execucao_desde` estiver
  preenchido; grava os três campos, aplica `AgentStarted` com `effort`/`phase`/
  `execution_id` e **persiste na hora**. O claim — não a coluna — é a fonte de verdade:
  `InProgress` sem claim (movimento manual, dado legado) não bloqueia execução.
- **Execução fora do lock**; o resultado é aplicado sob lock (`_apply_execution`, que não
  aplica mais `AgentStarted`).
- **Release** em `finally` sob lock (`_liberar_claim` + `_persist`), inclusive quando
  algo fora do provider levanta exceção. O laço de retry de `run_card` mantém o claim
  entre tentativas (novo `execution_id` + novo `AgentStarted` por tentativa).
- `run_plan` reivindica cada card `Ready` antes da onda e pula card já reivindicado;
  `race_card` reserva só o lease (`mover=False`: corrida não muda a coluna).
- `move_card_validado` (movimento manual) recusa card com claim ativo.
- **Recuperação:** ao reidratar uma orquestração (`_bundle` → `_hydrate`), card com
  claim de **outra** instância é execução interrompida — o runtime é single-process e o
  dono não existe mais. O card é liberado, movido para `Failed` com motivo
  "execução interrompida (reinício do runtime)" e o evento `ExecutionInterrupted` é
  registrado e persistido. Claims da própria instância nunca são tocados — o critério é
  o dono, não "estar no cache", para continuar correto quando o cache passar a
  descartar bundles (MEL-33).

## Consequências

- Uma gravação extra por execução (claim) e uma no release — aceitável; MEL-33 reduz o
  custo com persistência incremental.
- `GET .../cards` mostra `InProgress` enquanto o agente roda.
- A heurística `card_orfao` da ADR-0027 continua valendo para cards `InProgress` sem
  claim (dados anteriores a esta ADR, movimentos manuais).
- A recuperação é preguiçosa: acontece na primeira reidratação da orquestração após o
  reinício (qualquer leitura que a hidrate), não numa varredura de boot.
- **Limite conhecido:** com múltiplos processos (MEL-56) o critério "dono diferente =
  morto" deixa de valer e precisará de heartbeat/expiração do lease. A fila com workers
  (MEL-31) parte deste claim.
