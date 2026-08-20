# ADR-0032 — Incident como entidade de primeira classe

- **Status:** ACCEPTED
- **Fase:** F7 (operação e evolução)
- **Data:** 2026-08-06
- **Relaciona-se com:** [ADR-0023](ADR-0023-implantacao-governada.md) (implantação
  governada — `rollback_deploy` já criava `KanbanCard(type=Incident)`, continua
  criando exatamente igual; esta ADR só acrescenta o objeto `Incident` vinculado),
  [ADR-0025](ADR-0025-qa-hierarquia-aprendizado.md) (`QaCheck.gravidade`, vocabulário
  reaproveitado), [`fluxo.md`](../../fluxo.md) §21, [`wiframe-fluxo.md`](../../wiframe-fluxo.md)
  §27/§38

## Contexto

`fluxo.md` §21 fecha o rollback com: *"Depois do rollback, é aberta uma tarefa de
análise de causa raiz."* Isso já existia — `rollback_deploy` (ADR-0023) sempre cria
um `KanbanCard(type=CardType.INCIDENT, status=Backlog)`. O que faltava é o que o
wireframe (§27.2, tela 25) mostra: um objeto **com identidade própria**
("Incidente: INC-092"), gravidade, vínculo estruturado com o deploy revertido e um
ciclo de vida que sobrevive ao card de causa raiz (que é só uma tarefa a executar,
não o registro do incidente em si). `wiframe-fluxo.md` §38 lista `Incident` entre
33 entidades sugeridas, sem detalhar campos — mesma situação de `RoutingRule` antes
da ADR-0028.

## Decisão

### 1. Entidade própria, não campo do card — padrão de `PullRequest`/`CandidateRun`

Diferente de `preparation_checklist`/`tentativas`/`failures`/`qa_checks` (FID-01 a
FID-04 desta trilha, campos dentro de `KanbanCard` porque são inerentemente
escopados a UM card), `Incident` tem identidade própria e é referenciado de fora
(pelo card de causa raiz, pelo deploy revertido) — o padrão correto, confirmado
pelas entidades já existentes do mesmo formato (`governance/models.py::PullRequest`/
`CandidateRun`/`SloEvaluation`), é uma entidade Pydantic própria (`id`,
`orchestration_id`), persistida em tabela dedicada, listada em
`OrchestrationState`/`OrchestrationBundle` como `incidents: list[Incident]` — mesma
posição na cadeia de save/load das outras três, mesmo nível FK-safe em
`_CHILD_TABLES`.

### 2. `Incident.timeline` — a primeira entidade do projeto com timeline embutida

Nenhuma entidade de governança hoje tem uma sub-lista de eventos embutida —
`PullRequest.review_verdict` é só o último veredito, `PullRequest.review_rounds` é
um contador, e o "histórico" de `CandidateRun`/`SloEvaluation` é ter várias
instâncias imutáveis na lista, nunca uma lista dentro de uma instância. `Incident`
quebra esse padrão deliberadamente: um incidente é **um objeto de vida longa que
muda de estado** (aberto → investigando → resolvido), não um evento imutável nem
uma série de amostras — cada instância JÁ é "o incidente", então sua timeline
precisa viver dentro dela. `IncidentTimelineEntry` (`evento`/`detalhe`/`actor`/
`at`) é acrescentada em cada transição (`_criar_incidente`, `investigate_incident`,
`resolve_incident`) — nunca removida, nunca reescrita.

### 3. Vínculo com o deploy — por snapshot, não por FK real

`DeployRun` não tem `id` próprio (é um `dict` versionado dentro do ring
`Orchestration.deploy_runs`, ADR-0023) — não há o que referenciar por chave
estrangeira. `Incident.deploy_ambiente`/`deploy_estagio`/`deploy_versao` são um
**snapshot** dos mesmos campos do `DeployRun` revertido no momento da criação —
mesma disciplina de "só registra o que o runtime tem à mão" já usada em
`_build_card_closure` (§23, ADR-0021). Dar um `id` estável a `DeployRun` para
permitir uma FK real é mudança de escopo maior, fora deste card — registrada como
corte consciente, não lacuna esquecida.

### 4. Gravidade — reaproveita o vocabulário de `QaCheck`, derivada do risco da demanda

`baixa | media | alta | critica` — mesmo vocabulário de `QaCheck.gravidade`
(ADR-0025) e o que o wireframe usa literalmente (§27.2: "Gravidade: Crítica"), não
um novo vocabulário em inglês (`severity: ok|warning|critical`, que já existe em
`SloEvaluation` mas serve a um domínio diferente — burn-rate de SLO, não gravidade
de incidente operacional). `_RISCO_PARA_GRAVIDADE` (inverso de
`_GRAVIDADE_PARA_PRIORIDADE`, já usada por `_criar_bug_de_qa`) deriva a gravidade
do `RiskLevel` já triado na `DemandBrief` da orquestração — nenhuma pergunta nova
ao operador, nenhum valor inventado; sem ficha triada, cai em `"media"` (default
conservador, mesmo comportamento de `QaCheck`).

