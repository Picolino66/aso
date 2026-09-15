#!/usr/bin/env bash
# Smoke test end-to-end contra a API em execução (usada no CI e localmente).
set -euo pipefail

BASE="${1:-http://localhost:8000}"

# Rotas de execução respondem 202 + job com ASO_EXECUCAO_ASSINCRONA=1 (ADR-0067). `executar`
# faz o POST e devolve o corpo final nos dois modos (no assíncrono, espera o job por polling).
executar() {
  local url="$1" corpo="${2:-}" resp status job estado
  [ -n "$corpo" ] || corpo='{}'
  resp=$(curl -sS -X POST "$url" -H 'content-type: application/json' -d "$corpo" \
    -w $'\n%{http_code}')
  status=${resp##*$'\n'}
  resp=${resp%$'\n'*}
  if [ "$status" = "202" ]; then
    job=$(printf '%s' "$resp" | python3 -c "import sys,json;print(json.load(sys.stdin)['job_id'])")
    for _ in $(seq 1 600); do
      resp=$(curl -fsS "$BASE/v1/jobs/$job")
      estado=$(printf '%s' "$resp" | python3 -c "import sys,json;print(json.load(sys.stdin)['status'])")
      case "$estado" in
        done)
          printf '%s' "$resp" | python3 -c \
            "import sys,json;print(json.dumps(json.load(sys.stdin)['resultado'],separators=(',',':')))"
          return 0 ;;
        failed|cancelled) echo "job $job $estado: $resp" >&2; return 1 ;;
      esac
      sleep 0.2
    done
    echo "job $job não terminou" >&2
    return 1
  fi
  case "$status" in
    2??) printf '%s' "$resp" ;;
    *) echo "HTTP $status em $url: $resp" >&2; return 1 ;;
  esac
}

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
# ADR-0062: git init confirmado; pasta vazia → commit direto, senão → card + PR.
executar "$BASE/v1/orchestrations/$POID/analyze-folder" '{"inicializar_git":true}' \
  | grep -Eq '"has_aso_docs":true|"entrega":"pr"'
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
CARDJSON=$(curl -fsS "$BASE/v1/orchestrations/$OID/cards" \
  | python3 -c "import sys,json;c=json.load(sys.stdin)[0];print(c['id'], c['phase'])")
CARD=${CARDJSON% *}; FASE=${CARDJSON#* }
executar "$BASE/v1/orchestrations/$OID/cards/$CARD/run" >/dev/null
# Gate da fase do card (ADR-0060): fase vazia seria SKIPPED, sem snapshot.
curl -fsS -X POST "$BASE/v1/orchestrations/$OID/quality-gates/run" \
  -H 'content-type: application/json' -d "{\"phase\":\"$FASE\"}" | grep -q '"PASSED"'

echo "7) validar métricas/snapshot"
curl -fsS "$BASE/v1/orchestrations/$OID/cards/stats" | grep -q '"Testing"'
curl -fsS "$BASE/v1/orchestrations/$OID/snapshots" | grep -q "\"O${FASE#F}\""

echo "8) fila de execução (quando ASO_EXECUCAO_ASSINCRONA=1)"
FILA=$(curl -sS -o /tmp/aso-smoke-jobs.json -w '%{http_code}' "$BASE/v1/orchestrations/$OID/jobs")
if [ "$FILA" = "200" ]; then
  python3 -c "import json;j=json.load(open('/tmp/aso-smoke-jobs.json'));assert j and all(x['status']=='done' for x in j), j"
  echo "   jobs concluídos: $(python3 -c "import json;print(len(json.load(open('/tmp/aso-smoke-jobs.json'))))")"
else
  echo "   execução síncrona (fila desligada)"
fi

echo "SMOKE OK"
