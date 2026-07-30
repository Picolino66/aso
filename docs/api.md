# API — ASO Runtime

> Fase F3. Contrato-first. Versão base **v1**. Spec de máquina em [`contracts/openapi.yaml`](../contracts/openapi.yaml).
> Consistência forte; erros padronizados; idempotência em operações de criação (ver [ADR-0005](adrs/ADR-0005-data-consistency-and-api-versioning.md)).

## Convenções

- Prefixo de versão: `/v1`.
- Formato de erro (RFC 7807-like): `{ "type", "title", "status", "detail", "instance" }`.
- Idempotência: header `Idempotency-Key` em `POST` de criação (orchestrations, cards, adrs, approvals).
- Paginação: `?page`, `?page_size`; resposta `{ items[], total, page, page_size }`.
- Datas em ISO8601 UTC. IDs em UUID (exceto ADR: `ADR-XXXX`).

## Superfície de endpoints

### Workspace
```
GET    /v1/fs/dirs                         # navegador de pastas; só diretórios
GET    /v1/fs/analyze/stream?path=/projeto # SSE de pré-análise somente leitura
POST   /v1/orchestrations/{id}/analyze-folder # gera/atualiza docs-first governado
```

`GET /v1/fs/analyze/stream` retorna eventos SSE com `percent`, `current`, `total`
e `file` (caminho relativo). Ele valida e enumera apenas arquivos regulares,
ignorando diretórios técnicos como `.git`, caches, ambientes virtuais e
`node_modules`; não inicializa Git, não escreve documentação e não cria uma
orquestração. O console usa esse passo antes de liberar a demanda. A geração de
documentação docs-first continua em `POST .../analyze-folder`, já vinculada a uma
orquestração e sujeita à governança definida na ADR-0008.

### Executores e recuperação

```
GET    /v1/executors
POST   /v1/executors/sync                         # admin; Codex model/list
PATCH  /v1/orchestrations/{id}/execution-settings # operator; created/blocked
PUT    /v1/orchestrations/{id}/agents/{key}       # executor da etapa; body {executor, effort}
DELETE /v1/orchestrations/{id}/agents/{key}       # volta a etapa ao padrão
```

Perfis Codex gerenciados expõem `managed_by`, `supported_efforts`, `available`,
`availability_reason` e `runtime_version`. Modelo ou esforço indisponível retorna `409`
antes do worktree. A sincronização preserva perfis personalizados. O PATCH registra
`ExecutionSettingsUpdated`; comandos contínuos retornam `400`.

`{key}` é uma fase (`F1`..`F7`) ou `naming`, o agente que batiza branches e commits
([ADR-0014](adrs/ADR-0014-agente-por-etapa-e-nomes-semanticos.md)). O mapa resultante sai
em `agent_assignments` no `GET` da orquestração. A resolução do executor de uma execução
é, nesta ordem: parâmetro explícito da chamada → `agent_assignments[fase]` →
`selected_executor` → default do catálogo (quando há pasta) → provider global. Uma etapa
com executor próprio **não** herda `selected_effort` — o esforço casa com o modelo, então
sem esforço na etapa vale o do perfil. Fase que já ficou para trás retorna `409`
(`index(fase) < index(current_phase)`); `naming` é sempre editável. Ambos registram
`AgentAssignmentUpdated` com `before`/`after`/`actor`.

Para execução de código, a criação aceita `execution_mode`, `executor`, `effort` e
`validation_command`. O modo `code-execution` inicia em F5 e exige validação. A PR só
avança após `POST /v1/orchestrations/{id}/pulls/{pr}/ci/run`, revisão humana e merge.

### Projetos

```
GET    /v1/projects?include_archived=false
POST   /v1/projects
GET    /v1/projects/{id}
PATCH  /v1/projects/{id}                  # PUT é alias compatível
DELETE /v1/projects/{id}                  # arquiva; exige admin
POST   /v1/projects/{id}/restore           # exige admin; aceita novo target_path
GET    /v1/projects/{id}/events
```

`target_path` é obrigatório na criação, canonicalizado e único inclusive para projetos
arquivados. O `DELETE` nunca apaga orquestrações: altera o status para `archived` e
registra ator, estado anterior e posterior em `project_events`. Projetos arquivados não
aceitam novas orquestrações e ficam ocultos da listagem padrão.

### Orchestrations (§28.1)
```
POST   /v1/orchestrations
GET    /v1/orchestrations?project_id={projeto}
GET    /v1/orchestrations/{id}
GET    /v1/orchestrations/{id}/context
GET    /v1/orchestrations/{id}/plan
GET    /v1/orchestrations/{id}/timeline
GET    /v1/orchestrations/{id}/next-step    # o que falta para a esteira seguir
GET    /v1/orchestrations/{id}/agent-log?after={seq}&limit={n}   # saída ao vivo do agente
GET    /v1/phases                           # catálogo didático da esteira F1..F7
POST   /v1/orchestrations/{id}/resume
POST   /v1/orchestrations/{id}/cancel
POST   /v1/orchestrations/{id}/rollback     # body: { to_snapshot: "O3" }
POST   /v1/orchestrations/{id}/retry
PATCH  /v1/orchestrations/{id}/execution-settings
```

Ao receber `project_id`, `POST /v1/orchestrations` exige projeto ativo e copia seu
`target_path`. Um path divergente retorna `409`. Essa cópia não muda quando o projeto é
editado ou arquivado; orquestrações sem projeto continuam válidas por compatibilidade.

