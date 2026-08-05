# ADR-0022 — Bateria de validações e escolha automática de esforço

- **Status:** ACCEPTED
- **Fase:** F5 (evolução pós-O5)
- **Data:** 2026-07-31
- **Relaciona-se com:** [ADR-0008](ADR-0008-workspace-por-orquestracao.md) (precedente
  de sugestão determinística — scaffold docs-first), [ADR-0016](ADR-0016-ficha-da-demanda.md)
  (`DemandBrief.complexidade`, coletada desde ali e nunca lida até aqui),
  [ADR-0019](ADR-0019-roteamento-de-falha.md) (roteamento de falha, emendada aqui —
  o diagnóstico ganha precisão), [ADR-0021](ADR-0021-especificacao-e-revisao-documental.md)
  (`SPEC_KEY`, risco aceito do `blocked_by` ativo, emendada aqui), [`fluxo.md`](../../fluxo.md)
  §9, §12

## Contexto

`plano5.md` fecha duas lacunas do mesmo tema: **o orquestrador decide, em vez de o
operador configurar.**

**§12** lista quinze verificações próprias (formatação, lint, compilação, type
checking, testes unitários/integração/contrato/e2e, análise estática, dependências,
vulnerabilidades, migrations, documentação, cobertura, desempenho). O runtime tinha
só `Orchestration.validation_command: str | None` — um comando único que virava um
`Criterion("tests_pass", ...)` em `run_quality_gate`. Dava para encadear tudo num
`&&`, mas o gate só sabia que *"o comando falhou"*: perdia-se qual verificação
quebrou, e a primeira falha impedia as seguintes de rodar.

