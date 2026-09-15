# MEL-15 — Segurança por padrão

| Campo | Valor |
|---|---|
| Fase do roadmap | 2 — Correção |
| Prioridade | **P0** |
| Esforço | médio |
| Status | Backlog |
| Depende de | — |
| Origem | [feedback.md](../feedback.md) §3 (segurança), §13.3 problema 8 |
| Regras invioláveis | 4 (ações críticas = admin) e 9 (secrets por env) |
| Requer ADR | Sim: modelo de ameaça local e papéis para execução de comandos (referencia ADR-0008, ADR-0022, ADR-0023) |

## Problema

1. **Admin anônimo por padrão:** sem `ASO_API_KEYS`, `AuthService` entra em modo dev e
   todo cliente vira `admin` ([auth.py:42](../src/aso/api/auth.py#L42)). O
   `docker-compose.yml` passa `ASO_API_KEYS` vazio e publica `0.0.0.0:8000`; o Postgres
   fica exposto em `5432` com `aso/aso`.
2. **Operator executa comandos no host:** `PUT …/validation-checks`, `PUT …/deploy/config`,
   `PUT …/deploy/pipeline` e `POST …/deploy/run` caem no papel `operator`, e esses
   comandos rodam via `subprocess` no host (`run_gate_command`, `executar_deploy`).
3. **Navegação do FS do host:** `GET /v1/fs/dirs` e `GET /v1/fs/analyze/stream` aceitam
   qualquer caminho (`WorkspaceService.validate`, [workspace.py:63](../src/aso/execution/workspace.py#L63)).
   `POST /v1/orchestrations` aceita `target_path` arbitrário.
4. **Token em query string:** `?token=` é aceito em qualquer rota, não só no SSE.
5. **`/metrics` público e caro:** chama `slo_report` para todas as orquestrações,
   hidratando cada uma ([metrics.py:162](../src/aso/observability/metrics.py#L162)).

## Mudança proposta

1. Modo dev **explícito**: sem `ASO_API_KEYS`, a API só sobe se `ASO_DEV_MODE=1`;
   caso contrário, falha no boot com mensagem clara. `manager.sh` define `ASO_DEV_MODE=1`.
2. `docker-compose.yml`: `127.0.0.1:8000:8000` e `127.0.0.1:5432:5432`; senha do Postgres por variável.
3. `required_role`: rotas que configuram ou disparam comandos no host passam a exigir
   `admin` (`/validation-checks` PUT, `/deploy/config`, `/deploy/pipeline`, `/deploy/run`,
   `/execution-settings` quando altera comando).
4. `ASO_WORKSPACE_ROOTS` (lista de raízes permitidas): `validate`, `/v1/fs/*` e criação de
   orquestração/projeto recusam caminhos fora das raízes. Sem a variável, raiz = `$HOME`.
5. `?token=` aceito apenas em rotas `…/events/stream`.
6. `/metrics`: remover o bloco por orquestração que chama `slo_report`, ou restringir
   a métricas agregadas no repositório (sem hidratar). Avaliar exigir token para `/metrics`.

## Fora de escopo

- Sandbox de execução de comandos (container por comando).
- Multi-tenant e permissões por organização.

## Critérios de aceite

- [ ] Subir a API sem `ASO_API_KEYS` e sem `ASO_DEV_MODE=1` falha com mensagem em pt-BR.
- [ ] Token `operator` recebe 403 ao configurar comandos de validação/deploy e ao executar deploy.
- [ ] `GET /v1/fs/dirs?path=/etc` responde 400 com raiz padrão.
- [ ] `?token=` é ignorado fora do SSE.
- [ ] `/metrics` não chama `_bundle` para nenhuma orquestração (verificável por teste com repositório espião).
- [ ] `docker compose up` expõe portas só em `127.0.0.1`; smoke continua passando.

## Testes obrigatórios

- Unit: `AuthService.from_env` com e sem `ASO_DEV_MODE`.
- Integração API: matriz papel × rota para as rotas de comando.
- Unit: `WorkspaceService.validate` com raízes.
- Unit: `MetricsService.prometheus` sem hidratação.
- Docker: smoke com as novas portas.

## Arquivos prováveis

- `src/aso/api/auth.py`, `src/aso/api/app.py`
- `src/aso/execution/workspace.py`
- `src/aso/observability/metrics.py`
- `docker-compose.yml`, `scripts/manager.sh`, `scripts/smoke.sh`
- `docs/operations.md`, `README.md`, ADR nova

## Riscos

- Quebra o uso local sem variáveis: mitigar com `manager.sh` e mensagem de erro explicando `ASO_DEV_MODE=1`.
- O console precisa tratar 403 nas telas de configuração para operator.
