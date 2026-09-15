# ADR-0057 — Segurança por padrão: modelo de ameaça local e papéis para comandos no host

- **Status:** ACCEPTED
- **Fase:** F5/F6 (correção de governança — MEL-15, origem `feedback.md` §3 e §13.3 problema 8)
- **Data:** 2026-09-15
- **Relaciona-se com:** [ADR-0008](ADR-0008-workspace-por-orquestracao.md) (pasta de
  trabalho por orquestração), [ADR-0022](ADR-0022-bateria-de-validacoes-e-effort-automatico.md)
  (bateria de validações executada no host), [ADR-0023](ADR-0023-implantacao-governada.md)
  (implantação governada executa comandos de deploy/rollback)

## Contexto

O runtime executa comandos no host (`subprocess`) em três lugares: bateria de validação
(ADR-0022), comandos de implantação/rollback (ADR-0023) e agentes CLI. A revisão
encontrou que a configuração padrão tornava isso alcançável por qualquer cliente:

1. Sem `ASO_API_KEYS`, `AuthService` entrava em modo dev e **todo cliente virava admin**;
   o `docker-compose.yml` publicava a API em `0.0.0.0:8000` e o Postgres em `0.0.0.0:5432`
   com `aso/aso`; o `manager.sh` subia o uvicorn em `0.0.0.0`.
2. Mesmo com tokens, `PUT .../validation-checks`, `PUT .../deploy/config`,
   `PUT .../deploy/pipeline`, `POST .../deploy/run` e `validation_command` na criação /
   `execution-settings` eram de `operator` — ou seja, operator definia e disparava
   comandos arbitrários no host.
3. `GET /v1/fs/dirs`, `GET /v1/fs/analyze/stream` e `target_path` aceitavam qualquer
   caminho do host.
4. `?token=` era aceito em qualquer rota (vaza em log de acesso, histórico, Referer).
5. `/metrics` (público) recalculava `slo_report` hidratando todas as orquestrações a cada
   scrape.

### Modelo de ameaça adotado

O ASO é um runtime **local/single-tenant**: quem tem papel `admin` é tratado como dono
da máquina (pode rodar comandos). O que se protege é (a) a rede — nenhum serviço fica
exposto por padrão — e (b) a separação entre quem opera a esteira (`operator`) e quem
decide o que executa no host (`admin`). Sandbox por comando e multi-tenant ficam fora.

## Opções consideradas

- **Manter o modo dev implícito e só documentar.** Rejeitada: o padrão inseguro é o que
  roda na prática.
- **Remover o modo dev.** Rejeitada: o console local e o smoke dependem dele; exigiria
  gerenciar tokens em todo uso de desenvolvimento.
- **Modo dev explícito + bind local + admin para comandos + raízes de FS.** Adotada.

## Decisão

1. **Fail-closed no boot:** sem `ASO_API_KEYS`, `AuthService.from_env()` levanta
   `RuntimeError` (mensagem pt-BR) a menos que `ASO_DEV_MODE=1` (só o valor `1`).
   `scripts/manager.sh` liga `ASO_DEV_MODE=1` e escuta em `127.0.0.1` (`ASO_HOST`).
2. **Compose local-only:** portas `127.0.0.1:8000` e `127.0.0.1:5432`; senha do Postgres
   por `POSTGRES_PASSWORD` (default `aso` só para uso local). O compose declara
   `ASO_DEV_MODE: ${ASO_DEV_MODE:-1}` — o modo dev continua explícito (está escrito no
   arquivo) e só é alcançável pela interface local. Para expor a API, defina
   `ASO_API_KEYS` e `ASO_DEV_MODE=0`.
3. **Comandos no host exigem admin:** `required_role` devolve `admin` para escrita em
   `/validation-checks`, `/deploy/config`, `/deploy/pipeline` e `/deploy/run` (GET segue
   `viewer`). `validation_command` no corpo de `POST /v1/orchestrations` e
   `PATCH .../execution-settings` é checado no handler (403 para não-admin) — mesmo
   padrão de `report_review` (ADR-0017), porque `required_role` não lê o corpo.
   Consequência deliberada: operator não cria orquestração `code-execution` com comando
   próprio (a menos que `ASO_GATE_TEST_COMMAND` esteja definido pelo dono da máquina).
4. **Raízes de workspace:** `ASO_WORKSPACE_ROOTS` (separador do SO; default `$HOME`).
   `WorkspaceService.validate` e `list_dirs` recusam caminhos fora das raízes com
   `WorkspaceRootError` (400 na API), após `resolve()` — symlink e `..` não escapam.
   Cobre `/v1/fs/*`, criação de orquestração e de projeto (que já passam por `validate`).
   O botão "subir" do navegador de pastas não sai da raiz. O compose usa `/tmp`.
5. **`?token=` só em `…/events/stream`** (EventSource não envia header). Nas demais rotas
   o parâmetro é ignorado (401 sem header).
6. **`/metrics` sem hidratação:** o burn-rate/consumo de orçamento por orquestração vem da
   **última `SloEvaluation` persistida**, agregada em `repo.aggregate_metrics()`
   (`slo_latest`, via subquery `MAX(created_at)` no SQL). Orquestração sem amostra não
   aparece no gauge. `/metrics` segue público por ser agregado e barato (scrape
   Prometheus); o valor ao vivo continua em `GET .../slo` (autenticado).

## Consequências

- Subir a API "crua" sem variáveis falha com instrução clara; `manager.sh`, compose e a
  suíte de testes (`tests/conftest.py`) declaram o modo dev.
- Consoles com token `operator` recebem 403 nas telas de configuração de validação/deploy.
- Gauges `aso_slo_burn_rate`/`aso_error_budget_consumed_pct` passam a refletir a última
  avaliação registrada (`POST .../slo/evaluate`), não um recálculo a cada scrape.
- **Risco residual:** em modo dev local, qualquer processo/página com acesso a
  `127.0.0.1:8000` age como admin (inclui CSRF a partir do navegador). Uso com dados ou
  máquinas sensíveis deve usar `ASO_API_KEYS`.