`GET /v1/orchestrations/{id}/next-step` é o contrato de **"o que falta"**
([ADR-0013](adrs/ADR-0013-tela-de-detalhe-por-proximo-passo.md)): devolve a fase e seu
rótulo, `next_phase`, o `checklist` do ciclo da fase (workspace → docs-first → validação →
cards executados → entrega mesclada → gate → aprovação, com o item corrente em `atual`),
a lista `blockers` — cada um com `code`, `severity` (`bloqueia` > `aguardando_humano` >
`acao_do_operador` > `informativo`), `detail` e a `action` (método, rota v1, `body` e
`role` exigido) — e a `primary_action`, que é a ação do bloqueio de maior severidade.
As regras vêm do runtime, não da UI: é a mesma governança aplicada por `run_phase`,
`merge_pr`, o quality gate e o autopilot.

`GET /v1/orchestrations/{id}/agent-log` devolve a saída dos agentes CLI **enquanto eles
trabalham** ([ADR-0015](adrs/ADR-0015-observabilidade-ao-vivo-da-execucao.md)):
`{lines, next, running, sessions, last_seq, retained}`. Cada linha traz `seq`, `at`,
`stream` (`stdout`/`stderr`/`aso`), `kind` (`texto`/`ferramenta`/`resultado`/`marco`/`bruto`),
`text`, `detail`, `card_id`, `agent` e `executor`. `after` é o cursor: passe o `next` da
resposta anterior para receber só o que ainda não viu — o que permite acompanhar a execução
e também reexibir o log ao recarregar a página. O ring guarda as últimas 2 000 linhas por
orquestração **em memória**, então não sobrevive a um restart da API. Cada tentativa do
`AgentSupervisor` é uma sessão própria (ele tenta 2x), e `running` fica `true` enquanto
qualquer uma delas estiver aberta.

`GET /v1/phases` devolve `[{id, label, nome, resumo, entrega}]` para F1..F7 — a explicação
didática de cada etapa, para a UI montar a esteira sem duplicar texto.

`GET /v1/orchestrations/{id}/timeline` aceita `newest_first=true`, aplicado na consulta ao
banco. Sem ele, pedir "as N últimas atividades" devolvia as N **mais antigas**.

### Kanban (§28.2)
```
GET    /v1/boards
POST   /v1/boards
GET    /v1/boards/{id}
GET    /v1/boards/{id}/cards
POST   /v1/boards/{id}/cards
PATCH  /v1/cards/{id}
POST   /v1/cards/{id}/move          # body: { to_column }
POST   /v1/cards/{id}/assign-agent  # body: { agent_role | executor }
POST   /v1/cards/{id}/run
POST   /v1/cards/{id}/block         # body: { reason }
POST   /v1/cards/{id}/unblock
```

### Agents & execução (§28.3, §26A.8)
```
GET    /v1/agents
GET    /v1/agents/{id}
GET    /v1/agents/{id}/runs
POST   /v1/agents/{id}/run
POST   /v1/agent-runs/{id}/cancel
POST   /v1/agent-runs/{id}/nudge

GET/POST/PATCH/DELETE  /v1/providers ; POST /v1/providers/{id}/test ; GET /v1/providers/{id}/models
GET/POST/PATCH/DELETE  /v1/cli-agents ; POST /v1/cli-agents/{id}/detect ; POST /v1/cli-agents/{id}/test
GET/POST/PATCH/DELETE  /v1/agent-role-bindings
POST   /v1/agent-router/preview
POST   /v1/agent-router/select
```

### Governança (§28.4–28.7)
```
GET    /v1/orchestrations/{id}/quality-gates
POST   /v1/orchestrations/{id}/quality-gates/run   # body: { phase }
GET    /v1/quality-gates/{id}

GET    /v1/orchestrations/{id}/adrs
POST   /v1/orchestrations/{id}/adrs
GET    /v1/adrs/{id}
PATCH  /v1/adrs/{id}
```

### Consultas (lado de leitura / CQRS-lite)
```
GET    /v1/orchestrations/{id}/cards/stats                  # contagem por status
GET    /v1/orchestrations/{id}/cards/by-status/{status}     # ids de cards por status
GET    /v1/orchestrations/{id}/adrs/by-status/{status}      # ids de ADRs por status
GET    /v1/orchestrations/{id}/adrs/{adr_id}/linked-cards   # consulta reversa (card_links)

GET    /v1/orchestrations/{id}/snapshots
POST   /v1/orchestrations/{id}/snapshots
GET    /v1/snapshots/{id}
POST   /v1/snapshots/{id}/restore
GET    /v1/snapshots/{a}/diff/{b}

GET    /v1/approvals ; GET /v1/approvals/{id}
POST   /v1/approvals/{id}/approve ; POST /v1/approvals/{id}/reject

POST   /v1/context-patches            # submete patch ao ContextBus
GET    /v1/orchestrations/{id}/conflicts
```

## Regras de contrato relevantes

- `POST /v1/context-patches` nunca escreve direto: enfileira no ContextBus, que roda o pipeline de 7 etapas (§19) e responde `applied | rejected | queued_conflict`.
- `POST /v1/cards/{id}/run` só executa se as dependências (`depends_on`) estiverem `Done` e permissões de tool forem satisfeitas.
- `rollback` exige que `to_snapshot` seja um snapshot existente e aprovado; gera ADR de rollback.
- Ações críticas (§24) retornam `202 Accepted` + criam `HumanApproval` pendente em vez de executar.
- Leitura exige `viewer`; criar/editar projeto exige `operator`; arquivar/restaurar exige
  `admin`. O ator autenticado é persistido no evento do projeto.
