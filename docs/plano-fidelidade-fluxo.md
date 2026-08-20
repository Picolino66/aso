# Plano de fidelidade ao `fluxo.md` e ao `wiframe-fluxo.md`

Diagnóstico do estado atual do ASO Runtime frente às duas especificações e o
backlog necessário para chegar a 100% de aderência.

Data do diagnóstico: 2026-08-04 · Base: `main` @ `82ecf5b`

---

## 1. Veredito

| Dimensão | Referência | Fidelidade |
|---|---|---:|
| **Funcionalidade da esteira** | `fluxo.md` §1–§24 | **85%** |
| **Modelo de dados** | wireframe §38 (33 entidades) | **78%** |
| **Cobertura de telas** | wireframe telas 01–31 | **42%** |
| **Estrutura e navegação** | wireframe §2.2–§2.4 (header/sidebar) | **15%** |
| **Design visual** | wireframe §2.1 (estilo wireframe claro) | **25%** |
| **Requisitos de UX** | wireframe §39 (12 regras) | **45%** |
| **Entregáveis finais** | wireframe §40 (15 itens) | **50%** |
| **Global ponderado** | — | **≈ 55%** |

**Leitura curta:** a esteira existe e é sólida — o backend cobre quase todo o
`fluxo.md`, com 128 endpoints, 121 arquivos de teste e governança real
(ContextBus, worktree isolado, merge governado, roteamento de falha). O que está
longe do alvo é a **camada de apresentação**: o `wiframe-fluxo.md` especifica um
shell de aplicação (header de 9 elementos, sidebar de 16 seções, 31 telas, estilo
wireframe claro) e o que existe é um console denso de 4 páginas HTML em tema
escuro, sem sidebar e sem a maior parte das telas.

Ou seja: **o motor está pronto, o painel não.**

---

## 2. Funcionalidade — `fluxo.md` §1–§24 (85%)

### 2.1 Etapas cobertas

| § | Etapa | Onde vive | Situação |
|---|---|---|---|
| 1 | Entrada da demanda | `Orchestration.demand_brief`, `POST/GET .../brief` | ✅ |
| 2 | Classificação | `control/triage.py` (tipo, risco, complexidade, impactos) | ✅ |
| 3 | Discovery técnico | `control/discovery.py`, ring de 5 versões | ✅ |
| 4 | Aprovação do discovery | `POST .../discovery/decide` (ADR-0020) | ✅ |
| 5 | Criação da especificação | `control/spec.py` | ✅ |
| 6 | Revisão documental | `POST .../spec/review`, `.../spec/approve` (ADR-0021) | ✅ |
| 7 | Decomposição épico/história/card | `kanban/hierarchy.py` + geração via spec | ✅ |
| 8 | Cards no Kanban | `kanban/board_service.py`, `CardEvent` com data/agente/motivo/resultado/evidência/próxima ação | ✅ |
| 9 | Seleção de agente, modelo e effort | `control/selecao.py`, `agent_assignments` por fase | ✅ |
| 10 | **Preparação para implementação** | branch/worktree/plano existem; **checklist de 8 itens não é modelado** | ⚠️ |
| 11 | Implementação | `execution/worktree.py`, `cli_provider.py`, coleta de diff | ✅ |
| 12 | Validações automáticas | `Orchestration.validation_checks` (bateria nomeada, ADR-0022) | ✅ |
| 13 | Tratamento de falhas | `control/failure.py`, `POST .../cards/{id}/route` (ADR-0019) | ✅ |
| 14 | Code review | `control/review.py`, revisor ≠ implementador (ADR-0017) | ✅ |
| 15 | Código reprovado | `KanbanCard.correction_actions` | ✅ |
| 16 | Testes manuais | `control/qa.py`, `qa_checks` (ADR-0025) | ✅ |
| 17 | Falha em teste manual | `POST .../qa/{index}/fail` | ✅ |
| 18 | Aprovação para implantação | `POST .../deploy/approve` (admin) | ✅ |
| 19 | **Implantação** | `DeployRun`; **`ambiente` é uma string única — não há pipeline dev→testes→homologação→staging→produção** | ⚠️ |
| 20 | Validação pós-implantação | `deploy_health_checks`, `POST .../deploy/validate` | ✅ |
| 21 | Rollback | `POST .../deploy/rollback` + card `Incident` de causa raiz | ✅ |
| 22 | Aceite final | `DeployRun.aceite_status` / `origem_decisao` | ✅ |
| 23 | Encerramento do card | `KanbanCard.closure`, `GET .../cards/{id}/closure` | ✅ |
| 24 | Aprendizado da esteira | `observability/aprendizado.py`, `GET /v1/learning` | ✅ |

### 2.2 Lacunas funcionais reais

