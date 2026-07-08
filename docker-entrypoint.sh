#!/usr/bin/env bash
# Entrypoint da API: aplica migrations e sobe o servidor.
set -euo pipefail

if [[ -n "${ASO_DATABASE_URL:-}" ]]; then
  echo "Aplicando migrations (alembic upgrade head)..."
  alembic upgrade head
else
  echo "ASO_DATABASE_URL não definida — usando persistência in-memory (não recomendado em produção)."
fi

exec uvicorn aso.api.app:app --host 0.0.0.0 --port 8000
