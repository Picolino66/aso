# MEL-06 — Qualificar referências "§n" e remover referências mortas

| Campo | Valor |
|---|---|
| Fase do roadmap | 1 — Clareza |
| Prioridade | P2 |
| Esforço | médio |
| Status | Backlog |
| Depende de | — |
| Origem | [feedback.md](../feedback.md) §3 (manutenibilidade), §5 |
| Requer ADR | Não |

## Problema

- `src/` tem 860 referências `§n` sem indicar o documento. A mesma numeração existe em
  `requerimentos.md`, `fluxo.md` e `wiframe-fluxo.md` (ex.: `§13` = padrões multiagente em
  requerimentos e tratamento de falhas no fluxo).
- 211 referências `wf §` e 148 `Tela N` apontam para o wireframe.
- 24 referências a `plano4.md`–`plano7.md`, arquivos que não existem no repositório.
- Docstrings de 15+ linhas narram histórico de incrementos em vez do "porquê" atual.

## Mudança proposta

1. Convenção: `req §n` (requerimentos.md), `fluxo §n` (fluxo.md), `wf §n` (wiframe-fluxo.md), `ADR-NNNN`.
2. Script de apoio que lista cada `§` com o contexto da linha; a qualificação é revisada por
   módulo (não substituição cega), um PR/incremento por pacote.
3. Remover referências a `planoN.md`; quando o conteúdo importar, apontar para a ADR equivalente.
4. Encurtar docstrings narrativas nos módulos tocados: manter o porquê, mover histórico para a ADR.
5. Regra no CONTRIBUTING (MEL-07) para novas referências.

## Critérios de aceite

- [ ] Zero ocorrências de `§` não qualificado em `src/` (verificável por regex).
- [ ] Zero ocorrências de `plano[0-9]`.
- [ ] Nenhuma mudança de comportamento (suíte verde sem alteração de testes).
