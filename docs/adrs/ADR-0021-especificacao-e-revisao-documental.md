# ADR-0021 — Especificação e revisão documental

- **Status:** ACCEPTED
- **Fase:** F5 (evolução pós-O5)
- **Data:** 2026-07-31
- **Relaciona-se com:** [ADR-0008](ADR-0008-workspace-por-orquestracao.md) (docs-first —
  distingue spec de documentação do código existente), [ADR-0014](ADR-0014-agente-por-etapa-e-nomes-semanticos.md)
  (executor por etapa), [ADR-0016](ADR-0016-ficha-da-demanda.md) (`DemandBrief`),
  [ADR-0017](ADR-0017-revisao-independente-de-codigo.md) (padrão de veredito e
  independência de revisor), [ADR-0018](ADR-0018-kanban-fiel-colunas-e-dependencias.md)
  (dependências/`blocked_by`, emendada aqui), [ADR-0019](ADR-0019-roteamento-de-falha.md)
  (`stdout`/`stderr` do gate, emendada aqui), [ADR-0020](ADR-0020-discovery-e-aprovacao.md)
  (D1 — discovery/aprovação, versionamento emendado aqui), [`fluxo.md`](../../fluxo.md)
  §5–§7, §10, §23

## Contexto

`plano3.md` §10 batizou o Incremento D ("artefatos por fase", `fluxo.md` §3–§6) como a
maior lacuna do runtime e recomendou quebrá-lo em duas entregas. A ADR-0020 (D1)
fechou §3/§4 (discovery + aprovação). Esta ADR é **D2: especificação + revisão
documental (§5/§6)**, planejada em `plano4.md`. Com ela, a ponta documental do
`fluxo.md` fecha: demanda → ficha → discovery aprovado → **especificação → revisão
documental** → cards.

`plano4.md` também varreu vestígios deixados pelas ADRs 0016–0020 que só faziam
sentido resolver *depois* de existir uma especificação real — cinco entram nesta
entrega (o sexto, o desenho comum dos serviços de agente, também entra, mas como
decisão estrutural própria, não um vestígio de requisito):

1. **Discovery não era versionado** (risco aceito na ADR-0020) — o §6 exige um ciclo
   de reprovação/reenvio; sem histórico não há como responder "esta spec já foi
   reprovada duas vezes, pelos mesmos motivos?".
2. **Ficha de encerramento do card (§23)** — adiada duas vezes (ADR-0018, ADR-0019).
3. **`populate_from_plan` não populava `dependencies`** — e é o caminho que
   `full-pipeline` (modo default) usa de verdade.
4. **`blocked_by` preguiçoso** — só se preenchia quando alguém tentava rodar o card.
5. **`run_gate_command` colava `stdout`+`stderr` antes de cortar** — uma saída longa
   de stdout empurrava o stack trace de stderr para fora da janela do §13.

## Decisão

### 1. Extração comum aos serviços de agente (`control/agent_ask.py`)

Antes de escrever mais dois serviços (spec + revisão documental), a duplicação que
`naming`/`triage`/`review`/`discovery` já carregavam (`_perguntar` bifurcando
`kind == "llm"` / `kind == "cli"`, `_rodar_cli` com `TemporaryDirectory` +
`subprocess.run`, a mesma tupla de exceções, `parse_llm_json` nos dois ramos) foi
extraída para `perguntar_ao_agente(catalog, assignment, *, system, pedido, kind,
timeout)`. **Refatoração de forma, não de comportamento**: os quatro serviços
existentes passaram a chamá-la e a suíte pré-existente (naming/triage/review/
discovery) passou **sem alteração** — é o critério de aceite da extração. Prompt de
sistema, `_sanear` e fallback continuam em cada serviço.

### 2. Versionamento de documentos em ring (`control/documentos.py`)

`Orchestration.discovery_report: dict` (singular, ADR-0020) virou
`discovery_reports: list[dict]`, e ganhou uma irmã, `spec_documents: list[dict]` —
mesmo raciocínio das ADR-0014/0016/0017/0019 (sem tabela nova; a linha da
orquestração é reescrita a cada `save`), agora como **ring de até 5 versões**
(`LIMITE_RING`, `control/documentos.py`). Cada documento carrega `versao` (1-based,
**monotônica mesmo depois do ring descartar o item mais antigo** — calculada a
partir do último item, não do tamanho da lista) e `revisao_comentarios` da rodada
que o reprovou. `proxima_versao`/`acrescentar_versao`/`versao_atual` são funções
puras reaproveitadas por discovery e spec.

