#!/usr/bin/env bash
# Sincroniza o catálogo Codex com o binário/autenticação efetivos da API.
# Não executa prompts: a API consulta `codex app-server` → `model/list`.
set -euo pipefail

BASE="${1:-http://localhost:8000}"
AUTH=()
[ -n "${ASO_ADMIN_TOKEN:-}" ] && AUTH=(-H "Authorization: Bearer ${ASO_ADMIN_TOKEN}")

response="$(curl -fsS "${AUTH[@]}" -X POST "$BASE/v1/executors/sync")"
python3 - "$response" <<'PY'
import json, sys
profiles = json.loads(sys.argv[1])
managed = [item for item in profiles if item.get("managed_by") == "codex"]
default = next((item for item in managed if item.get("name") == "codex-default"), {})
print(f"Codex: {default.get('runtime_version', 'versão desconhecida')}")
for item in managed:
    model = item.get("model") or "padrão recomendado pelo CLI"
    efforts = ", ".join(item.get("supported_efforts") or [])
    print(f"  + {item['name']}: {model} [{efforts}]")
PY
