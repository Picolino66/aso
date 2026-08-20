# ADR-0039 — Cadastro de demanda completo (Tela 03)

- **Status:** ACCEPTED
- **Fase:** F4 (evolução pós-O5)
- **Data:** 2026-08-07
- **Relaciona-se com:** [ADR-0016](ADR-0016-ficha-da-demanda.md) (`DemandBrief`
  original), [ADR-0017](ADR-0017-revisao-independente-de-codigo.md)
  (`create_with_triage`, "o único caminho correto de criação" — este ADR
  documenta a exceção deliberada), [ADR-0028](ADR-0028-regras-de-roteamento.md)
  (`RoutingRuleAction.aprovacao_humana`, precedente do novo campo por demanda),
  [ADR-0038](ADR-0038-lista-de-demandas.md) (Tela 02 — "Editar" ficava
  desabilitada esperando este card; mesma convergência Prioridade/Risco),
  [`wiframe-fluxo.md`](../../wiframe-fluxo.md) §5 (requisito de origem)

## Contexto

O `wiframe-fluxo.md` §5.2 pede 4 blocos de campos no cadastro de demanda:
Informações gerais (Título, Descrição, Projeto, Solicitante, Origem da
demanda, Tipo, Resultado esperado), Contexto técnico (Sistemas, Módulos,
APIs, Banco de dados, Infraestrutura, Dependências afetados/conhecidas),
Critérios (Aceite, Restrições, Riscos, Evidências esperadas) e Configuração
inicial (Prioridade, Risco, Complexidade, Impacto, Aprovação humana
obrigatória, Prazo, Orçamento).

Investigação prévia (mesmo padrão do FID-10/FID-11) encontrou que apenas 8
dos ~24 campos citados já correspondem a algo em `DemandBrief` (ADR-0016).
Os outros 16 não existem em lugar nenhum do sistema — e, como no FID-11,
"Prioridade" continua sendo o mesmo valor de "Risco"
(`prioridade_de(brief) -> RiskLevel` já devolve `brief.risco` diretamente,
`orchestration_service.py`).

## Decisão

**(1) 11 campos novos em `DemandBrief`, todos aditivos.** `solicitante`,
`origem_da_demanda` (distinto de `origem`, que é técnico: agente ou
`"heuristica"`), `sistemas_afetados`, `apis_afetadas`,
`banco_de_dados_afetado`, `infraestrutura_afetada`, `dependencias_conhecidas`,
`restricoes`, `evidencias_esperadas`, `aprovacao_humana_obrigatoria`,
`prazo`. Todos com default seguro (`""`/`[]`/`False`/`None`) — nenhuma
orquestração existente muda de comportamento; `DemandBrief.model_validate`
de uma ficha antiga (sem esses campos) cai nos defaults normalmente.
**"Prioridade" não ganhou campo novo** — a UI usa `risco` diretamente, mesma
convergência do FID-11.

