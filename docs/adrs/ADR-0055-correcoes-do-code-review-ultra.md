# ADR-0055 — Correções do code-review ultra (6 bugs reais pós-FID-27)

- **Status:** ACCEPTED
- **Fase:** F5/F6 (correção pós-fidelidade, sem card de backlog dedicado — a
  missão FID-01–FID-27 já estava 100% `Done`; este incremento fecha achados de
  uma revisão multiagente sobre o diff acumulado, não um requisito de wireframe)
- **Data:** 2026-08-10
- **Relaciona-se com:** [ADR-0019](ADR-0019-roteamento-de-falha.md) (roteamento
  de falha, `decidir`), [ADR-0031](ADR-0031-limite-de-tentativas.md)
  (`tentativa_atual`, contador autoritativo), [ADR-0039](ADR-0039-cadastro-de-demanda-completo.md)
  (Tela 03, `demand_brief`), [ADR-0017](ADR-0017-revisao-independente-de-codigo.md)
  (ciclo de correção, `correction_actions`), [ADR-0050](ADR-0050-implantacao-validacao-rollback-aceite-encerramento.md)
  (saúde pós-deploy), [ADR-0044](ADR-0044-classificacao-editavel-e-recomendacao.md) (painel de
  recomendação, custo/tempo estimado), [ADR-0052](ADR-0052-metricas-e-aprendizado.md)
  (`get_learning_report_global`), [ADR-0053](ADR-0053-catalogo-de-agentes.md)
  (catálogo de agentes, fonte de verdade das permissões)

## Contexto

Com o backlog de fidelidade (FID-01–FID-27) 100% `Done`, o operador pediu uma
revisão `/code-review ultra` sobre o diff acumulado e ainda não commitado
(FID-22–FID-27: `orchestration_service.py` +2592 linhas, `deploy.py`,
`discovery.py`, `review.py`, `next_step.py`, `db/repository.py`,
`persistence/*`, `kanban/*`, `agents/*`, `governance/models.py`, `api/app.py`,
`api/auth.py`). A revisão devolveu 6 achados; todos foram verificados
independentemente (não aceitos "de graça") lendo o código real e, quando a
causa não era óbvia, delegando a um agente Explore para confirmar com
citações exatas — 2 achados tinham nuance real em relação à descrição
original da revisão (ver itens 1 e 5 abaixo). Decisão do usuário (opção
recomendada): corrigir os 6, não só os mais críticos.

## Decisão

### 1. Escalação prematura de falha (`orchestration_service.py`, `failure.py`)

