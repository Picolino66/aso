#!/usr/bin/env bash
# Smoke test end-to-end contra a API em execução (usada no CI e localmente).
set -euo pipefail

BASE="${1:-http://localhost:8000}"

echo "1) health"
curl -fsS "$BASE/health" | grep -q '"status":"ok"'

echo "2) console + catálogo multi-repo"
curl -fsS "$BASE/ui/" | grep -q 'Catálogo multi-repo'
curl -fsS "$BASE/ui/nova" | grep -q 'Pré-analisar pasta'
PID=$(curl -fsS -X POST "$BASE/v1/projects" \
  -H 'content-type: application/json' \
  -d '{"name":"Projeto smoke","description":"Docker/Postgres","target_path":"/tmp"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
curl -fsS "$BASE/v1/fs/analyze/stream?path=%2Ftmp" | grep -q '"percent": 100'

echo "3) criar orquestração vinculada + docs-first"
POID=$(curl -fsS -X POST "$BASE/v1/orchestrations" \
  -H 'content-type: application/json' \
  -d "{\"user_request\":\"smoke multi-repo\",\"project_id\":\"$PID\"}" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
curl -fsS -X POST "$BASE/v1/orchestrations/$POID/analyze-folder" \
  -H 'content-type: application/json' -d '{}' | grep -q '"has_aso_docs":true'
test "$(curl -fsS "$BASE/v1/orchestrations?project_id=$PID" \
  | python3 -c 'import sys,json;print(len(json.load(sys.stdin)))')" = "1"

echo "4) arquivar/restaurar sem apagar a orquestração"
curl -fsS -X DELETE "$BASE/v1/projects/$PID" | grep -q '"status":"archived"'
curl -fsS "$BASE/v1/orchestrations/$POID" | grep -q "\"id\":\"$POID\""
curl -fsS "$BASE/v1/projects/$PID/events" | grep -q 'ProjectArchived'
curl -fsS -X POST "$BASE/v1/projects/$PID/restore" \
  -H 'content-type: application/json' -d '{}' | grep -q '"status":"active"'

echo "5) criar orquestração compatível sem projeto"
OID=$(curl -fsS -X POST "$BASE/v1/orchestrations" \
  -H 'content-type: application/json' \
  -d '{"user_request":"smoke docker"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
echo "   oid=$OID"

echo "6) executar card + quality gate"
CARD=$(curl -fsS "$BASE/v1/orchestrations/$OID/cards" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)[0]['id'])")
curl -fsS -X POST "$BASE/v1/orchestrations/$OID/cards/$CARD/run" >/dev/null
curl -fsS -X POST "$BASE/v1/orchestrations/$OID/quality-gates/run" \
  -H 'content-type: application/json' -d '{}' >/dev/null

echo "7) validar métricas/snapshot"
curl -fsS "$BASE/v1/orchestrations/$OID/cards/stats" | grep -q '"Testing"'
curl -fsS "$BASE/v1/orchestrations/$OID/snapshots" | grep -q '"O1"'

echo "SMOKE OK"
