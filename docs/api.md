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

`{key}` é uma fase (`F1`..`F7`), `naming` (agente que batiza branches e commits,
[ADR-0014](adrs/ADR-0014-agente-por-etapa-e-nomes-semanticos.md)), `triagem` (agente
que interpreta a demanda, [ADR-0016](adrs/ADR-0016-ficha-da-demanda.md)) ou `revisao`
(agente que revisa o diff de uma PR, [ADR-0017](adrs/ADR-0017-revisao-independente-de-codigo.md)).
O mapa resultante sai em `agent_assignments` no `GET` da orquestração. A resolução do
executor de uma execução é, nesta ordem: parâmetro explícito da chamada →
`agent_assignments[fase]` → `selected_executor` → default do catálogo (quando há pasta)
→ provider global. Uma etapa com executor próprio **não** herda `selected_effort` — o
esforço casa com o modelo, então sem esforço na etapa vale o do perfil. Fase que já
ficou para trás retorna `409` (`index(fase) < index(current_phase)`); `naming`,
`triagem` e `revisao` são sempre editáveis (não são fase). Todos registram
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
GET    /v1/orchestrations/{id}/brief        # ficha estruturada da demanda (§1/§2)
POST   /v1/orchestrations/{id}/brief        # re-tria; body {executor, effort} (opcionais)
GET    /v1/orchestrations/{id}/discovery         # relatório de discovery atual (§3, ADR-0020)
GET    /v1/orchestrations/{id}/discovery/history # ring de até 5 versões (§4.2, ADR-0021)
POST   /v1/orchestrations/{id}/discovery/run     # roda o discovery; body {executor, effort} opcionais
POST   /v1/orchestrations/{id}/discovery/decide  # body {approved, comentario?}; admin (§4)
GET    /v1/orchestrations/{id}/spec              # especificação corrente (§5, ADR-0021)
GET    /v1/orchestrations/{id}/spec/history      # ring de até 5 versões
POST   /v1/orchestrations/{id}/spec/run          # gera/regenera; body {executor, effort} opcionais
POST   /v1/orchestrations/{id}/spec/review       # revisão documental (§6); body {executor?}
POST   /v1/orchestrations/{id}/spec/approve      # body {approved, comentario?}; admin (§4.4)
GET    /v1/orchestrations/{id}/validation-checks           # bateria efetiva (§12, ADR-0022)
PUT    /v1/orchestrations/{id}/validation-checks           # substitui a bateria; operator
GET    /v1/orchestrations/{id}/validation-checks/suggest   # sugestão determinística por stack
GET    /v1/orchestrations/{id}/deploy               # última implantação (§18-22, ADR-0023)
GET    /v1/orchestrations/{id}/deploy/history        # ring de até 5 tentativas
PUT    /v1/orchestrations/{id}/deploy/config         # comando/ambiente/health checks/rollback
POST   /v1/orchestrations/{id}/deploy/run            # §18 checklist + §19 executa
POST   /v1/orchestrations/{id}/deploy/validate       # §20 roda health checks
POST   /v1/orchestrations/{id}/deploy/approve        # admin — §22 aceite final
POST   /v1/orchestrations/{id}/deploy/rollback       # admin — §21, abre card de incidente
GET    /v1/orchestrations/{id}/cards/{card}/qa           # verificações de QA do card (§16, ADR-0025)
POST   /v1/orchestrations/{id}/cards/{card}/qa           # registra um QaCheck; operator
POST   /v1/orchestrations/{id}/cards/{card}/qa/{i}/fail  # reprova; cria o bug do §17; operator
GET    /v1/orchestrations/{id}/learning              # relatório de aprendizado da demanda (§24)
GET    /v1/learning                                  # mesmo relatório, consolidado entre todas
PUT    /v1/orchestrations/{id}/budget                # eleva/remove o teto de gasto; admin (ADR-0026)
GET    /v1/orchestrations/{id}/worktrees             # worktrees em disco, com `orfao` marcado (ADR-0027)
POST   /v1/orchestrations/{id}/worktrees/prune       # remove só os órfãos; admin (ADR-0027)
GET    /v1/orchestrations/{id}/pulls/{pr}/review       # veredito completo da revisão (§14)
POST   /v1/orchestrations/{id}/pulls/{pr}/review/run   # roda o agente revisor sobre o diff real
POST   /v1/orchestrations/{id}/pulls/{pr}/review       # reporta o resultado (governado, ADR-0017)
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

