#!/usr/bin/env bash
# manager.sh — painel local do ASO Runtime.
#
# Modelo: Postgres roda via Docker (serviço `postgres` do docker-compose.yml) e a
# API/back (FastAPI+uvicorn, que também serve o console em /ui) roda LOCAL na venv,
# conectando no Postgres do Docker via ASO_DATABASE_URL.
#
# Uso:  ./scripts/manager.sh [comando]
#   iniciar | parar | reiniciar | status | logs | db-logs | migrate | test | check | psql | shell
# Sem comando, abre o menu interativo.
set -u

# ---------------------------------------------------------------- localização
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VENV="$ROOT/.venv"
RUNDIR="$ROOT/.aso/run"
PID="$RUNDIR/api.pid"
LOG="$RUNDIR/api.log"
PORT="${ASO_PORT:-8000}"
DB_URL="${ASO_DATABASE_URL:-postgresql+psycopg://aso:aso@localhost:5432/aso}"
PG_SERVICE="postgres"

# ---------------------------------------------------------------- helpers de UI
c_reset=$'\e[0m'; c_ok=$'\e[32m'; c_err=$'\e[31m'; c_warn=$'\e[33m'; c_info=$'\e[36m'
ok()   { echo "${c_ok}✔${c_reset} $*"; }
err()  { echo "${c_err}✖${c_reset} $*" >&2; }
warn() { echo "${c_warn}⚠${c_reset} $*"; }
info() { echo "${c_info}➜${c_reset} $*"; }

# ---------------------------------------------------------------- pré-requisitos
COMPOSE=""
detect_compose() {
  if docker compose version >/dev/null 2>&1; then COMPOSE="docker compose"
  elif command -v docker-compose >/dev/null 2>&1; then COMPOSE="docker-compose"
  fi
}
require_docker() {
  command -v docker >/dev/null 2>&1 || { err "Docker não instalado (necessário para o Postgres)."; return 1; }
  docker info >/dev/null 2>&1 || { err "Docker não está em execução. Inicie o serviço do Docker."; return 1; }
  detect_compose
  [ -n "$COMPOSE" ] || { err "docker compose não disponível."; return 1; }
}
_install_deps() { "$VENV/bin/pip" install -q -e ".[dev,postgres]" && ok "Dependências instaladas."; }
require_venv() {
  if [ ! -x "$VENV/bin/uvicorn" ]; then
    warn "venv não encontrada em .venv (ou sem dependências)."
    read -r -p "Criar a venv e instalar dependências agora? [S/n] " a
    case "${a:-S}" in
      [Nn]*) err "Abortado: crie a venv com 'python -m venv .venv && . .venv/bin/activate && pip install -e \".[dev,postgres]\"'."; return 1;;
      *) python3 -m venv "$VENV" && _install_deps || { err "Falha ao preparar a venv."; return 1; };;
    esac
  fi
  # Driver do Postgres é obrigatório para conectar no banco do Docker.
  if ! "$VENV/bin/python" -c "import psycopg" >/dev/null 2>&1; then
    warn "Driver 'psycopg' ausente na venv (extra [postgres])."
    _install_deps || { err "Instale com: .venv/bin/pip install -e \".[postgres]\""; return 1; }
  fi
}

# ---------------------------------------------------------------- Postgres (Docker)
db_cid() { $COMPOSE ps -q "$PG_SERVICE" 2>/dev/null; }
db_up() {
  require_docker || return 1
  info "Subindo o Postgres (Docker)…"
  $COMPOSE up -d "$PG_SERVICE" || { err "Falha ao subir o Postgres."; return 1; }
}
db_wait_healthy() {
  info "Aguardando o Postgres ficar saudável…"
  for _ in $(seq 1 30); do
    local cid st; cid="$(db_cid)"
    if [ -n "$cid" ]; then
      st="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid" 2>/dev/null)"
      [ "$st" = "healthy" ] && { ok "Postgres saudável."; return 0; }
    fi
    sleep 1
  done
  err "Postgres não ficou saudável a tempo."; return 1
}

# ---------------------------------------------------------------- API local (uvicorn)
api_running() { [ -f "$PID" ] && kill -0 "$(cat "$PID" 2>/dev/null)" 2>/dev/null; }
migrate() {
  require_venv || return 1
  info "Aplicando migrations (alembic upgrade head)…"
  ASO_DATABASE_URL="$DB_URL" "$VENV/bin/alembic" upgrade head && ok "Migrations em dia." || { err "Falha nas migrations."; return 1; }
}
api_start() {
  require_venv || return 1
  if api_running; then warn "API já está rodando (PID $(cat "$PID"))."; return 0; fi
  mkdir -p "$RUNDIR"
  info "Iniciando a API local (uvicorn :$PORT)…"
  ASO_DATABASE_URL="$DB_URL" PYTHONPATH="$ROOT/src" nohup \
    "$VENV/bin/uvicorn" aso.api.app:app --host 0.0.0.0 --port "$PORT" >"$LOG" 2>&1 &
  echo $! > "$PID"
  for _ in $(seq 1 20); do
    if curl -fsS "http://localhost:$PORT/health" >/dev/null 2>&1; then
      ok "API no ar → http://localhost:$PORT/ui  (docs: /docs)"; return 0
    fi
    api_running || { err "A API caiu ao iniciar. Veja os logs: ./scripts/manager.sh logs"; return 1; }
    sleep 1
  done
  warn "API iniciada mas /health não respondeu ainda. Confira: ./scripts/manager.sh logs"
}
api_stop() {
  if api_running; then
    info "Parando a API local (PID $(cat "$PID"))…"; kill "$(cat "$PID")" 2>/dev/null
    for _ in $(seq 1 10); do api_running || break; sleep 1; done
    api_running && kill -9 "$(cat "$PID")" 2>/dev/null
    rm -f "$PID"; ok "API parada."
  else
    info "API não estava rodando."
  fi
}

