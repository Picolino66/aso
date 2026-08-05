# ADR-0019 — Roteamento de falha

- **Status:** ACCEPTED
- **Fase:** F5 (evolução pós-O5)
- **Data:** 2026-07-30
- **Relaciona-se com:** [ADR-0009](ADR-0009-entrega-de-codigo-governada.md) (entrega
  governada), [ADR-0016](ADR-0016-ficha-da-demanda.md) (a ficha alimenta o risco que
  decide o gate de risco, §4.7 desta ADR), [ADR-0017](ADR-0017-revisao-independente-de-codigo.md)
  (revisão independente e `card.executor` — sem ele a troca de executor não teria de
  onde partir; emendada por esta ADR), [ADR-0018](ADR-0018-kanban-fiel-colunas-e-dependencias.md)
  (colunas e `dependencies`/`blocked_by`; emendada por esta ADR), [`fluxo.md`](../../fluxo.md)
  §13 e o **Princípio central**

## Contexto

O `fluxo.md` fecha com um princípio que a esteira ainda não cumpria:

> *"Nenhuma falha encerra silenciosamente a execução. Quando uma etapa falha, a
> esteira identifica o ponto de interrupção, registra a causa, define um novo agente
> ou mantém o agente atual, ajusta o modelo ou o nível de effort quando necessário e
> retorna para a etapa correta. (...) Ele retorna exatamente ao ponto responsável
> pelo erro."*

A primeira metade (identificar e registrar) já existia (`block_reason`, event log,
`next_step`). A segunda (decidir e retornar ao ponto certo) não: `AgentSupervisor`
re-tentava 2x com o mesmo provider/modelo/effort e o nudge era o texto cru da
exceção; `OrchestrationService.retry` reexecutava cegamente todos os cards
`Ready`/`Failed`/`Blocked` sem olhar o motivo; a falha era registrada em só 400
caracteres (stdout+stderr colados); gate reprovado só travava, sem apontar o card
responsável.

Esta entrega também fecha duas pendências das ADRs anteriores, por sinergia com o
§13 (registrar causa/próxima ação a cada falha) e o §8 (registrar os mesmos campos a
cada movimentação de card) — é o mesmo dado, gravado no mesmo ponto:

1. **Gate de risco contornável (ADR-0017):** `report_review("approved")` só checava
   se havia um veredito aprovado, nunca se o *risco da demanda* exigia confirmação
   humana. Em demanda de alto risco, o agente aprovando bastava para fechar a
   revisão — a "confirmação humana" virava um clique de `operator`, sem
   justificativa, mesmo com `next_step` anunciando que o bloqueio exige `admin`.
2. **Auditoria de movimentação (ADR-0018):** `CardEvent` só guardava
   `from_status`/`to_status`/`actor`/`created_at`. O §8 exige motivo, resultado,
   evidências e próxima ação a cada movimentação — só `reason` existia, e só era
   usado para preencher `block_reason` quando o destino era `Blocked`.

Fora do escopo (registrado como limitação, não implementado): ficha de encerramento
do card (§23, é um bloco coeso e independente — pertence à entrega final do Kanban
fiel); `populate_from_plan` (planejamento por LLM) não popula `dependencies` (já
documentado na ADR-0018); `blocked_by` continua "preguiçoso" (ADR-0018).

## Decisão

### 1. `control/failure.py` — política pura, sem I/O

Mesmo princípio de `next_step.py`/`branch_naming.py`: `diagnosticar`/`decidir` são
funções puras — dado o mesmo `FailureRecord` e o mesmo catálogo, a decisão é sempre a
mesma. Nenhum LLM decide o roteamento; decisão de governança é regra, não palpite.

**`FailureRecord`** — o que o §13 manda registrar: `etapa` (`execucao`/`gate`/`ci`/
`review`), `tentativa`, `comando`, `mensagem`, `saida`, `arquivos`, `executor`,
`effort`, `at`.

**`diagnosticar`** — heurística por palavras-chave (não regex por linguagem: frágil
e fora de escopo) sobre `mensagem + saida`: `sem_permissao`, `timeout`,
`teste_falhou`, `diff_vazio`, `agente_indisponivel`, `desconhecido`. A marca
`"diff vazio"` (`MARCA_DIFF_VAZIO`) sai de `next_step.py` — que agora importa de
`control/failure.py` — para não duplicar a heurística em dois lugares.

