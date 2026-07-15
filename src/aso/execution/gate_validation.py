"""Validação preventiva de comandos usados como quality gate."""

from __future__ import annotations

import shlex


class GateCommandError(ValueError):
    """Comando vazio, inválido ou conhecido por não terminar sozinho."""


def validate_gate_command(command: str) -> str:
    """Recusa servidores/watchers; quality gate precisa produzir um exit code finito."""
    value = command.strip()
    if not value:
        raise GateCommandError("Informe um comando de validação finito.")
    try:
        tokens = shlex.split(value)
    except ValueError as exc:
        raise GateCommandError(f"Comando de validação inválido: {exc}") from exc
    lowered = [token.lower() for token in tokens]
    flattened = " ".join(lowered)
    npm_continuous = (
        len(lowered) >= 3
        and lowered[0] in {"npm", "pnpm", "yarn", "bun"}
        and lowered[1] == "run"
        and lowered[2] in {"dev", "serve", "start", "watch"}
    ) or (len(lowered) >= 2 and lowered[0] in {"npm", "yarn"} and lowered[1] == "start")
    continuous_binary = bool(lowered) and lowered[0] in {
        "vite",
        "webpack-dev-server",
        "live-server",
    }
    watch_flag = any(token == "--watch" or token.startswith("--watch=") for token in lowered)
    framework_server = len(lowered) >= 2 and (lowered[:2] in (["ng", "serve"], ["next", "dev"]))
    embedded_server = any(
        marker in flattened
        for marker in (
            "npm run dev",
            "npm run serve",
            "npm run start",
            "pnpm run dev",
            "yarn run dev",
        )
    )
    if npm_continuous or continuous_binary or watch_flag or framework_server or embedded_server:
        raise GateCommandError(
            "O comando de validação parece contínuo. Use teste, lint ou build que termine "
            "com exit code, por exemplo `npm test` ou `npm run build`."
        )
    return value
