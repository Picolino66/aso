#!/usr/bin/env bash
# Agente CLI de DEMONSTRAÇÃO (offline, sem LLM/chave) para provar a esteira ponta a
# ponta: recebe a tarefa do ASO (JSON no stdin), roda no worktree do card e ESCREVE
# CÓDIGO REAL (um módulo de calculadora + teste). Serve para ver o fluxo
# agente → diff → commit → PR → merge sem depender de Codex/Claude/DeepSeek.
#
# Configure como executor cli com este caminho absoluto no campo "comando CLI".
set -euo pipefail

# Consome a tarefa (o demo não precisa do conteúdo, mas drena o stdin).
cat >/dev/null || true

cat > calculadora.py <<'PY'
"""Calculadora simples gerada pelo agente-demo do ASO Runtime."""


def soma(a: float, b: float) -> float:
    return a + b


def subtrai(a: float, b: float) -> float:
    return a - b
PY

cat > test_calculadora.py <<'PY'
from calculadora import soma, subtrai


def test_soma():
    assert soma(2, 3) == 5


def test_subtrai():
    assert subtrai(5, 2) == 3
PY

echo "agente-demo: calculadora.py + test_calculadora.py escritos em $(pwd)"
