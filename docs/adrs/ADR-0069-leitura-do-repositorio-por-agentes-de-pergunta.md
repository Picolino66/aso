# ADR-0069 — Leitura somente do repositório por agentes de pergunta (discovery e revisão)

- **Status:** ACCEPTED
- **Fase:** F5 (inteligência — MEL-40, origem `feedback.md` §4)
- **Data:** 2026-09-15
- **Relaciona-se com:** [ADR-0017](ADR-0017-revisao-independente-de-codigo.md) (revisão
  independente), [ADR-0020](ADR-0020-discovery-e-aprovacao.md) (discovery),
  [ADR-0045](ADR-0045-discovery-tecnico-e-aprovacao.md) (discovery técnico),
  [ADR-0059](ADR-0059-contrato-task-envelope.md) (TaskEnvelope),
  [ADR-0065](ADR-0065-registro-de-execucoes-agent-runs.md) (`agent_runs`)

## Contexto

`perguntar_ao_agente` rodava o CLI numa pasta temporária vazia. O discovery recebia só nomes de
diretórios de topo e booleanos do scan; a própria ADR-0045 admite que as "etapas da análise" não
tinham correspondência real. O revisor via apenas o diff (truncado em 60 mil caracteres), sem
especificação, ADRs nem CI, e o prompt dizia que ele não tinha acesso ao repositório. Claude Code
e Codex sabem buscar e ler código; o ASO os privava disso.

## Decisão

1. **Worktree de leitura** (`execution/repositorio_leitura.py`): para discovery (HEAD da pasta
   da orquestração) e revisão (branch da PR), a pergunta a executor **CLI** roda num worktree
   **destacado e temporário** criado fora da pasta do usuário e removido ao final.
2. **Três camadas de proteção:** flag de leitura do CLI quando conhecida (Codex
   `--sandbox read-only`; Claude Code `--permission-mode plan`); worktree destacado (nenhuma
   branch aponta para ele); e verificação depois da pergunta — árvore suja (inclusive arquivos
   não rastreados) ou HEAD movido → `EscritaNoRepositorio`: a resposta é **descartada**, o
   `AgentRun` fica `falha` e a orquestração ganha o evento `PerguntaDescartadaPorEscrita`. O
   serviço cai no fallback de sempre (discovery heurístico; revisão `necessita_humano`).
3. **Discovery:** com leitura, o prompt pede `evidencias` com caminho de arquivo; o saneamento só
   aceita evidências de arquivos existentes e remove `componentes_afetados` que não existem no
   repositório nem são módulos detectados, registrando-os em `componentes_descartados`. O
   relatório marca `acesso_repo`.
4. **Revisão:** o pedido leva, além do diff, o item de especificação de origem, os critérios, as
   ADRs relacionadas (as mesmas do ContextBuilder, ADR-0063) e a última CI (status, origem e saída);
   com leitura, o prompt autoriza verificar impactos fora do diff.
5. **LLM via API** (sem acesso a arquivos) mantém o comportamento anterior e registra
   `acesso_repo = false` no envelope do `AgentRun`. Pasta sem git também fica sem leitura.

### Alternativas descartadas

- **Rodar a pergunta direto na pasta do usuário:** qualquer escrita do agente cairia na branch
  de trabalho do operador (regra 5).
- **Copiar arquivos para o prompt** (ex.: módulos inteiros): estoura o orçamento de contexto e
  decide pelo agente o que ele precisa ler; o índice estrutural fica para a MEL-44.
- **Confiar só na flag do CLI:** as flags variam por versão e wrappers genéricos podem ignorá-las;
  a verificação pós-pergunta vale para qualquer CLI.

## Consequências

- Discovery com CLI fundamenta o relatório em arquivos reais; o revisor enxerga chamadores e testes.
- A flag do Claude Code (`--permission-mode plan`) está declarada, mas não foi exercitada contra o
  binário real nos testes (CLIs fake); a verificação pós-pergunta cobre a falha dela.
- Perguntas com leitura custam um `git worktree add/remove` e seguem sob o lock da orquestração,
  como antes.
