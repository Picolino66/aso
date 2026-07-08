"""Persistência — portas de repositório e estado serializável das orquestrações.

Segue o padrão Ports & Adapters (ADR-0001): a aplicação depende da porta
`OrchestrationRepository`; os adapters concretos (in-memory, SQLAlchemy) vivem
na borda. Ver ADR-0006.
"""
