# ADR-0023 — Implantação governada (§18-22, "Incremento F")

- **Status:** ACCEPTED
- **Fase:** F6 (evolução pós-O5)
- **Data:** 2026-07-31
- **Relaciona-se com:** [ADR-0018](ADR-0018-kanban-fiel-colunas-e-dependencias.md)
  (colunas `Deploying`/`Validating`, "Incremento F" citado três vezes como
  pendência), [ADR-0020](ADR-0020-discovery-e-aprovacao.md) (padrão de aceite
  auto-vs-humano), [ADR-0021](ADR-0021-especificacao-e-revisao-documental.md)
  (versionamento em ring), [ADR-0022](ADR-0022-bateria-de-validacoes-e-effort-automatico.md)
  (`ValidationCheck` reaproveitado, `validate_gate_command`), [`fluxo.md`](../../fluxo.md)
  §18-22

## Não confundir com `docs/deploy.md`

**Dois conceitos de "deploy" completamente diferentes, mesma palavra.**
[`docs/deploy.md`](../deploy.md) documenta como implantar o **ASO Runtime em
si** — a imagem Docker da API que roda este projeto. Esta ADR é sobre o
runtime **rastrear e governar implantações dos projetos que ele orquestra** —
o código no `target_path` de cada orquestração. Se você está procurando como
subir a API do ASO, é `docs/deploy.md`, não este documento.

## Contexto