### 5. Ciclo de vida — dois estágios, `card_id` independente

`aberto` (criação, automática) → `investigando` (opcional, `POST .../investigate`)
→ `resolvido` (`POST .../resolve`, exige `causa_raiz` não vazia). Um incidente
resolvido não pode ser reaberto para investigação nem resolvido de novo (`ValueError`
em ambos os métodos) — resolver é uma decisão final; se a causa raiz precisar ser
revista, é uma decisão de produto fora do escopo deste card. `Incident.card_id`
aponta para o `KanbanCard(type=Incident)` que já existia (a tarefa de análise de
causa raiz do §21) — os dois ciclos de vida são **independentes**: o card segue seu
próprio caminho no kanban (`Backlog → ... → Done`), o incidente é resolvido pela
API dedicada quando a causa raiz é identificada, não quando o card fecha. Isto é
deliberado: a causa raiz pode ser identificada antes de todo o trabalho de
correção estar concluído.

### 6. API — mesmo padrão de Context Patches (list + detail escopados)

```
GET  /v1/orchestrations/{id}/incidents                       # viewer
GET  /v1/orchestrations/{id}/incidents/{incident_id}          # viewer, 404 se ausente
POST /v1/orchestrations/{id}/incidents/{incident_id}/investigate  # operator
POST /v1/orchestrations/{id}/incidents/{incident_id}/resolve      # operator
```

Nenhuma rota bate os sufixos de `required_role` que exigem `admin`
(`/approve`/`/reject`/`/rollback`/etc.) — investigar/resolver um incidente é
edição de um artefato operacional, não uma ação crítica; o rollback que o criou já
passou pelo próprio gate de `admin` (ADR-0023).

### 7. Cards `Incident` existentes — nenhuma migração de dado, nenhuma perda

`incidents` é uma tabela nova, vazia por padrão — **nenhum `KanbanCard` existente
é tocado, lido ou reescrito** por esta ADR. Todo `KanbanCard(type=Incident)`
criado por rollbacks anteriores a esta ADR continua exatamente como estava,
acessível por `GET .../cards` como sempre foi. Decisão consciente: **não** fazer
backfill retroativo de `Incident` para esses cards — não há como reconstruir
gravidade/vínculo de deploy de forma confiável a partir só do texto livre de
`description`, e um backfill malfeito (gravidade adivinhada) seria pior que a
ausência do registro. "Migram sem perda" é satisfeito por construção (mudança
100% aditiva), não por reconstrução de histórico.

## Consequências

**Positivas**
- `Incident` ganha identidade própria, gravidade e timeline — fecha a lacuna do
  wireframe §27/§38 sem inventar campos que o runtime não tem como preencher.
- Reaproveita três precedentes já validados no projeto (padrão de entidade de
  `PullRequest`, vocabulário de gravidade de `QaCheck`, disciplina de snapshot de
  `_build_card_closure`) em vez de inventar mecanismos novos.
- Zero regressão: `rollback_deploy` cria o `KanbanCard(Incident)` exatamente como
  antes; `Incident` é estritamente aditivo.

**Negativas / riscos aceitos**
- `Incident.timeline` é a primeira exceção ao padrão "várias instâncias formam o
  histórico" do projeto — um precedente novo, não uma extensão de um já existente;
  documentado aqui para quem ler o código depois não estranhar a inconsistência
  aparente com `PullRequest`/`CandidateRun`.
- Vínculo com o deploy é por snapshot, não FK — um `Incident` não "segue" o
  `DeployRun` se ele for de alguma forma alterado depois (não é o caso hoje:
  `deploy_runs` só cresce por novas tentativas, nunca edita uma entrada passada
  fora de `validate_deploy`/`decide_deploy`/`rollback_deploy`, que já mutam o
  próprio registro no ring antes do incidente existir).
- Cards `Incident` anteriores a esta ADR não têm `Incident` vinculado — visíveis
  só por `GET .../cards`, não por `GET .../incidents`. Aceito e documentado, não
  uma lacuna esquecida.
- `card_id`/ciclo de vida do incidente são independentes — um operador pode
  resolver o incidente (causa raiz identificada) antes do card de correção
  terminar, ou vice-versa; nenhum guard cruza os dois. Se essa sincronização for
  necessária no futuro, é extensão aditiva sem quebra de contrato.