`run_discovery`/`run_spec` **acrescentam** uma versão nova ao ring;
`decide_discovery`/`approve_spec`/`run_spec_review` **atualizam a última no lugar**
(mudam status/comentário sem criar versão — decidir não é uma nova rodada de
produção do documento).

**Migration com compatibilidade** (`c1a3e7f92b4d`): `discovery_report` singular
migra para `discovery_reports[0]` (com `versao=1` se ausente) antes de a coluna
antiga ser removida; `downgrade` é simétrico (pega a última versão do ring). A
mesma migration acrescenta `spec_documents` (`orchestrations`) e `closure`
(`kanban_cards`, decisão 5) — um único arquivo para as três mudanças de schema
deste incremento, mesmo padrão da ADR-0019.

### 3. `SpecDocument`/`SpecService` (`control/spec.py`) — espelha `discovery.py`

`especificar(assignment, *, demand_brief, discovery, comentarios_anteriores)` **exige
discovery aprovado** (`ValueError` → 409 se não): "com o discovery aprovado" é regra
do §5, não detalhe de implementação. Fallback determinístico (esqueleto a partir do
brief + discovery) nunca falha e **nunca sai `aprovado`** — nem o fallback nem o
agente: todo documento passa por `STATUS_AGUARDANDO_REVISAO` até a revisão
documental decidir.

Os artefatos opcionais do §5 (diagrama de componentes, diagrama de fluxo, modelo de
dados, contrato de API, plano de migração) são **conteúdo, não estrutura**: o
prompt instrui o agente a colocá-los em Markdown dentro de
`componentes`/`alteracoes_banco`/`alteracoes_infra` — a spec não ganhou onze campos
novos para isso.

`itens_de_trabalho: list[SpecWorkItem]` (`titulo`, `fase`, `dominio`,
`criterios_de_aceite`, `depende_de`) é a decomposição sugerida que alimenta o §7 e
resolve o vestígio 3 (abaixo). `depende_de` referencia **título** de um irmão da
mesma lista — saneado contra auto-referência e título inexistente (descartado, não
propagado).

**`SPEC_KEY = "especificacao"`** entra em `_validate_assignment_key`
(`control/models.py`) ao lado de `naming`/`triagem`/`revisao`/`discovery` — herda o
endpoint genérico `PUT/DELETE /agents/{key}` e a UI de configuração sem código
novo. (A mesma correção foi aplicada a `DISCOVERY_KEY`, que a ADR-0020 tinha
deixado fora dessa tupla por descuido — `agent_assignments["discovery"]` nunca
podia ser configurado via API antes desta ADR.)

### 4. Revisão documental — `ReviewService.revisar_documento` (§6)

**Estende `ReviewService`, não cria um terceiro serviço**: ele já tem a forma certa
(veredito + ações objetivas + fallback que nunca aprova). Vocabulário próprio —
`DocReviewVerdict` com os **quatro** desfechos do §6 (`aprovado`,
`aprovado_com_observacoes`, `reprovado`, `necessita_humano`), **não os cinco do
§14** (não existe `alteracoes_obrigatorias` aqui; reaproveitar o enum do code
review por preguiça teria misturado dois vocabulários com desfechos diferentes).

Dois dos nove eixos do §6 são **fatos, não opinião**, e reprovam **sem gastar um
agente**: presença de `estrategia_de_testes` e de `plano_de_rollback` (só se
aplicam a `SpecDocument` — checados via `getattr` com default, sem importar
`spec.py` de `review.py`, para não acoplar os dois módulos). Esta checagem roda
**antes** de qualquer resolução de revisor — inclusive quando não há revisor
disponível (`assignment=None`), porque ela não depende de agente.

**Independência do revisor**: `_resolve_reviewer` (`orchestration_service.py`,
ADR-0017) foi generalizado — trocou `card: KanbanCard` por `origem_executor: str |
None` — para servir tanto ao code review (`origem_executor=card.executor`) quanto à
revisão documental (`origem_executor=spec.origem`, `None` quando a origem é
`"heuristica"`, que não é um executor de verdade).