1. **Regras de roteamento configuráveis (§36.3, tela 31) — 0%.** O
   `MultiAgentDecisionEngine` decide por heurística compilada. Não existe a
   entidade `RoutingRule` nem qualquer forma de o operador declarar
   *"SE tipo=Segurança E risco≥Alto ENTÃO Opus, effort máximo, revisão humana,
   scan de vulnerabilidades, máx. 3 tentativas"*. É a maior lacuna de
   funcionalidade das duas specs.
2. **Pipeline de ambientes (§19, tela 23) — 40%.** Um deploy hoje é
   monoambiente. A spec exige 5 estágios sequenciais com estado por estágio.
3. **Checklist de preparação (§10, tela 14) — 10%.** Os 8 itens são executados
   implicitamente; não há registro auditável de que foram cumpridos.
4. **Limite de tentativas declarado (§36.4) — 40%.** `failures` acumula
   histórico e `failure.py` escala, mas `max_tentativas` não é campo do card nem
   é configurável por regra.
5. **Incidente como entidade (§38, sidebar) — 25%.** Existe `CardType.INCIDENT`,
   mas sem gravidade, timeline própria, vínculo com deploy/rollback ou painel.

### 2.3 Divergência intencional (não é lacuna)

O wireframe cita os modelos *Luna, Terra, Sol*. O runtime descobre modelos reais
via `execution/codex_discovery.py` e `ExecutorCatalog`. Manter os nomes reais é
correto — a spec usa nomes ilustrativos. **Nenhuma task foi criada para isso.**

---

## 3. Modelo de dados — wireframe §38 (78%)

| Entidade | Status | Entidade | Status |
|---|---|---|---|
| Project | ✅ `control/models.py` | Assignment | ✅ `AgentAssignment` |
| Demand | ⚠️ fundido em `Orchestration` | Execution | ✅ |
| Discovery | ✅ `discovery_reports` | ExecutionStep | ⚠️ implícito no stream |
| Document | ✅ `control/documentos.py` | QualityGate | ✅ |
| DocumentVersion | ✅ ring de 5 | TestRun / TestResult | ✅ `ValidationCheck` |
| Approval | ✅ | CodeReview | ✅ `control/review.py` |
| Epic / Story / Card | ✅ `kanban/hierarchy.py` | ReviewComment | ⚠️ sem arquivo/linha |
| Subtask | ⚠️ via `parent_id` | Deployment | ✅ `DeployRun` |
| Checklist | ❌ | **Environment** | ❌ |
| Agent | ✅ `AgentRegistry` | PostDeploymentValidation | ✅ |
| AgentCapability | ⚠️ parcial | Rollback | ✅ |
| Model / EffortLevel | ✅ `ExecutorCatalog` | Incident | ⚠️ só `CardType` |
| Evidence | ✅ | AuditLog | ✅ |
| Metric | ✅ | **RoutingRule** | ❌ |
| HumanIntervention | ⚠️ via `Approval` | | |

---

## 4. Interface — `wiframe-fluxo.md` (design 25% · navegação 15% · telas 42%)

### 4.1 O que existe

Quatro arquivos em `src/aso/api/static/`:

| Arquivo | Papel | Rota |
|---|---|---|
| `index.html` (70 KB) | Console: lista de orquestrações + 14 abas | `/ui/console`, `/ui/` |
| `detalhe.html` (81 KB) | Esteira F1→F7 de uma orquestração, ~12 seções empilhadas | `/ui/detalhe` |
| `nova.html` (17 KB) | Criação de orquestração | `/ui/nova` |
| `macro.html` (19 KB) | Visão macro | — |

Abas do console: `kanban · pulls · races · costs · worktrees · slo · learning ·
adrs · approvals · conflicts · snapshots · patches · audit · timeline`.

### 4.2 Diretrizes gerais — onde diverge

| Requisito | Spec | Hoje |
|---|---|---|
| **Estilo (§2.1)** | fundo claro, tons neutros, bordas visíveis, wireframe | tema escuro `--bg:#0f172a` + acento ciano `#38bdf8` ❌ |
| **Estrutura (§2.2)** | Header + **Sidebar** + área principal | Header + grid `320px 1fr`, **sem sidebar** ❌ |
| **Header (§2.3)** | 9 elementos | logo ✅, token ⚠️, config ⚠️ — faltam projeto atual, ambiente, execuções ativas, falhas, aprovações pendentes, busca, notificações ❌ |
| **Sidebar (§2.4)** | 16 seções nomeadas | **0** ❌ |
| **Componentes reutilizáveis (§2.1)** | sim | tokens CSS ✅, biblioteca de componentes ❌ |
| **Responsivo (§2.1)** | sim | parcial ⚠️ |

### 4.3 Cobertura das 31 telas

