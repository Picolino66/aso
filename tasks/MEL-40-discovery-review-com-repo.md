# MEL-40 — Discovery e revisão com leitura do repositório

| Campo | Valor |
|---|---|
| Fase do roadmap | 4 — Inteligência |
| Prioridade | P1 |
| Esforço | médio |
| Status | Backlog |
| Depende de | MEL-14 |
| Origem | [feedback.md](../feedback.md) §4 (contexto insuficiente, code search, progressive disclosure) |
| Requer ADR | Sim: acesso somente leitura ao repositório por agentes de pergunta (referencia ADR-0017, ADR-0020, ADR-0045) |

## Problema

- `perguntar_ao_agente` roda o CLI em **pasta temporária vazia** ([agent_ask.py:58](../src/aso/control/agent_ask.py#L58)).
- O Discovery recebe só nomes de diretórios de topo e booleanos (`_montar_pedido` em
  [discovery.py](../src/aso/control/discovery.py)); o próprio ADR-0045 admite que as
  "etapas da análise" não têm correspondência real.
- O revisor de código vê apenas o diff truncado em 60k caracteres, sem a especificação,
  sem as ADRs e sem a saída da CI, e seu prompt diz "você NÃO tem acesso ao restante do repositório".

Agentes CLI como Claude Code e Codex já sabem buscar e ler código; o ASO os priva disso.

## Mudança proposta

1. Novo modo de pergunta `ask_repo`: o CLI roda num **worktree temporário em modo leitura**
   da branch relevante (base para discovery; branch da PR para revisão):
   - Codex: `--sandbox read-only`;
   - Claude Code: modo de permissão sem edição (definir e testar o flag suportado);
   - worktree removido ao final; verificação de que nenhum arquivo mudou (`git status` limpo), senão o resultado é descartado e registrado.
2. **Discovery:** prompt pede evidências com caminho de arquivo; o saneamento rejeita
   `componentes_afetados` que não existam no repositório.
3. **Revisão de código:** o pedido inclui item de spec de origem, critérios, ADRs relacionadas
   e a última saída da CI; o prompt passa a permitir ler o repositório para verificar impactos.
4. Perfis LLM via API (sem acesso a arquivos) continuam com o comportamento atual e
   registram `acesso_repo = false` no relatório.
5. Timeout específico e custo registrados em `agent_runs` (MEL-30).

## Critérios de aceite

- [ ] Discovery com CLI fake que lê um arquivo do repositório inclui a evidência no relatório.
- [ ] Um agente que tenta escrever durante `ask_repo` tem o resultado descartado e o evento registrado.
- [ ] O revisor recebe spec, critérios, ADRs e saída da CI no pedido.
- [ ] Componentes afetados inexistentes são removidos pelo saneamento.
- [ ] Nenhuma alteração na branch base ou na branch da PR após as perguntas.

## Testes obrigatórios

- Integração com git real em `tmp_path` e CLI fake (leitura e tentativa de escrita).
- Unit do saneamento com caminhos inexistentes.
- Unit do pedido de revisão com todos os insumos.

## Arquivos prováveis

- `src/aso/control/agent_ask.py`, `src/aso/control/discovery.py`, `src/aso/control/review.py`
- `src/aso/execution/worktree.py`, `src/aso/execution/catalog.py`
- `src/aso/control/orchestration_service.py` (`run_discovery`, `run_review`)
