"""Execução do quality gate real (autopilot M5).

Roda um comando de validação (testes/lint) num diretório e devolve (ok, detalhe).
Usado pelo QualityGate nas fases de código para não aprovar com testes vermelhos.
O comando e o repo vêm do ambiente (ASO_GATE_TEST_COMMAND, ASO_TARGET_REPO).
"""

from __future__ import annotations

import subprocess


def run_gate_command(command: list[str], cwd: str, *, timeout: float = 300.0) -> tuple[bool, str]:
    """Executa `command` em `cwd`; ok = exit code 0. Nunca levanta — retorna o motivo."""
    try:
        proc = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"gate falhou ao executar {command}: {exc}"
    tail = (proc.stdout + proc.stderr).strip()[-400:]
    return proc.returncode == 0, f"exit={proc.returncode} {tail}".strip()
