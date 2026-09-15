#!/usr/bin/env bash
# Adaptador entre o ASO Runtime e um agente CLI (Codex, Claude Code, Aider, …).
#
# O ASO entrega a TAREFA como JSON no stdin; a maioria dos CLIs espera um PROMPT. Este
# wrapper converte um no outro e invoca o agente passado em "$@" com o prompt como último
# argumento. A montagem do prompt vive em Python testável
# (src/aso/agents/render_prompt.py, contrato TaskEnvelope v1 — ADR-0059):
#   - kind "execute": implementar o card/documentação no worktree isolado;
#   - kind "ask": responder só o JSON pedido (naming, triagem, discovery,
#     especificação, revisão), com o `system` completo — sem instrução de implementar.
# Tarefas no formato antigo (sem `envelope`) continuam aceitas.
#
# Uso (campo "comando CLI" da tela ⚙ Config, com caminho ABSOLUTO):
#   /app/scripts/aso-agent-wrapper.sh codex exec
#   /app/scripts/aso-agent-wrapper.sh claude -p
#
# Requer python3 no PATH (só biblioteca padrão). Exit 2 = contrato inválido.
set -euo pipefail

raiz="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
renderizador="$raiz/src/aso/agents/render_prompt.py"

if [ -f "$renderizador" ]; then
  prompt="$(python3 "$renderizador")"
else
  # Wrapper copiado para fora do repositório: usa o pacote instalado.
  prompt="$(python3 -m aso.agents.render_prompt)"
fi

exec "$@" "$prompt"
