#!/usr/bin/env bash
# Smoke test end-to-end contra a API em execução (usada no CI e localmente).
set -euo pipefail

BASE="${1:-http://localhost:8000}"

echo "1) health"
curl -fsS "$BASE/health" | grep -q '"status":"ok"'

echo "2) criar orquestração"
OID=$(curl -fsS -X POST "$BASE/v1/orchestrations" \
  -H 'content-type: application/json' \
  -d '{"user_request":"smoke docker"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
echo "   oid=$OID"

echo "3) executar card + quality gate"
CARD=$(curl -fsS "$BASE/v1/orchestrations/$OID/cards" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)[0]['id'])")
curl -fsS -X POST "$BASE/v1/orchestrations/$OID/cards/$CARD/run" >/dev/null
curl -fsS -X POST "$BASE/v1/orchestrations/$OID/quality-gates/run" \
  -H 'content-type: application/json' -d '{}' >/dev/null

echo "4) validar métricas/snapshot"
curl -fsS "$BASE/v1/orchestrations/$OID/cards/stats" | grep -q '"Testing"'
curl -fsS "$BASE/v1/orchestrations/$OID/snapshots" | grep -q '"O5"'

echo "SMOKE OK"