**(2) `aprovacao_humana_obrigatoria` tem efeito real, não é só um campo
guardado.** Reaproveita o precedente já existente de
`RoutingRuleAction.aprovacao_humana` (ADR-0028): em `create_orchestration`,
logo após `_apply_routing_rule`, `if brief.aprovacao_humana_obrigatoria:
plan.requires_human_approval = True` — só adiciona a exigência, nunca
remove o que o motor/regra já decidiram (mesma disciplina "fallback nunca
substitui, só reforça" já usada em toda regra de roteamento). O motivo
(`reason`) da `HumanApproval` criada registra explicitamente que foi o
solicitante quem marcou o campo — sem isso, o texto mostrado seria só o
motivo do motor de decisão (que pode nem ter pedido aprovação sozinho,
ex. "tarefa de baixo risco"), escondendo a causa real.

**(3) `orcamento_usd` aceito na criação — não só via `PUT .../budget`
depois.** `create_orchestration` ganha o parâmetro `orcamento_usd: float |
None`; quando informado, vence o default de ambiente
(`ASO_ORCAMENTO_PADRAO_USD`); `None` preserva o comportamento de sempre.

**(4) `POST /v1/orchestrations` ganha um segundo caminho de criação —
explicitamente uma exceção documentada ao "único caminho correto",
não uma ambiguidade nova.** Quando o corpo já traz `demand_brief`
completo, o handler chama `svc.create_orchestration(...)` **diretamente**,
não `create_with_triage`. A razão: o solicitante já preencheu a ficha à
mão, campo por campo — rodar o agente de triagem por cima dela descartaria
o trabalho estruturado do formulário e o substituiria por uma interpretação
de texto livre. O caminho antigo (sem `demand_brief` no corpo — o que
`nova.html` sempre envia) continua idêntico, chamando `create_with_triage`
exatamente como a ADR-0017 deixou. Crucialmente, o handler também constrói
o `decision_input` a partir da ficha (`brief.to_decision_input(...)`, método
que já existia) — sem isso, o motor de decisão veria sempre `domains:
["backend"]` e ignoraria os `dominios`/`impactos`/`risco` que o solicitante
escolheu, quebrando o critério de aceite "campos alimentam... o motor de
decisão".

**(5) `dominios` (multi-seleção) entra no formulário mesmo não estando na
lista literal do wiframe §5.2.** É a peça que falta para o critério de
aceite acima ser verdade — sem o solicitante escolher explicitamente os
domínios técnicos, o motor não tem como saber quais agentes acionar (não há
mais um passo de triagem automática interpretando texto livre nesse
caminho). Rotulado como "Domínios técnicos afetados", com nota explicando o
porquê.

**(6) Campos de lista usam um item por linha (textarea), não widgets
"+ Adicionar" dedicados por campo.** Simplificação deliberada: 9 campos de
lista com um botão de adicionar cada um seria consideravelmente mais
código para o mesmo resultado funcional (usuário pode adicionar/remover
livremente). Documentado aqui como escolha de escopo, não descoberta a
posteriori.

**(7) "Salvar rascunho" = só criar; "Iniciar" = criar + docs-first — sem
disparar Autopilot automaticamente.** Nenhum estado novo em
`Orchestration.status` foi necessário: toda orquestração já nasce em
`status="created"`, parada, até que o Autopilot seja acionado manualmente
(hoje só em `detalhe.html`) — "rascunho" já existia de fato. "Iniciar"
replica o comportamento que `nova.html` já tinha no botão único ("Criar e
gerar docs-first"): `POST /v1/orchestrations` seguido de `POST
.../analyze-folder`. Decisão consciente de **não** encadear
`POST .../autopilot` automaticamente: o comentário já existente em
`nova.html` ("Autopilot só começa quando você acioná-lo no detalhe") é um
limite de segurança deliberado do projeto — automatizar isso mudaria esse
comportamento sem pedido explícito do card.

**(8) Página nova (`/ui/demanda-nova`), não uma extensão de `nova.html`.**
`nova.html` é uma das 4 páginas legadas congeladas pela ADR-0036 ("rotas
antigas continuam válidas" significa inalteradas, não também retrofitadas).
A Tela 03 do wireframe é conceitualmente diferente (cadastro completo
estruturado vs. formulário rápido de texto livre) — ganha sua própria rota,
com header+sidebar (seção "demandas" ativa), linkada por um botão "+ Nova
demanda" em `/ui/demandas` (Tela 02, FID-11).

## Consequências

**Positivas**
- Os 4 blocos do wireframe existem com campos reais, alimentando
  genuinamente `demand_brief` e o motor de decisão (não só armazenados sem
  efeito).
- `aprovacao_humana_obrigatoria` funciona de ponta a ponta — testado
  criando uma demanda de risco baixo com o campo marcado e confirmando que
  uma `HumanApproval` pendente nasce mesmo assim.
- Nenhuma orquestração existente muda de comportamento — todos os campos
  novos são aditivos com default seguro.
- O caminho antigo (`nova.html`, sem `demand_brief` no corpo) continua
  idêntico — testado explicitamente que a triagem automática não regride.

**Negativas / riscos aceitos**
- `DemandBrief` cresce para 25 campos — mais superfície para manter
  coerente entre `_TRIAGE_SYSTEM` (que só preenche os 14 originais) e o
  formulário manual (que preenche os 11 novos). Aceito: são dois caminhos
  de preenchimento genuinamente diferentes (agente interpretando texto vs.
  humano preenchendo estrutura).
- Campos de lista por textarea (um item por linha) são menos refinados que
  widgets dedicados — aceito pela simplicidade.
- "Prazo" continua sem nenhum efeito no motor — documentado explicitamente
  no próprio formulário (`ajuda` ao lado do campo), não escondido.
