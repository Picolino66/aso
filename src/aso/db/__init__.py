"""Driven adapter de persistência relacional (SQLAlchemy).

Adapter concreto da porta OrchestrationRepository. Usa SQLite em dev/testes e
PostgreSQL em produção (mesmos modelos; JSONB via variant) — ADR-0005/0006.
"""
