# ADR-0064 — Contrato OpenAPI gerado do código

- **Status:** ACCEPTED
- **Fase:** F3/F5 (clareza — MEL-03, origem `feedback.md` §2 item 19)
- **Data:** 2026-09-15
- **Supersede parcialmente:** [ADR-0005](ADR-0005-data-consistency-and-api-versioning.md) no ponto
  "OpenAPI em `contracts/openapi.yaml`" (contrato-first manual)

## Contexto

`contracts/openapi.yaml` era mantido à mão e citado como "contrato de máquina", mas descrevia
19 paths contra ~200 rotas reais e incluía paths inexistentes (`/boards/{id}/cards`,
`/cards/{id}/move`). Um contrato que diverge do código em silêncio é pior que nenhum.

## Decisão

- O contrato de máquina é **gerado das rotas FastAPI**: `aso.api.openapi_export.gerar_openapi()`
  cria a app com serviço em memória e auth dev injetada e serializa `app.openapi()` com chaves
  ordenadas em `contracts/openapi.json` (`python scripts/export-openapi.py`).
- `tests/integration/test_openapi_contract.py` falha se o arquivo versionado divergir do gerado
  (com a instrução de regeneração) e garante que toda rota `/v1` está no schema; rotas `/ui/*`
  ficam fora (`include_in_schema=False`).
- O `openapi.yaml` manual foi removido. `/docs` e `/openapi.json` da API continuam sendo a
  visão ao vivo.

## Consequências

- Mudar/adicionar rota exige regenerar e versionar o contrato — a divergência aparece no CI.
- O "contrato-first" vira "código-first com contrato verificado": a revisão de contrato acontece
  no diff de `contracts/openapi.json`.
