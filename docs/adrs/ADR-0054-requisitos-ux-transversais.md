# ADR-0054 — Requisitos de UX obrigatórios aplicados transversalmente (Tela 39)

- **Status:** ACCEPTED
- **Fase:** F4 (evolução pós-O5, card de encerramento)
- **Data:** 2026-08-09
- **Relaciona-se com:** [ADR-0038](ADR-0038-lista-de-demandas.md) (`TOM_RISCO`,
  padrão de pill de risco em `demandas.html`, replicado aqui),
  [ADR-0041](ADR-0041-detalhes-do-card-em-dez-abas.md) (`CardEvent`
  append-only, `next_action`, aba Histórico do card — padrão de referência
  para o histórico da demanda), [ADR-0050](ADR-0050-implantacao-validacao-rollback-aceite-encerramento.md)
  (pills de "confirmação manual"/"aprovação humana", decisão automática vs
  humana), [ADR-0051](ADR-0051-auditoria-com-filtros.md) (auditoria
  cross-demanda, ponto de partida da navegação evidência → origem),
  [`wiframe-fluxo.md`](../../wiframe-fluxo.md) §39 (Tela 39)

## Contexto

FID-27 é o card de **encerramento** da missão de fidelidade — não pede uma
tela nova, mas uma varredura transversal dos 12 requisitos de UX
obrigatórios de wf §39 contra as ~20 páginas reais já entregues por FID-10
a FID-26. Numeração conferida sem divergência (§39 = Tela 39).

**Divergência de escopo encontrada e resolvida com o usuário**: a
`description` do card FID-27 em `board.json` resume só **10** dos **12**
pontos literais do wireframe — omite "toda tela deve informar claramente o
status atual" e "cada alteração deve gerar uma nova entrada de auditoria".
Decisão do usuário (opção recomendada): tratar os **12** pontos literais
como escopo real, não os 10 do resumo — o wireframe é a fonte, o resumo do
card é atalho. Os 2 pontos omitidos já saíram **cobertos** pela varredura
(status: pill presente em quase toda tela de entidade; auditoria: `CardEvent`/
`DomainEvent` são estritamente append-only, sem nenhum método de
update/delete encontrado) — não exigiram mudança, só ficam auditados aqui.

Uma investigação (Explore) varreu as ~20 páginas reais em
`src/aso/api/static/*.html` requisito a requisito e encontrou **9 lacunas
reais**, todas edições localizadas (nenhuma exige migration — o backend já
tinha os dados; o que faltava era exibi-los ou pedir confirmação antes de
agir).

## Decisão

**(1) Escopo: os 12 requisitos literais do wf §39** (decisão do usuário,
opção recomendada) — não os 10 resumidos no card.

**(2) `aprovacoes.html` (a inbox central) violava dois requisitos ao mesmo
tempo**: Aprovar/Rejeitar disparavam a decisão com um clique, sem mostrar
critérios nem pedir confirmação. Decisão do usuário (opção recomendada):
fechar as duas lacunas com o **padrão já existente** — `confirm()` nativo do
browser (mesmo padrão de `demandas.html`/`regras-roteamento.html`/
`card-detalhe.html`/`agentes.html`), com o texto do diálogo compondo um
resumo dos critérios (`action`/`tipo`/`risk`/`reason`/`payload` — não existe
um campo `criterios`/`checklist` pronto no backend para este tipo de
aprovação, então o resumo é montado no frontend a partir dos campos soltos
já retornados por `GET /v1/approvals`) — em vez de introduzir um novo
padrão de modal só para esta página. A coluna "Origem" da mesma tabela
ganhou pill (`automática (tipo)` vs `manual`), fechando também o requisito
de decisão automática vs humana, que já tinha pill para "Risco" na mesma
linha mas não para "Origem" — inconsistência dentro da própria tela.

**(3) Escopo de correção: as 9 lacunas + um teste de regressão novo**
(decisão do usuário, opção recomendada), sendo o card de encerramento da
missão — fechar em vez de documentar como limitação conhecida:

1. `aprovacoes.html` — confirmação + critérios (ver item 2).
2. `aprovacoes.html` — pill de origem automática/manual (ver item 2).
3. `execucoes.html` — faltava a coluna **Modelo** na tabela agregada
   (`card.executor`, já existia no backend, só não era buscado/renderizado).
