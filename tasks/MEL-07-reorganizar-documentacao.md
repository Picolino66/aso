# MEL-07 — Reorganizar a estrutura de documentação

| Campo | Valor |
|---|---|
| Fase do roadmap | 1 — Clareza |
| Prioridade | P2 |
| Esforço | médio |
| Status | Backlog |
| Depende de | MEL-02, MEL-04, MEL-05 |
| Origem | [feedback.md](../feedback.md) §10 |
| Requer ADR | Não (organização de docs) |

## Problema

Documentação espalhada em ~19 mil linhas, com várias fontes de verdade e sobreposição:
`docs/architecture.md` × `docs/phases/F2`, `docs/agents.md` × `agents/README.md` ×
`docs/modules/executores`, `docs/context.md` × `quality-gates.md` × `snapshots.md`,
CLAUDE.md idêntico ao AGENTS.md, 20 ADRs que descrevem telas, CHANGELOG com 130 itens
numa única versão "não lançada".

## Estrutura alvo

| Documento | Responsabilidade | Não deve conter |
|---|---|---|
| `README.md` | O que é, quickstart local e com agente real, links | Endpoints, env vars completas, contagem de testes |
| `docs/HOW_IT_WORKS.md` | Fluxo real + glossário (MEL-05) | API, histórico |
| `docs/ARCHITECTURE.md` | Módulos, dependências verificadas, estado, concorrência, persistência | Roadmap, telas |
| `docs/AGENTS_AND_EXECUTORS.md` | Funções de agente, contrato, prompts, matriz de capacidades por provider | Tabelas copiadas do código |
| `docs/GOVERNANCE.md` | Regras × código × teste (MEL-01), gates, snapshots, ledger | Estado do processo de construção |
| `docs/OPERATIONS.md` | Runbook, env vars, segurança, troubleshooting | Decisões |
| `docs/adrs/` + índice gerado | Decisões arquiteturais | Telas |
| `docs/ux/` | Design system, mapa de páginas, ADRs de tela (0034–0054) | Regras de backend |
| `CONTRIBUTING.md` | Bateria de validação, convenções de código e de referências | Regras duplicadas |
| `ROADMAP.md` | Backlog de alto nível, apontando para `tasks/` | Histórico |
| `CHANGELOG.md` | Entregas por versão/data, em ordem | Narrativa de incremento |
| `docs/origem/` | `requerimentos.md`, `fluxo.md`, `wiframe-fluxo.md` imutáveis | Estado atual |
| `docs/historico/` | Artefatos da construção (MEL-04) | Nada usado pelo runtime |

## Mudança proposta

1. Fundir os documentos conforme a tabela, preservando conteúdo válido e descartando o obsoleto.
2. `AGENTS.md` vira symlink para `CLAUDE.md` (ou vice-versa); CLAUDE.md referencia CONTRIBUTING.
3. Script que gera o índice de ADRs a partir dos cabeçalhos (título, status, data).
4. Mover ADRs de tela para `docs/ux/decisoes/` mantendo os números (links preservados via índice).
5. Reorganizar o CHANGELOG em versões/datas a partir do histórico do git.

## Critérios de aceite

- [ ] Estrutura alvo criada; documentos antigos removidos ou redirecionados.
- [ ] Nenhum link interno quebrado (checagem automática de links Markdown no CI).
- [ ] Índice de ADRs gerado e completo.
- [ ] CLAUDE.md e AGENTS.md não divergem por construção.
