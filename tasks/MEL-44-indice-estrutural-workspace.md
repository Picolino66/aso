# MEL-44 — Índice estrutural do workspace por commit

| Campo | Valor |
|---|---|
| Fase do roadmap | 4 — Inteligência |
| Prioridade | P2 |
| Esforço | alto |
| Status | Backlog |
| Depende de | MEL-19 |
| Origem | [feedback.md](../feedback.md) §4 (AST, índice de símbolos, grafo de dependências) |
| Requer ADR | Sim: índice estrutural determinístico (e por que não embeddings/banco vetorial) |

## Problema

Discovery ("componentes afetados"), especificação e revisão ("risco de regressão") decidem
sem nenhum fato estrutural do código. `WorkspaceAnalyzer` só detecta diretórios de topo e a
presença de docs. `docs_drift` também opera por diretório.

Não há necessidade de RAG vetorial: os agentes CLI já leem código (MEL-40). O que falta é
um mapa **barato e determinístico** para orientar e verificar as respostas.

## Mudança proposta

1. `execution/code_index.py`: gera um índice por `(repositório, commit)` com:
   - árvore de módulos e linguagem por arquivo;
   - símbolos públicos (classes, funções) com arquivo e linha — via `tree-sitter` ou `ctags` (avaliar na ADR);
   - grafo de imports para Python e TypeScript/JavaScript;
   - arquivos de teste e o que importam;
   - pontos de entrada (rotas HTTP, CLIs) quando detectáveis.
2. Armazenamento em arquivo JSON dentro de `.aso/index/<commit>.json` do repositório-alvo
   (fora do banco e do `OrchestratorContext`); só caminho e hash entram no ledger.
3. Consultas pequenas: `vizinhanca(arquivo)`, `testes_que_cobrem(arquivo)`, `quem_importa(modulo)`.
4. Uso:
   - `ContextBuilder` (MEL-19) inclui a vizinhança dos arquivos citados no card;
   - Discovery valida `componentes_afetados` contra o índice;
   - Revisão recebe "arquivos que importam os alterados" e "testes relacionados".
5. Nunca indexar `.env`, segredos, `node_modules`, `.venv`, binários.

## Critérios de aceite

- [ ] Índice gerado para o próprio repositório do ASO em tempo aceitável (medir e registrar na ADR).
- [ ] Mesmo commit reaproveita o índice sem recalcular.
- [ ] Revisão de um diff recebe a lista de módulos dependentes e testes relacionados.
- [ ] Teste garante que arquivos ignorados e padrões de segredo não entram no índice.