`plano5.md` §11 marcou implantação (§18-22) como "a maior lacuna restante". As
colunas `Deploying`/`Validating` existem desde a ADR-0018 mas eram puramente
decorativas — `POST /cards/{id}/move` genérico as aceitava, mas nada as
acionava automaticamente. Três lugares do código já apontavam para este
incremento nomeando-o: `board_service.py:25-27` ("gatilho automático... é o
Incremento F"), `docs/kanban.md:14-18` (idêntico) e a ADR-0018 (Decisão §3 e
Consequências negativas, que já cunhou a fórmula "gate governado + comando por
ambiente" — a mesma que esta ADR implementa).

**Tensão de escopo, resolvida com o operador antes de desenhar isto**:
`fluxo.md` §18-22 descreve implantação real — múltiplos ambientes, health
checks pós-deploy, rollback de aplicação no ar. Mas `requerimentos.md` exclui
explicitamente "deploy automático em produção" e "provisionamento cloud
automático" do MVP, e `.aso/context/orchestrator-context.json`
(`scope.excluded`) registra o mesmo. A decisão tomada: **governança do gate +
comando configurável** — o mesmo padrão que `validation_checks` (ADR-0022) já
usa para testes/lint. O runtime não provisiona infraestrutura nenhuma; ele
orquestra um comando de implantação configurável pelo operador, rastreia o
resultado, aplica o checklist/aprovação do §18, roda validações pós-deploy
configuráveis (§20), decide aceite final (§22, automático ou humano) e
registra rollback com abertura de tarefa de causa raiz (§21).

## Decisão

### 1. `control/deploy.py` — sem classe, sem agente

Diferente de `DiscoveryService`/`SpecService` (ADR-0020/0021), não há LLM
envolvido — implantação é execução determinística de um comando configurado,
mais perto do estilo de `control/validation.py` do que do estilo agent-backed
de `discovery.py`. `DeployRun` (situação de uma tentativa) tem os campos do
§19 (`ambiente`, `versao_app`, `commit`, `branch`, `comando`, `responsavel`,
`logs`, `resultado`, `duracao_segundos`) mais o estado dos §18/20-22
(`status`, `validacao_status`, `validacao_resultados`, `aceite_status`,
`aceite_comentario`, `origem_decisao`, `rollback_motivo`). `versao_app`/
`commit`/`branch` são informados pelo operador no corpo do `POST` — o runtime
não inventa `git log`; mesma disciplina da ficha de encerramento (§23,
ADR-0021): campo sem dado disponível fica vazio, não inventado.

`executar_deploy`/`validar_pos_deploy` rodam via `run_gate_command`
(`execution/gate_command.py`) — a mesma função determinística que já roda a
bateria de validações e nunca lança. `validar_pos_deploy` reaproveita
`ValidationCheck` (ADR-0022) para os health checks do §20 — "nome + comando +
categoria + bloqueante" já é exatamente a forma de um health check
(health check, smoke test, teste de rota, verificação de logs/métricas...);
inventar um `HealthCheck` quase idêntico não teria propósito. Health check
não-bloqueante que falha não reprova a validação — mesmo espírito da bateria.

### 2. §18 e §22 colapsam numa única decisão de aceite

O fluxo.md pede aprovação humana em dois pontos: §18 (antes de implantar,
"quando necessário") e §22 (aceite final, depois de validar). Em vez de dois
mecanismos de aprovação, `run_deploy` **sempre executa** o comando — mesmo
raciocínio de `DiscoveryService.investigar`: a decisão humana é sobre
**aceitar o resultado**, não sobre autorizar a tentativa. `exige_aceite_humano`
espelha `exige_aprovacao_discovery` (ADR-0020): risco alto/crítico, impacto
sensível (`_SENSITIVE_IMPACTS`, `decision_engine.py`) ou validação pós-deploy
reprovada exigem decisão humana; senão, aceite automático. Uma implantação que
**falha** (`executar_deploy` devolve `ok=False`) nunca fica
`aguardando_aprovacao` — vai direto a `reprovado`, porque não há nada para um
humano "aceitar" num comando que já falhou; a ação certa é corrigir e rodar de
novo, não aprovar.

### 3. Versionamento em ring — terceira reutilização de `documentos.py`

`Orchestration.deploy_runs: list[dict]` (ring de até 5,
`control/documentos.py`) — mesmo raciocínio de `discovery_reports`/
`spec_documents` (ADR-0021 §4.2): reexecutar depois de uma falha acrescenta
uma versão nova, não apaga o histórico. `validate_deploy`/`decide_deploy`
substituem a **última** entrada do ring **in place** (não versionam de novo —
validar/decidir não é "implantar de novo"); só `run_deploy` versiona.

### 4. Critério de gate `deploy_aprovado` — F6, mesma prova de não-regressão

`run_quality_gate` ganha um `Criterion("deploy_aprovado", ...)` para
`target_phase == Phase.F6`, **só quando `deploy_runs` não está vazio** —
mesmo padrão exato de `discovery_aprovado` (F1, ADR-0020): ring vazio (nunca
implantou) não passa por aqui, então nenhuma orquestração existente muda de
comportamento no gate de F6. Confirmado por teste
(`test_gate_f6_sem_deploy_runs_nao_ganha_criterio_novo`) e pela suíte completa
inalterada. Operacionaliza a linha do gate F6 do `requerimentos.md` §11:
"deploy validado, **se aplicável**".

`run_deploy` também exige o **último `QualityGateResult` da orquestração**
com `status == PASSED` (senão `ValueError`/`409`) — operacionaliza "testes
aprovados" do §18 sem inventar um segundo motor de checklist paralelo ao
`QualityGateEngine` que já existe.

### 5. Rollback abre uma tarefa de causa raiz — `CardType.INCIDENT`

`rollback_deploy` (§21) marca a implantação como `revertido`, roda
`deploy_rollback_command` quando configurado (best-effort — não bloqueia o
rollback se o comando falhar, só registra a saída no card) e **sempre** cria
um `KanbanCard(type=CardType.INCIDENT, status=Backlog)` — o tipo já existia em
`shared/types.py` desde o levantamento original de requisitos e nunca tinha
sido usado. É a única parte do §21 que faz sentido implementar sem
infraestrutura real: o runtime não reverte uma aplicação no ar, mas garante
que o rollback nunca fica sem uma tarefa de investigação aberta.

### 6. API — zero mudança em `api/auth.py`

```
GET  /v1/orchestrations/{id}/deploy                # viewer — último DeployRun
GET  /v1/orchestrations/{id}/deploy/history         # viewer — ring completo
PUT  /v1/orchestrations/{id}/deploy/config          # operator
POST /v1/orchestrations/{id}/deploy/run             # operator — §18 checklist + §19
POST /v1/orchestrations/{id}/deploy/validate        # operator — §20
POST /v1/orchestrations/{id}/deploy/approve         # admin — §22 aceite final
POST /v1/orchestrations/{id}/deploy/rollback        # admin — §21
```
`required_role` (`api/auth.py`) já resolve qualquer rota terminando em
`/approve` ou `/rollback` para `admin` por sufixo — nomear os endpoints assim
zerou a necessidade de tocar `auth.py`, mesmo truque que já tinha zerado
mudanças de RBAC em D1/D2 (ADR-0020/0021).

### 7. `next_step.py` e UI

`_deploy_blocker` segue o mesmo molde de `_discovery_blocker`/`_spec_blocker`:
falhou → operador (rodar de novo); `aguardando_aprovacao` → humano/admin;
reprovado no aceite → operador. Wired em `_card_blockers`/`_checklist` só
quando `phase == Phase.F6 and deploy.status != "pendente"` — mesma regra de
não-regressão. UI: painel "Implantação" no mesmo esqueleto condicional de
Discovery/Spec, com um detalhe: como `run_deploy` **exige** um comando já
configurado (diferente de discovery/spec, que sempre têm um fallback
heurístico), o painel também aparece quando só a **configuração** existe
(ainda sem tentativa) — senão o operador nunca teria como abrir o editor pela
primeira vez. Um atalho "🚀 Configurar implantação →" no modal de
Configurações (`⚙`) já existente resolve a descoberta inicial.

## Consequências

**Positivas**
- `fluxo.md` §18-22 fecham dentro do escopo real do MVP — sem provisionar
  nada, sem contrariar o que `requerimentos.md` exclui.
- Fecha as três pendências nomeadas da ADR-0018 apontando para "Incremento F".
- Reaproveita `ValidationCheck`, `run_gate_command`, `validate_gate_command`,
  `documentos.py` e o molde de `exige_aprovacao_discovery` — nenhum mecanismo
  novo foi inventado, só recombinado.
- 730 testes (39 novos deste incremento), 92%+ cobertura, validado ponta a
  ponta em Docker/Postgres: risco baixo aceita automático e libera o gate;
  risco alto aguarda aprovação, gate reprova nomeando `deploy_aprovado`,
  aprovar libera; rollback cria o card de incidente; JSONB persistido.

**Negativas / riscos aceitos**
- **Nenhuma automação de coluna Kanban** — `Deploying`/`Validating` continuam
  só selecionáveis via `/cards/{id}/move` manual. Decisão consciente: deploy é
  modelado no nível da ORQUESTRAÇÃO (como discovery/spec), não por card — não
  existe um único "card certo" para mover automaticamente sem inventar um
  vínculo artificial. Registrado aqui, não escondido.
- `ambiente` é um campo de texto livre, não um pipeline de estágios
  (dev→teste→homologação→staging→produção do §19) — o operador chama
  `/deploy/run` quantas vezes quiser com `environment` diferente; não há
  progressão automática entre estágios.
- Itens do checklist §18 que o runtime não tem como verificar (migrations
  validadas, variáveis de ambiente configuradas, dependências implantadas,
  janela de implantação) **não são checados** — só "testes aprovados" (último
  gate) é operacionalizado. Inventar uma checagem sem dado real seria pior do
  que não checar.
- Épico → história → subtarefa (§7) e escolha automática de agente (§9,
  parte de modelo/effort continua manual) seguem fora de escopo — ver
  `plano5.md` §11.

## Escopo cortado

Nenhum corte foi necessário — a ordem de corte planejada (`validate_deploy`
dobrado dentro de `run_deploy`; UI; comando de rollback em `rollback_deploy`)
não precisou ser acionada.
