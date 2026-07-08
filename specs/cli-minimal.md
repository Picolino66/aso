# SPEC — CLI mínima (Typer)

- **Card:** TASK-14
- **Épico:** EPIC-7 (Interfaces API/CLI)
- **Fase:** F5
- **ADRs:** —
- **Requisitos:** §31, §40 Task 14
- **Depende de:** TASK-13

## Objetivo

Entregar a CLI `aso` (Typer), driving adapter que expõe as operações do runtime na linha de comando (§31). É a interface primária de uso do MVP-1 (a UI web é diferida — F2 §54), permitindo criar orquestrações, inspecionar o board, retomar, fazer rollback e aprovar ações.

A CLI consome a API mínima ([api-minimal.md](api-minimal.md)) e/ou os serviços de aplicação, apresentando os resultados de forma legível no terminal.

## Escopo

- Incluído (comandos §31):
  - `aso init` — inicializa configuração local do projeto/orquestração.
  - `aso run "<demanda>"` — cria orquestração a partir de uma solicitação (gera plano, contexto e board).
  - `aso status <orchestrationId>` — mostra status/fase/progresso.
  - `aso board <orchestrationId>` — exibe cards por coluna.
  - `aso resume <orchestrationId>` — retoma execução.
  - `aso rollback <orchestrationId> --to O3` — restaura snapshot.
  - `aso approve <approvalId>` — aprova ação pendente (e reject correspondente).
  - `aso agents list` — lista agentes registrados.
  - `aso snapshots list <orchestrationId>` / `aso snapshots diff O3 O4` — snapshots.
  - `aso adrs list <orchestrationId>` — lista ADRs.
- Fora de escopo (MVP-1):
  - Modo interativo/TUI e streaming de logs ao vivo.
  - Comandos de configuração de providers/CLI agents (§26A — MVP posterior).
  - Execução real de código via CLI agents (mock apenas).

## Comportamento esperado

- `aso run "<demanda>"` cria uma orquestração, dispara a geração de `ExecutionPlan` e `OrchestratorContext`, cria o board com cards e imprime o `orchestration_id` (§35 critérios 1–5).
- `aso board <id>` mostra as colunas e os cards em cada uma (reflete o estado real — §39.14).
- `aso approve <approvalId>` aprova a `HumanApproval` pendente e libera a ação bloqueada (§8.6).
- `aso rollback <id> --to O3` restaura o snapshot O3 (delegado ao SnapshotEngine; exige snapshot existente/aprovado).
- `aso agents list` lista os 16 agentes do AgentRegistry.
- `aso snapshots diff O3 O4` mostra o diff (pode ser textual simples no MVP-1).
- Erros são exibidos de forma amigável (mensagem clara + exit code ≠ 0); saída padrão legível (tabelas/linhas).
- Cada comando propaga correlation IDs para logs (ver [observability-basic.md](observability-basic.md)).

## Contratos / Interfaces

Módulo: `src/aso/cli/`. App Typer em `src/aso/cli/main.py` (entrypoint `aso`).

```python
# src/aso/cli/main.py
app = typer.Typer(help="ASO Runtime CLI")

@app.command()
def run(demanda: str) -> None: ...
@app.command()
def status(orchestration_id: str) -> None: ...
@app.command()
def board(orchestration_id: str) -> None: ...
@app.command()
def resume(orchestration_id: str) -> None: ...
@app.command()
def rollback(orchestration_id: str, to: str = typer.Option(..., "--to")) -> None: ...
@app.command()
def approve(approval_id: str) -> None: ...

# subcomandos: aso agents list ; aso snapshots list|diff ; aso adrs list
agents_app = typer.Typer(); snapshots_app = typer.Typer(); adrs_app = typer.Typer()
app.add_typer(agents_app, name="agents")
app.add_typer(snapshots_app, name="snapshots")
app.add_typer(adrs_app, name="adrs")
```

- Cliente interno reutiliza os serviços de aplicação (ou um `httpx` client contra a API `/v1`).

## Critérios de aceite

- [ ] `aso run "<demanda>"` cria uma orquestração (com plano, contexto e board).
- [ ] `aso board <id>` mostra os cards por coluna.
- [ ] `aso approve <approvalId>` aprova a ação pendente.
- [ ] `aso agents list`, `aso snapshots list/diff`, `aso adrs list`, `aso rollback --to`, `aso status`, `aso resume` funcionam.

## Rastreabilidade

§31/§40 Task 14 → (sem ADR) → esta spec → TASK-14 → `src/aso/cli/main.py`, `src/aso/cli/commands/*` → `tests/integration/test_cli.py`