**Ciclo com limite**: `ASO_MAX_RODADAS_DOC` (default 3, env var). `spec.rodadas_
revisao` atravessa regenerações (carregado de `anterior.rodadas_revisao` em
`run_spec`, não reiniciado a cada nova versão) — um "reprovado" que estouraria o
limite vira `necessita_humano` em `run_spec_review`, e só admin decide via
`POST .../spec/approve` (mesmo padrão crítico de `decide_discovery`). Sem o limite,
dois agentes (autor/revisor) discordando indefinidamente queimaria tokens sem fim —
o §6 diz "o ciclo continua até que o documento seja aprovado", mas isso descreve o
objetivo, não uma licença para rodar sem parar.

Quando a especificação chega a `aprovado`/`aprovado_com_observacoes`,
`_materialize_spec_cards` cria os cards de `itens_de_trabalho` — mesmo padrão de
`populate_from_plan` (domínio→agente via `_DOMAIN_AGENTS`, agora um módulo
compartilhado), com dependências resolvidas título→id numa segunda passada.
Domínio desconhecido é **descartado** (não recusa a aprovação da spec por isso —
diferente de `populate_from_plan`, que roda antes de qualquer custo ser pago).

### 5. Ficha de encerramento do card (§23) — `KanbanCard.closure`

`closure: dict[str, Any]` (JSONB), preenchida em `merge_pr` — o ponto em que o card
chega a Done. Só registra o que o runtime **já tem à mão**: resumo (título da PR),
executor (`card.executor`), revisor (`pr.reviewed_by`), branch, id da PR, rodadas
de revisão, versões correntes de discovery/spec (quando existirem), evidências
(`CI: <status>`, `Revisão: <status>`) e riscos residuais (ações do veredito com
severidade `sugestao` — por definição, não bloquearam a aprovação, mas ficam
registradas). Campos do §23 que o runtime não tem (data de implantação, commits
individuais) **ficam de fora** — ficha com campo inventado é pior que ficha curta.

### 6. Dependências no caminho padrão (`populate_from_plan`)

`BacklogItem.depends_on: list[str]` (títulos de irmãos) — `_PLANNING_SYSTEM` passa a
pedir a ordem de execução ao LLM. `populate_from_plan` resolve título→id numa
segunda passada, **exatamente** o padrão que `create_orchestration` já usa para
`PlannedAgent.depends_on` (`id_por_agente`) — inclusive o descarte silencioso de
referência desconhecida. `full-pipeline` é o modo default de
`CreateOrchestrationBody`, e é ele que passa por `populate_from_plan`: sem isto,
quase nenhum card nascia com dependência no caminho que os usuários realmente usam,
e o trabalho de dependências da ADR-0018 ficava adormecido.

### 7. `blocked_by` ativo (`BoardService._refresh_dependents`)

Quando um card chega a `Done` (`move_card`), os cards que o listam em
`dependencies` têm `blocked_by` recalculado. Se um card **já estava em `Blocked`
por dependência** (`blocked_by` não vazio antes do recálculo) e a última pendência
acabou de resolver, ele é movido automaticamente para `Ready`. **Deliberadamente
conservador**: só libera cards que a checagem de dependência já havia marcado —
nunca mexe em cards bloqueados por outro motivo (conflito de contexto, roteamento
de falha) —, e `OrchestrationService._pending_dependencies` continua sendo a
checagem autoritativa antes de qualquer execução (este observador é conveniência de
visualização/desbloqueio, não a fonte de verdade).

### 8. `stdout`/`stderr` separados (`gate_command.py`)

`run_gate_command` cortava `(stdout + stderr)` **depois** de concatenar — uma
`SAIDA_MAX` saída longa de stdout empurrava o stack trace de stderr para fora da
janela, exatamente o que o §13 (ADR-0019) precisa preservar. Agora cada fluxo é
cortado no seu próprio `SAIDA_MAX` antes de juntar.

### 9. API

```
GET  /v1/orchestrations/{id}/spec                     # viewer — versão corrente
GET  /v1/orchestrations/{id}/spec/history              # viewer — o ring
POST /v1/orchestrations/{id}/spec/run                  # operator — gera/regenera
POST /v1/orchestrations/{id}/spec/review                # operator — revisão documental
POST /v1/orchestrations/{id}/spec/approve                # admin — decisão humana (§4.4)
GET  /v1/orchestrations/{id}/discovery/history          # viewer — o ring do D1
GET  /v1/orchestrations/{id}/cards/{card_id}/closure    # viewer — ficha do §23
```
`especificacao` herda `PUT/DELETE /agents/{key}` de graça (decisão 3).
`required_role` (`api/auth.py`) já manda `/approve`-suffixed para admin e `GET` para
viewer; só `/spec/approve` precisou entrar na lista de sufixos administrativos
(ao lado de `/discovery/decide`).

