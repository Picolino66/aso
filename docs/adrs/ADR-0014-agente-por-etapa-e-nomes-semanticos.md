# ADR-0014 — Executor por etapa da esteira e nomes de branch derivados do card

- **Status:** ACCEPTED
- **Fase:** F5 (evolução pós-O5)
- **Data:** 2026-07-29
- **Relaciona-se com:** [ADR-0009](ADR-0009-entrega-de-codigo-governada.md) (worktree
  isolado, merge governado), [ADR-0010](ADR-0010-catalogo-multi-repo-governado.md)
  (catálogo multi-repo), [ADR-0013](ADR-0013-tela-de-detalhe-por-proximo-passo.md)
  (tela por próximo passo)

## Contexto

A primeira execução real de F5 num repositório-alvo expôs três limites do modelo de
execução, todos com a mesma raiz: **o runtime tratava a esteira como uma coisa só e o
card como um identificador opaco.**

1. **Um executor para as sete fases.** `Orchestration.selected_executor` era único e
   valia de F1 a F7, propagado entre fases pelo `payload` da aprovação de gate. Não
   havia como usar um modelo barato em F1 (discovery, texto) e o mais forte em F5
   (código) — decisão que muda custo e qualidade de forma desproporcional.

2. **O agente executava cego.** `_build_task` mandava ao agente apenas o
   `user_request` da orquestração inteira e o `card_id`. O título do card, sua
   descrição e seus critérios de aceite existiam no board e **nunca saíam de lá**. Um
   agente rodando o card "Exportar relatório em PDF" recebia só "criar sistema de
   vendas" e um uuid.

3. **Nomes de branch sem significado.** Como consequência direta de (2), o único
   material disponível para nomear a branch era o papel do agente e o executor:
   `aso/BackendDevelopmentAgent-claude-sonnet-medium-c6950ea8ee3e4eb8a75a083e00001043`.
   Quatro branches assim, lado a lado, não dizem qual delas tem a calculadora.

O item (2) é o gargalo dos outros: sem a informação do card chegando à camada de
execução, nem o nome nem o prompt podem melhorar.

## Opções consideradas

1. **Executor por papel de agente** (`AgentSpec.default_executor`, campo que já existe
   no `AgentRegistry` e não é lido por ninguém). Rejeitada: o eixo que importa para
   custo é a **fase**, não o papel — o mesmo `BackendDevelopmentAgent` atua em F5 e F6
   com exigências diferentes, e o operador raciocina por etapa da esteira, que é o que
   a UI mostra.

2. **Tabela `agent_execution_selection`** (uma linha por fase), como esboçado em
   `docs/domain-model.md`. Rejeitada: são no máximo 8 entradas, sempre lidas junto da
   orquestração e nunca consultadas isoladamente. Uma tabela filha traria ordem de
   INSERT e deleção FK-safe — a armadilha nº 1 deste repositório no Postgres — sem
   nenhum ganho de consulta.

3. **Nome de branch sempre gerado por um agente.** Rejeitada: paga uma chamada de
   LLM/CLI por card, e transformaria falha de nomeação em falha de card. Nomear é
   acessório; o trabalho de engenharia é o que importa.

4. **Coluna JSONB `agent_assignments` + nome determinístico com agente opcional.**
   Escolhida.

## Decisão

**(1) Executor por etapa.** `Orchestration.agent_assignments: dict[str, AgentAssignment]`
(coluna JSONB), com chaves `"F1"`..`"F7"` e `"naming"`. `selected_executor`/
`selected_effort` continuam existindo como **padrão da orquestração**. A resolução passa
a ter cinco níveis, nesta ordem:

```
parâmetro explícito da chamada
  → agent_assignments[fase]
  → selected_executor (padrão da orquestração)
  → catalog.default_name() (quando há pasta de trabalho)
  → provider global do bootstrap (legado)
```

Duas consequências deliberadas:

- **Uma etapa com executor próprio não herda o esforço global.** Esforço casa com o
  modelo, não com a orquestração: um `high` válido no Codex pode nem existir no modelo
  escolhido para aquela fase. Sem esforço na etapa, vale o do perfil do executor.
