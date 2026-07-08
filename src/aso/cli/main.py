"""CLI do ASO Runtime (Typer, TASK-14).

Comandos mínimos (§31). Como o MVP-1 é in-memory (sem persistência), `aso run`
é autocontido: cria a orquestração, executa os agentes (mock), roda o quality gate
e imprime o resultado — demonstrando o ciclo completo de governança.
"""

from __future__ import annotations

import typer

from aso import __version__
from aso.bootstrap import build_service
from aso.observability.metrics import MetricsService

app = typer.Typer(help="ASO Runtime — Autonomous Software Orchestrator Runtime")
_service = build_service()
_metrics = MetricsService(_service)


@app.command()
def version() -> None:
    """Mostra a versão do runtime."""
    typer.echo(f"ASO Runtime {__version__}")


@app.command()
def run(request: str) -> None:
    """Cria uma orquestração a partir de uma demanda e executa o ciclo (mock)."""
    orch = _service.create_orchestration(request)
    typer.echo(f"Orquestração criada: {orch.id}")

    plan = _service.get_plan(orch.id)
    typer.echo(f"Estratégia: {plan.strategy.value} — {plan.reason}")
    typer.echo(f"Aprovação humana necessária: {plan.requires_human_approval}")

    typer.echo("\nCards:")
    for card in _service.get_cards(orch.id):
        _service.run_card(orch.id, card.id)
        card_now = next(c for c in _service.get_cards(orch.id) if c.id == card.id)
        typer.echo(f"  [{card_now.status.value:>10}] {card.title}")

    gate = _service.run_quality_gate(orch.id)
    typer.echo(f"\nQuality gate: {gate.status.value}")

    ctx = _service.get_context(orch.id)
    chash = str(ctx["context_hash"])
    typer.echo(f"Contexto: versão {ctx['version']} | {chash[:24]}...")
    n_adrs = len(_service.list_adrs(orch.id))
    n_snaps = len(_service.list_snapshots(orch.id))
    typer.echo(f"ADRs: {n_adrs} | Snapshots: {n_snaps}")


@app.command()
def timeline(orchestration_id: str, page: int = 1, page_size: int = 50) -> None:
    """Exibe a timeline de eventos (paginada)."""
    events = _service.timeline(orchestration_id)
    start = max(page - 1, 0) * page_size
    for event in events[start : start + page_size]:
        typer.echo(f"{event.created_at}  {event.type}")
    typer.echo(f"({len(events)} eventos no total — página {page})")


@app.command()
def cards(
    orchestration_id: str,
    status: str | None = typer.Option(None, help="Filtrar por status/coluna"),
    card_type: str | None = typer.Option(None, "--type", help="Filtrar por tipo de card"),
) -> None:
    """Lista cards de uma orquestração, com filtros opcionais."""
    for card in _service.filter_cards(orchestration_id, status=status, card_type=card_type):
        typer.echo(f"[{card.status.value:>10}] {card.type.value:<12} {card.title}")


@app.command()
def adrs(
    orchestration_id: str,
    status: str | None = typer.Option(None, help="Filtrar por status"),
    q: str | None = typer.Option(None, help="Buscar no título/decisão"),
) -> None:
    """Lista/busca ADRs de uma orquestração."""
    for adr in _service.search_adrs(orchestration_id, status=status, query=q):
        typer.echo(f"{adr.id} [{adr.status.value}] {adr.title}")


@app.command()
def metrics(orchestration_id: str) -> None:
    """Mostra métricas e SLOs de uma orquestração (F7)."""
    m = _metrics.orchestration_metrics(orchestration_id)
    typer.echo(f"fase={m['phase']} snapshot={m['snapshot_version']}")
    typer.echo(f"cards={m['cards_total']} adrs={m['adrs_total']} snapshots={m['snapshots_total']}")
    typer.echo(f"conflitos_abertos={m['open_conflicts']} eventos={m['events_total']}")
    report = _metrics.slo_report(orchestration_id)
    status = "OK" if not report["breaches"] else f"BREACH: {report['breaches']}"
    typer.echo(f"SLOs: {status}")


@app.command()
def feedback(orchestration_id: str, text: str) -> None:
    """Registra feedback como card de backlog (F7)."""
    card = _service.add_feedback(orchestration_id, text)
    typer.echo(f"Card criado: {card.id} [{card.type.value}] {card.title}")


@app.command()
def approvals(orchestration_id: str) -> None:
    """Lista aprovações humanas de uma orquestração (§24)."""
    for a in _service.list_approvals(orchestration_id):
        typer.echo(f"{a.id} [{a.status}] risco={a.risk} — {a.action}")


@app.command()
def approve(approval_id: str) -> None:
    """Aprova uma solicitação de aprovação humana."""
    a = _service.decide_approval(approval_id, approved=True)
    typer.echo(f"Aprovado: {a.id} [{a.status}]")


@app.command()
def rollback(
    orchestration_id: str, to: str = typer.Option(..., "--to", help="Snapshot alvo")
) -> None:
    """Restaura o contexto para um snapshot (gera ADR de rollback)."""
    orch = _service.rollback(orchestration_id, to)
    typer.echo(f"Rollback concluído: snapshot={orch.snapshot_version} status={orch.status}")


@app.command()
def stats(orchestration_id: str) -> None:
    """Mostra a contagem de cards por status (consulta indexada)."""
    counts = _service.count_cards_by_status(orchestration_id)
    if not counts:
        typer.echo("Sem cards.")
        return
    for status, count in sorted(counts.items()):
        typer.echo(f"  {status:>12}: {count}")


if __name__ == "__main__":
    app()