**F5 não começa sem especificação aprovada em `full-pipeline`** — guarda em
`run_phase` (não uma checagem de quality gate): `ValueError` → 409 antes de rodar
qualquer card de F5. **Não-regressivo**: só ativa quando o fluxo de discovery foi
de fato usado (`discovery_reports` não vazio) — mesma regra da ADR-0020 §6 para o
critério `discovery_aprovado`. Sem isso, a suíte inteira (que testa F5 chamando
`run_phase(Phase.F5)` diretamente, sem nunca passar por discovery) teria quebrado:
confirmado revertendo a checagem para "sempre exigir" e observando 9 testes
pré-existentes falharem, depois corrigido para a regra condicional acima —
**zero regressão** com a versão final. `next_step` espelha a mesma condição
(`_spec_blocker`, severidade `bloqueia` só quando a checagem está de fato ativa).

## Consequências

**Positivas**
- `fluxo.md` §1–§6 fecham: demanda → ficha → discovery → **spec → revisão
  documental** → cards, todos versionados e auditáveis.
- Cinco vestígios de ADRs anteriores resolvidos (versionamento, ficha de
  encerramento, dependências do caminho padrão, `blocked_by` ativo,
  `stdout`/`stderr` do gate) sem abrir cinco ADRs separadas.
- A extração de `agent_ask.py` evita a sexta cópia do bloco `_perguntar`/
  `_rodar_cli` que este incremento teria produzido.
- Suíte pré-existente de naming/triage/review/discovery **inalterada** (624 testes
  no total, 92%+ cobertura) — confirma que a extração foi refatoração pura e que o
  gate de F5 é vacuamente ok para quem nunca usa discovery/spec.

**Negativas / riscos aceitos**
- `_materialize_spec_cards` descarta silenciosamente item de trabalho com domínio
  desconhecido — aceito porque recusar a aprovação da spec por isso desperdiçaria
  o ciclo de revisão já pago; o operador vê menos cards do que o esperado, não um
  erro.
- `blocked_by` ativo cobre só o caminho feliz (card chega a Done); um card
  cancelado ou arquivado não libera dependentes automaticamente — aceito como
  simplificação (`_pending_dependencies` continua correto, só não recalcula
  proativamente nesses casos).
- Épico → história → subtarefa (§7) e a bateria de checks por categoria (§12) 
  continuam fora de escopo — ver `plano4.md` §11 para o mapa completo do que resta.

## Emenda (2026-07-31, ADR-0022)

Dois itens deste ADR fecharam na [ADR-0022](ADR-0022-bateria-de-validacoes-e-effort-automatico.md):

- O risco aceito acima ("`blocked_by` ativo cobre só o caminho feliz... cancelado
  ou arquivado não libera dependentes") está **resolvido**:
  `BoardService._refresh_dependents` agora reage também a `Cancelled`/`Archived` —
  bloqueia o dependente com motivo explícito (a dependência foi abandonada, não
  satisfeita), em vez de deixá-lo bloqueado para sempre em silêncio.
- `tipo="especificacao"` era um literal solto em `review.py`/coincidia por acaso
  com `SPEC_KEY` (`control/models.py`); os dois pontos agora importam a constante —
  se divergissem, a checagem determinística de testes/rollback do §6 se desligaria
  sem erro nenhum.

A bateria de checks por categoria (§12) também fechou na ADR-0022; épico → história
→ subtarefa (§7) segue fora de escopo, pendência nomeada lá.

## Emenda (2026-07-31, ADR-0025)

Épico → história → subtarefa (§7) fechou na
[ADR-0025](ADR-0025-qa-hierarquia-aprendizado.md). `SpecWorkItem` ganha
`tipo: str = "Task"` e `itens_filhos: list[SpecWorkItem]` (só um nível);
`_materialize_spec_cards` resolve `parent_id` pelo título do pai, na mesma
segunda passada que já resolvia `depende_de`.
