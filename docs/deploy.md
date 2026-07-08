# Deploy & Rollback — ASO Runtime

> Fase F6. Deploy automático em produção está **fora do escopo do MVP** (§7); este documento
> define o **plano** e os procedimentos manuais/containerizados validados.

## Artefato

Imagem Docker da API ([Dockerfile](../Dockerfile)) — o entrypoint aplica `alembic upgrade head`
e sobe `uvicorn aso.api.app:app`.

```bash
docker build -t aso-runtime:0.1.0 .
docker run -e ASO_DATABASE_URL="postgresql+psycopg://user:pass@host:5432/aso" -p 8000:8000 aso-runtime:0.1.0
```

## Imagem versionada no registry (GHCR)

O workflow [`.github/workflows/release.yml`](../.github/workflows/release.yml) publica a imagem
no GitHub Container Registry ao criar uma tag `vX.Y.Z`:

```bash
git tag v0.1.0 && git push origin v0.1.0
# → ghcr.io/<owner>/<repo>:0.1.0
docker run -e ASO_DATABASE_URL=... -e ASO_API_KEYS=... -p 8000:8000 ghcr.io/<owner>/<repo>:0.1.0
```

## Plano de deploy

1. CI verde na branch principal (ruff, mypy, testes≥80%, alembic check, bandit, pip-audit).
2. Build e publicação da imagem versionada (`aso-runtime:<versão>`).
3. **Backup do banco** antes de migrar.
4. `alembic upgrade head` (idempotente; aplicado no start do container).
5. Subir a nova versão; validar smoke test (`GET /v1/orchestrations` responde 200).
6. Monitorar timeline/eventos e taxa de erro.

## Plano de rollback

| Situação | Ação |
|---|---|
| App com defeito, schema compatível | Reimplantar a imagem anterior (`aso-runtime:<versão-anterior>`) |
| Migration problemática | `alembic downgrade -1` (ou até a revisão estável) + reimplantar versão anterior |
| Estado de orquestração inconsistente | Restaurar snapshot estável (SnapshotEngine) + ADR de rollback (protocolo de contexto) |
| Corrupção de dados | Restaurar backup do banco anterior ao deploy |

## Smoke test pós-deploy

```bash
curl -fsS http://localhost:8000/v1/orchestrations | head -c 200
curl -fsS -X POST http://localhost:8000/v1/orchestrations \
  -H 'content-type: application/json' -d '{"user_request":"smoke"}'
```

## Pré-requisitos de segurança (§34)

- Secrets apenas via variáveis de ambiente (nunca no repositório/imagem).
- Aprovação humana para deploy e alteração de secrets (HumanApprovalEngine — evolui no MVP-2).
