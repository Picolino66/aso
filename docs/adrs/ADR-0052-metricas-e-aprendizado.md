# ADR-0052 — Métricas e aprendizado com recorte por projeto e período (Tela 29)

- **Status:** ACCEPTED
- **Fase:** F4 (evolução pós-O5)
- **Data:** 2026-08-09
- **Relaciona-se com:** [ADR-0025](ADR-0025-qa-hierarquia-aprendizado.md)
  (`observability/aprendizado.py`, `consolidar`/`RelatorioDeAprendizado`/
  `DesempenhoPorExecutor`, estendidos aqui sem quebrar a forma existente),
  [ADR-0038](ADR-0038-lista-de-demandas.md) (`list_orchestrations`, filtro SQL
  real reaproveitado para "recorte por projeto e período"),
  [ADR-0051](ADR-0051-auditoria-com-filtros.md) (mesmo cuidado de não
  hidratar o sistema inteiro sem filtro antes de agregar),
  [ADR-0031](ADR-0031-limite-de-tentativas.md) (`tentativa_atual`, contador
  autoritativo reaproveitado para "primeiro ciclo"/"nº médio de tentativas"),
  [`wiframe-fluxo.md`](../../wiframe-fluxo.md) §31 (Tela 29)

## Contexto

Numeração conferida sem divergência (§31 = Tela 29). Investigação prévia
encontrou que a maior parte da Tela 29 já tinha fonte real:
`observability/aprendizado.py` (ADR-0025) já agregava por executor (modelo)
— execuções, falhas, retrabalho, tempo médio, custo — e `list_orchestrations`
(ADR-0038) já filtrava por projeto/período em SQL real e indexado. Dois
pontos, porém, exigiam trabalho genuinamente novo:

1. **As 8 recomendações automáticas do wf §31.3** — o card cita
   `observability/aprendizado.py` como origem, mas o módulo produzia só
   **1** frase de texto livre (`_recomendar`, um único heurístico: pior
   executor por taxa de falha). Nenhuma das 8 categorias do wireframe
   (aumentar effort / evitar modelo / criar agente / adicionar teste /
   modificar critérios de aprovação / alterar limite de tentativas / criar
   template de card / ajustar roteamento) existia como lógica distinta.
2. **"Recorte por projeto e período" para métricas/aprendizado
   especificamente** — `get_learning_report_global()` não tinha nenhum
   parâmetro; a única precedente de filtro cross-orquestração real (SQL,
   indexado) era `audit_page` (ADR-0051), para um domínio diferente
   (eventos de card, não agregação de aprendizado).

Além disso, 4 dos 15 indicadores do wf §31.1 (tempo médio por demanda, custo
por demanda, número médio de tentativas, falhas por agente) não tinham
nenhuma agregação existente — só os dados brutos para construí-los.

Duas decisões foram confirmadas com o usuário.

## Decisão

**(1) 6 recomendações reais + 2 desabilitadas** (opção recomendada,
aprovada) — nova `recomendacoes_estruturadas(relatorio)` em `aprendizado.py`,
com regra determinística (limiares fixos, documentados no código, mesma
disciplina de `checklist_aprovacao_implantacao`/`saude_pos_deploy`,
ADR-0050) para 6 das 8 categorias:
- **Aumentar effort**: categoria de falha recorrente (≥2 ocorrências).
- **Evitar modelo**: um executor com ≥50% de taxa de falha.
- **Adicionar teste automático**: falha recorrente de categoria
  "testes"/"qa".
- **Modificar critérios de aprovação**: taxa de aprovação <50%.
- **Alterar limite de tentativas**: intervenções humanas ≥30% dos cards.
- **Ajustar regras de roteamento**: retrabalho ≥30% dos cards.

**"Criar novo agente especializado"** e **"criar template de card"** ficam
**permanentemente desabilitadas** — nenhum sinal nos dados distingue "falta
um agente" de "falta contexto"/"tarefa mal decomposta", e não existe
NENHUM sinal de recorrência estrutural de card no runtime hoje. Mesmo
padrão de "criar investigação separada" desabilitada no FID-21/ADR-0048.
Cada recomendação (disponível ou não) devolve `{tipo, rotulo, disponivel,
disparada, justificativa}` — nunca uma decisão automática, só sugestão com
justificativa para o operador ler (mesmo limite deliberado de `_recomendar`,
ADR-0025).

