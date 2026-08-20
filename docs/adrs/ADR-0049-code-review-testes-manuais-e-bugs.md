# ADR-0049 — Code review, correção obrigatória, testes manuais e registro de bug (Telas 18, 19, 20 e 21)

- **Status:** ACCEPTED
- **Fase:** F4 (evolução pós-O5)
- **Data:** 2026-08-09
- **Relaciona-se com:** [ADR-0017](ADR-0017-revisao-independente-de-codigo.md)
  (`ReviewService`/`ReviewVerdict`, reaproveitados sem mudança de contrato),
  [ADR-0033](ADR-0033-comentario-de-revisao-ancorado.md) (`ReviewComment`),
  [ADR-0025](ADR-0025-qa-hierarquia-aprendizado.md) (`QaCheck`/`_criar_bug_de_qa`,
  base do registro manual de bug), [ADR-0032](ADR-0032-incidente-de-primeira-classe.md)
  (`Incident`, precedente direto do padrão de armazenamento de `BugReport`),
  [ADR-0048](ADR-0048-execucao-quality-gates-e-falhas.md) (`card-detalhe.html`,
  expandida aqui — mesmo padrão do FID-18/FID-21), [`wiframe-fluxo.md`](../../wiframe-fluxo.md)
  §20 (Tela 18), §21 (Tela 19), §22 (Tela 20), §23 (Tela 21)

## Contexto

Numeração conferida sem divergência (§20=Tela 18, §21=Tela 19, §22=Tela 20,
§23=Tela 21). As quatro telas formam um único fluxo contínuo — revisão de
código → correção obrigatória → testes manuais → registro de bug — e todas
giram em torno de **um card específico**, então a investigação prévia (mesmo
raciocínio do FID-21/ADR-0048) confirmou expandir `card-detalhe.html`
(aba "Review" e aba "Testes"), não criar páginas novas. `/ui/code-reviews`
(seção fixa da sidebar, ainda placeholder) vira lista agregada por demanda,
mesmo padrão de `/ui/execucoes`/`/ui/testes` (FID-21). `/ui/testes?id=`, já
construída no FID-21 só com quality gates automatizados, ganha aqui o plano
de teste manual e o registro de bug que ela já anunciava como pendentes.

Investigação prévia encontrou:

- **Resumo do review (wf §20.1)**: PR/branch/CI já existiam; commits e
  linhas adicionadas/removidas não tinham nenhuma fonte no runtime
  (`WorktreeManager` só tinha `branch_diff`/`changed_files`).
- **Checklist (wf §20.2)**: os 12 eixos já existiam **verbatim** dentro do
  prompt do revisor (`_REVIEW_SYSTEM`, `control/review.py`), mas só como
  instrução ao LLM — não como estrutura persistida por item.
  `ReviewVerdict.pontos_verificados` é texto livre (o próprio agente relata
  o que checou), nunca um mapa `{eixo: bool}`.
- **Comentários (wf §20.3)**: `ReviewComment` (ADR-0033) já cobre 7 dos 8
  campos pedidos; a UI só mostrava 4 deles.
- **Correção obrigatória (wf §19, Tela 19)**: `NeedsFix` já existe como
  `ColumnKey` e a máquina de transições (ADR-0047) já só permite
  `NeedsFix→InProgress`, mas nada impedia rodar `run_review` de novo
  enquanto o card seguia em `NeedsFix` sem ter passado por `Testing`.
- **Testes manuais (wf §22.1, Tela 20)**: `QaCheck` (ADR-0025) já cobria 7
  dos 10 campos pedidos — faltavam `codigo`, `titulo`, `pre_condicoes`.
- **Registro de bug (wf §23, Tela 21)**: só existia a criação **automática**
  de bug a partir de QA reprovado (`_criar_bug_de_qa`) — nenhum caminho
  manual, e nenhum dos campos extras do wireframe (impacto, frequência,
  agente sugerido, retorno de fluxo) tinha representação em lugar nenhum.

Duas decisões foram confirmadas com o usuário.

## Decisão

**(1) Correção obrigatória travada de verdade no backend** (opção
recomendada, aprovada) — `run_review` recusa com `409` quando
`card.status == NeedsFix`: o operador precisa mover o card de volta por
`Testing` (rodar os testes) antes de uma nova rodada de revisão, igual ao
fluxograma do wf §19.2. Reaproveita o `ColumnKey`/máquina de estados que já
existia (ADR-0047) — nenhum mecanismo novo de estado.

