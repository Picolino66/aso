"""Descoberta local de modelos do Codex CLI sem consumir uma inferência.

O App Server é a fonte operacional porque combina a versão do binário com a
autenticação ativa. A lista pública de modelos não garante acesso numa conta.
"""

from __future__ import annotations

import json
import os
import selectors
import shutil
import subprocess
import time
from dataclasses import dataclass


class CodexDiscoveryError(RuntimeError):
    """Falha controlada ao consultar capacidades do Codex instalado."""


@dataclass(frozen=True)
class CodexModel:
    """Modelo anunciado pelo App Server para a autenticação atual."""

    model: str
    display_name: str
    is_default: bool
    default_effort: str
    supported_efforts: tuple[str, ...]


@dataclass(frozen=True)
class CodexCapabilities:
    """Inventário efetivo do binário Codex usado pelo processo da API."""

    binary: str
    version: str
    models: tuple[CodexModel, ...]


def _send(proc: subprocess.Popen[str], payload: dict[str, object]) -> None:
    if proc.stdin is None:
        raise CodexDiscoveryError("Codex App Server iniciou sem canal de entrada.")
    proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
    proc.stdin.flush()


def _read_response(
    proc: subprocess.Popen[str], selector: selectors.BaseSelector, request_id: int, deadline: float
) -> dict[str, object]:
    while time.monotonic() < deadline:
        ready = selector.select(max(0.0, deadline - time.monotonic()))
        if not ready or proc.stdout is None:
            break
        line = proc.stdout.readline()
        if not line:
            break
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if message.get("id") != request_id:
            continue
        if message.get("error"):
            raise CodexDiscoveryError(f"Codex recusou model/list: {message['error']}")
        result = message.get("result")
        if not isinstance(result, dict):
            raise CodexDiscoveryError("Codex devolveu uma resposta model/list inválida.")
        return result
    raise CodexDiscoveryError("Codex não respondeu à descoberta de modelos no tempo limite.")


def discover_codex(*, timeout: float = 5.0, binary: str | None = None) -> CodexCapabilities:
    """Consulta `model/list` paginado do Codex autenticado, sem executar prompt."""
    configured = binary or os.environ.get("ASO_CODEX_BIN", "codex")
    resolved = shutil.which(configured) if os.path.sep not in configured else configured
    if not resolved:
        raise CodexDiscoveryError(
            f"Codex CLI não encontrado: configure ASO_CODEX_BIN (recebido: {configured})."
        )
    try:
        version_proc = subprocess.run(
            [resolved, "--version"], capture_output=True, text=True, timeout=min(timeout, 2.0)
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CodexDiscoveryError(f"Não foi possível consultar a versão do Codex: {exc}") from exc
    if version_proc.returncode != 0:
        raise CodexDiscoveryError("O binário Codex não respondeu a --version.")
    version = version_proc.stdout.strip() or version_proc.stderr.strip()

    try:
        proc = subprocess.Popen(
            [resolved, "app-server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
    except OSError as exc:
        raise CodexDiscoveryError(f"Não foi possível iniciar o Codex App Server: {exc}") from exc

    selector = selectors.DefaultSelector()
    try:
        if proc.stdout is None:
            raise CodexDiscoveryError("Codex App Server iniciou sem canal de saída.")
        selector.register(proc.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + timeout
        _send(
            proc,
            {
                "id": 1,
                "method": "initialize",
                "params": {"clientInfo": {"name": "aso-runtime", "version": "1"}},
            },
        )
        _read_response(proc, selector, 1, deadline)
        _send(proc, {"method": "initialized"})

        models: list[CodexModel] = []
        cursor: str | None = None
        request_id = 2
        while True:
            _send(
                proc,
                {
                    "id": request_id,
                    "method": "model/list",
                    "params": {"limit": 100, "includeHidden": False, "cursor": cursor},
                },
            )
            result = _read_response(proc, selector, request_id, deadline)
            data = result.get("data")
            if not isinstance(data, list):
                raise CodexDiscoveryError("Codex devolveu model/list sem a lista `data`.")
            for item in data:
                if not isinstance(item, dict) or not isinstance(item.get("model"), str):
                    continue
                efforts_raw = item.get("supportedReasoningEfforts", [])
                efforts = tuple(
                    str(option["reasoningEffort"])
                    for option in efforts_raw
                    if isinstance(option, dict) and option.get("reasoningEffort")
                )
                models.append(
                    CodexModel(
                        model=str(item["model"]),
                        display_name=str(item.get("displayName") or item["model"]),
                        is_default=bool(item.get("isDefault")),
                        default_effort=str(item.get("defaultReasoningEffort") or "medium"),
                        supported_efforts=efforts or ("medium",),
                    )
                )
            next_cursor = result.get("nextCursor")
            cursor = str(next_cursor) if next_cursor else None
            if cursor is None:
                break
            request_id += 1
        if not models:
            raise CodexDiscoveryError("O Codex não anunciou nenhum modelo disponível.")
        return CodexCapabilities(binary=str(resolved), version=version, models=tuple(models))
    finally:
        selector.close()
        proc.terminate()
        try:
            proc.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=1.0)
