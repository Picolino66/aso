# ADR-0029 — Pipeline de implantação multi-estágio (Environment)

- **Status:** ACCEPTED
- **Fase:** F6 (implantação)
- **Data:** 2026-08-06
- **Relaciona-se com:** [ADR-0023](ADR-0023-implantacao-governada.md) (implantação governada —
  esta ADR fecha a lacuna que a própria ADR-0023 registrou como "Negativa" em suas
  Consequências), [ADR-0019](ADR-0019-roteamento-de-falha.md) (padrão de diagnóstico
  puro reaproveitado, não a tabela de retry de agente/executor), [`fluxo.md`](../../fluxo.md)
  §19/§20/§21, [`wiframe-fluxo.md`](../../wiframe-fluxo.md) §25

## Contexto

A ADR-0023 implantou `DeployRun`/`run_deploy`/`validate_deploy`/`decide_deploy`/
`rollback_deploy` deliberadamente monoambiente — `ambiente` é uma string livre, e
suas próprias "Consequências negativas" já registram a lacuna:

> *"`ambiente` é um campo de texto livre, não um pipeline de estágios (dev→teste→
> homologação→staging→produção do §19) — o operador chama `/deploy/run` quantas
> vezes quiser com `environment` diferente; não há progressão automática entre
> estágios."*

`docs/plano-fidelidade-fluxo.md` nomeia essa lacuna como FID-02, dependente da
FID-01 (regras de roteamento) só pela ordem do backlog, sem acoplamento técnico
real. O `fluxo.md` §19 exige cinco estágios sequenciais (desenvolvimento → testes
→ homologação → staging → produção) com estado, logs e gate por estágio, e uma
tabela de roteamento por tipo de falha (build/configuração/migration/pós-deploy/
crítica) que não existe em lugar nenhum do runtime hoje.

## Decisão

### 1. `Environment` é configuração, não estado — sem tabela nova

`control/models.py::Environment` (`chave`, `nome`, `ordem`, `comando?`,
`health_checks`, `rollback_command?`, `requer_aprovacao_humana`) é persistida em
`Orchestration.deploy_pipeline: list[dict[str, Any]] = []` — **por-orquestração**,
não global (pipelines diferentes por projeto são esperados), embutida como JSONB
exatamente como `deploy_health_checks` já é. **Lista vazia = implantação
monoambiente legada** (`deploy_command`/`deploy_environment` continuam valendo
sozinhos, comportamento idêntico a antes desta ADR) — só ativa quando o operador
grava `PUT .../deploy/pipeline` com ao menos um estágio.

`Environment` vive em `control/models.py` (não em `control/deploy.py`, onde vive
`DeployRun`) pelo mesmo motivo de `ValidationCheck`: `deploy.py` importa de
`models.py`, então o modelo compartilhado tem que estar no módulo que não cria
ciclo. `Orchestration.deploy_pipeline` fica `list[dict[str, Any]]` (não
`list[Environment]`), espelhando `deploy_runs` — a mesma razão por trás de
`DeployRun` nunca ser tipado dentro de `Orchestration`.

O status de cada estágio **nunca é guardado em `Environment`** — é sempre
derivado do ring `deploy_runs` (`control/deploy.py::status_do_pipeline`), a
mesma fonte única de verdade que já existia. `DeployRun` ganha só um campo:
`estagio: str = ""` (`""` = tentativa monoambiente legada).

### 2. O ring de 5 vira "5 estágios", não "5 tentativas do mesmo estágio"

`LIMITE_RING = 5` (`control/documentos.py`) não muda. Com um pipeline de 5
estágios rodando em ordem sem retry, o ring guarda exatamente uma entrada por
estágio — cabe perfeitamente. Se um estágio falha e é re-executado, a entrada
mais antiga (tipicamente `desenvolvimento`) é descartada do ring — mesmo
trade-off já aceito por `discovery_reports`/`spec_documents` (histórico além de
5 versões se perde). `status_do_pipeline` busca a **última** entrada do ring por
`chave` de estágio (`_ultima_execucao`); um estágio sem entrada no ring aparece
como `pendente` mesmo que já tenha rodado uma vez e sido evictado — limitação
aceita, documentada, não um bug.

### 3. Avanço governado — `pode_avancar_estagio`/`proximo_estagio_pendente`

Funções puras em `control/deploy.py` (mesmo princípio de `failure.py`/
`selecao.py`/`routing_rules.py`: determinístico, sem I/O): um estágio só roda
depois que o **imediatamente anterior** (por `ordem`) está concluído —
`status == sucesso` e, se `requer_aprovacao_humana`, `aceite_status == aprovado`.
`run_deploy` recusa (`ValueError`→409) tentar rodar um estágio fora de ordem.
Sem `estagio` explícito no corpo do `POST .../deploy/run`, resolve
automaticamente para o primeiro pendente — o operador não precisa saber a ordem
de cor.

### 4. Classificação de falha (§19) — reaproveita o PADRÃO da ADR-0019, não a tabela

`control/failure.py::decidir` decide retry de **agente/executor/effort** — não
se aplica a uma falha de implantação (não há agente rodando o comando de
deploy). Em vez de forçar esse encaixe, `control/deploy.py::classificar_falha_deploy`
segue o mesmo **princípio** (puro, determinístico, nunca lança, sempre produz
uma próxima ação nomeada — Princípio central do `fluxo.md`) com um vocabulário
próprio de deploy: `build`, `configuracao`, `migration`, `pos_deploy`, `critica`.