| # | Tela | Hoje | # | Tela | Hoje |
|---:|---|---:|---:|---|---:|
| 01 | Dashboard operacional | **0%** | 17 | Tratamento de falhas | 40% |
| 02 | Lista de demandas | 20% | 18 | Code review | 45% |
| 03 | Cadastro de demanda | 30% | 19 | Correções do review | 40% |
| 04 | Detalhes da demanda | 50% | 20 | Testes manuais | 65% |
| 05 | Classificação | 40% | 21 | Registro de bug manual | 45% |
| 06 | Discovery técnico | 70% | 22 | Aprovação para implantação | 50% |
| 07 | Aprovação do discovery | 70% | 23 | Implantação | 40% |
| 08 | Documentos e especificações | 30% | 24 | Validação pós-implantação | 65% |
| 09 | Revisão documental | 60% | 25 | Rollback | 40% |
| 10 | Estrutura da demanda (árvore) | **10%** | 26 | Aceite final | 60% |
| 11 | Kanban operacional | 55% | 27 | Encerramento | 40% |
| 12 | Detalhes do card | **15%** | 28 | Auditoria | 45% |
| 13 | Seleção agente/modelo/effort | 35% | 29 | Métricas e aprendizado | 50% |
| 14 | Preparação para implementação | **10%** | 30 | Configuração de agentes | 35% |
| 15 | Execução da implementação | 45% | 31 | **Regras de roteamento** | **0%** |
| 16 | Quality gates | 70% | | | |

### 4.4 Requisitos de UX (§39) — 45%

Atendidos: status visível, execução mostra agente/modelo/effort, histórico não
sobrescrito (ring de versões + `CardEvent`), auditoria por alteração.

Não atendidos: falha nem sempre indica a próxima ação na UI; item bloqueado não
mostra a dependência; aprovação não exibe os critérios usados; retorno de fluxo
não é visualmente identificado; não há navegação demanda → evidência; ações
irreversíveis sem confirmação; risco crítico não é destacado; decisão automática
não é distinguida da humana.

---

## 5. Backlog para 100%

26 tasks em 5 trilhas. **Trilhas A e B são pré-requisito das demais.**

### Trilha A — Lacunas funcionais da esteira (backend)

| ID | Task | Ref. | Prioridade |
|---|---|---|---|
| **FID-01** | Entidade `RoutingRule` + motor de avaliação SE/ENTÃO plugado no `MultiAgentDecisionEngine`, com ADR de superseção da decisão heurística | fluxo §36.3, wf §33 | crítica |
| **FID-02** | `Environment` como entidade + pipeline de implantação multi-estágio (desenvolvimento → testes → homologação → staging → produção) com estado, logs e gate por estágio | fluxo §19, wf §25 | alta |
| **FID-03** | Checklist de preparação (8 itens) persistido no card + bloqueio automático por dependência pendente com criação de tarefa vinculada | fluxo §10, wf §16 | alta |
| **FID-04** | `max_tentativas` / `tentativa_atual` no card + política de escalonamento declarativa consumida por `failure.py` | fluxo §36.4 | alta |
| **FID-05** | `Incident` como entidade de primeira classe (gravidade, timeline, vínculo deploy/rollback, causa raiz) | fluxo §21, wf §38 | média |
| **FID-06** | `ReviewComment` com arquivo, linha, categoria, severidade, obrigatório/opcional e status de resolução | wf §20.3 | média |

### Trilha B — Shell da aplicação (pré-requisito de C, D e E)

| ID | Task | Ref. | Prioridade |
|---|---|---|---|
| **FID-07** | Design system wireframe: tema claro/neutro, tokens, biblioteca de componentes reutilizáveis (card indicador, tabela filtrável, checklist, pill de status, timeline, árvore, abas), grid responsivo | wf §2.1 | crítica |
| **FID-08** | Header completo com os 9 elementos: logo, projeto atual, seletor de ambiente, execuções ativas, falhas, aprovações pendentes, busca global, notificações, perfil | wf §2.3 | crítica |
| **FID-09** | Sidebar com as 16 seções + estrutura de rotas `/ui/*` correspondente + mapa de páginas documentado | wf §2.4, §40.1/§40.3 | crítica |

### Trilha C — Telas ausentes (0–20% hoje)

| ID | Task | Ref. | Prioridade |
|---|---|---|---|
| **FID-10** | Tela 01 — Dashboard operacional: 4 cards de indicador com variação, fluxo mermaid da esteira, cards por status, aprovações pendentes, atividades recentes | wf §3 | crítica |
| **FID-11** | Tela 02 — Lista de demandas com os 11 filtros e as 11 ações por linha | wf §4 | alta |
| **FID-12** | Tela 03 — Cadastro de demanda com os 4 blocos completos (gerais, contexto técnico, critérios, configuração inicial) incluindo prazo e limite de custo | wf §5 | alta |
| **FID-13** | Tela 10 — Estrutura da demanda: árvore navegável Projeto → Épico → História → Card → Subtarefa | wf §12 | alta |
| **FID-14** | Tela 12 — Detalhes do card com as 10 abas (Resumo, Plano, Implementação, Arquivos, Testes, Review, Evidências, Dependências, Execuções, Histórico) | wf §14 | crítica |
| **FID-15** | Tela 31 — Editor visual de regras de roteamento (UI da FID-01) | wf §33 | alta |

