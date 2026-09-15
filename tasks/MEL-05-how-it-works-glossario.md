# MEL-05 — `HOW_IT_WORKS.md` com fluxo real e glossário

| Campo | Valor |
|---|---|
| Fase do roadmap | 1 — Clareza |
| Prioridade | P1 |
| Esforço | baixo |
| Status | Backlog |
| Depende de | MEL-02 |
| Origem | [feedback.md](../feedback.md) §1 (fluxo textual real), §5, §8 perguntas 1 e 3 |
| Requer ADR | Não |

## Problema

Um desenvolvedor novo não consegue entender em 30 minutos como uma demanda percorre o
sistema: é preciso ler `run_phase`, `run_card` e `decide_approval` num arquivo de 7 mil
linhas. Termos centrais têm vários significados ("agente", "fase", "snapshot", "rollback").

## Mudança proposta

Criar `docs/HOW_IT_WORKS.md` (2 páginas no máximo):

1. **Glossário:**
   - *Papel* (rótulo com permissões, `AgentRegistry`);
   - *Executor* (perfil do catálogo: CLI, LLM, mock);
   - *Função de agente* (triagem, discovery, spec, implementador, revisor, nomeação, documentação);
   - *Fase* (F1–F7) × *Etapa* da esteira (`fluxo.md` §1–§24), com tabela de mapeamento;
   - *Ledger* (ContextBus/OrchestratorContext), *Snapshot*, *Gate*, *Aprovação*.
2. **Fluxo de uma demanda:** diagrama de sequência Mermaid (criação → triagem → plano →
   cards → autopilot → execução → PR → CI → revisão → merge → gate → aprovação).
3. **Onde está cada coisa:** tabela "quero mudar X → arquivo/função".
4. **Limites atuais** com link para as tasks MEL.

Manter o documento curto: detalhes vão para ARCHITECTURE/GOVERNANCE (MEL-07).

## Critérios de aceite

- [ ] Todo termo do glossário aponta para a classe/função real.
- [ ] O diagrama bate com o código atual (revisado contra `run_phase`, `run_card`, `decide_approval`, `merge_pr`).
- [ ] README aponta para o documento logo no início.
