"""Teste de integração da CLI (TASK-14)."""

from __future__ import annotations

from typer.testing import CliRunner

from aso.cli.main import app

runner = CliRunner()


def test_run_command_executes_full_cycle() -> None:
    result = runner.invoke(app, ["run", "Implementar módulo PDF no backend"])
    assert result.exit_code == 0
    assert "Orquestração criada" in result.stdout
    # Gate da fase que recebeu o card (ADR-0060), não da fase corrente vazia.
    assert "Quality gate F5: PASSED" in result.stdout


def test_version_command() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "ASO Runtime" in result.stdout
