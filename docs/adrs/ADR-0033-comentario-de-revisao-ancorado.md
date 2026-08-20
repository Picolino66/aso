# ADR-0033 — Comentário de revisão ancorado em arquivo/linha (wf §20.3)

- **Status:** ACCEPTED
- **Fase:** F5 (evolução pós-O5)
- **Data:** 2026-08-06
- **Relaciona-se com:** [ADR-0017](ADR-0017-revisao-independente-de-codigo.md) (revisão
  independente de código — este ADR estende o mecanismo, sem substituí-lo),
  [ADR-0025](ADR-0025-checklist-de-preparacao-e-qa-manual.md) (vocabulário de
  gravidade `baixa|media|alta|critica`, reaproveitado aqui),
  [ADR-0032](ADR-0032-incidente-de-primeira-classe.md) (mesmo padrão de entidade de
  primeira classe adicionada a um domínio já existente),
  [`wiframe-fluxo.md`](../../wiframe-fluxo.md) §20.3/§21 (requisito de origem)

## Contexto

A ADR-0017 fechou o code review real (agente revisando o diff, `ReviewVerdict` com os
cinco desfechos do §14 e uma lista de `ReviewAction` — descrição + categoria +
severidade `obrigatoria`/`sugestao`). O que ela **não** cobre é o que o wireframe pede
na Tela 18 (§20.3):

> "Cada comentário deve possuir: Arquivo; Linha; Categoria; Severidade; Descrição;
> Sugestão; Obrigatório ou opcional; Status da resolução."

São 8 campos por comentário — `ReviewAction` hoje só tem 3 (`descricao`, `categoria`,
`severidade`), e sua `severidade` codifica **obrigatório/opcional**, não uma escala de
gravidade. O wireframe pede os dois como campos **distintos**. Além disso, a Tela 19
(§21, "Correções do review") consome uma **lista de ações individualmente
rastreáveis**, cada uma com seu próprio status de resolução — hoje
`card.correction_actions` é uma lista de strings soltas, sem identidade nem estado.

A ADR-0017 já havia avaliado — e rejeitado — criar uma tabela filha para o veredito:
*"mapa pequeno, sempre lido junto da PR — colunas novas em `pull_requests`, não tabela
nova"* (opção 4). Essa rejeição continua certa para o **veredito agregado**
(`ReviewVerdict`), que não muda de premissa aqui. Mas o comentário individual é outra
categoria de dado: uma lista de tamanho variável em que **cada item tem ciclo de vida
próprio** (pendente → resolvido), o que uma coluna JSONB no `pull_requests` não modela
— não há como consultar/atualizar um item sem reescrever o array inteiro, e não há
como o merge governado checar "existe algum comentário obrigatório ainda pendente?"
sem uma varredura ad-hoc do JSON.

## Opções consideradas

1. **Estender `ReviewAction` com `arquivo`/`linha`/`sugestao`/`status`, mantendo tudo
   dentro do JSONB de `review_verdict`.** Rejeitada: resolve os campos que faltam, mas
   não resolve o problema de fundo — resolução individual de um item dentro de um blob
   read-modify-write é frágil sob concorrência (duas resoluções simultâneas de
   comentários diferentes da mesma PR se sobrescrevem) e não é indexável (o merge
   precisaria desserializar e escanear o JSON a cada checagem).
2. **Substituir `ReviewAction`/`ReviewVerdict.acoes` por `ReviewComment`.** Rejeitada:
   quebraria o critério de aceite do card FID-06 ("review agregado atual continua
   válido") e o `_build_card_closure` (riscos residuais derivados de
   `pr.review_verdict.get("acoes")`), sem necessidade — os dois modelos servem a
   propósitos diferentes (parecer agregado auditável vs. lista de itens resolvíveis).
3. **`ReviewComment` como entidade de primeira classe, aditiva.** Aceita — ver Decisão.

## Decisão

**(1) `ReviewComment` (`governance/models.py`) é aditivo, não substitui nada.**
`ReviewVerdict`/`ReviewAction`/`PullRequest.review_verdict` continuam existindo e
sendo populados exatamente como antes (ADR-0017 intacta). `ReviewComment` é uma nova
lista de itens **derivados** do mesmo veredito, ancorados em arquivo/linha, com ciclo
de vida próprio: `id`, `orchestration_id`, `pr_id`, `card_id`, `arquivo`, `linha`,
`categoria` (mesmo vocabulário de `ReviewAction.categoria`), `severidade`
(`baixa|media|alta|critica` — vocabulário de `QaCheck.gravidade`/`Incident.gravidade`,
**não** o `obrigatoria|sugestao` de `ReviewAction.severidade`), `descricao`,
`sugestao`, `obrigatorio: bool`, `status` (`pendente`/`resolvido`), `review_round`
(rodada em que nasceu), `resolved_by`, `resolved_at`.

