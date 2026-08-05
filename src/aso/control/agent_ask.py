"""`perguntar_ao_agente` — dispatch comum aos serviços de agente (§2.6/§4.1 do plano4.md).

Extraído porque naming/triage/review/discovery repetiam, cada um, o mesmo bloco:
bifurcar `kind == "llm"` / `kind == "cli"`, rodar o CLI numa pasta temporária
descartável e envolver tudo na mesma tupla de exceções (`ERROS_DE_AGENTE`). Nenhum
destes serviços altera código (só produzem texto/JSON), então nada de
`git worktree add` — o CLI roda num diretório vazio e descartável, e só o stdout
interessa.

**Refatoração de forma, não de comportamento**: o prompt de sistema, o `_sanear` e o
fallback continuam em cada serviço — aqui só o transporte até o executor.
"""

from __future__ import annotations

import json
import subprocess
import tempfile

from aso.control.models import AgentAssignment
from aso.execution.catalog import ExecutorCatalog
from aso.execution.llm_client import LlmError
from aso.execution.llm_provider import parse_llm_json

# Qualquer indisponibilidade do agente (timeout, JSON inválido, executor removido do
# catálogo, sandbox sem permissão) cai nesta tupla — cada serviço decide o próprio
# fallback ao capturá-la em volta de `perguntar_ao_agente`.
ERROS_DE_AGENTE = (LlmError, ValueError, KeyError, OSError, subprocess.SubprocessError)


def perguntar_ao_agente(
    catalog: ExecutorCatalog,
    assignment: AgentAssignment,
    *,
    system: str,
    pedido: str,
    kind: str,
    timeout: float,
) -> dict[str, object]:
    """Pergunta em JSON a um executor do catálogo — LLM ou CLI em pasta temporária.

    `kind` rotula a tarefa no wrapper JSON enviado ao CLI (ex.: "naming", "triagem",
    "revisao", "discovery", "especificacao") — cada serviço usa o próprio rótulo.
    """
    profile = catalog.get(assignment.executor)
    if profile is None:
        raise KeyError(f"Executor '{assignment.executor}' não está no catálogo.")
    if profile.kind == "llm":
        client = catalog.llm_client(assignment.executor, effort_override=assignment.effort)
        return parse_llm_json(client.complete(system=system, user=pedido))
    if profile.kind == "cli":
        command = catalog.cli_command(assignment.executor, effort_override=assignment.effort)
        saida = _rodar_cli(command, pedido, system=system, kind=kind, timeout=timeout)
        return parse_llm_json(saida)
    raise ValueError(f"Executor '{assignment.executor}' não sabe produzir texto.")


def _rodar_cli(command: list[str], pedido: str, *, system: str, kind: str, timeout: float) -> str:
    """Roda o agente CLI só para obter texto — em pasta temporária, sem worktree."""
    tarefa = json.dumps(
        {"kind": kind, "content": {"request": pedido, "system": system}},
        ensure_ascii=False,
    )
    with tempfile.TemporaryDirectory(prefix=f"aso-{kind}-") as tmp:
        proc = subprocess.run(
            command,
            cwd=tmp,
            input=tarefa,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    if proc.returncode != 0:
        raise ValueError(f"exit={proc.returncode}: {(proc.stderr or proc.stdout)[-200:]}")
    return proc.stdout
