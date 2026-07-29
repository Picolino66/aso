#!/usr/bin/env bash
# Corrige a permissão de escrita dos executores CLI do catálogo (diff vazio).
#
# PROBLEMA: `claude -p` roda sem permissão de escrita em modo não-interativo — responde em
# texto, sai com código 0 e deixa o worktree intacto. O ASO detecta o diff vazio e marca o
# card como Failed. O mesmo vale para `codex exec` quando o sandbox cai em read-only.
#
# ESCOLHA DE SEGURANÇA: `--dangerously-skip-permissions` dá autonomia total ao agente
# DENTRO do worktree isolado do card. A contenção do ASO continua sendo o worktree + diff
# coletado + merge governado com CI e revisão (regra 5 · ADR-0009). Se preferir algo mais
# conservador, troque FLAG por "--permission-mode acceptEdits" (o agente edita arquivos,
# mas não executa comandos — pode travar cards que precisem rodar build/testes).
#
# Uso: ./scripts/fix-executor-permissions.sh [http://localhost:8000]
set -euo pipefail

BASE="${1:-http://localhost:8000}"
FLAG="${ASO_CLAUDE_PERMISSION_FLAG:---dangerously-skip-permissions}"
AUTH=()
[ -n "${ASO_ADMIN_TOKEN:-}" ] && AUTH=(-H "Authorization: Bearer ${ASO_ADMIN_TOKEN}")

echo "Catálogo: $BASE · flag: $FLAG"

perfis="$(curl -fsS "${AUTH[@]}" "$BASE/v1/executors")"

# Monta o corpo de cada perfil claude-* com a flag inserida logo após `claude -p`.
corpos="$(FLAG="$FLAG" python3 - "$perfis" <<'PY'
import json, os, sys
flag = os.environ["FLAG"]
for p in json.loads(sys.argv[1]):
    comando = p.get("command") or ""
    if not p["name"].startswith("claude-") or flag in comando:
        continue
    print(json.dumps({
        "name": p["name"], "kind": p["kind"], "provider": p.get("provider") or "",
        "model": p.get("model") or "", "effort": p.get("effort") or "medium",
        "command": comando.replace("claude -p ", f"claude -p {flag} ", 1),
        "base_url": p.get("base_url") or "", "api_key_env": p.get("api_key_env") or "",
        "is_default": bool(p.get("is_default")),
    }, ensure_ascii=False))
PY
)"

if [ -z "$corpos" ]; then
  echo "Nenhum perfil claude-* pendente (já corrigidos)."
else
  while IFS= read -r corpo; do
    nome="$(printf '%s' "$corpo" | python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])')"
    curl -fsS "${AUTH[@]}" -X POST "$BASE/v1/executors" \
      -H 'content-type: application/json' -d "$corpo" > /dev/null
    echo "  corrigido: $nome"
  done <<< "$corpos"
fi

# Perfis Codex são gerenciados: o comando (já com --sandbox workspace-write) vem do código,
# então basta ressincronizar. Requer a API rodando com o código atualizado.
echo "Ressincronizando perfis Codex gerenciados…"
curl -fsS "${AUTH[@]}" -X POST "$BASE/v1/executors/sync" > /dev/null && echo "  sync OK"

echo
echo "--- comandos resultantes ---"
# Heredoc quotado: o shell não interpreta o corpo, então aspas dentro do Python ficam intactas.
curl -fsS "${AUTH[@]}" "$BASE/v1/executors" | python3 <<'PY'
import json, sys

for p in json.load(sys.stdin):
    if p["kind"] != "cli":
        continue
    comando = (p.get("command") or "").split("wrapper.sh")[-1].strip('" ')
    print(f"  {p['name']:22} {comando}")
PY