- **No autopilot, a configuração da próxima etapa vence a herdada.** `run_phase` guarda
  o executor no `payload` da aprovação para o auto-avanço; se a fase seguinte tem
  escolha própria, o valor herdado é descartado — do contrário a configuração por etapa
  nunca valeria justamente onde ela mais importa.

Governança: uma fase só aceita troca de agente enquanto **não ficou para trás**
(`index(fase) >= index(current_phase)`). Reconfigurar F1 com a esteira em F5 sugeriria
falsamente que o trabalho seria refeito. `"naming"` não é fase e é sempre editável.
Toda mudança emite `AgentAssignmentUpdated` com `before`/`after`/`actor`.

**(2) O card chega ao agente.** `_build_task` passa a incluir `card_title`,
`card_description`, `card_type` e `acceptance_criteria`; o wrapper
(`scripts/aso-agent-wrapper.sh`) monta o prompt com esses campos e lista os critérios de
aceite. É a correção de maior efeito prático deste incremento — independe do nome da
branch.

**(3) Nome de branch derivado do card.** Novo módulo `execution/branch_naming.py`
(funções puras): `slugify`, `branch_stem`, `unique_branch`, `worktree_dir_name`. O
formato é `feat/calculadora-basica-a1b2c3d4` — prefixo Conventional Commits vindo do
`CardType`, slug do título, sufixo curto de unicidade.

A separação entre **raiz** (`branch_stem`, identidade do card) e **sufixo**
(`unique_branch`, aplicado por quem cria o worktree) não é estética: `retry` e candidatos
concorrentes (§26A.6) executam a *mesma* task e colidiriam em `git worktree add` se a
branch fosse fixa na task.

O prefixo `aso/` foi abandonado a pedido do operador — as branches passam a parecer
branches humanas. Em troca, o runtime deixa de identificar o que é seu por *glob*: a
limpeza passa por `card.branch` gravado no banco.

**(4) Nomeador opcional.** `control/naming.py` usa o executor de
`agent_assignments["naming"]` para sugerir nome e assunto de commit. Contrato de
governança explícito: **nomear nunca derruba um card.** Timeout, JSON inválido, exit ≠ 0,
executor removido do catálogo — tudo cai no caminho determinístico e registra
`NamingFallback`. O agente influencia apenas o miolo do slug; prefixo e sufixo são
sempre impostos por nós, então ele não consegue produzir branch malformada nem colidir
com a de um candidato paralelo. Sem nomeador configurado (o padrão), não há chamada
nenhuma — o nome sai do título do card, de graça.

**(5) Mensagens de commit por prompt, não por reescrita.** Quem commita é o agente CLI
(o wrapper pede "commits pequenos"; o `commit()` do ASO é no-op com árvore limpa, ver
ADR-0009 e a correção do `collect_diff`). Governar o formato por *squash* significaria
reescrever o histórico do agente e descartar a granularidade que ele criou. Optou-se por
injetar a convenção e o assunto sugerido **no prompt**. A mensagem do merge governado
passa a citar branch e título do card, em vez do `"aso: merge governado"` fixo.

## Consequências

**Positivas**
- Custo e qualidade calibráveis por etapa numa mesma orquestração.
- O agente sabe qual card está implementando e quais critérios precisa satisfazer.
- `git branch` e `git log` do repositório-alvo passam a ser legíveis por um humano.
- O nomeador é um ponto de extensão sem custo quando não usado.

**Negativas / riscos aceitos**
- Sem o prefixo `aso/`, distinguir branches do runtime das branches humanas exige o
  banco. Documentado em `docs/operations.md`.
- Um título de card ruim vira um nome de branch ruim; o nomeador existe para isso, mas
  é opcional.
- A instrução de commit no prompt é **pedido**, não garantia: um agente pode ignorá-la.
  Escolha consciente — a alternativa era reescrever o histórico dele.
- `agent_assignments` em JSONB não é consultável por SQL relacional. Aceito: o mapa só
  é lido junto da orquestração.
