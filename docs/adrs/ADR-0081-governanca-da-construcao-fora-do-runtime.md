# ADR-0081 — Governança da construção do ASO fora de `.aso/`

- **Status:** ACCEPTED
- **Fase:** F4/F5 (clareza — MEL-04, origem `feedback.md` §1 item 5, §5, §7)
- **Data:** 2026-10-01
- **Decisão do operador:** aprovada em 2026-10-01, com ajuste em relação à task (ver Decisão, 2)
- **Relaciona-se com:** [ADR-0003](ADR-0003-contextbus-governance.md) (contexto canônico **do
  runtime**, que vive no banco — não confundir com o arquivo de governança do repositório),
  [ADR-0077](ADR-0077-indice-estrutural-por-commit.md) (`.aso/index/`, estado de runtime)

## Contexto

`.aso/` misturava dois conceitos com os mesmos nomes:

- **estado do runtime**: `.aso/worktrees/`, `.aso/executors.json`, `.aso/run/`, `.aso/index/` —
  gravados pelo ASO aqui e nos repositórios-alvo;
- **papelada do processo de construção do próprio ASO**: `.aso/context/orchestrator-context.json`,
  `.aso/kanban/board.json`, `.aso/snapshots/`, `.aso/quality-gates/`, `.aso/reviews/` — mantidos à
  mão a cada incremento e **nunca lidos pelo runtime**.

Quem abria `.aso/` concluía que `board.json` era estado do produto, e frases como "F7 concluída"
(do processo de construção) conflitavam com "F5 pendente" (de uma orquestração real).

A task propunha mover tudo para `docs/historico/`. O `git log` mostrou que isso estaria errado para
duas pastas: `.aso/context` e `.aso/kanban` mudam **a cada task** (o CLAUDE.md manda atualizá-las,
e o `module_map` do contexto é conferido pelo teste da regra de dependência, MEL-36). Chamá-las de
histórico diria que estão aposentadas.

## Decisão

1. **`.aso/` passa a ser só estado de runtime**, e o `.gitignore` ignora a pasta inteira.
2. **Governança viva → `governanca/`** (raiz): `governanca/context/orchestrator-context.json` e
   `governanca/kanban/board.json`. O nome diz que é processo, e continua versionado.
3. **O que não muda mais → `docs/historico/`**: `governanca-construcao/{snapshots,quality-gates,
   reviews}` (parados desde 07/07), `specs-mvp1/` (antes `specs/`), `phases/`, `mvp/` e
   `plano-fidelidade-fluxo.md`.
4. **Instruções e links acompanham**: CLAUDE.md, AGENTS.md, README, `scripts/reset.sh`, os docs
   vivos, as ADRs que citavam os caminhos e os 61 links relativos que a mudança quebraria
   (inclusive dentro das pastas movidas). Registros históricos (`requerimentos.md`, `feedback.md`,
   `tasks/`, `CHANGELOG.md`) mantêm o texto da época — só links clicáveis foram reapontados.
5. **Teste da invariante** (`tests/unit/test_governanca_fora_do_runtime.py`): falha se algo do
   processo voltar para `.aso/`, se os caminhos novos sumirem, se `.aso/` deixar de ser ignorada ou
   se instrução/doc vivo citar o caminho antigo.

### Alternativas descartadas

- **Tudo em `docs/historico/`** (a task original): rotularia como histórico o board e o contexto,
  que são atualizados a cada incremento.
- **`docs/governanca/`**: misturaria arquivos JSON de processo com a documentação do produto; uma
  pasta na raiz deixa claro que não é doc do runtime.
- **Manter em `.aso/` e só documentar a diferença**: a confusão é de nome e lugar; documentação não
  desfaz um diretório que diz uma coisa e guarda outra.

## Consequências

- `.aso/` em qualquer repositório significa uma coisa só: o que o runtime grava.
- Quem automatiza o fluxo deste repositório precisa apontar para os caminhos novos — em particular
  o prompt do `/loop` que cita `.aso/kanban/board.json`. O CLAUDE.md é a fonte do caminho.
- O commit que o operador fizer registra a mudança como remoções em `.aso/` + arquivos novos em
  `governanca/` e `docs/historico/` (o git reconhece como renomeação pelo conteúdo).
- Os 47 links relativos que **já estavam** quebrados antes desta mudança (a maioria em
  `feedback.md`, apontando para linhas de código antigas) continuam como estavam — fora do escopo.
