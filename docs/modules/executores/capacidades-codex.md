# Descoberta e sincronização do Codex

## Descrição

Mantém o catálogo Codex compatível com o binário, autenticação e rollout efetivos.

## Localização no código

`src/aso/execution/codex_discovery.py`, `catalog.py` e o serviço de orquestração.

## Entrada

`ASO_CODEX_BIN`, autenticação local do Codex e chamada administrativa de sincronização.

## Saída

Perfil `codex-default` e um perfil por modelo anunciado, com versão e esforços suportados.

## Dependências

Codex CLI com App Server, wrapper de agentes e armazenamento JSON de executores.

## Regras de negócio

A descoberta não executa prompt. Perfis personalizados são preservados. Modelo ou esforço
incompatível falha antes do worktree, sem fallback silencioso.

## Fluxo resumido

Inicializar App Server → paginar `model/list` → substituir perfis gerenciados → validar
seleção → executar no workspace isolado.

## Possíveis erros

Binário ausente, timeout, protocolo incompatível, autenticação sem modelos, perfil legado,
modelo removido ou esforço não suportado.
