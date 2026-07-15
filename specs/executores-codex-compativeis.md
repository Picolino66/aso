# SPEC — Executores Codex compatíveis e recuperação docs-first

- **Card:** TASK-85
- **ADRs:** ADR-0007, ADR-0008, ADR-0010, ADR-0011

## Objetivo

Impedir que modelos estáticos incompatíveis alcancem worktrees, sincronizando o catálogo
com o Codex autenticado e permitindo recuperar uma orquestração sem descartá-la.

## Critérios de aceite

- `model/list` paginado define modelos e esforços gerenciados; `codex-default` não fixa `-m`.
- Perfis legados ficam indisponíveis e a sincronização preserva perfis personalizados.
- Modelo/esforço são validados antes do worktree e respeitados em toda a execução.
- Configuração pode ser corrigida em `created`/`blocked` com evento auditável.
- Docs-first falho permanece repetível; sucesso marca o workspace preparado.
- Servidores/watchers são rejeitados como quality gate.
- API, console, operação, testes e documentação permanecem sincronizados.
