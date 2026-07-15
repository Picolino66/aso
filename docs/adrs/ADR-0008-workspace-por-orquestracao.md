# ADR-0008 — Workspace por orquestração e documentação docs-first

- **Status:** ACCEPTED
- **Fase:** F5 (evolução pós-O5)
- **Data:** 2026-07-09
- **Relaciona-se com:** [ADR-0001](ADR-0001-runtime-architecture.md) (Hexagonal),
  [ADR-0003](ADR-0003-contextbus-governance.md) (ContextBus soberano),
  [ADR-0007](ADR-0007-llm-provider-and-autopilot.md) (autopilot)

## Contexto

Até aqui, **toda** orquestração operava num único repositório global definido pela
variável `ASO_TARGET_REPO`, lida no boot. Isso impedia trabalhar em pastas distintas
por orquestração e não havia um passo que preparasse o projeto para a IA navegar
(documentação docs-first). O usuário pediu um fluxo em que, ao criar a orquestração,
se **seleciona uma pasta** (vazia ou com projeto), se **analisa** essa pasta para
gerar/atualizar a documentação IA-first e, então, se pede ao ASO para construir —
mantendo a esteira F1–F7 existente.

## Opções consideradas

1. **Manter `ASO_TARGET_REPO` global** — simples, mas impede múltiplas pastas e não
   cobre o fluxo pedido.
2. **`target_path` por orquestração + override no provider** — a orquestração carrega
   a pasta; os providers CLI e o gate passam a usá-la, com o env global como
   *fallback* (compatibilidade). Escolhida.
3. **Serviço de projetos separado (multi-repo com CRUD próprio)** — poderoso, porém
   grande demais para a necessidade deste incremento; adiado naquele momento e adotado
   depois pela [ADR-0010](ADR-0010-catalogo-multi-repo-governado.md).

## Decisão

Adotar a **opção 2**. A `Orchestration` ganha `target_path` (coluna nullable; migração
Alembic manual). `ExecutorCatalog.build` aceita `repo_override`, e um helper único
`OrchestrationService._provider_for` resolve o provider **atrelado à pasta** da
orquestração (executor escolhido, ou o default do catálogo quando há pasta), caindo no
provider global só quando não há pasta — zero regressão. `run_phase`, `run_card`,
`run_plan`, `run_quality_gate` e o endpoint de corrida passam a usar a pasta.

A documentação docs-first segue a skill **ai-docs-self-healing**: `docs/index.md` +
`docs/modules/<módulo>/<feature>.md` com o template de 8 seções. Pasta **vazia** recebe
um **scaffold determinístico** (sem agente); **projeto existente** é documentado pelo
**agente selecionado** em worktree isolado, com o diff mesclado (governado) — e uma
rede de segurança garante a navegação mínima. O passo é exposto por
`POST /analyze-folder` e registra evento + `ContextPatch` (`engineering.docs_first`) via
ContextBus (ADR-0003), **sem** aprovação humana (docs = baixo risco). O navegador de
pastas usa `GET /v1/fs/dirs` (lista só diretórios, nunca conteúdo de arquivo).

## Trade-offs

- **+** Cada orquestração trabalha na sua pasta; a IA passa a ler docs antes do código.
- **+** Governança preservada: worktree isolado, diff, patch validado, rastreabilidade.
- **+** Compatível com o legado (env global como *fallback*).
- **−** Worktrees exigem HEAD: pastas sem git recebem `git init` + commit inicial
  (`--allow-empty`), o que cria um `.gitignore` mínimo no projeto do usuário.
- **−** A qualidade dos docs de projetos existentes depende do agente CLI selecionado.

## Consequências

- O console começa com uma pré-análise somente leitura (`GET /v1/fs/analyze/stream`),
  que mostra os arquivos e o progresso antes de liberar o campo da demanda. Essa
  etapa não cria Git, docs ou orquestração; a análise docs-first governada permanece
  em `POST /analyze-folder` depois da criação.
- O `ASO_TARGET_REPO` continua válido como padrão global e para execuções sem pasta.
- O catálogo multi-repo relacional foi implementado posteriormente pela ADR-0010; o
  drift-check contínuo de docs (self-healing) durante F5/F6 permanece como evolução.
