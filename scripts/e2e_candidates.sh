#!/usr/bin/env bash
# Corrida de agentes CLI candidatos ponta a ponta contra a API em execução (§26A.6).
#
# Roda N agentes CLI em worktrees isolados sobre um repo alvo, compara os diffs,
# abre PR do candidato recomendado e faz o merge governado (CI + review + admin).
#
# Para usar agentes CLI REAIS (Claude Code, Codex, Aider), exporte antes de subir a API:
#   export ASO_TARGET_REPO=/caminho/do/repo
#   export ASO_CANDIDATE_COMMANDS='[{"id":"claude","command":"claude -p"},{"id":"codex","command":"codex exec"}]'
# e garanta que a API foi iniciada com essas variáveis (docker compose ou uvicorn).
#
# Sem argumentos, cria um repo alvo temporário e usa dois "agentes" determinísticos,
# apenas para demonstrar/validar o fluxo. Requer TOKEN admin se ASO_API_KEYS estiver definido.
set -euo pipefail

BASE="${1:-http://localhost:8000}"
AUTH=()
[ -n "${ASO_ADMIN_TOKEN:-}" ] && AUTH=(-H "Authorization: Bearer ${ASO_ADMIN_TOKEN}")

pyget() { python3 -c "import sys,json;print(json.load(sys.stdin)$1)"; }

echo "1) health"
curl -fsS "$BASE/health" | grep -q '"status":"ok"'

echo "2) criar orquestração + pegar card"
OID=$(curl -fsS "${AUTH[@]}" -X POST "$BASE/v1/orchestrations" \
  -H 'content-type: application/json' \
  -d '{"user_request":"corrida de candidatos"}' | pyget "['id']")
CARD=$(curl -fsS "${AUTH[@]}" "$BASE/v1/orchestrations/$OID/cards" | pyget "[0]['id']")
echo "   oid=$OID card=$CARD"

echo "3) corrida de candidatos (menor diff válido vence)"
CMP=$(curl -fsS "${AUTH[@]}" -X POST "$BASE/v1/orchestrations/$OID/cards/$CARD/race")
echo "$CMP" | python3 -m json.tool
REC=$(echo "$CMP" | pyget "['recommended_branch']")
echo "   recomendado=$REC"

echo "4) abrir PR do recomendado + CI/review + merge governado"
PR=$(curl -fsS "${AUTH[@]}" -X POST "$BASE/v1/orchestrations/$OID/cards/$CARD/open-pr" \
  -H 'content-type: application/json' -d "{\"branch\":\"$REC\"}" | pyget "['id']")
curl -fsS "${AUTH[@]}" -X POST "$BASE/v1/orchestrations/$OID/pulls/$PR/ci" \
  -H 'content-type: application/json' -d '{"status":"passed"}' >/dev/null
curl -fsS "${AUTH[@]}" -X POST "$BASE/v1/orchestrations/$OID/pulls/$PR/review" \
  -H 'content-type: application/json' -d '{"status":"approved"}' >/dev/null
curl -fsS "${AUTH[@]}" -X POST "$BASE/v1/orchestrations/$OID/pulls/$PR/merge" | grep -q '"merged"'

echo "E2E CANDIDATES OK (branch $REC mesclado na base)"