### Trilha D — Telas parciais a completar

| ID | Task | Ref. | Prioridade |
|---|---|---|---|
| **FID-16** | Tela 04 — Detalhes da demanda: cabeçalho com 11 campos, barra de progresso, painel de responsáveis, 11 abas, linha do tempo | wf §6 | alta |
| **FID-17** | Telas 05 + 13 — Classificação editável e painel de recomendação (plataforma, modelo, effort, confiança, motivos, custo/tempo estimados) + histórico de desempenho do modelo | wf §7, §15 | alta |
| **FID-18** | Telas 06 + 07 — Discovery: etapas da análise com progresso, logs ao vivo, e checklist dos 7 critérios de aprovação automática com motivos da escalada humana | wf §8, §9 | média |
| **FID-19** | Telas 08 + 09 — Documentos: os 13 tipos, lista versão/autor/status, editor markdown com render, diff entre versões, comentários com severidade e resposta do autor | wf §10, §11 | alta |
| **FID-20** | Tela 11 — Kanban operacional: as 14 colunas da spec visíveis, card resumido com os 11 campos (código, título, prioridade, agente, modelo, effort, tentativas, falhas, bloqueio, aprovação humana, tempo na etapa), arrastar e soltar | wf §13 | crítica |
| **FID-21** | Telas 15 + 16 + 17 — Execução (plano, logs, arquivos alterados) com os 8 controles em voo; quality gates com duração e evidência por validação; falha com diagnóstico automático, confiança e decisão do orquestrador | wf §17, §18, §19 | alta |
| **FID-22** | Telas 18 + 19 + 20 + 21 — Code review (resumo, checklist de 12 itens, comentários por arquivo/linha), lista de correções obrigatórias, plano de teste manual e registro de bug com retorno de fluxo selecionável | wf §20, §21, §22, §23 | alta |
| **FID-23** | Telas 22 a 27 — Aprovação de implantação (checklist de 9 + avaliação de risco), pipeline de 5 ambientes, validação pós-deploy com os 4 resultados, rollback com estratégias e checklist, aceite final com os 5 tipos, relatório de encerramento exportável | wf §24–§29 | alta |

### Trilha E — Transversais

| ID | Task | Ref. | Prioridade |
|---|---|---|---|
| **FID-24** | Tela 28 — Auditoria com os 6 filtros e as 14 colunas de registro | wf §30 | média |
| **FID-25** | Tela 29 — Métricas: os 15 indicadores, tabela comparativa de modelos e recomendações automáticas | wf §31 | média |
| **FID-26** | Tela 30 — Configuração de agentes com os 13 campos + os 14 agentes-exemplo pré-provisionados | wf §32 | média |
| **FID-27** | Os 12 requisitos de UX do §39 aplicados transversalmente: próxima ação em toda falha, dependência em todo bloqueio, critérios em toda aprovação, retorno de fluxo destacado, navegação demanda→evidência, confirmação em ação irreversível, risco crítico em destaque, decisão automática vs. humana distinguidas | wf §39 | alta |

### Ordem de execução sugerida

```
FID-01 ─┐
FID-02  ├─ Trilha A (backend, paralelizável)
FID-03  │
FID-04  │
FID-05  │
FID-06 ─┘
        ↓
FID-07 → FID-08 → FID-09      (shell — bloqueia tudo abaixo)
        ↓
FID-10, FID-20, FID-14        (dashboard, kanban, card — o núcleo diário)
        ↓
FID-11, FID-12, FID-13, FID-16, FID-17
        ↓
FID-18, FID-19, FID-21, FID-22, FID-23, FID-15
        ↓
FID-24, FID-25, FID-26
        ↓
FID-27                        (varredura final de UX)
```

### Critério de pronto por task

Toda task só fecha com o fluxo obrigatório do `CLAUDE.md`: `ruff check` →
`ruff format` → `mypy src` → `alembic upgrade head && alembic check` →
`pytest --cov-fail-under=80`, mais atualização de
`.aso/context/orchestrator-context.json`, `.aso/kanban/board.json` e
`CHANGELOG.md`. Tasks que alterem persistência exigem validação em
Docker/Postgres. Decisões arquiteturais (FID-01, FID-02, FID-05, FID-07) exigem
ADR referenciando as ADRs vigentes.
