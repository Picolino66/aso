# ADR-0011 — Descoberta de capacidades de executores CLI

- **Status:** aceita
- **Data:** 2026-07-14
- **Relacionadas:** ADR-0007, ADR-0008, ADR-0010

## Contexto

O seed de executores fixava modelos (`gpt-5`, `gpt-5-codex`, `o4-mini`) sem considerar a
versão do Codex, a autenticação ChatGPT e o rollout da conta. O docs-first só descobria a
incompatibilidade depois de criar a orquestração e o worktree.

## Decisão

O catálogo Codex gerenciado será derivado de `codex app-server`/`model/list`, usando o
binário indicado por `ASO_CODEX_BIN`. A consulta não executa prompt. Haverá um perfil
`codex-default` sem `-m` e um perfil por modelo anunciado, com esforços efetivamente
suportados. O perfil gerenciado usa `--ignore-user-config`: mantém a autenticação, mas
impede um `config.toml` pessoal de forçar modelo incompatível com o binário descoberto.
Perfis personalizados continuam sob controle administrativo.

Modelo e esforço serão validados antes de operações que criem worktrees. Não haverá troca
silenciosa de modelo: incompatibilidade é falha governada e auditável. Gates devem ser
comandos finitos; servidores e watchers são rejeitados.

## Consequências

- O catálogo representa a combinação real de binário, conta e rollout.
- Atualizar/trocar o Codex exige nova sincronização, sem migração de banco.
- Uma orquestração criada ou bloqueada pode corrigir executor, esforço e gate sem perder
  workspace, eventos ou documentação existente.
- O docs-first concluído marca o workspace como preparado e não é repetido pelo Autopilot.
- Um workspace sem código que contenha apenas o scaffold ASO continua sendo tratado como
  vazio no retry e recebe deterministicamente a feature `projeto` com as oito seções.