**(2) "Cobertura de testes" mostrado como "não disponível"** (opção
recomendada, aprovada) — `RelatorioDeAprendizado.cobertura_de_testes` é
**sempre** `None`, nunca calculado. O runtime não tem nenhum número de
cobertura de testes chegando ao domínio (só a categoria de falha "testes",
uma correlação fraca que mentiria sobre o que está sendo medido se usada
como proxy). Documentado explicitamente no código, mesma disciplina de
outros campos honestamente ausentes (ex.: itens de checklist sem sinal,
ADR-0050).

**(3) "Recorte por projeto e período" via filtro SQL real, não
hidratação completa** — `get_learning_report_global` ganhou
`project_id`/`data_de`/`data_ate`, aplicados **antes** de hidratar qualquer
orquestração: reaproveita o filtro já indexado de `list_orchestrations`
(ADR-0038) para restringir a LISTA de orquestrações, só então monta os
`CardSnapshot`s das que sobraram — mesmo cuidado de escala de `audit_page`
(ADR-0051), que rejeitou explicitamente hidratar o sistema inteiro em
Python.

**(4) 4 indicadores novos, contagens brutas somadas antes de dividir.**
`consolidar()` ganhou parâmetros de contagem bruta (`aprovados`,
`decisoes_de_aprovacao`, `rollbacks`, `deploys`, `sucesso_primeiro_ciclo`,
`cards_com_tentativa`, `soma_tentativas`, `tempo_por_etapa_ms`,
`total_orchestrations`) — o coletor (`_coletar_indicadores_extra`, novo em
`orchestration_service.py`) soma os brutos de cada orquestração no recorte
ANTES de qualquer divisão; a divisão final acontece só dentro de
`consolidar`, num único lugar. Sem isso, a taxa global viraria uma
média-de-médias (matematicamente errada quando as orquestrações têm
tamanhos de amostra diferentes). "Primeiro ciclo"/"número médio de
tentativas" usam `card.tentativa_atual` — o contador AUTORITATIVO e sem
limite de ring (ADR-0031) — nunca o ring de `tentativas` (capado em 10, que
mentiria para cards com histórico de retry mais longo). "Falhas por
agente" usa um campo novo `CardSnapshot.agente` (`card.assignee`, o PAPEL do
agente) — agrupamento deliberadamente diferente de `desempenho_por_executor`
(agrupado por `card.executor`, o MODELO), já que o wireframe pede os dois
como indicadores distintos (itens 7 e 8 do wf §31.1).

**(5) Tabela de comparação de modelos é só renderização** — as 4 colunas do
wf §31.2 (Modelo/Sucesso/Retrabalho/Custo médio/Tempo médio) já estavam
100% cobertas por `DesempenhoPorExecutor` (nada novo no backend); "Sucesso"
é calculado no frontend a partir de `execucoes`/`falhas` já existentes.

**(6) `/ui/metricas` é página única cross-demanda**, mesmo padrão de
`/ui/auditoria` (ADR-0051) — a Tela 29 já é naturalmente global (o próprio
"recorte por projeto e período" só faz sentido cross-demanda), não
picker+drilldown. `demanda-detalhe.html` ganhou um link de uma linha para
ela na aba Métricas, mesmo padrão de cross-link já usado no FID-21/22/23.

## Consequências

**Positivas**
- Nenhum mecanismo paralelo de agregação foi criado — os 4 indicadores
  novos e as 6 recomendações reais reaproveitam 100% a estrutura já testada
  de `consolidar()`/`RelatorioDeAprendizado`.
- `aprendizado.py` continua sem importar `control` (regra de módulo já
  imposta por teste automatizado, `test_aprendizado_nao_importa_control`) —
  todas as contagens novas entram como parâmetro bruto, coletadas pelo
  `control`.
- O padrão "filtrar a lista de orquestrações em SQL antes de hidratar"
  (já usado em `audit_page`) se confirma reutilizável para um segundo
  domínio de agregação cross-demanda.

**Negativas / riscos aceitos**
- 2 das 8 recomendações permanecem indisponíveis — nenhum heurístico
  substituiu julgamento de produto genuíno.
- "Cobertura de testes" nunca é preenchido — indicador permanentemente
  "não disponível" até (e se) o runtime ganhar integração real com uma
  ferramenta de cobertura.
- Limiares das 6 recomendações reais são fixos e documentados no código
  (não configuráveis pelo operador) — mesma limitação já aceita para
  `checklist_aprovacao_implantacao`/`saude_pos_deploy` (ADR-0050).