`POST /v1/orchestrations` roda a triagem da demanda **antes** de criar a orquestração
([ADR-0016](adrs/ADR-0016-ficha-da-demanda.md)): interpreta `user_request` numa ficha
estruturada (`tipo`, `objetivo`, `dominios`, `impactos`, `risco`, `complexidade`,
`perguntas_abertas`, …) que alimenta o `MultiAgentDecisionEngine` (estratégia, equipe,
aprovação humana) e a prioridade dos cards. O agente de triagem resolve, nesta ordem:
`executor` do corpo do `POST` → default do catálogo → heurística determinística
(`origem: "heuristica"`); a triagem **nunca** falha o `POST` — qualquer erro do agente
cai no caminho heurístico com `fallback_reason` preenchido. A ficha sai em
`demand_brief` no `GET` da orquestração e em `GET/POST .../brief`. `GET` exige
`viewer`, `POST` (re-triagem) exige `operator`. `perguntas_abertas` não vazio aparece
em `GET .../next-step` como bloqueio `severity: "aguardando_humano"` — não trava a
esteira.

`POST /v1/orchestrations/{id}/discovery/run` roda o discovery
([ADR-0020](adrs/ADR-0020-discovery-e-aprovacao.md), §3 do fluxo): analisa o workspace
(`WorkspaceAnalyzer`) e a `demand_brief` já triada, produzindo um `DiscoveryReport`
(situação atual, problema, componentes afetados, riscos, alternativas, recomendação
técnica, pontos de decisão). Exige `target_path` configurado (`409` senão). Sem agente
de discovery configurado (ou com falha), cai num resumo heurístico determinístico com
`confianca: "baixa"` — nunca falha. `exige_aprovacao_discovery` (§4) decide o `status`:
`aprovado` automático quando confiança alta e risco/impacto da demanda não são
sensíveis; senão `aguardando_aprovacao`. `POST .../discovery/decide`
(`{approved, comentario?}`) decide a aprovação pendente — ação crítica, exige `admin`;
reprovar registra o comentário, que entra no pedido da próxima chamada a `/run` para o
agente ajustar o documento. `GET .../discovery` traz o relatório atual (`status:
"rascunho"` = nunca rodado). O gate de F1 só exige `discovery_aprovado` quando um
relatório foi de fato gerado — orquestrações que nunca chamam `/discovery/run` (a
maioria, inclusive todo `CODE_EXECUTION`) não mudam de comportamento.

`POST /v1/orchestrations/{id}/spec/run` gera/regenera a especificação
([ADR-0021](adrs/ADR-0021-especificacao-e-revisao-documental.md), §5 do fluxo):
**exige discovery aprovado** — `409` senão. Produz um `SpecDocument` (o que será
construído, fora de escopo, como funciona, critérios de aceite, regras de negócio,
componentes, alterações de código/banco/infra, estratégia de testes, estratégia de
implantação, plano de rollback, checklist de segurança, `itens_de_trabalho`).
Diagramas/modelos opcionais do §5 (componentes, fluxo, dados, contrato de API,
migração) vão em Markdown dentro dos campos existentes — não há campos extras para
eles. Sem agente configurado (ou com falha), cai num esqueleto heurístico — nunca
falha, e **nunca sai `aprovado`** direto: todo documento passa por
`status: "aguardando_revisao"`. `POST .../spec/review` roda a revisão documental
(§6): dois dos nove eixos são checados **deterministicamente antes de qualquer
agente** — `estrategia_de_testes`/`plano_de_rollback` vazios reprovam sozinhos. O
revisor precisa ser diferente de quem produziu a spec (mesmo princípio do §14).
Esgotado `ASO_MAX_RODADAS_DOC` (default 3) rodadas de reprovação, o veredito vira
`necessita_humano` e só `POST .../spec/approve` (admin) decide. Aprovada
(`aprovado`/`aprovado_com_observacoes`), os `itens_de_trabalho` viram cards com
dependências resolvidas por título. `GET .../spec`/`GET .../spec/history` trazem a
versão corrente e o ring completo (§4.2) — mesmo padrão de
`GET .../discovery/history`. **`POST .../run-phase` recusa (`409`) rodar F5 sem
especificação aprovada** quando `execution_mode == "full_pipeline"` **e** o
discovery já foi usado (`GET .../discovery` diferente de `"rascunho"`) —
orquestrações que nunca chamam `/discovery/run` (a maioria, inclusive todo
`CODE_EXECUTION`) não mudam de comportamento.

