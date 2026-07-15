# Catálogo multi-repo governado

## Descrição

Mantém uma identidade única por workspace e agrupa várias orquestrações sem possuir o
ciclo de vida delas. Remoção pública significa arquivamento.

## Localização no código

`src/aso/control/project_service.py`, `src/aso/persistence/ports.py`,
`src/aso/persistence/memory.py`, `src/aso/db/models.py`, `src/aso/db/repository.py` e
`migrations/versions/f84c2a1d9e30_projects_catalog.py`.

## Entrada

Nome, descrição, path do workspace e ator autenticado. Restauração pode receber novo path.

## Saída

`Project` persistido e `ProjectEvent` append-only; listagens ocultam arquivados por padrão.

## Dependências

`WorkspaceService` para validação/canonicalização, Pydantic, porta de persistência e
SQLAlchemy/Alembic no adapter relacional.

## Regras de negócio

Path obrigatório em projeto novo, absoluto/canônico e único inclusive quando arquivado.
Somente projeto ativo cria orquestração. Arquivar preserva todos os vínculos e históricos.

## Fluxo resumido

API autentica → `ProjectService` valida estado/path → repository grava projeto e evento na
mesma transação → consulta devolve o estado atualizado.

## Possíveis erros

`400` para nome/path inválido, `404` para ID ausente, `409` para path duplicado, edição de
arquivado ou workspace divergente, e `403` por papel insuficiente.
