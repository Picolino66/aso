# ADR-0050 — Aprovação, pipeline, validação, rollback, aceite e encerramento (Telas 22-27)

- **Status:** ACCEPTED
- **Fase:** F4 (evolução pós-O5)
- **Data:** 2026-08-09
- **Relaciona-se com:** [ADR-0023](ADR-0023-implantacao-governada.md) (`control/deploy.py`
  — checklist §18 já documentava os itens sem sinal real, reaproveitado aqui),
  [ADR-0029](ADR-0029-pipeline-de-implantacao.md) (`PIPELINE_PADRAO`/`status_do_pipeline`,
  reaproveitados sem nenhuma mudança), [ADR-0032](ADR-0032-incidente-de-primeira-classe.md)
  (`Incident`, reaproveitado no checklist de rollback), [ADR-0021](ADR-0021-especificacao-e-revisao-documental.md)
  (`_build_card_closure`, precedente direto de `_build_demand_closure`),
  [ADR-0049](ADR-0049-code-review-testes-manuais-e-bugs.md) (mesmo padrão de
  expandir aba existente em vez de criar página nova),
  [`wiframe-fluxo.md`](../../wiframe-fluxo.md) §24 (Tela 22), §25 (Tela 23),
  §26 (Tela 24), §27 (Tela 25), §28 (Tela 26), §29 (Tela 27)

## Contexto

Numeração conferida sem divergência (§24=Tela 22 ... §29=Tela 27). As 6 telas
giram em torno de UM `DeployRun` da demanda (Telas 22-26) ou da demanda inteira
(Tela 27) — nunca de um card específico —, então a investigação prévia
confirmou expandir a aba "Deploys"/"Incidentes" de `demanda-detalhe.html` (mesmo
padrão de "expandir aba existente" já usado no FID-18/FID-22), mais uma aba nova
"Encerramento" só para a Tela 27, que não tinha nenhum lar na arquitetura atual.

Investigação prévia encontrou a Tela 23 (pipeline de 5 estágios) **100%
construída no backend desde o FID-02**: `PIPELINE_PADRAO` já usa os mesmos 5
nomes do wireframe, `DeployRun`/`status_do_pipeline` já têm todos os campos
pedidos — só faltava a UI. Em contraste, a Tela 27 (encerramento) não tinha
nenhum agregador no nível da demanda: só existia `_build_card_closure` (ADR-0021),
por CARD. As Telas 22/24/25/26 tinham suporte parcial: PR/gate/rollback-command/
aceite já davam sinal real para parte dos itens, mas várias listas do wireframe
(saúde de 4 níveis, 6 estratégias de rollback, 3 sub-tipos de aceite humano, 5
itens do checklist de aprovação) não tinham representação nenhuma.

Três decisões foram confirmadas com o usuário.

## Decisão

**(1) Arquitetura de páginas** (opção recomendada, aprovada): a aba "Deploys"
de `demanda-detalhe.html` ganha o pipeline visual (Tela 23), o checklist de
aprovação + avaliação de risco (Tela 22), a saúde pós-implantação + decisão
sugerida (Tela 24) e o formulário de rollback com estratégia + checklist
(Tela 25); a aba "Incidentes" ganha timeline completa e os botões
investigar/resolver (companion do rollback, Tela 25); nova aba "Encerramento"
cobre a Tela 27. `/ui/implantacoes` (Telas 22-25) e `/ui/aprovacoes` (Tela 22/
aprovações em geral) deixam de ser placeholders e viram páginas agregadas
reais, mesmo padrão de `/ui/execucoes`/`/ui/testes`/`/ui/code-reviews`
(FID-21/22) — picker sem `?id=`, conteúdo com `?id=`. **Exceção deliberada**:
`/ui/aprovacoes` NÃO segue o padrão picker-por-demanda dos outros, porque já
existe `GET /v1/approvals?status=` — um endpoint cross-orquestração REAL
(`HumanApproval`, ADR-0024/ADR-0037) — então a página vira uma inbox de
verdade (todas as aprovações pendentes de todas as demandas numa lista só),
mais honesto e mais útil do que replicar o padrão picker só por consistência
visual. Aproveita também a correção já registrada em `HumanApproval.tipo`
(ADR-0037, dashboard operacional): os 4 rótulos do wireframe do dashboard
(Discovery/Arquitetura/Deploy/Aceite final) não existem no runtime — a
origem real é uma das 3 automáticas ou "manual", mostrada como está, sem
forçar nos 4 rótulos.

**(2) Quanto construir de verdade nas lacunas de vocabulário** (opção
recomendada, aprovada): construir o que for real e barato, honesto e manual
no resto — mesmo raciocínio já usado desde o FID-17. Especificamente:
- **Saúde de 4 níveis (Tela 24, wf §26.2)**: `saude_pos_deploy` deriva de
  FATO — `validacao_resultados` já distingue item bloqueante de
  não-bloqueante (§20); "saudável com alertas" é só quando um item
  NÃO-bloqueante falhou, nunca heurística. "Falha crítica" vs. "instável" usa
  o mesmo fato que `classificar_falha_deploy` já usava (produção vs. resto).
