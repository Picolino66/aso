# MEL-01 — Mapa regra inviolável → código → teste

| Campo | Valor |
|---|---|
| Fase do roadmap | 1 — Clareza |
| Prioridade | P1 |
| Esforço | baixo |
| Status | Backlog |
| Depende de | — |
| Origem | [feedback.md](../feedback.md) §2, §12 Fase 1 |
| Requer ADR | Não |

## Problema

As 9 regras invioláveis do [CLAUDE.md](../CLAUDE.md) são citadas como a razão de existir do
projeto, mas nenhum documento diz **onde** cada uma é aplicada nem **qual teste** a protege.
A revisão encontrou regras declaradas e não aplicadas (3, 4, 5, 6) sem que nada acusasse.

## Mudança proposta

Criar `docs/GOVERNANCE.md` com uma tabela, uma linha por regra:

| Regra | Onde é aplicada (função) | Pontos de entrada cobertos | Teste que prova | Lacuna conhecida | Task |
|---|---|---|---|---|---|

Preencher com o estado **atual** do código, incluindo as lacunas (apontando para MEL-10…MEL-18).
A tabela é atualizada pelas tasks P0 à medida que fecham as lacunas.

## Critérios de aceite

- [ ] As 9 regras aparecem com função e arquivo reais.
- [ ] Cada lacuna aponta para a task que a corrige.
- [ ] Nenhuma linha afirma cobertura sem teste citado.
- [ ] O CLAUDE.md aponta para o documento.

## Arquivos prováveis

- `docs/GOVERNANCE.md` (novo), `CLAUDE.md`, `AGENTS.md`