# ---------------------------------------------------------------- comandos
cmd_iniciar() { db_up && db_wait_healthy && migrate && api_start; }
cmd_parar()   { api_stop; require_docker && { info "Derrubando o Postgres…"; $COMPOSE stop "$PG_SERVICE" >/dev/null && ok "Postgres parado (dados preservados)."; }; }
cmd_reiniciar(){ api_stop; cmd_iniciar; }
cmd_status() {
  echo "── Postgres (Docker) ──"
  if require_docker 2>/dev/null; then
    local cid; cid="$(db_cid)"
    if [ -n "$cid" ]; then
      docker inspect -f '  container: {{.Name}}  status: {{.State.Status}}  health: {{if .State.Health}}{{.State.Health.Status}}{{else}}n/a{{end}}' "$cid"
    else echo "  parado"; fi
  fi
  echo "── API local (uvicorn) ──"
  if api_running; then
    echo "  rodando (PID $(cat "$PID")) em http://localhost:$PORT/ui"
    curl -fsS "http://localhost:$PORT/health" >/dev/null 2>&1 && ok "  /health OK" || warn "  /health sem resposta"
  else echo "  parada"; fi
  echo "  ASO_DATABASE_URL=$DB_URL"
}
cmd_logs()    { [ -f "$LOG" ] || { warn "Sem log ainda (inicie a API)."; return 0; }; info "Logs da API (Ctrl+C p/ sair):"; tail -n 80 -f "$LOG"; }
cmd_dblogs()  { require_docker || return 1; info "Logs do Postgres (Ctrl+C p/ sair):"; $COMPOSE logs -f "$PG_SERVICE"; }
cmd_test()    { require_venv || return 1; "$VENV/bin/python" -m pytest -q -p no:cacheprovider; }
cmd_check()   { require_venv || return 1; "$VENV/bin/ruff" check src tests && "$VENV/bin/ruff" format --check src tests && "$VENV/bin/mypy" src && ok "Lint + tipagem OK"; }
cmd_seed()    {
  if ! curl -fsS "http://localhost:$PORT/health" >/dev/null 2>&1; then
    warn "API não está no ar — iniciando primeiro…"; cmd_iniciar || return 1
  fi
  info "Cadastrando executores Codex/Claude (todos os modelos × níveis)…"
  bash "$ROOT/scripts/seed-executors.sh" "http://localhost:$PORT"
  ok "Executores no catálogo. Abra ⚙ Config no console para ver/editar."
}
cmd_psql()    { require_docker || return 1; local cid; cid="$(db_cid)"; [ -n "$cid" ] || { err "Postgres não está rodando."; return 1; }; info "Console psql (\\q p/ sair):"; docker exec -it "$cid" psql -U aso -d aso; }
cmd_shell()   { require_docker || return 1; local cid; cid="$(db_cid)"; [ -n "$cid" ] || { err "Postgres não está rodando."; return 1; }; docker exec -it "$cid" bash; }

# ---------------------------------------------------------------- menu
menu() {
  while true; do
    echo
    echo "${c_info}==== ASO Runtime · manager ====${c_reset}"
    echo "  1) Iniciar (Postgres no Docker + migrations + API local)"
    echo "  2) Parar (API local + Postgres)"
    echo "  3) Reiniciar"
    echo "  4) Status"
    echo "  5) Logs da API"
    echo "  6) Logs do Postgres"
    echo "  7) Migrations (alembic upgrade head)"
    echo "  8) Rodar testes"
    echo "  9) Lint + tipagem (ruff/mypy)"
    echo " 10) Console psql"
    echo " 11) Shell do Postgres"
    echo " 12) Seed de executores (Codex + Claude, todos os modelos/níveis)"
    echo "  0) Sair"
    read -r -p "Opção: " opt
    case "$opt" in
      1) cmd_iniciar;; 2) cmd_parar;; 3) cmd_reiniciar;; 4) cmd_status;;
      5) cmd_logs;; 6) cmd_dblogs;; 7) migrate;; 8) cmd_test;; 9) cmd_check;;
      10) cmd_psql;; 11) cmd_shell;; 12) cmd_seed;; 0) exit 0;;
      *) warn "Opção inválida.";;
    esac
  done
}

case "${1:-menu}" in
  iniciar|start|up)      cmd_iniciar;;
  parar|stop|down)       cmd_parar;;
  reiniciar|restart)     cmd_reiniciar;;
  status)                cmd_status;;
  logs)                  cmd_logs;;
  db-logs|dblogs)        cmd_dblogs;;
  migrate|migrations)    migrate;;
  test|testes)           cmd_test;;
  check|lint)            cmd_check;;
  psql|db)               cmd_psql;;
  shell)                 cmd_shell;;
  seed)                  cmd_seed;;
  menu|"")               menu;;
  -h|--help|help)        sed -n '2,12p' "$0";;
  *) err "Comando desconhecido: $1"; sed -n '2,12p' "$0"; exit 1;;
esac
