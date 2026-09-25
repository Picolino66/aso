# ADR-0077 — Índice estrutural do repositório por commit (e por que não embeddings)

- **Status:** ACCEPTED
- **Fase:** F5 (inteligência — MEL-44, origem `feedback.md` §4)
- **Data:** 2026-09-25
- **Relaciona-se com:** [ADR-0063](ADR-0063-contexto-da-tarefa.md) (contexto da tarefa),
  [ADR-0069](ADR-0069-leitura-do-repositorio-por-agentes-de-pergunta.md) (agentes de pergunta leem
  o repositório), [ADR-0020](ADR-0020-discovery-e-aprovacao.md) (discovery),
  [ADR-0017](ADR-0017-revisao-independente-de-codigo.md) (revisão independente),
  [ADR-0008](ADR-0008-workspace-por-orquestracao.md) (workspace por orquestração)

## Contexto

Discovery decidia "componentes afetados", a especificação listava "alterações de código" e a
revisão julgava "risco de regressão" sem **nenhum** fato estrutural do repositório: o
`WorkspaceAnalyzer` só enxergava diretórios de topo e a existência de `docs/`. A validação do
discovery (ADR-0069) aceitava qualquer caminho que existisse no disco — inclusive `.env` — e a
revisão recebia o diff sem saber quem chama o código alterado nem quais testes o cobrem.

Falta um mapa. A pergunta é de que tipo.

## Decisão

1. **Índice determinístico por `(repositório, commit)`** em `execution/code_index.py`, gerado da
   própria árvore de arquivos: linguagem e linhas por arquivo, símbolos públicos com linha, imports
   **já resolvidos para caminhos do repositório**, marcação de teste e pontos de entrada
   detectáveis (rotas HTTP e comandos).
   - **Python: `ast` da stdlib** (exato) — classes, funções (inclusive métodos, como
     `Classe.metodo`), constantes de módulo, `import`/`from ... import` com resolução de
     relativos e de raízes comuns
     (`src/`, `lib/`, `app/`), e rotas declaradas por decorador (`@router.get("/v1/...")`),
     inclusive dentro de fábricas como `criar_router`.
   - **TypeScript/JavaScript: expressões regulares conservadoras** (aproximado) — `export`s,
     `import ... from`/`require` relativos e rotas `app|router.get(...)`. O índice **declara** essa
     diferença em `precisao`, para nenhum consumidor tratar aproximação como fato exato.
   - Outras linguagens entram apenas no inventário (arquivo + linguagem): sem parser, inventar
     símbolos seria pior que não ter.
2. **Sem dependência nova.** `tree-sitter`/`ctags` (sugeridos na task) foram avaliados e recusados
   para esta entrega: exigiriam binário/roda nativa no container e no CI para ganhar precisão em
   linguagens que o ASO ainda não indexa a fundo. O `ast` cobre 100% do código do próprio runtime e
   dos projetos Python que ele opera hoje; TS/JS entra por regex, com a imprecisão declarada. Trocar
   o coletor depois não muda os consumidores: eles só usam `ArquivoIndexado` e as três consultas.
3. **Armazenamento fora do banco e fora do contexto:** `.aso/index/<commit>.json` no
   repositório-alvo (o `ensure_git` acrescenta `.aso/index/` ao `.gitignore`, como já fazia com
   `.aso/worktrees/`). Mesmo commit reaproveita o arquivo; schema diferente ou JSON corrompido
   recalcula. **Árvore suja não grava nem reaproveita** — um índice assim não descreve commit
   nenhum, e gravá-lo envenenaria o cache do commit. O que o runtime escreve em `.aso/` não conta
   como sujeira (senão gravar o índice sujaria a árvore e nada seria reaproveitado).
   Reaproveitamento adicional no processo por 60 s (`indice_para_uso`), para executar N cards não
   custar N reconstruções.
4. **Consultas pequenas**, que é a razão de o índice existir: `vizinhanca(arquivo)` (usa / usado por
   / testes), `testes_que_cobrem(arquivo)` (diretos primeiro, depois um nível indireto) e
   `quem_importa(modulo)`. `execution/impacto.py` reduz isso ao que cabe num prompt.
5. **Três usos, todos verificáveis:**
   - **Contexto do card** (ADR-0063): uma linha por arquivo citado — símbolos, entradas, quem usa,
     testes. Os "arquivos citados" são `linked_files` e os `componentes_afetados` do discovery
     **aprovado** (já validados contra o índice); sem arquivo citado, o índice nem é construído.
     Prioridade abaixo das ADRs e acima do ledger; o item respeita o orçamento como os demais.
   - **Discovery** (ADR-0020): o pedido leva um mapa compacto (módulos, pontos de entrada,
     números) e todo `componente_afetado` é conferido contra o índice — o que não existe lá é
     descartado e registrado em `componentes_descartados`. Isso é **mais estrito** que a checagem anterior por
     disco: `.env`, `node_modules`, caches e binários não estão no índice, logo não passam.
   - **Revisão** (ADR-0017): o pedido recebe "arquivos que importam os alterados" e "testes
     relacionados", derivados dos arquivos do diff. "Risco de regressão" deixa de ser adivinhação.
6. **Nunca indexar segredo nem lixo:** diretórios ignorados são os mesmos do workspace
   (`DIRETORIOS_IGNORADOS` — uma lista só, para o índice não divergir do scan), e por nome ficam
   fora `.env*`, `*secret*`, `*credential*`, `*password*`/`*senha*`, `id_rsa`, `*.pem|key|p12|crt`,
   binários conhecidos e qualquer arquivo acima de 1 MB.

### Por que não embeddings / banco vetorial

Os agentes CLI já leem o repositório em worktree de leitura (ADR-0069): recuperar trechos por
similaridade resolveria um problema que o ASO não tem. O que o runtime precisa é (a) orientar a
pergunta e (b) **verificar** a resposta — e verificação exige fato exato, não vizinhança semântica:
`componentes_afetados` só é aceito se o caminho existir no índice. Um índice vetorial ainda traria
dependência nativa, custo por token, reindexação por mudança e indeterminismo entre execuções (o
mesmo commit poderia validar respostas diferentes). Similaridade **de demandas** é outra coisa e
tem task própria (MEL-45); cache de discovery por commit é a MEL-57, que se apoia neste mesmo par
`(repositório, commit)`.

## Consequências

- **Medição no próprio repositório do ASO** (critério de aceite 1, teste
  `test_indice_do_proprio_aso_em_tempo_aceitavel`):
  642 arquivos indexados, 3.163 símbolos, 216 arquivos de teste, 206 pontos de entrada,
  **~1,0 s** de construção completa e ~388 KB de JSON. Reaproveitado, custa a leitura do arquivo.
- Discovery ficou mais estrito: caminho que o agente inventa (ou que aponta para arquivo ignorado)
  cai em `componentes_descartados` em vez de virar "componente afetado".
- A vizinhança no contexto consome orçamento (ADR-0063): entram no máximo 5 arquivos citados, e o
  item é omitido inteiro se não couber — como qualquer outro item.
- A aproximação de TS/JS pode perder símbolo ou import exótico (`export { a } from`, imports
  dinâmicos). O índice declara `precisao`, e o consumidor que precisar de exatidão em TS deve
  esperar um coletor com parser — não há promessa em contrário.
- `.aso/index/` cresce um arquivo por commit indexado; são artefatos derivados, ignorados pelo git
  e removíveis a qualquer momento (o próximo uso reconstrói). Limpeza automática por idade fica
  para a MEL-57, que passa a gerenciar cache por commit.
