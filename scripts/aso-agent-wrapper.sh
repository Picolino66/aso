#!/usr/bin/env bash
# Adaptador entre o ASO Runtime e um agente CLI (Codex, Claude Code, Aider, …).
#
# O ASO executa o comando do executor no worktree do card e entrega a TAREFA como
# JSON no stdin. A maioria dos CLIs espera um PROMPT, não esse JSON. Este wrapper lê
# o JSON, monta um prompt em pt-BR (fase/demanda/alvo) e invoca o agente passado em
# "$@" com o prompt como último argumento.
#
# Uso (campo "comando CLI" da tela ⚙ Config, com caminho ABSOLUTO):
#   /app/scripts/aso-agent-wrapper.sh codex exec
#   /app/scripts/aso-agent-wrapper.sh claude -p
#
# Requer python3 no PATH (já presente na imagem do ASO).
set -euo pipefail

export ASO_TASK="$(cat)"

prompt="$(python3 <<'PY'
import json, os
try:
    d = json.loads(os.environ.get("ASO_TASK") or "{}")
except Exception:
    d = {}
c = d.get("content") or {}
req = c.get("request") or c.get("by") or "(sem demanda)"
gate = c.get("validation_command")
print(
    f"Você é um agente de engenharia autônoma no ASO Runtime (fase {d.get('phase', '?')}).\n"
    f"Demanda do produto: {req}\n"
    f"Seção-alvo do contexto: {d.get('target_path', '')}\n"
    "Implemente/produza o necessário NESTE diretório (worktree isolado do card), em "
    "pt-BR, com commits pequenos e foco na fase atual. Se for fase de código, deixe os "
    "testes verdes."
    + (f"\nComando de aceite obrigatório e finito: {gate}" if gate else "")
)
PY
)"

exec "$@" "$prompt"
