"""MEL-36 — regra de dependência: sem ciclos, camadas do import-linter e doc no mesmo grafo.

Não depende do `import-linter` instalado: lê os imports por AST, para a bateria normal também
proteger a regra (o CI roda `lint-imports` além disto).
"""

from __future__ import annotations

import ast
import json
import tomllib
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
PACOTE = RAIZ / "src" / "aso"


def _grafo_real() -> dict[str, set[str]]:
    grafo: dict[str, set[str]] = defaultdict(set)
    for arquivo in PACOTE.rglob("*.py"):
        origem = arquivo.relative_to(PACOTE).parts[0].removesuffix(".py")
        for no in ast.walk(ast.parse(arquivo.read_text(encoding="utf-8"))):
            modulos: list[str] = []
            if isinstance(no, ast.ImportFrom) and no.module and no.module.startswith("aso."):
                modulos = [no.module]
            elif isinstance(no, ast.Import):
                modulos = [a.name for a in no.names if a.name.startswith("aso.")]
            for modulo in modulos:
                destino = modulo.split(".")[1]
                if destino != origem:
                    grafo[origem].add(destino)
    return grafo


def _camadas() -> list[set[str]]:
    config = tomllib.loads((RAIZ / "pyproject.toml").read_text(encoding="utf-8"))
    contrato = config["tool"]["importlinter"]["contracts"][0]
    return [
        {nome.strip().removeprefix("aso.") for nome in camada.split("|")}
        for camada in contrato["layers"]
    ]


def test_nenhum_ciclo_entre_pacotes() -> None:
    grafo = _grafo_real()
    visitando: set[str] = set()
    concluidos: set[str] = set()
    ciclos: list[str] = []

    def visitar(no: str, caminho: list[str]) -> None:
        visitando.add(no)
        for vizinho in sorted(grafo.get(no, ())):
            if vizinho in visitando:
                ciclos.append(" → ".join([*caminho, vizinho]))
            elif vizinho not in concluidos:
                visitar(vizinho, [*caminho, vizinho])
        visitando.discard(no)
        concluidos.add(no)

    for pacote in sorted(grafo):
        if pacote not in concluidos:
            visitar(pacote, [pacote])
    assert ciclos == []


def test_imports_respeitam_as_camadas_do_import_linter() -> None:
    camadas = _camadas()
    nivel = {pacote: i for i, camada in enumerate(camadas) for pacote in camada}
    violacoes = [
        f"{origem} → {destino}"
        for origem, destinos in _grafo_real().items()
        for destino in destinos
        if origem in nivel and destino in nivel and nivel[destino] <= nivel[origem]
    ]
    assert violacoes == []
    pacotes = {p.name.removesuffix(".py") for p in PACOTE.iterdir() if not p.name.startswith("_")}
    pacotes.discard("__pycache__")
    assert pacotes <= set(nivel), "todo pacote de aso precisa estar numa camada"


def test_module_map_documentado_e_o_grafo_real() -> None:
    contexto = json.loads(
        (RAIZ / ".aso/context/orchestrator-context.json").read_text(encoding="utf-8")
    )
    documentado = {k: set(v) for k, v in contexto["engineering"]["module_map"].items()}
    real = {k: v for k, v in _grafo_real().items()}
    real.update({k: set() for k in documentado if k not in real})
    assert documentado == real