**(2) Bug manual como entidade estruturada, companion de um novo
`KanbanCard(type=Bug)`** (opção recomendada, aprovada) — mesmo papel que
`Incident` (ADR-0032) tem para `KanbanCard(type=Incident)`: tabela
relacional própria (`bug_reports`), não um blob JSONB no card nem na
orquestração. Investigação comparou os dois precedentes já existentes no
código — `Documento` (FID-19/ADR-0046, JSONB por ser "ring versionado, lido
sempre junto da orquestração") e `Incident`/`ReviewComment` (tabela própria,
por serem "lista de tamanho variável em que cada item tem ciclo de vida
próprio") — e `BugReport` se encaixa no segundo padrão: cada bug é um
registro independente, criado a qualquer momento, sem relação de "última
versão" com os demais. `BugReport.card_original_id` é o campo "Card
original" do wf §23.1 (o card que tinha o problema); `BugReport.card_id` é o
bug em si (o `KanbanCard(type=Bug)` recém-criado, objeto rastreável no
Kanban) — nomeação explícita para não confundir os dois papéis.

`create_bug_report` reaproveita a mesma forma de descrição textual de
`_criar_bug_de_qa` (cenário/ambiente/passos/resultados/evidências/gravidade),
sem duplicar lógica — só monta o `KanbanCard` a partir dos campos do
formulário manual em vez de um `QaCheck` reprovado. Das 6 opções de "retorno
de fluxo" do wf §23.2, só **"Criar card independente"** tem efeito real: o
bug nasce sem `dependencies`/`parent_id` apontando para o card original. As
outras 5 ("Retornar para implementação/infraestrutura/banco de
dados/documentação/arquitetura") são **metadado descritivo** — o runtime não
tem mecanismo de roteamento automático entre disciplinas/times (não existe
"time de infraestrutura" nem fila separada no domínio), então fabricar esse
roteamento mentiria sobre o que o sistema faz. A intenção do operador fica
gravada em `BugReport.retorno_de_fluxo` e visível na UI, nunca escondida.

**(3) Resumo do review com commits e linhas reais.** `WorktreeManager` ganha
`commit_count(branch)` (`git rev-list --count`) e `line_stats(branch)`
(`git diff --shortstat`, parseado por regex — git não tem saída
estruturada para isso) — mesma comparação `HEAD...branch` de
`branch_diff`/`changed_files`, já existentes. Novo método de serviço
`get_card_diff_stats` agrega os três (`commit_count`/`line_stats`/
`len(changed_files)`) num único dict, zerado quando o card nunca teve
branch (honesto, mesmo raciocínio de `get_card_changed_files`).

**(4) Checklist de 12 eixos mostrado sem fabricar granularidade que não
existe.** A UI mostra os 12 rótulos fixos do wf §20.2 lado a lado com o
`pontos_verificados` REAL (texto livre do revisor) — nunca tenta cruzar um
com o outro marcando ✓/✗ por eixo, porque isso exigiria casar texto livre de
LLM com rótulo fixo, fabricando uma precisão de auditoria que o dado não
sustenta. Mesma disciplina de "fato, não palpite" já aplicada à confiança do
diagnóstico de falha (ADR-0048) e à confiança da recomendação de roteamento
(ADR-0044).

**(5) Comentários de review mostram os 8 campos do wf §20.3 por completo**
(arquivo, linha, categoria, severidade, descrição, sugestão,
obrigatório/opcional, status) — `ReviewComment` já tinha todos; só a UI
cortava para 4. Nenhuma mudança de modelo.

**(6) Plano de teste manual ganha `codigo`/`titulo`/`pre_condicoes` em
`QaCheck`** (wf §22.1) — sem migration (ring JSONB no card, como já era).
`codigo` é **gerado** (`gen_id("qa")`), nunca um código sequencial fictício
tipo "QA-001" do exemplo do wireframe — mesma disciplina de não fabricar
identificador humano-sequencial já usada em `Incident.id`/`ADR.id`.

**(7) `/ui/code-reviews` vira lista agregada por demanda** (mesmo padrão
picker/tabela de `/ui/execucoes`/`/ui/testes`, FID-21) — cada linha é uma PR
com link para o resumo completo em `card-detalhe.html`, aba Review.
`/ui/testes?id=` ganha uma tabela de bugs registrados ao lado da tabela de
QA por card, cobrindo o gap que o próprio FID-21 já documentava no texto da
página.

## Consequências

**Positivas**
- `BugReport` reaproveita 100% o precedente arquitetural de `Incident`
  (mesmo raciocínio de tabela própria vs. JSONB, já validado e testado) —
  nenhuma decisão de armazenamento nova sendo inventada do zero.
- Correção obrigatória agora é **imposta pelo backend**, não só sugerida na
  UI — reaproveita a máquina de estados do ADR-0047 sem mecanismo paralelo.
- `commit_count`/`line_stats` seguem exatamente o padrão de
  `changed_files`/`branch_diff` já testado e em produção.

**Negativas / riscos aceitos**
- 5 das 6 opções de "retorno de fluxo" do bug são só metadado — o runtime
  não roteia automaticamente entre disciplinas/times. Rotulado
  explicitamente na UI, não escondido.
- O checklist de 12 eixos nunca é marcado item a item — só os rótulos fixos
  ao lado do relato livre do revisor. Rejeitamos deliberadamente fabricar
  esse cruzamento.
- `line_stats` depende de parsear a saída textual de `git diff --shortstat`
  (sem opção estruturada no git) — comportamento estável entre versões
  recentes de git, mas não é uma API formal.
