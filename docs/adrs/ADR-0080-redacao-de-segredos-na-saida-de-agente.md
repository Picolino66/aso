# ADR-0080 — Redação de segredos como invariante do estado governado

- **Status:** ACCEPTED
- **Fase:** F5 (governança — MEL-58, origem DISCOVERED-03, regra 9)
- **Data:** 2026-09-30
- **Relaciona-se com:** [ADR-0065](ADR-0065-registro-de-execucoes-agent-runs.md) (`agent_runs`
  já mascarado), [ADR-0067](ADR-0067-execucao-assincrona-com-fila.md) (resultado do job
  mascarado), [ADR-0015](ADR-0015-observabilidade-ao-vivo-da-execucao.md) (log ao vivo),
  [ADR-0057](ADR-0057-seguranca-por-padrao.md) (segurança por padrão)

## Contexto

A regra 9 diz que segredo só existe em variável de ambiente. Mas nada impedia que a **saída do
agente** carregasse o valor de um segredo para dentro do estado governado: um
`echo $ASO_LLM_API_KEY` no stdout, um `Authorization: Bearer …` numa mensagem de erro do CLI, um
`api_key=` num stack trace. A ADR-0065 mascarou só o `agent_runs`; continuavam abertos o
`EventLog` (servido em `/timeline`, `/audit` e SSE), o `block_reason` e o ring `failures` do card, o
histórico de movimentação, o log ao vivo (`/agent-log`) e o log estruturado do processo.

O teste de governança escrito para esta decisão (um agente real que imprime o segredo e falha com
ele na mensagem) encontrou dois vazamentos que nem estavam no inventário inicial: o **log
estruturado do processo** e o **desfecho da sessão** do log ao vivo.

## Decisão

1. **Uma implementação, em `shared/segredos.py`**: `mascarar_segredos`, `mascarar_valor`
   (recursiva, preserva a forma) e `mascarar_json`. Mora em `shared` porque é aplicada em camadas
   diferentes; `observability/agent_runs.py` reexporta para quem já a usava.
2. **Duas fontes do que é segredo**: valores de variáveis de ambiente com nome sensível (`*KEY*`,
   `*TOKEN*`, `*SECRET*`, `*PASSWORD*`, `*SENHA*`, a partir de 8 caracteres — o mais eficaz,
   compara o valor exato) e padrões conhecidos de credencial (`sk-…`, `gh?_…`, `AKIA…`,
   `Bearer …`, `api_key=…`).
3. **Redação no ponto de entrada, não em cada chamador** — todo caminho novo que gravar por ali
   já sai limpo:
   - `EventLog.append` (payload inteiro, recursivo);
   - `FailureRecord` (validador: `comando`, `mensagem`, `saida`);
   - `BoardService.move_card` (`reason`, `result`, `next_action`, `evidence`) e a escrita direta de
     `block_reason` no roteamento de falha;
   - `AgentLogBus._append` (linha e `detail`) e `_close` (desfecho da sessão);
   - processador do structlog (`observability/logging.py`), antes do render.
4. **Irreversível de propósito**: o original não é guardado em lugar nenhum.

### Alternativas descartadas

- **Mascarar só na serialização da API**: o segredo continuaria no banco e no log do processo —
  a regra fala de onde o segredo existe, não de onde ele é mostrado.
- **Impedir o agente de ver as variáveis**: os agentes CLI precisam das próprias chaves para
  funcionar, e o worktree isolado não muda o ambiente herdado. Redigir a saída é o controle que
  funciona para qualquer CLI.
- **Lista explícita de nomes de variável**: quebraria a cada provedor novo; o padrão por nome
  (`*KEY*` etc.) cobre o catálogo inteiro (ADR-0076 guarda só o nome da variável).

## Consequências

- Nenhum valor de variável sensível aparece em evento, card, histórico, log ao vivo, `agent_runs`,
  resposta da API ou log do processo — travado por
  `tests/integration/test_redacao_de_segredos.py`, que executa um agente que vaza de propósito.
- Falso positivo é possível (um texto legítimo com `token=algumacoisa` vira
  `[SEGREDO REMOVIDO]`); foi aceito: perder um trecho de diagnóstico é melhor que vazar credencial.
- Valor de ambiente com menos de 8 caracteres não é mascarado (estragaria texto comum e não é
  credencial utilizável).
- Custo: uma varredura de regex por texto gravado — irrelevante perto da execução de um agente.
