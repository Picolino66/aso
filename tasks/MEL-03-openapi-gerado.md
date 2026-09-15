# MEL-03 — OpenAPI gerado a partir do FastAPI, verificado no CI

| Campo | Valor |
|---|---|
| Fase do roadmap | 1 — Clareza |
| Prioridade | P1 |
| Esforço | baixo |
| Status | Backlog |
| Depende de | — |
| Origem | [feedback.md](../feedback.md) §2 item 19 |
| Requer ADR | Sim, curta: o contrato passa a ser gerado do código (supersede o "contrato-first manual" da ADR-0005) |

## Problema

[contracts/openapi.yaml](../contracts/openapi.yaml) descreve 19 paths; a API tem 198 rotas, e
alguns paths do arquivo não existem (`/boards/{id}/cards`, `/cards/{id}/move`). O arquivo é
citado como "contrato de máquina".

## Mudança proposta

1. Script `scripts/export-openapi.py`: `create_app(OrchestrationService())` → `app.openapi()` →
   `contracts/openapi.json` (ou `.yaml`), ordenado e estável.
2. Teste `tests/integration/test_openapi_contract.py` que falha se o arquivo versionado
   divergir do gerado (com instrução de como regenerar).
3. Remover o `openapi.yaml` manual.
4. Rotas `/ui/*` fora do schema (já usam `include_in_schema=False`).

## Critérios de aceite

- [ ] Arquivo gerado contém todas as rotas `/v1/*`.
- [ ] Mudar uma rota sem regenerar faz o teste falhar.
- [ ] `docs/api.md` e `README.md` apontam para o arquivo gerado e para `/docs`.

## Arquivos prováveis

- `scripts/export-openapi.py` (novo), `contracts/`, `tests/integration/`, `docs/api.md`
