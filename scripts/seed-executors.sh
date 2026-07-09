#!/usr/bin/env bash
# Seed de executores: cadastra Codex CLI e Claude CLI com todos os modelos e todos os
# níveis de esforço (low/medium/high) via POST /v1/executors na API em execução.
#
# As CHAVES/segredos NÃO entram aqui — os CLIs (codex/claude) usam a própria
# autenticação instalada na máquina. Requer, para EXECUTAR (não para cadastrar):
#   export ASO_TARGET_REPO=/caminho/do/repo   # repo alvo dos worktrees
#   binários `codex` e `claude` no PATH do processo da API
#
# Os modelos abaixo são defaults sensatos — edite os arrays conforme sua instalação.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE="${1:-http://localhost:8000}"
WRAPPER="$ROOT/scripts/aso-agent-wrapper.sh"   # caminho pode ter espaços → citado abaixo

AUTH=()
[ -n "${ASO_ADMIN_TOKEN:-}" ] && AUTH=(-H "Authorization: Bearer ${ASO_ADMIN_TOKEN}")

# Ajuste conforme os modelos disponíveis na sua conta/instalação:
CLAUDE_MODELS=(opus sonnet haiku)
CODEX_MODELS=(gpt-5-codex gpt-5 o4-mini)
EFFORTS=(low medium high)

_post() { # name kind model effort command is_default
  local body
  body="$(python3 - "$@" <<'PY'
import json, sys
name, kind, model, effort, command, default = sys.argv[1:7]
print(json.dumps({
    "name": name, "kind": kind, "model": model, "effort": effort,
    "command": command, "is_default": default == "1",
}))
PY
)"
  curl -fsS "${AUTH[@]}" -X POST "$BASE/v1/executors" \
    -H 'content-type: application/json' -d "$body" >/dev/null && echo "  + $1"
}

echo "Cadastrando executores em $BASE …"

# Claude Code: aliases de modelo estáveis; sem flag de esforço nativa (o nível vai no
# perfil e é passado ao agente como sinal via o wrapper).
for m in "${CLAUDE_MODELS[@]}"; do
  for e in "${EFFORTS[@]}"; do
    d=0; [ "$m" = "sonnet" ] && [ "$e" = "high" ] && d=1   # default do seed
    _post "claude-$m-$e" cli "$m" "$e" "\"$WRAPPER\" claude -p --model $m" "$d"
  done
done

# Codex CLI: modelo via -m e esforço de raciocínio via -c model_reasoning_effort.
for m in "${CODEX_MODELS[@]}"; do
  for e in "${EFFORTS[@]}"; do
    _post "codex-$m-$e" cli "$m" "$e" \
      "\"$WRAPPER\" codex exec -m $m -c model_reasoning_effort=$e" 0
  done
done

echo "Seed concluído. Para EXECUTAR: defina ASO_TARGET_REPO e garanta codex/claude no PATH."