A distinção `pos_deploy` vs. `critica` é por **fato**, não heurística: quando a
falha vem de `validar_pos_deploy` (health check reprovado depois que o comando
de deploy já sucedeu) e o estágio é `producao`, é sempre `critica` — o §19 isola
produção como o único caso que aciona rollback; a mesma falha em qualquer outro
estágio é só "volta para correção" (`pos_deploy`). Falha do próprio comando de
deploy (`origem="deploy"`, antes de qualquer validação rodar) é classificada por
palavra-chave entre `build`/`configuracao`/`migration` — mesma limitação aceita
de `failure.py::diagnosticar` sem categoria estruturada (não existe bateria
nomeada equivalente para comandos de deploy).

`DeployRun.diagnostico_falha`/`.proxima_acao_falha` (novos campos, vazios por
padrão) são preenchidos em `run_deploy` (falha do comando) e `validate_deploy`
(falha de validação) — **também no caminho monoambiente legado** (`estagio=""`):
a classificação roda sempre que há falha, pipeline configurado ou não, porque
"nenhuma falha encerra silenciosamente" (Princípio central) não é um benefício
exclusivo de quem configurou pipeline. Isto não quebra nenhum teste existente —
os campos são aditivos, vazios sempre que não há falha.

### 5. `next_step` — próxima ação nomeada, nunca "veja os logs" como único recurso

`_deploy_blocker` (`control/next_step.py`) passa a: (a) nomear o estágio no
título quando `deploy.estagio` está preenchido; (b) preferir
`proxima_acao_falha` ao texto genérico de `resultado`/`aceite_comentario`
sempre que presente. Uma falha `critica` em produção aparece como
`deploy_aguardando_aceite` (`SEVERITY_HUMAN`, papel `admin`) com o texto
"Falha crítica em produção — executar rollback..." já no `detail` — **sem
executar rollback automaticamente**: ações críticas exigem aprovação humana
(`CLAUDE.md` regra 4), e rollback já é uma dessas ações desde a ADR-0023
(`POST .../deploy/rollback`, papel `admin`). A esteira recomenda com a maior
ênfase possível; quem decide continua sendo o operador.

### 6. Gate F6 (`deploy_aprovado`) — pipeline completo, não só a última tentativa

Sem pipeline configurado, o critério é **idêntico** ao de antes (`deploy_runs[-1]
.aceite_status == aprovado`). Com pipeline configurado, `pipeline_aprovado`
exige que **todos** os estágios estejam concluídos — a última entrada do ring
pode ser um estágio intermediário (`testes`), então usar só ela aprovaria o gate
antes de `producao` sequer rodar. Este é o único ponto onde o comportamento de
uma orquestração com pipeline diverge estruturalmente do monoambiente — e é
proposital: o gate de F6 tem que significar "pronto para produção", não "o
último comando rodou".

### 7. API

```
GET  /v1/orchestrations/{id}/deploy/pipeline   # viewer — status derivado por estágio
PUT  /v1/orchestrations/{id}/deploy/pipeline   # operator — configura o pipeline inteiro
POST /v1/orchestrations/{id}/deploy/run        # ganha `estagio` opcional no corpo
```

`PUT .../deploy/pipeline` substitui a lista inteira (mesmo padrão de
`PUT .../validation-checks`) — cada `comando`/`rollback_command`/health check
passa por `validate_gate_command`, mesmo guard de `set_deploy_config`. `chave`/
`ordem` repetidos são recusados (`ValueError`→409) antes de persistir.

## Consequências

**Positivas**
- Fecha a lacuna que a própria ADR-0023 registrou como pendência.
- `deploy_aprovado` do gate F6 passa a significar "pronto para produção" de
  verdade quando há pipeline, não "a última tentativa (seja qual for) foi aceita".
- Toda falha de implantação — monoambiente ou pipeline — ganha diagnóstico e
  próxima ação nomeada, fechando mais uma instância do Princípio central.
- Zero migração de dado: `deploy_pipeline` nasce `[]` em toda orquestração
  existente; `DeployRun.estagio` nasce `""` — nenhum registro histórico muda de
  interpretação.

**Negativas / riscos aceitos**
- Ring de 5 compartilhado entre estágios: um pipeline com retries frequentes em
  estágios iniciais pode perder a entrada de `desenvolvimento` do ring antes de
  chegar a `producao` — mesmo trade-off já aceito em `discovery_reports`/
  `spec_documents`, não resolvido aqui (aumentar o limite é decisão separada,
  fora de escopo).
- `classificar_falha_deploy` para `origem="deploy"` é heurística por
  palavra-chave (build/configuração/migration) — sem uma bateria nomeada
  equivalente à do §12/ADR-0022 para comandos de deploy, uma mensagem atípica
  cai em `desconhecido` (fallback seguro, nunca lança, nunca finge saber).
- Nenhum auto-rollback: uma falha `critica` em produção só recomenda — o
  operador ainda precisa chamar `POST .../deploy/rollback` manualmente. Decisão
  deliberada (regra de governança), não lacuna técnica.
- `Environment` é configuração por-orquestração, não um catálogo global
  reutilizável entre projetos — cada orquestração configura seu próprio
  pipeline do zero. Se um catálogo de pipelines-padrão por tipo de projeto for
  necessário, é extensão futura sem quebra de contrato.
