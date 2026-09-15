# MEL-14 — Contrato do wrapper CLI: perguntas × execução

| Campo | Valor |
|---|---|
| Fase do roadmap | 2 — Correção |
| Prioridade | **P0** |
| Esforço | médio |
| Status | Backlog |
| Depende de | — |
| Origem | [feedback.md](../feedback.md) §4 (contrato frágil com CLI), §2 item 27 |
| Requer ADR | Sim: contrato `TaskEnvelope` versionado entre runtime e agentes CLI (referencia ADR-0014, ADR-0017, ADR-0045) |

## Problema

Existem dois tipos de chamada a agente CLI e um único wrapper que só entende um deles:

1. **Execução de card** (`CliAgentExecutionProvider`): JSON da tarefa no stdin → wrapper monta prompt de implementação.
2. **Pergunta** (`perguntar_ao_agente`, [agent_ask.py:58](../src/aso/control/agent_ask.py#L58)): usado por naming, triagem, discovery, especificação e revisão; envia `{"kind", "content": {"request", "system"}}`.

Defeitos em [aso-agent-wrapper.sh](../scripts/aso-agent-wrapper.sh):

- Só `kind == "naming"` é tratado como pergunta (linha 32). Para `triagem`, `discovery`,
  `especificacao` e `revisao`, o `system` — que contém o schema JSON — é **descartado** e
  o agente recebe "Implemente/produza o necessário NESTE diretório…" [F].
- `contexto_adicional` (ADR-0048), `nudge` (supervisor) e `effort` vão no JSON, mas não
  entram no prompt [F].
- Com `--output-format stream-json` (necessário para custo, ADR-0026), o stdout vira
  NDJSON e `parse_llm_json` não consegue interpretar a resposta das perguntas [H].
- O wrapper não tem nenhum teste.

Consequência provável: com perfis CLI via wrapper (inclusive os Codex gerenciados), os
agentes de triagem, discovery, spec e revisão caem silenciosamente em heurística ou
`necessita_humano` [H].

## Mudança proposta

1. **Contrato versionado** em `src/aso/agents/contract.py` (Pydantic):
   - `TaskEnvelope`: `schema_version`, `kind` (`execute` | `ask`), `task_type`
     (`card`, `naming`, `triagem`, `discovery`, `especificacao`, `revisao`, `docs`),
     `system`, `request`, `card` (título, descrição, critérios, correções, contexto
     adicional), `nudge`, `effort`, `validation_command`, `commit_subject`, `output_schema`.
   - Construído por `_build_task` e por `perguntar_ao_agente`.
2. **Wrapper**:
   - `kind == "ask"`: prompt = `system` + `request` + instrução "responda somente o JSON";
     sem instrução de implementar.
   - `kind == "execute"`: incluir `contexto_adicional`, `nudge` e correções.
   - Mover a lógica de montagem de prompt para Python (`python -m aso.agents.render_prompt`)
     para ser testável; o `.sh` vira um adaptador de poucas linhas.
3. **Streaming × JSON**: `_rodar_cli` extrai o texto final do NDJSON com
   `agent_stream.extrair_texto` antes do `parse_llm_json`, **ou** o perfil ganha um
   `command_ask` sem flags de streaming. Decidir na ADR; testar os dois formatos.
4. Registrar no evento de fallback o motivo real ("resposta não é JSON", "schema ausente").

## Fora de escopo

- Structured outputs nativos das APIs de LLM (MEL-42).
- Mapeamento de effort por provider (MEL-43) — aqui só se repassa o valor.

## Critérios de aceite

- [ ] Para cada `task_type` de pergunta, o prompt renderizado contém o `system` completo e não contém instrução de implementar.
- [ ] Para execução, o prompt contém critérios, correções, `contexto_adicional` e `nudge` quando presentes.
- [ ] Uma resposta NDJSON de Claude `stream-json` com o JSON final é interpretada corretamente por `perguntar_ao_agente`.
- [ ] Um agente CLI fake que só responde corretamente quando recebe o schema produz ficha de triagem com `origem` = executor (não "heuristica").
- [ ] Envelope com `schema_version` desconhecida é recusado com erro claro.

## Testes obrigatórios

- Unit do renderizador de prompt: tabela de casos por `task_type`.
- Integração com CLI fake (script em `tmp_path`) executando o wrapper real: triagem, revisão, naming e execução.
- Unit de parse NDJSON (fixture de saída `stream-json`).

## Arquivos prováveis

- `scripts/aso-agent-wrapper.sh`
- `src/aso/agents/contract.py` (novo), `src/aso/agents/render_prompt.py` (novo)
- `src/aso/control/agent_ask.py`, `src/aso/control/orchestration_service.py` (`_build_task`)
- `src/aso/execution/cli_provider.py`, `src/aso/execution/agent_stream.py`
- `docs/modules/executores/`, ADR nova

## Riscos

- Perfis de executor já salvos em `.aso/executors.json` apontam para o wrapper atual: manter compatibilidade com o formato antigo do stdin durante uma versão.