**Tabela de política** (`_TABELA`, diagnóstico → passos por nº de falha):

| Diagnóstico | 1ª falha | 2ª | 3ª | 4ª |
|---|---|---|---|---|
| `sem_permissao` | **bloquear** | — | — | — |
| `timeout` | aumentar effort | trocar executor | escalar humano | — |
| `teste_falhou` | mesmo agente + nudge | aumentar effort | trocar executor | escalar humano |
| `diff_vazio` | mesmo agente + nudge | trocar executor | escalar humano | — |
| `agente_indisponivel` | trocar executor | escalar humano | — | — |
| `desconhecido` | mesmo agente | escalar humano | — | — |

`sem_permissao` nunca re-tenta: é a única causa fora do alcance do agente (nenhum
effort concede permissão de escrita ao CLI). Quando um passo não é resolvível
(`aumentar_effort` já no topo do effort, `trocar_executor` sem outro perfil
disponível ou sem catálogo), a política cai para o próximo degrau da tabela.

`ASO_MAX_ESCALONAMENTOS` (default `3`) é o limite duro: esgotado, a ação é sempre
`escalar_humano`, mesmo que a tabela ainda tivesse passo de retry — o laço de
`run_card` nunca fica aberto para sempre.

**`proximo_effort`** sobe um degrau em `low/medium/high` respeitando
`supported_efforts` do perfil (perfis Codex gerenciados podem ter uma lista própria).
**`proximo_executor`** escolhe outro perfil **disponível** (`profile.available`) do
mesmo `kind`, nunca o atual.

### 2. Persistência: `card.failures` (ring de 5) + `CardEvent` ampliado

`KanbanCard.failures: list[dict[str, Any]]` — ring das últimas 5 falhas, coluna
JSONB em `kanban_cards` (mesmo raciocínio das ADR-0014/0016/0017: o repositório
reescreve a linha inteira do card a cada `save`).

`CardEvent` ganha `reason`/`result`/`evidence`/`next_action`. `BoardService.move_card`
passa a receber e gravar todos os quatro (antes só usava `reason` para
`block_reason` quando o destino era `Blocked`); `apply_event` (transições
automáticas) preenche `result`/`next_action` a partir de uma tabela por evento
(`_EVENT_RESULT`). `evidence` é `list[str]` → coluna `JSON` (não `card_links`: seguiria
o padrão de `card_links`/`rel`, mas a granularidade por evento não compensa a
indireção de mais uma tabela de junção para uma lista pequena por linha).

Migration `774265ae4b87` (`down_revision=b6e2f4a91c53`): `kanban_cards.failures`
(JSONB) e as 4 colunas de `card_events`.

### 3. Onde a decisão é aplicada — `run_card`, não `AgentSupervisor`

`agents/` só pode importar `shared` e `governance` — `AgentSupervisor` **não** pode
importar `control.failure`. Ele continua burro (retry 2x + nudge textual, como
sempre foi). Quem decide é `OrchestrationService`, que já importa `execution`
(catálogo) e pode importar `control.failure`.

`_route_failure` (chamado por `_apply_execution` em erro): monta o `FailureRecord`,
acrescenta ao ring, diagnostica, decide, registra `FailureRouted` **e** `AgentFailed`
(mantido por compatibilidade — `db/repository.py::aggregate_metrics` já conta
`AgentFailed` para a métrica `agent_failures`) no event log, e move o card via
`move_card` com `reason`/`result`/`next_action` preenchidos (o mesmo dado do §13 e
do §8, gravado no mesmo lugar). `card.block_reason` combina a mensagem técnica crua
com o motivo da política (`"{mensagem} — {motivo}"`) — a política não substitui o
erro real, só acrescenta o porquê da decisão. O nudge da política reaproveita
`card.correction_actions` (canal que `_build_task` já encaminha ao agente desde a
ADR-0017, antes só para correções de revisão) — uma fonte, não duas.