**(2) Tabela filha própria (`review_comments`), revertendo a opção 4 da ADR-0017 para
este caso específico.** A justificativa da ADR-0017 ("mapa pequeno, sempre lido junto
da PR") vale para o veredito — não vale aqui: `review_comments` é uma lista de tamanho
variável (zero a dezenas por PR) em que cada item muda de estado independentemente dos
outros, o mesmo raciocínio que levou `Incident` (ADR-0032) a ganhar tabela própria em
vez de virar mais um campo do card. Persistência segue o padrão exato de
`IncidentRow`/`PullRequestRow`: FK real para `orchestrations.id`, índice por
`(orchestration_id, pr_id, status)` (a consulta mais comum é "comentários pendentes
desta PR"), migration `7c1e9a5f2d4b`, `down_revision = 4ba98fa43986`.

**(3) O agente revisor produz `comentarios` ao lado de `acoes`, com fallback vazio.**
`_REVIEW_SYSTEM` (`control/review.py`) pede um array `comentarios` extra no JSON,
saneado por `_sanear_comentarios` (mesmo raciocínio de `_sanear_acoes`: categoria e
severidade fora do vocabulário caem no padrão mais conservador; item sem `arquivo` ou
sem `descricao` é descartado, não vira lixo). Um agente que responde só com `acoes`
(comportamento anterior a esta ADR, ou fallback `_indisponivel`) produz
`comentarios=[]` — zero regressão, é a mesma garantia de compatibilidade aditiva já
usada em `RoutingRule`/`tentativa_atual` (ADR-0028/ADR-0031).

**(4) Auto-resolução pelo ciclo do §15, não por um clique à parte.** O `fluxo.md` §15
descreve o ciclo como *"correção → testes automáticos → nova revisão de código"*, que
se repete *"até a aprovação"*. `_apply_review_verdict` reflete isso literalmente:
quando uma rodada aprova (`aprovado`/`aprovado_com_sugestoes` sem exigir confirmação
humana), todo comentário `pendente` da PR é marcado `resolvido` (`resolved_by="system"`)
— a aprovação da revisão É o sinal de que o que estava pendente foi endereçado. Isso
evita a alternativa de exigir que alguém clique "resolver" em cada comentário
individualmente antes do sistema aceitar uma aprovação que o próprio revisor já deu.
`resolve_review_comment` continua existindo para o override humano (ex.: um comentário
que o revisor concorda ser inaplicável antes de uma nova rodada rodar).

**(5) `card.correction_actions` passa a preferir `ReviewComment`, com fallback para o
comportamento antigo.** Quando `ReviewComment`s existem para a PR (agente já devolveu
`comentarios`), a lista vem deles (`obrigatorio and status == "pendente"`) — é o
critério de aceite "correções obrigatórias derivadas dos comentários". Quando não
existem (orquestrações antigas, ou agente que só devolve `acoes`), a derivação
continua sendo `[acao.descricao for acao in verdito.acoes if acao.severidade ==
"obrigatoria"]`, exatamente como a ADR-0017 deixou — não regride nada.

**(6) `merge_pr` ganha uma segunda trava, além de `review_status == "approved"`.**
Defesa explícita do critério "comentário obrigatório não resolvido bloqueia
aprovação": mesmo que `review_status` já esteja `approved` (ex.: aprovação humana com
justificativa, que não passa pela auto-resolução do item 4), existir um
`ReviewComment` `obrigatorio`/`pendente` para a PR barra o merge com `ValueError`
(`409`), apontando `arquivo:linha`.

**(7) `next_step` ganha um bloqueio novo.** `_pr_blocker` passa a receber os
comentários da PR e, entre "revisão aprovada" e "pronta para merge", checa comentário
obrigatório pendente: `pr_comentario_obrigatorio_nao_resolvido`, detalhando
`arquivo:linha` e a descrição, com ação apontando para
`POST .../comments/{id}/resolve`.

**(8) API.** `GET /v1/orchestrations/{id}/pulls/{pr_id}/comments` (lista, alimenta a
Tela 19) e `POST .../comments/{comment_id}/resolve` (resolução manual). Ambos caem no
papel padrão de `required_role` — `GET` é `viewer`, o `POST` não bate nenhum sufixo
crítico (`/approve`, `/merge`, etc.) e cai em `operator`, o mesmo nível de
`report_ci`/`run_review`; resolver um comentário é parte do trabalho operacional do
ciclo de correção, não uma decisão de aprovação (essa continua em `report_review`/
`merge_pr`, ambos já governados pela ADR-0017/ADR-0009).

## Consequências

**Positivas**
- Os 8 campos do wireframe §20.3 existem de fato, com identidade e ciclo de vida
  próprios — a Tela 19 tem de onde ler uma lista de correções rastreável, não strings
  soltas.
- `ReviewVerdict`/`ReviewAction`/`review_verdict` continuam intocados: nenhum consumidor
  existente (`_build_card_closure`, `get_review`, a UI atual) quebra.
- O merge governado (ADR-0009/ADR-0017) ganha uma trava adicional e específica, com
  mensagem que aponta o arquivo/linha exatos — não só "review não aprovada".
- A auto-resolução pelo ciclo (§15) significa que o operador não precisa clicar em cada
  comentário depois de uma correção bem-sucedida — o próprio ciclo de revisão já fecha.

**Negativas / riscos aceitos**
- Depende de o agente revisor efetivamente devolver `comentarios` no JSON — um agente
  que só produz `acoes` (prompt mais antigo, ou modelo que ignora parte do schema)
  deixa a PR sem comentários ancorados, caindo no fallback de `correction_actions`
  (item 5) e sem a trava extra do item 6 (não há o que bloquear se não há comentário).
  Aceito: é o mesmo trade-off de qualquer extensão de prompt — a ADR-0017 já aceita
  isso para os cinco vereditos.
- `review_round` é informativo (para distinguir comentários de rodadas diferentes), mas
  a auto-resolução (item 4) resolve **todos** os pendentes da PR na aprovação, não só
  os da rodada atual — comentários de rodadas anteriores que ficaram pendentes por
  algum motivo também fecham. Aceito: um veredito aprovado significa que o revisor
  olhou o estado atual do diff e não achou motivo para reabrir nada.
