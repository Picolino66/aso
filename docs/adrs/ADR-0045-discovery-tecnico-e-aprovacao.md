# ADR-0045 — Discovery técnico e sua aprovação (Telas 06 e 07)

- **Status:** ACCEPTED
- **Fase:** F4 (evolução pós-O5)
- **Data:** 2026-08-07
- **Relaciona-se com:** [ADR-0020](ADR-0020-discovery-e-aprovacao.md) (`DiscoveryService`,
  `exige_aprovacao_discovery`), [ADR-0043](ADR-0043-detalhes-da-demanda-em-onze-abas.md)
  (aba "Discovery" pré-existente em `demanda-detalhe.html`, expandida aqui, não
  substituída por página nova), [`wiframe-fluxo.md`](../../wiframe-fluxo.md)
  §8 (Tela 06) e §9 (Tela 07)

## Contexto

Numeração conferida sem divergência (§8 = Tela 06, §9 = Tela 07). A aba
"Discovery" de `demanda-detalhe.html` (ADR-0043) já mostrava o
`DiscoveryReport` final, mas investigação prévia encontrou lacunas reais
entre o que o wireframe pede e o que o backend síncrono de fato permite
observar:

- **Discovery roda como UMA chamada síncrona ao agente** (`DiscoveryService.
  investigar()`) — não há sub-etapas observáveis. As 7 "Etapas da análise"
  do wireframe (Estrutura do projeto, Código existente, Documentação, Banco
  de dados, Dependências externas, Testes existentes, Impactos sistêmicos)
  **não têm nenhuma correspondência real** — a chamada ao agente é uma
  caixa-preta, o orquestrador não observa o que o agente investiga por
  dentro.
- **O transporte do agente CLI (`agent_ask.py::_rodar_cli`) usa
  `subprocess.run` bloqueante**, sem streaming — diferente de
  `cli_provider.py::_rodar`, que usa `Popen` + threads lendo os pipes
  **enquanto** o processo roda, alimentando o `AgentLogBus` que já serve
  `GET .../agent-log` (usado na aba Execuções, FID-16). Fazer o discovery
  ter logs verdadeiramente **ao vivo** (token a token, pollável enquanto a
  chamada original ainda está em voo) exigiria portar esse mesmo padrão de
  streaming para `perguntar_ao_agente` — função compartilhada por **5
  serviços** (naming, triagem, revisão, discovery, especificação), um raio
  de impacto desproporcional para uma tela de UI.
- **Não existiam `started_at`/`finished_at`/duração** — só um timestamp
  único (`at`) de criação do relatório.
- **O wireframe pede 7 critérios de aprovação automática**, mas o código
  real (`exige_aprovacao_discovery`) só tem **3 condições booleanas**
  (confiança baixa / risco alto-crítico / impacto sensível — 5 categorias
  combinadas numa única condição), sem mapeamento 1:1 para os 7 rótulos, e
  sem nenhum texto de "motivo" quando escala para humano.
- **Das 4 ações de aprovação do wireframe** (Reprovar, Solicitar ajustes,
  Aprovar com observações, Aprovar), o backend só distinguia **2 desfechos
  reais** via um único parâmetro booleano (`decide_discovery(approved:
  bool)`).

Duas decisões foram confirmadas explicitamente com o usuário. Uma delas
(observabilidade do discovery) foi refinada durante a implementação, depois
que a investigação de código revelou que streaming verdadeiro exigiria
tocar uma função compartilhada por 5 serviços — decisão registrada abaixo
como parte da decisão 1.

## Decisão

**(1) Observabilidade real, mas não streaming — escopo refinado do que foi
aprovado.** O usuário aprovou "instrumentar de verdade" em vez de omitir
progresso/logs. Implementado dentro do raio de impacto de `discovery.py`
apenas (sem tocar `agent_ask.py`, compartilhado por 5 serviços):
- `DiscoveryReport` ganha `started_at`, `finished_at`, `duration_ms` e
  `log: list[str]` — timestamps e duração **reais**, medidos em
  `DiscoveryService.investigar()` com `time.monotonic()`.