`PUT /v1/orchestrations/{id}/validation-checks` substitui a bateria de validações do
§12 ([ADR-0022](adrs/ADR-0022-bateria-de-validacoes-e-effort-automatico.md)): uma
lista de `{nome, comando, categoria, bloqueante}`, cada `comando` validado por
`validate_gate_command` (o mesmo guard do `validation_command` legado — recusa
comando contínuo, `400`). Falha parcial não aplica nada. `GET .../validation-checks`
devolve a bateria **efetiva**: configurada, ou o `validation_command` legado
convertido numa única verificação `"testes"` — nenhuma orquestração pré-existente
muda de comportamento. `GET .../validation-checks/suggest` inspeciona o workspace
(`pyproject.toml`/`package.json`/`go.mod`/`Cargo.toml`) e sugere uma bateria por
stack sem gravar nada; `package.json` só sugere os scripts que existem de fato.
Nas fases F5/F6, `run_quality_gate` roda **um `Criterion` por verificação** — todas
rodam até o fim (sem parar na primeira falha), e uma verificação `bloqueante: false`
que falha vira `warnings`, não `blocking_issues`. Cada verificação nomeada também
alimenta o roteamento de falha (ADR-0019 emendada): a categoria decide o
diagnóstico direto, sem heurística por palavra-chave.

`Orchestration.demand_brief.complexidade` (coletada desde a ADR-0016) agora decide
o esforço efetivo quando nenhuma escolha humana o sobrepõe (§9 do fluxo,
ADR-0022): `sugerir_effort(complexidade, risco)` entra como penúltimo degrau da
resolução (`explícito → etapa → orquestração → sugestão automática → perfil`) e
emite `EffortSugerido` no timeline. `ASO_EFFORT_AUTOMATICO=0` desliga a automação.

`POST /v1/orchestrations/{id}/deploy/run` implanta o projeto orquestrado
([ADR-0023](adrs/ADR-0023-implantacao-governada.md), §18-19 do fluxo — **não
confundir com [`docs/deploy.md`](../deploy.md)**, que é sobre implantar o ASO
Runtime em si): exige `deploy_command` configurado (`PUT .../deploy/config`,
`409` senão) e o **último quality gate da orquestração** com `status: PASSED`
(`409` senão — "testes aprovados" do §18). Sempre executa o comando — a
decisão humana é sobre aceitar o resultado, não sobre autorizar a tentativa
(mesmo raciocínio do discovery). Implantação que falha vai direto a
`aceite_status: "reprovado"`; que sucede aplica a mesma regra de
`exige_aprovacao_discovery` (risco alto/crítico, impacto sensível ou validação
reprovada → `"aguardando_aprovacao"`; senão `"aprovado"` automático).
`POST .../deploy/validate` roda as verificações pós-implantação (§20,
reaproveita `ValidationCheck` da ADR-0022) e pode reabrir um aceite automático
para `aguardando_aprovacao` se reprovar. `POST .../deploy/approve` (admin) é o
aceite final (§22). `POST .../deploy/rollback` (admin, `{reason}`) marca a
implantação como revertida e **sempre** abre um `KanbanCard(type="Incident")`
em `Backlog` — a tarefa de análise de causa raiz do §21. `GET .../deploy` /
`GET .../deploy/history` trazem a versão corrente e o ring completo (§4.2,
mesmo padrão de discovery/spec). O gate de F6 ganha o critério
`deploy_aprovado` **só quando `deploy_runs` não está vazio** — orquestrações
que nunca chamam `/deploy/run` (a maioria) não mudam de comportamento.

