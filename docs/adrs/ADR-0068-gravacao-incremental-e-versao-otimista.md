# ADR-0068 — Gravação incremental, versão otimista e cache de agregados com descarte

- **Status:** ACCEPTED
- **Fase:** F5 (robustez — MEL-33, origem `feedback.md` §3, §13.3 problema 7)
- **Data:** 2026-09-15
- **Supersede (em parte):** o **modelo de gravação** de
  [ADR-0006](ADR-0006-persistence-repository-adapters.md) (apagar filhos e reinserir o agregado a
  cada `save`); portas, adapters e normalização da ADR-0006 continuam valendo
- **Relaciona-se com:** [ADR-0066](ADR-0066-camada-de-aplicacao.md) (`BundleStore`),
  [ADR-0067](ADR-0067-execucao-assincrona-com-fila.md) (jobs em workers)

## Contexto

`SqlAlchemyOrchestrationRepository.save` apagava todas as tabelas filhas da orquestração e
reinseria tudo — eventos, patches, histórico do contexto, card events — a cada `_persist`. O custo
crescia com o histórico e o log "append-only" era regravado. O cache de bundles nunca descartava
entradas. Locks eram só do processo: API e CLI sobre o mesmo banco sobrescreviam uma à outra
(última gravação vencia). E o boot chamava `create_all` além do Alembic.

## Decisão

1. **Gravação incremental** (`db/gravacao.py`): o estado vira unidades comparadas por impressão
   (hash do conteúdo) com o que foi gravado na versão lida.
   - *entidade* (linha com PK: card, PR, aprovação, gate…) alterada → `UPDATE` (merge);
   - *grupo* de junção de um dono (links de card/ADR, critérios de gate, `value_items`…) alterado
     → apaga e reinsere **só aquele grupo**;
   - *sequência* (`events`, `context_history`) → insere só a cauda; se o prefixo divergiu,
     remove apenas o sufixo gravado.
   Remoções vão das folhas para os pais e inserções dos pais para as folhas (FK-safe no
   Postgres). As impressões ficam no repositório por orquestração+versão, montadas no `load` e no
   `save`; sem cache compatível, são recalculadas do banco.
2. **Versão otimista:** `orchestrations.versao`; cada gravação faz
   `UPDATE … WHERE id = :id AND versao = :esperada`. Zero linhas → `ConcurrentModificationError`
   (nada é escrito). O `BundleStore` descarta o bundle velho do cache; a API responde 409 e o job
   assíncrono registra `erro_status = 409`. O adapter em memória aplica a mesma regra.
3. **Ordem das coleções:** coluna `posicao` em cards, card events, snapshots, conflitos, gates,
   aprovações, patches, PRs, comentários, corridas, incidentes, bugs e amostras de SLO. Com
   `UPDATE` no lugar, o Postgres não preserva a ordem física; a leitura ordena por `posicao`.
   Linhas antigas ficam com 0 e caem no desempate anterior até a próxima gravação.
4. **Cache com descarte:** `CacheDeBundles` (LRU, `ASO_BUNDLE_CACHE_MAX`, padrão 128) não
   descarta o recém-inserido nem bundle com lock ocupado (evita duas instâncias vivas da mesma
   orquestração). **Sonda de versão** no `get`: no máximo uma consulta por orquestração a cada
   `ASO_BUNDLE_VERIFICACAO_S` (padrão 1 s; negativo desliga), só com o lock livre — nunca troca o
   bundle no meio de uma operação desta instância.
5. **Schema só por migrations:** `bootstrap` cria os repositórios com `create_schema=False`;
   `create_all` fica para os testes.

### Alternativas descartadas

- **Rastrear "persistido até" dentro do agregado** (contadores por coleção nos serviços de
  domínio): espalharia detalhe de persistência pelo domínio e não cobre mutações no meio das
  listas (status de patch, resolução de conflito). A comparação por impressão fica toda no adapter.
- **`SELECT … FOR UPDATE` do agregado a cada operação:** serializaria processos, mas seguraria
  linha durante execuções de agente de minutos; a versão otimista só custa na gravação.
- **Invalidar o cache a cada leitura** (sem sonda com intervalo): uma consulta por `_bundle`, que é
  chamado dezenas de vezes por operação.

## Consequências

- Gravar um evento ou uma aprovação insere só essas linhas (teste conta `INSERT`/`DELETE`);
  reler numa instância nova e gravar sem mudança escreve apenas a versão.
- Dois processos sobre o mesmo banco não perdem dados: o segundo recebe conflito e recarrega.
  Continua valendo **processo único por banco** para execução (claims e fila da ADR-0067 são do
  processo); múltiplas réplicas são a MEL-56.
- A CLI e a API exigem `alembic upgrade head` antes do boot (o entrypoint do Docker e o
  `scripts/manager.sh` já fazem).
- Testes de persistência rodam em SQLite e, com `ASO_TEST_POSTGRES_URL`, no Postgres.