- `log` é uma lista curta de eventos **reais** (início com executor/effort,
  desfecho com confiança ou motivo da falha) — nunca uma linha fabricada
  como o exemplo ilustrativo do wireframe ("14:04 Módulo authentication
  identificado"). Não é streaming: só existe depois que a chamada síncrona
  termina (a mesma resposta HTTP de `POST .../discovery/run` já devolve o
  relatório completo, incluindo o log).
- **As 7 "Etapas da análise" NÃO viraram um checklist fictício** — a aba
  mostra uma nota honesta explicando que sub-etapas não são rastreáveis
  hoje, em vez de fingir progresso granular que o backend não tem.
- Streaming verdadeiro (log atualizando enquanto a chamada ainda está em
  voo) fica documentado como possível evolução futura que exigiria portar
  o padrão `Popen`+threads+`AgentLogBus` de `cli_provider.py` para
  `agent_ask.py` — fora do escopo deste card pelo raio de impacto.

**(2) Checklist com os 7 rótulos literais do wireframe** (opção
NÃO-recomendada, escolhida explicitamente pelo usuário sobre a alternativa
de mostrar só os 3 critérios reais). Nova função pura
`avaliar_criterios_aprovacao(report, brief)` em `discovery.py`:
- Retorna os 7 itens, cada um com `verificado: bool` — **3 têm verificação
  automática real** ("Baixo risco" ← risco não é HIGH/CRITICAL, "Sem
  mudança relevante de arquitetura" ← "architecture" não está em
  `impactos`, "Sem risco de perda de dados" ← "database" não está em
  `impactos`, "Alta confiança do agente" ← confiança != "baixa"); os
  **4 restantes** ("Escopo claro", "Sem impacto financeiro significativo",
  "Padrões já aprovados") ficam com `verificado: False`, `atendido: None` —
  a UI os mostra com tooltip "sem verificação automática hoje", nunca um
  `atendido` fabricado.
- `motivos_escalada` (satisfaz "motivos da escalada humana listados
  explicitamente" — este SIM é dado 100% real): deriva das condições
  reais que falharam, mais qualquer impacto sensível que não tem linha
  própria entre os 7 rótulos (`contract`/`security`/`deploy`) — para não
  esconder um motivo real só porque o wireframe não previu uma linha
  específica para ele.
- Novo endpoint `GET .../discovery/approval-criteria` (só leitura, sem
  novo papel de RBAC).

**(3) As 4 ações de aprovação mapeiam para as 2 operações reais já
existentes** (`decide_discovery(approved: bool, comentario)`), sem estado
novo persistido: "Aprovar" e "Aprovar com observações" chamam
`approved=true` (a diferença é só UX — comentário recomendado na segunda);
"Reprovar" e "Solicitar ajustes" chamam `approved=false` (mesma distinção).
Nenhum mecanismo de aprovação novo foi inventado — documentado
explicitamente como simplificação honesta, não uma quarta opção real de
backend.

**(4) Painel de execução (agente/modelo/effort/status/tempo decorrido)
reaproveita `agent_assignments["discovery"]`** (chave já existente desde a
ADR-0020) cruzado com `GET /v1/executors` para o campo "Modelo" — mesmo
padrão já usado no painel de responsáveis da Tela 04 (ADR-0043).

**(5) Conteúdo expandido dentro da mesma aba "Discovery" de
`demanda-detalhe.html`** — não uma página satélite nova. Mesma leitura já
aplicada nos FID-16/17: "Tela 06"/"Tela 07" no wireframe não têm indício de
modal ou tela cheia separada, e ambas falam da mesma demanda já em foco.

**(6) Botão "▶ Rodar discovery"/"Rodar discovery de novo" adicionado à
aba** — reaproveita `POST .../discovery/run`, que já existia (usado até
agora só em `detalhe.html`); sem ele, a aba não teria como disparar a
primeira execução.

## Consequências

**Positivas**
- Timing/log são dado real, nunca fabricado — mesmo quando o resultado é
  "falha real capturada" (testado ao vivo: um erro genuíno de sandbox do
  CLI vira uma linha de log honesta, não escondida).
- Zero mudança em `agent_ask.py`/`cli_provider.py` — o raio de impacto
  ficou inteiramente contido em `discovery.py`/`orchestration_service.py`/
  `app.py`, sem risco a naming/triagem/revisão/especificação.
- "Motivos da escalada humana" — o único dos 4 critérios de aceite que
  pedia dado antes inexistente — agora é 100% real.

**Negativas / riscos aceitos**
- Logs não são literalmente "ao vivo" (streaming) — só aparecem depois que
  a chamada síncrona termina. Documentado explicitamente como refinamento
  de escopo durante a implementação, não a interpretação original da
  pergunta feita ao usuário.
- 4 dos 7 critérios do checklist são permanentemente decorativos (sem
  `atendido` real) — escolha explícita do usuário, com tooltip honesto em
  cada um.
- "Solicitar ajustes"/"Aprovar com observações" não são estados distintos
  persistidos — só rótulos de UX sobre as 2 operações reais já existentes.
  Um consumidor da API que não seja a UI não teria como distinguir "Aprovar"
  de "Aprovar com observações" olhando só o `status` do relatório (teria
  que inspecionar `revisao_comentarios`).
