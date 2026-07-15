# Fluxo multi-repo do console

## Descrição

Permite administrar projetos e iniciar uma orquestração somente depois de pré-analisar o
workspace selecionado.

## Localização no código

`src/aso/api/static/macro.html`, `src/aso/api/static/nova.html` e a seção Kanban de
`src/aso/api/static/index.html`.

## Entrada

Token Bearer, projeto ativo, demanda, modo de execução, executor, esforço e comando real de
validação quando a execução é direta.

## Saída

Projeto criado/editado/arquivado/restaurado; ou orquestração persistida com workspace
copiado, documentação docs-first gerada e detalhe aberto para decisão do Autopilot.

## Dependências

Endpoints `/v1/projects`, `/v1/orchestrations`, `/v1/fs/analyze/stream`, `/analyze-folder`,
`/v1/executors` e endpoints de cards.

## Regras de negócio

Criar projeto não toca a pasta. Trocar projeto invalida a pré-análise. O console não inicia
Autopilot implicitamente e não oferece configuração de executor por card sem persistência.
Executores incompatíveis ficam desabilitados; o esforço vem das capacidades do modelo.
Comandos contínuos não são aceitos como quality gate.

## Fluxo resumido

Selecionar projeto → SSE somente leitura → informar demanda/configuração → criar
orquestração → executar docs-first governado → abrir detalhe → usuário aciona Autopilot.
Se a documentação falhar, o detalhe permite corrigir executor/gate e repetir apenas essa etapa.

## Possíveis erros

Projeto arquivado, path inacessível, pipeline sem LLM, validação ausente, falha do agente de
documentação ou autorização insuficiente. Se docs-first falhar, a orquestração é preservada
e o detalhe continua acessível.
