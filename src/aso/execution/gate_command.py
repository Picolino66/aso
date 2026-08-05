"""Execução do quality gate real (autopilot M5).

Roda um comando de validação (testes/lint) num diretório e devolve (ok, detalhe).
Usado pelo QualityGate nas fases de código para não aprovar com testes vermelhos.
O comando e o repo vêm do ambiente (ASO_GATE_TEST_COMMAND, ASO_TARGET_REPO).
"""

from __future__ import annotations

import subprocess

# 400 não cabia um stack trace nem a linha do teste que falhou (ADR-0019, §13 do
# fluxo.md pede comando, teste, mensagem e stack trace no registro de falha).
SAIDA_MAX = 4000


def run_gate_command(command: list[str], cwd: str, *, timeout: float = 300.0) -> tuple[bool, str]:
    """Executa `command` em `cwd`; ok = exit code 0. Nunca levanta — retorna o motivo.

    `stdout`/`stderr` são cortados CADA UM no seu próprio limite antes de juntar
    (§2.5/§4.8 do plano4.md): coladas primeiro e cortadas depois, uma saída longa de
    `stdout` empurrava o stack trace de `stderr` para fora da janela — exatamente o
    que o §13 do fluxo.md precisa preservar.
    """
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
    saida = proc.stdout.strip()[-SAIDA_MAX:]
    erro = proc.stderr.strip()[-SAIDA_MAX:]
    tail = "\n".join(p for p in (saida, erro) if p)
    return proc.returncode == 0, f"exit={proc.returncode} {tail}".strip()
