# ADR-0066 — Camada de aplicação por caso de uso (extração incremental do `OrchestrationService`)

- **Status:** ACCEPTED
- **Fase:** F5 (robustez — MEL-32, origem `feedback.md` §3, §11, §13.3 problema 5)
- **Data:** 2026-09-15
- **Relaciona-se com:** [ADR-0001](ADR-0001-runtime-architecture.md) (Modular Monolith +
  Hexagonal), [ADR-0006](ADR-0006-persistence-repository-adapters.md) (portas de persistência),
  [ADR-0058](ADR-0058-claim-de-execucao-do-card.md) (lock por orquestração)

## Contexto

`application/orchestration_service.py` passou de 7.800 linhas e ~260 métodos cobrindo 12
subdomínios; `api/app.py` tem ~2.800 linhas e 200 rotas com regra de negócio em handler. A
disciplina de lock variava entre métodos. Reescrever de uma vez é inviável e arriscado.

## Decisão

- Criar o pacote `src/aso/application/` com **serviços por caso de uso**, extraídos em passos
  pequenos (MEL-32: bundles → queries → delivery → execution → preparation → release → workflow
  → intake → catalogs → routers da API), cada passo com a suíte completa verde e **sem mudar a
  API pública** (o contrato OpenAPI gerado detecta).
- Durante a transição, `OrchestrationService` é uma **façade** que delega aos serviços extraídos.
- **Passo 1 (feito):** `application/bundles.py` — `OrchestrationBundle` e `BundleStore`, dono do
  cache de agregados, da hidratação (com gancho `ao_hidratar` para a recuperação de execuções
  interrompidas), da persistência e do **lock por orquestração** — a fonte única de lock para
  todos os serviços. A façade mantém `_bundle`/`_persist`/`_lock_for` como delegações finas e
  `_bundles` aponta para o mesmo dict do store.
- **Passo 2 (feito):** `application/queries.py` — `QueryService` com as consultas de leitura
  (listagens, busca, header, dashboard, auditoria e leituras por orquestração), sem importar a
  façade; delegadores de assinatura idêntica.
- **Passo 3 (feito):** `application/delivery.py` — `DeliveryService` (PR, CI, revisão,
  comentários e merge governado), com catálogo, executor por etapa, worktree e perguntas
  registradas injetados por construtor.
- **Passo 4 (feito):** `application/agent_task.py` (`AgentTaskService` — tarefa do agente,
  contexto e `AgentRun`), `application/execution.py` (`ExecutionService` — claim, execução,
  aplicação do resultado, roteamento de falha e freios) e `application/candidates.py`
  (`CandidateRaceService` — corrida de candidatos). Colaboradores mutáveis da façade
  (catálogo, provider) são lidos por callback a cada uso.
- **Passo 5 (feito):** `application/preparation.py` (`PreparationService` — discovery,
  especificação, documentos, revisão documental e materialização da spec em cards).
- **Passo 6 (feito):** `application/qa.py` (`QaService` — QA humano, bugs e encerramento da
  demanda) e `application/release.py` (`ReleaseService` — implantação, pipeline, validação,
  rollback de deploy e incidentes).
- **Passo 7 (feito):** `application/workflow.py` (`WorkflowService` — fases, gate, avanço,
  autopilot e `run_plan`: único lugar que muda fase), `application/recovery.py`
  (`RecoveryService` — retry e roteamento manual) e `application/approvals.py`
  (`ApprovalService` — aprovações, kill-switch e restauração do ledger/seção).
- **Passo 8 (feito):** `application/intake.py` (`IntakeService` — criação da orquestração,
  triagem, regra de roteamento, cards iniciais e planejamento LLM, que saiu do handler HTTP).
- **Passo 9 (feito):** `application/catalogs.py` (`CatalogService` — projetos, executores com
  descoberta do Codex sob cache/lock próprios, regras de roteamento e catálogo de agentes).
- **Passo 10 (feito):** `api/routers/*.py` — um `APIRouter` por recurso com `criar_router(deps)`,
  `api/deps.py` (`ApiDeps` e mapeamento de erros) e `api/schemas.py` (corpos). `api/app.py` só
  compõe o gateway (correlation-id, rate limit, RBAC, tracing, log) e inclui os routers na ordem
  original de registro (a ordem de casamento do Starlette foi verificada rota a rota).
- **Passo 11 (feito):** o resíduo de lógica da façade vai para `settings.py`
  (`ExecutionSettingsService`), `docs_first.py` (`DocsFirstService`), `cards.py` (`CardService`),
  `governanca.py` (`GovernanceOpsService`), `insights.py` (`InsightService`) e
  `classificacao.py` (`ClassificationService`).
- **Passo 12 (feito) — façade declarativa:** `application/composicao.py` é a raiz de composição
  (`LimitesDoRuntime` resolve limites de ambiente; `Colaboradores` → `compor_servicos`), e cada
  método público da façade é uma linha `nome = Delegado("_servico", Servico.metodo)`
  (`application/delegacao.py`). `Delegado` é um descritor genérico em `ParamSpec`: o mypy tipa o
  chamador pela assinatura do serviço, então façade e serviço não divergem em silêncio. Um
  descritor sem `__set__` preserva `monkeypatch.setattr` por instância. Alternativas descartadas:
  `__getattr__` dinâmico (os chamadores perderiam a tipagem sob `mypy --strict`) e manter os ~230
  delegadores escritos à mão (≈1.100 linhas repetindo assinaturas).
- **Passo 13 (feito) — disciplina de lock:** todo `_persist` em `application/` ocorre dentro de
  `with self._lock_for(...)` (o lock vem só do `BundleStore`); as exceções são quatro auxiliares
  que recebem o bundle já sob o lock do chamador, listados no teste AST
  `test_todo_mutador_persiste_sob_o_lock_do_bundle_store`. `run_quality_gate` e `run_pr_ci`, que
  persistiam fora do lock, passam a rodar inteiros sob ele, como `run_review` já fazia: mutações
  concorrentes da mesma orquestração esperam o resultado (o gate decide sobre um estado estável),
  mas leituras não pegam o lock (bundle em cache) e a UI continua respondendo.
- Regras que ficam: serviços recebem `BundleStore` e colaboradores por construtor e não importam a
  façade; nenhum módulo de `application/` ou `api/routers/` acima de ~800 linhas; o único lugar
  que muda fase é `application/workflow.py`.

## Consequências

- `application/orchestration_service.py`: 7.834 → 466 linhas, sem lógica; `api/app.py`: 2.756 → 170.
  API pública (Python e HTTP) inalterada — o contrato OpenAPI gerado ficou idêntico.
- A façade continua sendo a porta de entrada de API, CLI e testes; chamadores novos podem usar os
  serviços diretamente, mas não é obrigatório (a tabela de `Delegado` não tem custo de manutenção
  além de uma linha por método).
- Funções privadas que testes importavam da façade passaram a ser importadas do serviço
  (`_faixa` → `application/insights.py`); limites resolvidos ficam em `svc._limites`.
- A verificação automática da regra de dependência (MEL-36) deve incluir `application`.
- **Adendo (MEL-36):** a façade saiu de `control/` para `application/orchestration_service.py`, e
  `project_service`, `routing_rule_service` e `agent_catalog_service` foram para `application/` —
  em `control` ela criava os ciclos de pacote `control`↔`application` e `control`↔`persistence`.
  A regra de camadas passou a ser verificada por `import-linter` (`pyproject.toml`).