4. `auditoria.html` — "Card: X · Demanda: Y" era texto puro, sem navegação
   de volta ao card/demanda de origem; ganhou `<a href>` para
   `/ui/card-detalhe` e `/ui/demanda-detalhe` (`orchestration_id`/`card_id`
   já vinham no item da página, só não eram usados como link).
5. `demanda-detalhe.html`/`card-detalhe.html` — o campo de risco
   (`campo('Prioridade / risco', ...)`) era texto plano, inconsistente com
   `demandas.html`/`aprovacoes.html` (que já usam pill colorido); nova
   função `pillRisco()` replicando o `TOM_RISCO` de `demandas.html`
   (ADR-0038) nas duas páginas.
6. `card-detalhe.html` — a timeline genérica de eventos (aba Histórico) não
   marcava visualmente retrocessos ("retorno de fluxo"); nova
   `ehRetornoDeFluxo(de, para)`, heurística documentada no código: colunas
   `NeedsFix`/`Blocked`/`Failed` são sempre retorno; fora isso, retorno é
   mover para uma coluna anterior numa `ORDEM_FLUXO_FELIZ` fixa — não existe
   campo booleano de "retorno" no `CardEvent`, então a classificação é
   inferida, nunca fabricada como fato do backend.
7. `card-detalhe.html` — a aba Falhas não reexibia o `next_action` que já
   existia no evento (só a aba Histórico mostrava); passou a reexibir a
   próxima ação recomendada mais recente também na aba Falhas.
8. `demanda-detalhe.html` — a aba Histórico (que consome `/timeline`, a
   timeline de **eventos de domínio** — `OrchestrationCreated`,
   `ApprovalRequested`, patches, gates — um stream mais grosso e
   estruturalmente diferente do `CardEvent` do card, que tem
   `actor`/`reason`/`next_action` tipados) só mostrava `type`+`created_at`,
   descartando o `payload` inteiro de cada evento. Corrigido exibindo o
   `payload` por completo (chave: valor) — **sem fabricar** campos
   `actor`/`next_action` que esse tipo de evento genuinamente não tem.
9. Novo teste `tests/integration/test_ux_transversal_wf39.py` (8 testes) —
   trava as 8 correções acima contra regressão futura; antes não existia
   nenhum teste cross-página para os 12 requisitos (gap identificado pela
   investigação: "nenhum mecanismo de teste automatizado cross-página
   existe hoje para os 12 requisitos").

**(4) Nenhuma lacuna exigiu migration** — todos os dados já existiam no
backend (`card.executor`, `orchestration_id`/`card_id` no item de auditoria,
`e.payload`); o trabalho foi inteiramente de exibição/confirmação no
frontend.

## Consequências

**Positivas**
- Os 12 requisitos de wf §39 ficam auditáveis: 3 já cobertos "de graça"
  pelas 26 cards anteriores sem mudança nenhuma, 9 fechados aqui, 0
  documentados como limitação aceita.
- `aprovacoes.html` deixa de ser a única tela da esteira onde uma decisão
  crítica (aprovar/rejeitar) acontece sem confirmação nem contexto visível.
- O teste novo é o primeiro gate automatizado cross-página da missão —
  qualquer regressão futura numa das 8 correções quebra a suíte, não exige
  auditoria manual repetida tela a tela.

**Negativas / riscos aceitos**
- A heurística de "retorno de fluxo" (`ORDEM_FLUXO_FELIZ`) é inferida no
  frontend a partir da ordem das colunas, não um fato gravado no backend —
  se uma nova coluna for adicionada ao `ColumnKey` sem atualizar essa lista,
  a classificação degrada silenciosamente (deixa de marcar um retorno real,
  não gera erro). Aceito porque o `CardEvent` não tem — e não deveria
  ganhar só para isso — um campo booleano dedicado.
- O histórico da demanda (`abaHistorico` de `demanda-detalhe.html`) continua
  estruturalmente mais pobre que o do card — exibe o `payload` bruto de cada
  evento de domínio, não campos tipados `actor`/`reason`/`next_action`,
  porque esse stream genuinamente não carrega esses campos. Unificar os dois
  domínios de evento (`DomainEvent`, nível de orquestração, vs `CardEvent`,
  card-level) ficaria fora do escopo de um card de encerramento.

- `aprovacoes.html` usa `confirm()` nativo do browser, não um modal rico —
  decisão deliberada de reaproveitar o padrão já usado em 5 outras páginas
  em vez de introduzir um sexto padrão de confirmação na base de código.
