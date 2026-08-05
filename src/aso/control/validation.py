"""Bateria de validações (§12 do fluxo.md) — ADR-0022.

Puro e determinístico, no mesmo espírito de `next_step.py`/`failure.py`: dado o
mesmo estado (orquestração ou workspace), o resultado é sempre o mesmo — nenhum
agente decide aqui.
"""

from __future__ import annotations

import json
from pathlib import Path

from aso.control.models import Orchestration, ValidationCheck

# Nome da verificação sintética quando só existe o `validation_command` legado —
# preserva o rótulo "testes" que já aparecia nos critérios/eventos antigos, então
# nenhuma orquestração existente muda de comportamento no gate.
NOME_CHECK_LEGADO = "testes"


def checks_efetivos(orch: Orchestration) -> list[ValidationCheck]:
    """A bateria efetiva da orquestração.

    Sem bateria configurada (`validation_checks` vazio), o `validation_command`
    legado vira uma verificação única chamada "testes" — compatibilidade é
    requisito, não cortesia (§4.1 do plano5.md): toda orquestração criada antes
    deste incremento continua funcionando exatamente igual.
    """
    if orch.validation_checks:
        return list(orch.validation_checks)
    if orch.validation_command:
        return [ValidationCheck(nome=NOME_CHECK_LEGADO, comando=orch.validation_command)]
    return []


# Scripts de `package.json` reconhecidos, na ordem em que aparecem na bateria
# sugerida — só entram os que existem de fato no arquivo (§4.5: nunca inventar).
_SCRIPTS_NPM: tuple[tuple[str, str, str], ...] = (
    ("lint", "lint", "lint"),
    ("test", "testes", "testes"),
    ("build", "build", "compilacao"),
)


def sugerir_bateria(target_path: str) -> list[ValidationCheck]:
    """Sugestão determinística por stack (§4.5) — nunca grava nada e nunca inventa
    comando de arquivo/script que não existe no workspace. Pasta sem stack
    reconhecida devolve lista vazia."""
    raiz = Path(target_path).expanduser()
    if (raiz / "pyproject.toml").is_file() or (raiz / "setup.cfg").is_file():
        return [
            ValidationCheck(nome="lint", comando="ruff check .", categoria="lint"),
            ValidationCheck(
                nome="formatacao", comando="ruff format --check .", categoria="formatacao"
            ),
            ValidationCheck(nome="tipos", comando="mypy .", categoria="tipos"),
            ValidationCheck(nome="testes", comando="pytest -q", categoria="testes"),
        ]
    package_json = raiz / "package.json"
    if package_json.is_file():
        try:
            dados = json.loads(package_json.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            dados = {}
        scripts = dados.get("scripts") if isinstance(dados, dict) else None
        scripts = scripts if isinstance(scripts, dict) else {}
        return [
            ValidationCheck(nome=nome, comando=f"npm run {script}", categoria=categoria)
            for script, nome, categoria in _SCRIPTS_NPM
            if script in scripts
        ]
    if (raiz / "go.mod").is_file():
        return [
            ValidationCheck(nome="vet", comando="go vet ./...", categoria="estatica"),
            ValidationCheck(nome="build", comando="go build ./...", categoria="compilacao"),
            ValidationCheck(nome="testes", comando="go test ./...", categoria="testes"),
        ]
    if (raiz / "Cargo.toml").is_file():
        return [
            ValidationCheck(nome="clippy", comando="cargo clippy", categoria="lint"),
            ValidationCheck(nome="formatacao", comando="cargo fmt --check", categoria="formatacao"),
            ValidationCheck(nome="testes", comando="cargo test", categoria="testes"),
        ]
    return []