`run_card` ganha um laço: em falha, se a decisão for `mesmo_agente`/
`aumentar_effort`/`trocar_executor`, tenta de novo **dentro da mesma chamada**
(ajustando `effort`/`provider` conforme a decisão); se for `bloquear`/
`escalar_humano`, para. O contador de tentativas vem de `len(card.failures)`,
persistido — o limite sobrevive a um restart da API. `run_plan` (execução
multiagente automática) chama a mesma `_apply_execution`/`_route_failure` uma vez
por card e **não** olha a decisão — a próxima onda simplesmente segue com o que
sobrou; só o caminho manual (`run_card`) re-tenta internamente.

`_catalog_name_of(provider)` resolve o nome do perfil no catálogo a partir de
`provider.id` (que para `LlmExecutionProvider` vem prefixado `llm:`) — sem isto,
`ExecutorCatalog.get()`/`proximo_executor` nunca encontrariam o perfil ao decidir.

### 4. `Failed` vs `NeedsFix` vs `Blocked` — coluna por decisão, não por causa

- **`Failed`**: reservado ao que a política decidiu **não re-tentar automaticamente**
  (`escalar_humano`, ou o limite duro esgotado). Antes, `Failed` recebia toda falha
  de execução indiscriminadamente.
- **`NeedsFix`**: CI reprovada (`report_ci`, evento `CIFailed`) — corrigível e
  reexecutável, não um beco sem saída. `_EVENT_TRANSITIONS["CIFailed"]` mudou de
  `Failed` para `NeedsFix` (o `plano2.md`/ADR-0017 já adiava essa troca de
  propósito para este incremento). `report_ci` também registra um `FailureRecord`
  (`etapa=ci`) e um nudge em `correction_actions`.
- **`Blocked`**: `bloquear` (ex.: `sem_permissao`) ou dependência pendente (ADR-0018)
  — ambos "pare e corrija algo externo antes de tentar de novo".

### 5. Reentrada na etapa correta (Princípio central)

`OrchestrationService.retry` deixa de reexecutar tudo às cegas: se o **último**
`QualityGateResult` da orquestração reprovou (`GateStatus.FAILED`) e ainda é o mais
recente da sua fase, roteia **só os cards dessa fase que não chegaram a `Done`** —
"retorna exatamente ao ponto responsável pelo erro", não reinicia a fase inteira.
Cada card pendente ganha um `FailureRecord` (`etapa=gate`) com o resumo do gate
(`required_actions`/`blocking_issues`/`criteria` reprovados — já capturados pelo
`QualityGateResult`, sem re-executar o comando) e um nudge, depois passa por
`run_card` normalmente (que aplica sua própria política de execução em cima). Fora
desse caso, `retry` cai na varredura genérica de sempre (`Ready`/`Failed`/`Blocked`).
Cada `run_card` dentro do laço é protegido por `try/except (KeyError, ValueError)`:
uma dependência ainda pendente (ADR-0018) não derruba o resto do retry.

`execution/gate_command.py`: `SAIDA_MAX` sobe de 400 para 4000 — 400 caracteres não
cabiam um stack trace nem a linha do teste que falhou. Isto já beneficia
`GateCriterionResult.failure_reason` (herda a cauda maior automaticamente), que é o
que `retry`/`next_step` leem — nenhuma nova função foi necessária para isto:
avaliada e descartada uma variante que devolvesse um `FailureRecord` estruturado
direto de `gate_command.py` (ficaria em `execution/`, que não pode importar
`control/failure.py` — regra de dependência —, e devolveria dados sem consumidor real
neste incremento; melhor não introduzir código morto).

### 6. Gate de risco contornável (§4.7) — pendência da ADR-0017

Uma condição em `report_review`: além de exigir veredito aprovado OU justificativa,
agora também exige justificativa quando `exige_confirmacao_humana(brief)` é
verdadeiro — mesmo com veredito aprovado pelo agente. Risco alto/crítico (ou
impacto sensível) não fecha a revisão com o clique de aprovar sozinho; precisa de
uma decisão humana registrada. Como a justificativa passa a ser obrigatória nesse
caminho, o handler da API já escala para `admin` (checagem existente desde a
ADR-0017) — o `role="admin"` que o bloqueio `pr_review_humana` do `next_step`
declara passa a ser verdade, sem mudar `required_role`.

### 7. API e UI

```
GET  /v1/orchestrations/{id}/cards/{card}/failures   # viewer — histórico do §13
POST /v1/orchestrations/{id}/cards/{card}/route      # operator — aplica a política agora
```