`POST /v1/orchestrations/{id}/cards/{card}/qa` registra uma verificação manual
([ADR-0025](adrs/ADR-0025-qa-hierarquia-aprendizado.md), §16 do fluxo) — ring
de 10 por card. `POST .../qa/{i}/fail` reprova a verificação no índice `i`,
cria um card `Bug` vinculado por `dependencies` (e por `parent_id` quando a
hierarquia — §7, `KanbanCard.parent_id` — permitir) e registra a falha no
mesmo roteamento de `card.failures` (ADR-0019): diagnóstico `falha_de_qa`,
política `mesmo_agente → aumentar_effort → escalar_humano`, sem taxonomia
nova. `next_step` cobra `qa_pendente`/`qa_reprovado` só quando
`exige_qa_manual` (domínio `frontend`, complexidade `complexa`/`estrategica`,
ou tipo `Epic`/`Feature`) decide que o card precisa — fora disso, QA é
opcional. `GET /v1/orchestrations/{id}/learning` (e `GET /v1/learning`,
consolidado entre todas) devolve o relatório de aprendizado do §24: retrabalho,
falhas por etapa, desempenho por executor, taxa de aprovação, erros
recorrentes — **informativo, não altera nenhuma decisão automaticamente**
(a escolha de executor/modelo continua manual, §9). Desde a
[ADR-0026](adrs/ADR-0026-custo-real-e-orcamento.md), o relatório também traz
`custo_total_usd`/`custo_por_entrega`/`execucoes_sem_custo` por executor —
capturados do envelope real do CLI (`usage`/`total_cost_usd`) quando
disponível; sem isso, `execucoes_sem_custo` conta a execução em vez de
somá-la como custo zero.

`PUT /v1/orchestrations/{id}/budget` eleva ou remove (`teto_usd: null`) o
teto de gasto ([ADR-0026](adrs/ADR-0026-custo-real-e-orcamento.md), §1.2/§3.2
do plano7) — ação crítica, exige `admin`. Sem teto configurado, nenhuma
orquestração muda de comportamento. Com teto, `GET .../next-step` mostra
`orcamento_em_alerta` (informativo, ≥ 80%) ou `orcamento_estourado`
(bloqueia, ≥ 100%) — estourado recusa (`409`) **nova** chamada de
`POST .../cards/{id}/run` e `POST .../cards/{id}/race`, sem interromper uma
execução já em curso. Antes de `aumentar_effort`/`trocar_executor` (ADR-0019),
o roteamento de falha consulta o mesmo teto: estourado vira `escalar_humano`
com motivo de orçamento, em vez de escalar para um executor mais caro.

`GET /v1/orchestrations/{id}/worktrees` lista os worktrees em disco do
repositório da orquestração ([ADR-0027](adrs/ADR-0027-sobrevivencia-a-crash.md),
§1.4/§3.3 do plano7), cada um com `orfao: true/false` — órfão quando nenhum
card ativo (fora de `Done`/`Cancelled`/`Archived`) o referencia por
`branch`/`worktree`. Sempre devolve a lista completa, mesmo antes de
remover algo. `POST .../worktrees/prune` (admin) remove só os órfãos via
`git worktree remove` + `git worktree prune` — **nunca `rm -rf`** — e
devolve o que foi removido; o banco não é tocado. Um card `InProgress` cuja
`updated_at` passou de `ASO_AGENT_TIMEOUT` (default 1800s) sem se mover
aparece em `GET .../next-step` como `card_orfao`, com ação apontando para
`POST .../cards/{id}/route` (mesmo roteamento da ADR-0019 — nenhum caminho
novo de recuperação).