**§9** pede que o orquestrador escolha agente, modelo e esforço por card,
considerando complexidade e risco. Desde o Incremento A (ADR-0016),
`DemandBrief.complexidade` é produzida pelo agente de triagem a cada criação de
orquestração — e nunca foi lida: o único consumidor era um `pill` informativo em
`detalhe.html`. O `plano.md` §4.6 adiou a automação de propósito ("fica para um
incremento próprio"), e esse incremento nunca veio até agora.

O ganho maior está na interação entre os dois: com uma bateria nomeada, o
roteamento de falha (ADR-0019) deixa de **adivinhar** a causa por palavra-chave
(`_PALAVRAS_TESTE_FALHOU` etc.) e passa a **saber**: o gate sabe que falhou `mypy`
(categoria `tipos`), não que "a saída continha a palavra 'error'". A política de
escalonamento passa a distinguir "falhou o lint" (trivial, mesmo agente, nunca sobe
effort) de "falharam os testes de integração" (sobe effort na repetição) — por isso
este incremento vem antes do de implantação: melhora retroativamente o que já foi
construído.

Varredura de vestígios das ADRs 0016–0021 (`plano5.md` §2) trouxe mais dois itens
pequenos, ambos fechados aqui:

1. **`"especificacao"` como literal solto** em `review.py`/`orchestration_service.py`
   — coincidia com `SPEC_KEY` (`control/models.py`) por acidente; se divergissem, a
   checagem determinística de testes/rollback (§6) se desligaria em silêncio.
2. **Card `Cancelled`/`Archived` não liberava dependentes** — risco aceito
   explicitamente na ADR-0021 ("`blocked_by` ativo cobre só o caminho feliz").

Um terceiro item — hierarquia épico → história → subtarefa (§7: `KanbanCard` sem
`parent_id`, nenhum caminho produz cards que não sejam `TASK`) — **fica de fora**
por ser tema diferente (estrutura da decomposição, não decisão automática) e por
mexer em `populate_from_plan`, `SpecWorkItem`, board, UI e migration — tamanho de
incremento próprio. Registrado como pendência nomeada (ver Consequências).

## Decisão

### 1. A bateria (`ValidationCheck`, `control/validation.py`)

```python
class ValidationCheck(BaseModel):
    nome: str
    comando: str
    categoria: str = "testes"   # vocabulário fechado do §12 (CATEGORIAS_VALIDACAO)
    bloqueante: bool = True

# em Orchestration:
validation_checks: list[ValidationCheck] = Field(default_factory=list)
```

**Compatibilidade é requisito, não cortesia**: `validation_command` continua
existindo e funcionando — inclusive em `run_pr_ci` (CI da PR), que continua usando
o campo único sem alteração. `checks_efetivos(orch)` é o único ponto de resolução:
bateria configurada → ela; senão, `validation_command` (ou nada) vira uma
verificação sintética `"testes"`. Nenhuma orquestração existente muda de
comportamento — a maioria nunca vai chamar `PUT .../validation-checks`.

`validate_gate_command` (já usado no `validation_command` legado) passa a validar
**cada comando** da bateria em `set_validation_checks` — um `npm run dev` no meio
da lista travaria o gate para sempre, exatamente como travaria sozinho. Falha
parcial não aplica nada: a lista antiga permanece intacta.

### 2. Um `Criterion` por verificação (`run_quality_gate`)

O bloco único `tests_pass` virou um `Criterion` por `ValidationCheck`, via uma
fábrica (`_check_predicate(comando, repo)`) que fecha `comando`/`repo` por
parâmetro — não por variável de laço. Um `lambda` com `comando=check.comando` como
default-arg funcionaria em runtime, mas o `mypy --strict` não consegue inferir o
tipo contra `Predicate`; a fábrica resolve os dois problemas (closure E tipagem) de
uma vez. **Nenhuma verificação para as outras no primeiro erro**: o
`QualityGateEngine.run` já roda todo `Criterion` registrado num laço simples, sem
curto-circuito — o valor deste incremento é justamente saber *quais* verificações
falharam, não só a primeira.

### 3. Diagnóstico preciso no roteamento de falha (`control/failure.py`)

`FailureRecord` ganha `check: str` e `categoria: str` (vazios = falha de execução,
não de gate nomeado — compatível com todo registro legado). `diagnosticar` passa a
**preferir o fato à heurística**: com `categoria` preenchida, mapeia direto via
`_CATEGORIA_DIAGNOSTICO` — `formatacao`/`lint` → `falha_trivial` (novo
diagnóstico); `seguranca`/`dependencias` → `risco_alto` (novo, escala já na
primeira falha); as demais categorias → `teste_falhou`. Só cai nas palavras-chave
quando não há categoria, preservando o comportamento de toda orquestração legada.

Nova linha na tabela de política (§4.1 da ADR-0019):

| Diagnóstico | 1ª | 2ª | 3ª |
|---|---|---|---|
| `falha_trivial` | mesmo agente + nudge com a saída | mesmo agente | escalar humano |
| `risco_alto` | escalar humano | — | — |

Falha de lint não sobe effort à toa — merece a mensagem do lint no prompt, não um
modelo maior.

`_gate_retry_targets` (chamado por `retry()`) passa a atribuir `check`/`categoria`
ao `FailureRecord` (a partir do primeiro `blocking_issue` presente na bateria
efetiva) e a rodar `diagnosticar`/`decidir` — a escalada (effort maior/outro
executor) é gravada em `agent_assignments[fase]`, não no card isolado: a próxima
chamada de `run_card` de qualquer card da fase já nasce com o degrau novo, porque
`_effective_effort`/`_effective_executor` já consultam a atribuição da etapa antes
de tudo o mais. Sem isso, cada card escalaria isoladamente e do zero.

**Sem re-execução seletiva.** O §13 do `fluxo.md` é categórico: *"Após a correção,
todos os testes relevantes são executados novamente. Não apenas o teste que
falhou."* Com verificações nomeadas, "só rodar o check que falhou" é a otimização
óbvia — e é exatamente o que o `fluxo.md` proíbe (consertar o lint quebra o teste
com frequência). **Decisão explícita: não implementado.** Registrado aqui para que
ninguém "otimize" isso depois sem reabrir esta ADR.

### 4. Sugestão de bateria por stack (`sugerir_bateria`)

Determinística, sem agente (mesmo espírito do scaffold docs-first da ADR-0008):
inspeciona `pyproject.toml`/`setup.cfg` → ruff/mypy/pytest; `package.json` → só os
scripts (`lint`/`test`/`build`) que **existem de fato**; `go.mod` → vet/build/test;
`Cargo.toml` → clippy/fmt/test. Exposta em
`GET .../validation-checks/suggest` — não grava nada; o operador aceita com `PUT`.
Nunca aplicada automaticamente: um comando de gate errado trava a esteira, e
adivinhar por extensão de arquivo erra.

### 5. Escolha automática de esforço (`control/selecao.py`, §9)

```python
def sugerir_effort(complexidade: str, risco: RiskLevel) -> str: ...
```

| Complexidade | Risco `low`/`medium` | Risco `high`/`critical` |
|---|---|---|
| `simples` | `low` | `medium` |
| `intermediaria` | `medium` | `high` |
| `complexa` | `high` | `high` |
| `estrategica` | `high` | topo suportado pelo perfil |

`resolver_topo` resolve o sentinela ("topo suportado pelo perfil") para o último
item de `ExecutorProfile.supported_efforts` (perfis Codex gerenciados descobrem a
lista do menor para o maior; sem lista, "high" é o topo do vocabulário padrão).

**Onde entra na cadeia de `_effective_effort`**: penúltimo degrau, entre a
orquestração e o perfil —

```
explícito → etapa → padrão da orquestração → sugestão automática (§9) → perfil
```

Toda escolha humana continua vencendo; a automação só preenche o vazio que, sem
ela, cairia no default do perfil. **Só age quando a triagem de fato rodou**
(`demand_brief` não vazio) — ficha vazia é "nunca triou", mesma regra de
não-regressão do `discovery_reports`/`spec_documents` (ADR-0020/0021): nenhuma
orquestração que nunca chamou `/brief` muda de effort.

**Interruptor:** `ASO_EFFORT_AUTOMATICO` (default `1`, ligado). Ligar por padrão
**muda comportamento observável** — por isso a sugestão entra abaixo de toda
escolha humana (nunca sobrescreve) e emite `EffortSugerido` no event log
(complexidade, risco, fase, effort escolhido): sem o evento, o operador veria o
esforço mudar sem saber por quê. `ASO_EFFORT_AUTOMATICO=0` restaura o
comportamento anterior byte a byte.

### 6. Os dois vestígios pequenos

- **`SPEC_KEY`**: `review.py` e `orchestration_service.py` agora importam a
  constante de `control/models.py` em vez de comparar contra o literal
  `"especificacao"`. Teste dedicado (`test_vestigios.py`) chama a checagem
  determinística com a CONSTANTE — quebra se `review.py` voltar a um literal
  divergente.
- **Cancelado/arquivado libera dependentes** (risco aceito da ADR-0021, **resolvido
  aqui**): `BoardService._refresh_dependents` agora reage também a
  `Cancelled`/`Archived`, não só a `Done`. Decisão: um dependente de card
  cancelado/arquivado é **bloqueado com motivo explícito**
  (`"dependência(s) cancelada(s)/arquivada(s): <título>"`), não liberado em
  silêncio — a dependência não foi satisfeita, foi abandonada.

### 7. API

```
GET  /v1/orchestrations/{id}/validation-checks           # viewer
PUT  /v1/orchestrations/{id}/validation-checks           # operator — substitui a bateria
GET  /v1/orchestrations/{id}/validation-checks/suggest   # viewer — sugestão por stack
```

`required_role` (`api/auth.py`) já resolvia `GET` → viewer e não-`GET` sem sufixo
especial → operator — nada mudou lá. A tela de detalhe passa a listar a última
execução do gate **verificação por verificação** (✓/✗, evidência num `<details>`) e
mostra a bateria efetiva com um editor simples (JSON + "sugerir por stack"); o pill
de effort da ficha da demanda passa de "sugerido (apenas informativo)" para "efetivo
(automático)", com indicação explícita quando uma escolha manual o sobrepõe.

## Consequências

**Positivas**
- `fluxo.md` §12 fecha: uma bateria nomeada, não um comando único — o gate sabe
  qual verificação falhou, todas rodam até o fim.
- `fluxo.md` §9 fecha parcialmente: esforço automático por complexidade/risco;
  escolha de agente continua manual (não pedida por este incremento).
- O roteamento de falha (ADR-0019) fica **retroativamente mais preciso**: falha
  trivial não desperdiça um degrau de effort; risco alto escala mais cedo.
- Os dois vestígios (`SPEC_KEY`, cancelado/arquivado) fecham sem abrir ADRs
  próprias — ambos eram riscos/lacunas já registrados em ADRs anteriores.
- 691 testes (67 novos deste incremento), 92%+ cobertura, validado em
  Docker/Postgres (bateria com falha nomeada, roteamento por categoria, effort
  automático auditável em `EffortSugerido`, JSONB persistido) — nenhuma
  orquestração pré-existente (só `validation_command`, sem `demand_brief`) muda de
  comportamento.

**Negativas / riscos aceitos**
- **Sem re-execução seletiva de checks** — decisão deliberada (§13 do
  `fluxo.md`), registrada para não ser "otimizada" por engano depois.
- A escalada de effort/executor por falha de gate é da ETAPA
  (`agent_assignments[fase]`), não do card isolado — um card que nunca falhou na
  mesma fase também herda o degrau novo. Aceito: falha de gate é intrinsecamente
  de fase (todos os cards da fase compartilham a mesma bateria), e escalar
  card-a-card exigiria estado adicional sem ganho real.
- **Escolha de agente/modelo continua manual** (só o effort é automático) — §9 do
  `fluxo.md` pede os três; fica para um incremento futuro se houver sinal
  suficiente (hoje não há regra clara de "que agente para qual demanda").
- Épico → história → subtarefa (§7) — `KanbanCard` sem `parent_id`, nenhum caminho
  produz cards que não sejam `TASK` — **continua fora de escopo**, pendência
  nomeada explicitamente (ver `plano5.md` §2.4) para não sumir de novo.

## Escopo cortado

Nenhum corte foi necessário: bateria (§4.2/§4.3), sugestão por stack (§4.5),
seleção automática de esforço (§4.6) e os dois vestígios (§4.7) entraram todos,
conforme a ordem de corte declarada em `plano5.md` §10 (que previa cortar §4.5 e
§4.6 primeiro, se apertasse).

## Emenda (2026-07-31, ADR-0025)

Épico → história → subtarefa (§7) fechou na
[ADR-0025](ADR-0025-qa-hierarquia-aprendizado.md) — deixa de ser pendência
nomeada. A escolha de agente/modelo (§9, parágrafo acima) foi **declinada
formalmente**, não apenas adiada: sem dado sobre desempenho por executor, a
automação seria adivinhação. O relatório de aprendizado (§24) que a ADR-0025
também fecha produz exatamente esse dado (`desempenho_por_executor` por
falhas/tempo/rodadas de revisão) — reavaliar quando houver massa de várias
demandas reais.
