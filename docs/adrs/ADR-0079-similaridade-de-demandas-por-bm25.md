# ADR-0079 — Demandas parecidas por BM25 em processo (e por que não `tsvector`/FTS5 nem embeddings)

- **Status:** ACCEPTED
- **Fase:** F5 (inteligência — MEL-45, origem `feedback.md` §4)
- **Data:** 2026-09-25
- **Relaciona-se com:** [ADR-0052](ADR-0052-metricas-e-aprendizado.md) (relatório de aprendizado),
  [ADR-0044](ADR-0044-classificacao-editavel-e-recomendacao.md) (painel de recomendação),
  [ADR-0026](ADR-0026-custo-real-e-orcamento.md) (custo real: ausente ≠ zero),
  [ADR-0077](ADR-0077-indice-estrutural-por-commit.md) (mesma escolha: fato determinístico em vez
  de vizinhança semântica)

## Contexto

O relatório de aprendizado agrega por faixas de complexidade e risco; o painel de recomendação
decide por regra de roteamento ou heurística. Nenhum dos dois responde a pergunta que o operador
faz antes de aprovar uma estratégia: **demandas parecidas com esta falharam onde, com qual executor
e a que custo?** A informação existe (texto da demanda, ficha, executor por card, tentativas, custo,
veredito de review, diagnóstico de falha), mas não havia como chegar nela partindo do texto.

A MEL-45 propunha índice full-text do banco (`tsvector` no Postgres, FTS5 no SQLite) e, se
insuficiente, embeddings.

## Decisão

1. **Ranqueamento por BM25 (Okapi, k1=1.5, b=0.75) em processo**, em `control/similaridade.py`:
   função pura que recebe as demandas já lidas e devolve as mais parecidas com a consulta, com a
   pontuação e os termos em comum. O coletor é uma consulta enxuta
   (`textos_de_demandas`) que lê **só** as colunas de texto de uma janela de demandas recentes
   (`LIMITE_DE_CANDIDATAS = 500`), no mesmo espírito da MEL-52 (nada de hidratar agregado).
   - **Por que não `tsvector`/FTS5:** exigiriam schema, migração e sintaxe de consulta **diferentes
     por banco** — o teste rodaria contra um mecanismo (FTS5) e a produção contra outro
     (`tsvector`), exatamente o risco que o projeto evita validando no Postgres. Com BM25 puro, a
     mesma fórmula roda nos três adapters (memória, SQLite, Postgres) e o teste afirma a **ordem**,
     não "veio algo".
   - **Por que não embeddings:** a task pede busca textual primeiro; e recomendação precisa de
     **evidência citável** ("estas duas demandas, com estes ids"), não de vizinhança semântica sem
     fonte. Embeddings ainda trariam dependência nativa, custo por token e indeterminismo entre
     execuções — a mesma decisão da ADR-0077.
   - **Quando trocar:** se a janela de 500 apertar, o coletor vira um índice do banco sem mexer em
     quem chama (a interface é `ranquear(...)`). A medição que justificaria a troca é o tempo do
     ranqueamento, hoje irrelevante no volume de dev.
2. **O texto comparado é conteúdo, não rótulo:** pedido + `objetivo`, `problema`,
   `resultado_esperado`, `modulos_afetados`, `sistemas_afetados`, `criterios_de_aceite` e `riscos`
   da ficha. `tipo`, `risco`, `complexidade` e `dominios` ficam **fora**: são vocabulário fechado,
   aparecem em toda demanda e empurrariam o ranqueamento a ordenar por rótulo, não por assunto —
   medido na validação no Docker, onde `dominios` colocava "backend" entre os termos em comum de
   demandas sem relação.
3. **Desfecho só das vencedoras** (duas fases): ranqueia a janela pelo texto e, para as N
   escolhidas, lê o desfecho por `amostras_de_aprendizado` (MEL-52) — executor mais usado,
   tentativas por card, custo, último veredito de review e diagnósticos de falha recorrentes.
4. **Recomendação sempre com fonte.** Cada frase (`executor`, `falha`, `custo`, `tentativas`) traz
   os ids das demandas de onde o número veio, e o console linka cada uma. Abaixo de
   `MINIMO_DE_HISTORICO = 2` demandas **com execução registrada**, a resposta é explícita
   ("histórico insuficiente para recomendar") e `recomendacoes` volta vazia: uma demanda parecida é
   coincidência, não padrão.
5. **Custo ausente é `None`, nunca zero** (ADR-0026): "ninguém informou" e "custou zero" são
   afirmações diferentes, e o painel mostra "não informado".
6. **Só leitura.** `GET /v1/orchestrations/{id}/similar-demands` (com `limite` e `do_projeto`) não
   grava nada e não altera decisão nenhuma automaticamente — é insumo para o humano, como o
   relatório de aprendizado (ADR-0052).

### Alternativas descartadas

- **`tsvector` com coluna gerada + GIN:** melhor em escala, mas divergiria do caminho testado em
  SQLite e exigiria migração por banco; sem volume que justifique, é complexidade adiantada.
- **Similaridade por rótulos (tipo/risco/complexidade/domínios):** é o que o relatório de
  aprendizado já faz por faixas; não responde "parecida com **esta**".
- **Reaproveitar `control/search.py`:** é substring no título, sem ranking — serve à caixa de busca
  do header, não a "quais demandas ensinam algo sobre esta".
- **Recomendar com uma única demanda parecida:** foi recusado de propósito; o limiar de duas é o
  que separa padrão de coincidência.

## Consequências

- O painel de recomendação (aba Recomendação da demanda) passa a mostrar demandas parecidas com
  executor, tentativas, custo, review e falhas — cada linha clicável para a demanda de origem.
- `limite` é a janela de evidência: pedir uma só demanda devolve os dados mas **nenhuma**
  recomendação (o histórico visível fica abaixo do mínimo). Documentado e testado.
- O ranqueamento é determinístico: mesma entrada, mesma ordem — empate resolvido pela demanda mais
  recente, para a lista não oscilar entre chamadas.
- Falso positivo é possível quando duas demandas compartilham vocabulário sem compartilhar
  problema; por isso a saída mostra **termos em comum** e o score, em vez de afirmar "é igual".
- O tokenizador é pt-BR (paradas + jargão do runtime). Demanda escrita em outro idioma ranqueia
  pior — limitação declarada, não corrigida com tradução automática.