`POST /v1/orchestrations/{id}/pulls/{pr}/review/run` roda o agente revisor sobre o
**diff real** da PR ([ADR-0017](adrs/ADR-0017-revisao-independente-de-codigo.md)): sem
`executor` no corpo, resolve por `agent_assignments["revisao"]` → default do catálogo —
**desde que diferente do executor que rodou o card** (`card.executor`); se o único
candidato for o próprio implementador, a revisão recusa com
`fallback_reason="revisor seria o mesmo executor do card"` em vez de aprovar por
omissão. O fallback de indisponibilidade do agente é **sempre** `necessita_humano` —
nunca `aprovado` (diferente de `naming`/`triagem`, não existe revisão determinística).
O veredito sai em `review_verdict` no `GET` da PR e em `GET .../pulls/{pr}/review`.
`POST .../pulls/{pr}/review` reporta o resultado: `status: "approved"` só é aceito com
um veredito `aprovado`/`aprovado_com_sugestoes` já registrado **e**, se o risco da
demanda exigir confirmação humana (`exige_confirmacao_humana`, §4.3 da ADR-0017 —
risco alto/crítico ou impacto sensível), também com `justificativa` não vazia no
corpo — nesse caso a rota exige papel `admin` ([ADR-0019](adrs/ADR-0019-roteamento-de-falha.md)
§4.7, corrigindo um gate contornável: antes um veredito aprovado sozinho bastava
mesmo em risco alto). Sem veredito aprovado nenhum, `justificativa` também é
obrigatória e exige `admin`. Risco alto/crítico sem justificativa faz um veredito
aprovado ficar `review_status: "pending"` em vez de fechar sozinho. Veredito
`alteracoes_obrigatorias`/`reprovado` move o card para a coluna `NeedsFix` e grava as
ações obrigatórias em `card.correction_actions`, que chegam ao agente na
re-execução.

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
POST   /v1/cards/{id}/cancel        # body: { reason }; coluna Cancelled (ADR-0018)
GET    /v1/cards/{id}/failures      # histórico de falhas do card (ADR-0019, §13)
POST   /v1/cards/{id}/route         # aplica o roteamento de falha manualmente (ADR-0019)
GET    /v1/cards/{id}/closure       # ficha de encerramento (ADR-0021, §23) — vazio até o merge
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
- `POST /v1/cards/{id}/run` recusa (`409`) e move o card para `Blocked` se alguma
  dependência (`card.dependencies`, populado do `depends_on` do plano multiagente —
  [ADR-0018](adrs/ADR-0018-kanban-fiel-colunas-e-dependencias.md)) ainda não estiver
  `Done`; a execução automática via `run_plan` já ordena por `depends_on` nas suas
  próprias ondas e não passa por este guard.
- `POST /v1/cards/{id}/run` também re-tenta internamente em falha (ADR-0019, §13): se
  o roteamento decidir `mesmo_agente`/`aumentar_effort`/`trocar_executor`, o mesmo
  `run_card` já tenta de novo antes de devolver a resposta; só `bloquear`/
  `escalar_humano` encerram sem sucesso (`Blocked`/`Failed`). `POST .../route` refaz
  o mesmo laço manualmente — para quando o automático parou por limite
  (`ASO_MAX_ESCALONAMENTOS`, default 3) e o operador já corrigiu a causa.
- O gate de F1 só exige `discovery_aprovado` quando `POST .../discovery/run` já foi
  chamado ao menos uma vez (ADR-0020, §6); sem isso, o critério nem entra e o gate
  segue vacuamente aprovado como sempre — nenhuma orquestração existente muda de
  comportamento por não usar discovery.
- Mesma regra para F5: `POST .../run-phase` só recusa (`409`) por falta de
  especificação aprovada quando `execution_mode == "full_pipeline"` **e** o
  discovery já foi usado nesta orquestração (ADR-0021, §9) — `CODE_EXECUTION` e
  orquestrações que nunca chamam `/discovery/run` não mudam de comportamento.
- `rollback` exige que `to_snapshot` seja um snapshot existente e aprovado; gera ADR de rollback.
- Ações críticas (§24) retornam `202 Accepted` + criam `HumanApproval` pendente em vez de executar.
- Leitura exige `viewer`; criar/editar projeto exige `operator`; arquivar/restaurar exige
  `admin`. O ator autenticado é persistido no evento do projeto.
