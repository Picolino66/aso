# Contrato do wrapper CLI (TaskEnvelope v1)

## Descrição
Contrato versionado entre o runtime e agentes CLI (ADR-0059). Distingue **execução**
(implementar card/documentação no worktree) de **pergunta** (responder JSON: naming,
triagem, discovery, especificação, revisão) e define como o prompt é montado.

## Localização no código
- `src/aso/agents/contract.py` — `TaskEnvelope`, `CardBrief`, `ler_envelope`, `ContratoInvalido`.
- `src/aso/agents/render_prompt.py` — renderizador só-stdlib chamado pelo wrapper.
- `scripts/aso-agent-wrapper.sh` — adaptador: stdin → prompt → `"$@" "$prompt"`.
- `src/aso/control/agent_ask.py` (`_rodar_cli`) e `OrchestrationService._build_task`,
  `_docs_task`, `_docs_heal_task` — produtores do envelope.
- `src/aso/execution/agent_stream.py` (`extrair_resposta_final`) — NDJSON → texto final.

## Entrada
JSON no stdin com o formato antigo (`content`, `kind`) e a chave `envelope`
(`schema_version: "1"`, `kind: execute|ask`, `task_type`, `system`, `request`, `card`,
`nudge`, `effort`, `validation_command`, `commit_subject`, `output_schema`, `phase`,
`target_path`). `nudge`/`effort` no topo da tarefa vencem os do envelope.

## Saída
Prompt em pt-BR como último argumento do agente. Perguntas: `system` completo + pedido +
"responda somente o JSON". Execução: card, critérios, correções, contexto adicional,
nudge, effort, assunto de commit e comando de aceite.

## Dependências
Nenhuma além de `python3` (biblioteca padrão) no ambiente do agente.

## Regras de negócio
- Versão desconhecida é recusada (exit 2), sem chamar o agente.
- Pergunta sem `system` é recusada ("schema ausente").
- Tarefa sem `envelope` é convertida do formato antigo (compatibilidade temporária).

## Fluxo resumido
Serviço → `perguntar_ao_agente`/`_build_task` → envelope → CLI (wrapper) →
`render_prompt.py` → agente → stdout (texto ou NDJSON) → `extrair_resposta_final` →
`parse_llm_json` → saneamento do serviço.

## Possíveis erros
- `aso-agent-wrapper: contrato inválido — …` (exit 2): versão ou campos fora do contrato.
- `LlmError: Resposta do LLM não é JSON` no `fallback_reason`: o agente não respondeu JSON.
