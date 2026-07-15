# Imagem da API do ASO Runtime (ADR-0004/0006).
FROM python:3.12-slim

WORKDIR /app

# Docs-first e agentes de código dependem de worktrees/commits também no runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# Dependências primeiro (cache de camada).
COPY pyproject.toml ./
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./

RUN pip install --no-cache-dir -e ".[postgres]"

# Migra o banco e sobe a API. ASO_DATABASE_URL deve apontar para o Postgres.
COPY docker-entrypoint.sh ./
RUN chmod +x docker-entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["./docker-entrypoint.sh"]