`card.tentativa_atual` conta sucesso **e** falha (ADR-0031: "incrementado a
cada execução real, sucesso ou falha"), mas era passado direto para
`decidir()` como o contador de escalação — cujo próprio docstring já dizia
"`len(card.failures)` depois de registrar a falha atual", isto é, um contador
**só de falha**. Card com 2 sucessos + 1 falha real chamava `decidir(_, 3,
max=3)`: `tentativa > limite` (`3>3`) é falso, mas o índice da tabela de
política (`min(tentativa-1, len(passos)-1)`) caía no ÚLTIMO passo —
`escalar_humano` — na primeira falha real, pulando `mesmo_agente`/
`aumentar_effort`. `fail_qa_check` tinha o mesmo padrão.

Corrigido com um contador NOVO e dedicado, `card.tentativa_falha_atual`
(`kanban/models.py`) — incrementa só em falha (execução ou QA), zera a cada
sucesso (a intenção que o comentário em `_apply_execution` já registrava, mas
não implementava), nunca truncado (como `tentativa_atual`, ao contrário de
`len(failures)`, ring travado em 5 — não reintroduz o bug que motivou a
ADR-0031). `_recusar_se_limite_do_agente_estourado` (ADR-0053) foi verificado
e **não** alterado: seu propósito documentado é um teto de tentativas TOTAIS
por agente (sucesso conta), não um streak de falha — `tentativa_atual`
continua correto ali.

Requer migration (`kanban_cards.tentativa_falha_atual`, `server_default='0'`
para não quebrar linhas existentes) — validada no Postgres real (`docker
compose up`, `/health`, `./scripts/smoke.sh`), não só SQLite.

### 2. Classificação da Tela 03 nunca chegava ao planejador (`api/app.py`)

O caminho `POST /v1/orchestrations` com `demand_brief` completo (Tela 03,
ADR-0039) passava `demand_brief=` para `create_orchestration` mas **não**
`decision_input=` — o planejador e `_apply_routing_rule` viam sempre o
`DecisionInput` default (`domains=["backend"]`), ignorando
tipo/complexidade/impactos/domínios preenchidos à mão no formulário.
`create_with_triage` já fazia a tradução certa
(`brief.to_decision_input(user_request)`); o caminho de `demand_brief`
explícito só precisava da mesma chamada.

### 3. Correção de review descartada quando só havia comentário antigo resolvido (`orchestration_service.py`)

`_apply_review_verdict`, no ramo reprovado, só caía no fallback
`verdito.acoes` quando `comentarios_da_pr` (TODOS os comentários já
anexados à PR, de qualquer rodada) estava vazio. Uma PR com comentários de
uma rodada ANTERIOR já resolvidos deixa essa lista não-vazia, mas o filtro
`obrigatorio and status == "pendente"` dá `[]` — o veredito ATUAL (com ações
obrigatórias reais) era descartado, e o card ia para `NeedsFix` sem nenhuma
orientação. Corrigido: o fallback agora olha o resultado FILTRADO
(`pendentes_obrigatorios`), não a existência histórica de comentários.

### 4. Comando de deploy que falha era relatado como saudável (`deploy.py`)

`saude_pos_deploy` checava só `validacao_status`; quando o comando de deploy
em si falha (`status == STATUS_FALHOU`), a validação pós-deploy nunca chega a
rodar (`validacao_status` fica `pendente`) — o código lia isso como "nada
reprovado ainda" e devolvia `SAUDE_SAUDAVEL` com `decisao_sugerida =
concluir_implantacao`. Corrigido: `status == STATUS_FALHOU` checa primeiro e
sempre devolve `SAUDE_FALHA_CRITICA`, fato gravado por `run_deploy`, nunca
heurística.

### 5. `_faixa` colapsava empates no rank mais baixo + custo/tempo hidratava o sistema inteiro (`orchestration_service.py`)

Dois problemas no mesmo helper (`_estimar_custo_e_tempo`, painel de
recomendação, Tela 13, ADR-0044):

- `sorted(todos).index(valor)` devolve sempre a 1ª ocorrência — um grupo de
  valores empatados no topo do custo/tempo colapsava no rank do MENOR índice
  do grupo, sub-representando sistematicamente qualquer cluster de empate
  (verificado, não é "sempre baixo" em todo caso, mas sempre enviesado para
  baixo). Extraído para uma função de módulo `_faixa` (antes um closure
  interno, impossível de testar isolado) e corrigido para usar o RANK MÉDIO
  do grupo empatado (fractional ranking) — convenção estatística padrão, sem
  inventar heurística nova.
- `_estimar_custo_e_tempo` chamava `get_learning_report_global()` **sem**
  filtro — o próprio docstring desse método existe para evitar exatamente
  isto (ADR-0052: "recorte por projeto... em vez de hidratar todo o sistema
  e filtrar em memória"), mas o painel de recomendação (endpoint só-leitura,
  chamado a cada edição de classificação) nunca usava o filtro disponível.
  Corrigido passando `project_id=b.orchestration.project_id` — reaproveita o
  filtro SQL já indexado e, de quebra, compara contra o histórico do MESMO
  projeto, mais relevante do que o sistema inteiro. **Risco aceito**:
  orquestrações sem `project_id` continuam hidratando tudo — não há recorte
  mais fino disponível sem inventar um novo, fora do escopo desta correção.

### 6. PUT de definição de agente podia revogar permissão real por omissão (`api/app.py`, `agent_catalog_service.py`)

`AgentDefinitionBody.ferramentas`/`.permissoes` tinham default `[]` — um
PUT que só queria mudar `nome`/`ativo` e omitia esses dois campos os
enviava como lista vazia de qualquer forma (Pydantic preenche o default), e
`AgentCatalogService.update` fazia `list(x or [])` incondicional,
substituindo (não mesclando). Como este catálogo é a fonte de verdade real
das permissões (`AgentRegistry.seed_from_catalog`, ADR-0053), isso revogava
silenciosamente `allowed_tools`/`context_sections` de um papel ativo.
Verificado: a única UI existente (`agentes.html`) sempre envia o objeto
completo (fetch → edita → PUT), então não era explorável pela tela hoje —
mas violava deny-by-default (regra 2 do CLAUDE.md) como contrato de API.

Corrigido com semântica PATCH-like só para os campos de lista: default
`None` no `AgentDefinitionBody` (campo omitido ou `null` explícito);
`create_agent_definition` continua tratando `None` como lista vazia (correto
para uma definição nova); `AgentCatalogService.update` agora trata `None`
como "não mude este campo" — só uma lista explícita (inclusive `[]`
explícito) substitui de verdade. Campos escalares
(`limite_custo_usd`/`limite_tentativas`) não foram alterados: `None` já
tinha lá um significado de domínio válido ("sem limite"), diferente dos
campos de lista onde `None` nunca foi um valor de domínio, só um artefato do
Pydantic.

## Consequências

**Positivas**
- Os 6 achados têm teste de regressão dedicado, verificado FALHANDO antes da
  correção (não só passando depois) — `test_tentativas_historico.py`,
  `test_cadastro_completo_api.py`, `test_ciclo_de_correcao.py`,
  `test_deploy_aprovacao_saude_rollback.py`,
  `test_classificacao_e_recomendacao.py`, `test_agent_catalog.py`/
  `test_agent_catalog_api.py`.
- Nenhuma correção introduziu campo/conceito novo além do estritamente
  necessário (`tentativa_falha_atual` é o único campo novo, e existe porque
  os dois contadores existentes — `tentativa_atual` e `len(failures)` — têm,
  cada um, uma razão documentada (ADR-0031) para não servir).
- Bateria completa (ruff, mypy --strict, alembic upgrade+check, pytest
  --cov) verde; migration validada no Postgres real via
  `docker compose up`/`smoke.sh`, não só SQLite (regra do CLAUDE.md para
  mudanças de schema).

**Negativas / riscos aceitos**
- `_estimar_custo_e_tempo` ainda hidrata o sistema inteiro para orquestrações
  sem `project_id` (item 5) — aceito por ser um recorte incremental sobre o
  filtro já existente, não uma solução completa de cache/paginação.
- A tabela de política de falha (`_TABELA` em `failure.py`) não foi alterada
  — a correção do item 1 é sobre QUAL contador chega até ela, não sobre o
  conteúdo da tabela em si.

**Sem mudança de comportamento observável para o operador em uso normal**:
os 6 bugs só se manifestavam em condições específicas (card com sucesso
anterior + falha real; Tela 03 com brief manual; PR com comentário antigo
resolvido; comando de deploy quebrado; empate de custo/tempo entre
executores; PUT de definição de agente por API direta sem UI) — nenhum
requer migração de dados além da coluna nova do item 1.
