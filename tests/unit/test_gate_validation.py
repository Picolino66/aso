"""Quality gate precisa terminar e devolver exit code."""

import pytest

from aso.execution.gate_validation import GateCommandError, validate_gate_command


@pytest.mark.parametrize(
    "command",
    [
        "npm run dev",
        "pnpm run serve",
        "yarn start",
        "vite",
        "pytest --watch",
        "sh -c 'npm run dev'",
    ],
)
def test_rejeita_comandos_continuos(command: str) -> None:
    with pytest.raises(GateCommandError, match="contínuo"):
        validate_gate_command(command)


@pytest.mark.parametrize("command", ["npm test", "npm run build", "pytest -q", "ruff check src"])
def test_aceita_comandos_finitos(command: str) -> None:
    assert validate_gate_command(command) == command
