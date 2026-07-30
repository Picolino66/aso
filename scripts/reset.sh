#!/usr/bin/env bash
# reset.sh — zera o estado de runtime do ASO para recomeçar do zero.
#
# O QUE APAGA:
#   - o banco (volume do Postgres no Docker) e o schema é recriado por Alembic;
#   - o `aso.db` residual na raiz (SQLite criado por `alembic` sem ASO_DATABASE_URL);
#   - worktrees git órfãos em `.aso/worktrees/` deste repositório;
#   - `.aso/run/` (pid/log da API local).
#
# O QUE **NÃO** APAGA (de propósito):
#   - `.aso/context/`, `.aso/kanban/`, `.aso/quality-gates/`, `.aso/snapshots/`,
#     `.aso/reviews/` — governança versionada do PRÓPRIO ASO, não estado de runtime;
#   - `.aso/executors.json` — o catálogo de executores vive em arquivo, fora do banco,
#     então seus perfis Claude/Codex sobrevivem (use --executores para apagá-lo também);
#   - os repositórios-alvo das orquestrações. Eles são listados no fim para você decidir.
#
# Uso: ./scripts/reset.sh [--sim] [--executores]
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

SIM=0
APAGAR_EXECUTORES=0
for arg in "$@"; do
  case "$arg" in
    --sim|-y) SIM=1;;
    --executores) APAGAR_EXECUTORES=1;;
    *) echo "Argumento desconhecido: $arg" >&2; exit 2;;
  esac
done

c_reset=$'\e[0m'; c_ok=$'\e[32m'; c_err=$'\e[31m'; c_warn=$'\e[33m'; c_info=$'\e[36m'
ok()   { echo "${c_ok}✔${c_reset} $*"; }
err()  { echo "${c_err}✖${c_reset} $*" >&2; }
warn() { echo "${c_warn}⚠${c_reset} $*"; }
info() { echo "${c_info}➜${c_reset} $*"; }

COMPOSE=""
if docker compose version >/dev/null 2>&1; then COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then COMPOSE="docker-compose"
else err "docker compose não disponível."; exit 1; fi

# ------------------------------------------------------- 1. o que será perdido
# Os caminhos dos repos-alvo só existem no banco: se não forem lidos ANTES do
# drop, some a lista de onde o runtime mexeu.
info "Lendo os repositórios-alvo antes de derrubar o banco…"
ALVOS=""
CID="$($COMPOSE ps -q postgres 2>/dev/null)"
if [ -n "$CID" ] && docker exec "$CID" pg_isready -U aso >/dev/null 2>&1; then
  ALVOS="$(docker exec "$CID" psql -U aso -d aso -tAc \
    "select distinct target_path from orchestrations where target_path is not null
     union select distinct target_path from projects where target_path is not null" 2>/dev/null)"
fi
if [ -n "$ALVOS" ]; then
  warn "Repositórios-alvo registrados (NÃO serão tocados por este script):"
  printf '    %s\n' $ALVOS
else
  info "Nenhum repositório-alvo registrado (ou o Postgres está parado)."
fi

echo
warn "Este reset apaga o banco inteiro: orquestrações, boards, cards, ADRs, snapshots."
if [ "$APAGAR_EXECUTORES" = "1" ]; then
  warn "E também .aso/executors.json — você reconfigura os agentes do zero."
fi
if [ "$SIM" != "1" ]; then
  read -r -p "Digite RESETAR para confirmar: " confirma
  [ "$confirma" = "RESETAR" ] || { err "Abortado."; exit 1; }
fi

# ------------------------------------------------------- 2. para a API local
if [ -f ".aso/run/api.pid" ]; then
  pid="$(cat .aso/run/api.pid 2>/dev/null || true)"
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    info "Parando a API local (PID $pid)…"; kill "$pid" 2>/dev/null; sleep 1
  fi
fi
rm -rf .aso/run && ok "Runtime local limpo (.aso/run)."

# ------------------------------------------------------- 3. worktrees órfãos
# `rm -rf` deixaria refs órfãs em .git/worktrees — sempre pela porta do git.
if [ -d ".aso/worktrees" ]; then
  info "Removendo worktrees registrados em .aso/worktrees…"
  git worktree list --porcelain 2>/dev/null | awk '/^worktree /{print $2}' | while read -r wt; do
    case "$wt" in
      "$ROOT/.aso/worktrees/"*) git worktree remove --force "$wt" 2>/dev/null \
        && ok "  removido: ${wt#"$ROOT"/}" || warn "  não removido: ${wt#"$ROOT"/}";;
    esac
  done
  git worktree prune
  rm -rf .aso/worktrees
fi
ok "Worktrees do repositório ASO limpos."

# ------------------------------------------------------- 4. banco
info "Derrubando o Postgres e apagando o volume…"
$COMPOSE down -v >/dev/null 2>&1 || true
ok "Volume do Postgres removido."

rm -f aso.db && ok "SQLite residual (aso.db) removido."

if [ "$APAGAR_EXECUTORES" = "1" ]; then
  rm -f .aso/executors.json
  ok "Catálogo de executores apagado — rode ./scripts/manager.sh seed para recriar os Codex."
fi

# ------------------------------------------------------- 5. sobe limpo
info "Subindo o Postgres novamente…"
$COMPOSE up -d postgres >/dev/null || { err "Falha ao subir o Postgres."; exit 1; }
for _ in $(seq 1 30); do
  CID="$($COMPOSE ps -q postgres)"
  [ -n "$CID" ] && docker exec "$CID" pg_isready -U aso >/dev/null 2>&1 && break
  sleep 1
done
ok "Postgres no ar."

info "Recriando o schema com Alembic…"
ASO_DATABASE_URL="${ASO_DATABASE_URL:-postgresql+psycopg://aso:aso@localhost:5432/aso}" \
  "$ROOT/.venv/bin/alembic" upgrade head || { err "Falha na migration."; exit 1; }
ok "Schema recriado (head)."

# ------------------------------------------------------- 6. o que sobrou para você
echo
ok "ASO zerado. Suba a API com: ./scripts/manager.sh iniciar"
if [ -n "$ALVOS" ]; then
  echo
  warn "Os repositórios-alvo abaixo NÃO foram tocados. Se quiser limpá-los, em cada um:"
  printf '    cd %s && git worktree prune\n' $ALVOS
  echo "    # e revise as branches do runtime antes de apagar (elas guardam trabalho real):"
  echo "    #   git branch --list --format '%(refname:short) %(committerdate:relative)'"
fi