`route_card` só chama `run_card` de novo — reaproveita o mesmo laço; existe para o
operador destravar um card escalado/bloqueado depois de corrigir a causa (ex.: ajustar
o perfil do executor), sem o que "escalar para humano" seria um beco sem saída.

`next_step`: `cards_falhos` passa a ter severidade `SEVERITY_HUMAN` (não
`SEVERITY_BLOCKS`) — `Failed` só é alcançado via `escalar_humano` agora — e o
`detail` mostra o diagnóstico (recomputado com `diagnosticar` sobre a última entrada
de `card.failures`) e o número de tentativas, não só `block_reason`.

Tela de detalhe: `<details>` com o histórico de tentativas (etapa, mensagem,
executor, effort, timestamp) por card; botão "↻ Rodar roteamento" quando o card está
em `Failed`.

## Consequências

**Positivas**
- Nenhuma falha reexecuta cegamente com a mesma configuração — a decisão é
  determinística e testável isoladamente (`control/failure.py` não tem I/O).
- `Failed` deixa de ser "qualquer falha de execução" e passa a significar "a
  política decidiu que precisa de humano" — sinal mais confiável para o operador.
- Gate reprovado aponta exatamente os cards responsáveis, não força reexecutar a
  fase inteira.
- `docs/api.md` deixa de subestimar o que `pr_review_humana` exige — o `role=admin`
  anunciado pelo `next_step` agora é sempre verdade.
- `CardEvent` vira uma trilha de auditoria de verdade (§8), não só um log de
  transições de coluna.

**Negativas / riscos aceitos**
- A política é determinística e não aprende com o tempo — o §24 (aprendizado da
  esteira) é outro incremento; `card.failures` é o insumo estruturado que faltava
  para ele, não a implementação.
- `diagnosticar` é heurística por palavras-chave sobre texto livre — pode
  classificar errado uma mensagem atípica; o fallback (`desconhecido`) sempre existe
  e ainda assim tenta uma vez antes de escalar.
- `sem_permissao` depende da mesma heurística de texto que já existia em
  `next_step.py` (agora centralizada, não duplicada) — não é uma detecção
  estrutural do exit code/flag do CLI.
- Nudge da política reaproveita `card.correction_actions` (canal criado para
  correções de revisão, ADR-0017) — dois usos no mesmo campo; aceito para não criar
  um canal novo redundante, mas exige lembrar disso ao ler o campo.

## Emenda (2026-07-31, ADR-0021)

`run_gate_command` ainda colava `(stdout + stderr)` antes de cortar em `SAIDA_MAX`
— uma saída longa de stdout podia empurrar o stack trace de stderr para fora da
janela. A [ADR-0021](ADR-0021-especificacao-e-revisao-documental.md) (D2, §4.8)
corrigiu: cada fluxo é cortado no seu próprio `SAIDA_MAX` antes de juntar.

## Emenda (2026-07-31, ADR-0022)

`diagnosticar` deixou de depender só de heurística por palavra-chave. A
[ADR-0022](ADR-0022-bateria-de-validacoes-e-effort-automatico.md) deu a
`FailureRecord` os campos `check`/`categoria` (preenchidos quando a falha vem de
uma verificação nomeada da bateria do §12): com `categoria` preenchida, o
diagnóstico é direto (`_CATEGORIA_DIAGNOSTICO`) — fato, não palpite. A heurística
por palavras-chave só roda quando não há categoria, preservando o comportamento de
toda falha de execução (não de gate) e de toda orquestração sem bateria nomeada.

Dois diagnósticos novos entraram na tabela de política (§4.1 acima):

| Diagnóstico | 1ª | 2ª | 3ª |
|---|---|---|---|
| `falha_trivial` (formatação/lint) | mesmo agente + nudge com a saída | mesmo agente | escalar humano |
| `risco_alto` (segurança/dependências) | escalar humano | — | — |

`_gate_retry_targets` passa a diagnosticar e decidir a cada gate reprovado,
gravando a escalada (effort/executor) em `agent_assignments[fase]` — antes, uma
reprovação de gate só registrava a falha e reexecutava com o mesmo agente/effort,
sem passar pela política de escalonamento nenhuma vez.