- **Decisão sugerida (wf §26.3)**: `decisao_sugerida_pos_deploy` é só uma
  SUGESTÃO textual — nunca uma ação automática; quem executa é sempre o
  endpoint real (`run_deploy`/`rollback_deploy`/etc.), acionado manualmente
  pelo operador. Falha crítica sem `rollback_command` configurado escala
  para "solicitar análise humana", já que a ação sugerida não teria como
  rodar sozinha.
- **6 estratégias de rollback (Tela 25, wf §27.1)**: campo novo
  `DeployRun.rollback_estrategia`, puramente descritivo — o runtime já roda
  sempre o mesmo `deploy_rollback_command` (best-effort) independente da
  estratégia escolhida; não existe execução diferenciada por estratégia
  hoje, documentado explicitamente no docstring do campo.
- **Checklist de 6 itens do rollback (wf §27.2)**: 4 dos 6 itens têm sinal
  real ("confirmar versão anterior" = existe deploy anterior bem-sucedido;
  "executar rollback" = `status == revertido`; "rodar smoke tests" =
  validação já rodou neste deploy; "abrir análise de causa raiz" = o
  `Incident` que `rollback_deploy` já cria automaticamente, ADR-0032); os 2
  restantes ("validar compatibilidade do banco", "suspender novas
  execuções") não têm NENHUM mecanismo real no domínio (sem verificação de
  schema, sem pausa de tráfego) — ficam com `ok=None`, mesmo vocabulário do
  item (4).
- **Checklist de 9 itens de aprovação (Tela 22, wf §24.1)**: 4 itens reais
  (PR aprovada, testes aprovados = último gate PASSED, plano de rollback
  disponível = comando de rollback configurado em algum nível, aprovação
  humana realizada); os outros 5 (migrations validadas, variáveis
  configuradas, documentação atualizada, dependências implantadas, janela
  de implantação definida) já eram documentados como sem sinal na ADR-0023
  — continuam `ok=None`, sem fabricar verificação nova.
- **3 sub-tipos de aceite humano (Tela 26, wf §28.2)**: campo novo
  `DeployRun.tipo_aceite_humano` (produto/técnico/negócio), opcional,
  só populado quando o operador informa em `POST deploy/approve`. Vazio =
  aceite humano genérico — nunca inferido, sempre o que o operador digitou.
- **`ok: bool | None`, não confirmação persistida**: os itens `manual` (sem
  sinal real) usam `None` para "requer confirmação manual", não um terceiro
  mecanismo de persistência/auditoria — simplificação deliberada dado o
  volume já grande de superfície nova neste card; documentado aqui para não
  ser confundido com omissão.

**(3) Exportação do relatório de encerramento** (opção recomendada, aprovada):
novo `GET .../closure/export` no backend, devolvendo markdown pronto
(`Content-Disposition: attachment`) — reutilizável por qualquer consumidor
(CLI, outra UI), consistente com o resto do backend, em vez de montagem
client-side.

**(4) Tela 27 — 13 blocos, não 14.** A wireframe (§29.1) tem 14 blocos
(inclui "Cards concluídos"); o `fluxo.md` §23 ("Encerramento do card", a
mesma seção que já origina `_build_card_closure`) e o próprio critério de
aceite do card FID-23 ("relatório de encerramento... com os 13 blocos") só
têm 13. Resolvido honrando o texto literal do card: os 13 blocos do
`fluxo.md` §23 formam o relatório (`_build_demand_closure`); "Cards
concluídos" vira métrica de resumo (`_demand_closure_metricas`, wf §29.2),
não um 14º bloco — reconcilia as duas specs sem contradizer nenhuma.
`_build_demand_closure` segue a MESMA disciplina de `_build_card_closure`
("só monta o que o runtime já tem à mão"): sem tabela central de commits,
"Commits" vira a lista de branches mescladas (fato real); "Decisões
técnicas" reaproveita os `ADR` já registrados, sem taxonomia nova.

## Consequências

**Positivas**
- Tela 23 (pipeline) foi praticamente só UI — o backend já batia
  byte-a-byte com o wireframe desde o FID-02, confirmando a disciplina de
  "verificar o que já existe antes de construir" da investigação prévia.
- Todos os campos/checklists novos reaproveitam sinais REAIS já existentes
  (`gate_results`, `pull_requests`, `Incident`, `validacao_resultados`) —
  nenhuma lógica de decisão nova duplicada.
- `_build_demand_closure` prova que o padrão "assemble, don't invent" de
  `_build_card_closure` escala para o nível da demanda sem modificação
  conceitual.

**Negativas / riscos aceitos**
- 2 dos 6 itens do checklist de rollback e 5 dos 9 itens do checklist de
  aprovação continuam `ok=None` — o runtime não tem como verificá-los hoje,
  rotulado honestamente, não escondido.
- `rollback_estrategia` é só metadado — não existe execução diferenciada por
  estratégia no runtime (rollback sempre roda o mesmo comando configurado).
- Itens manuais (`ok=None`) não têm confirmação persistida/auditável — uma
  simplificação deliberada, documentada aqui, não um mecanismo completo de
  checklist assinado.
- `/ui/aprovacoes` quebra deliberadamente o padrão visual picker-por-demanda
  das outras páginas agregadas — julgado um trade-off correto dado que o
  dado real já é cross-orquestração.
