# ADR-0059 — Contrato `TaskEnvelope` versionado entre runtime e agentes CLI

- **Status:** ACCEPTED
- **Fase:** F5 (correção de integração — MEL-14, origem `feedback.md` §4 e §2 item 27)
- **Data:** 2026-09-15
- **Relaciona-se com:** [ADR-0014](ADR-0014-agente-por-etapa-e-nomes-semanticos.md) (naming
  por agente, primeira pergunta via wrapper), [ADR-0017](ADR-0017-revisao-independente-de-codigo.md)
  (revisão por agente), [ADR-0045](ADR-0045-discovery-tecnico-e-aprovacao.md) (discovery por
  agente), [ADR-0015](ADR-0015-observabilidade-ao-vivo-da-execucao.md) (NDJSON dos agentes),
  ADR-0026 (custo via `stream-json`), [ADR-0048](ADR-0048-execucao-quality-gates-e-falhas.md)
  (`contexto_adicional`, controles em voo)

## Contexto

O runtime chama agentes CLI de dois jeitos: **execução** (implementar um card ou
documentação no worktree) e **pergunta** (`perguntar_ao_agente`: naming, triagem,
discovery, especificação, revisão de código e documental — resposta JSON). Um único
wrapper (`scripts/aso-agent-wrapper.sh`) montava o prompt, mas:

- só `kind == "naming"` era tratado como pergunta; para as demais o `system` — que traz o
  schema JSON — era descartado e o agente recebia "Implemente o necessário…";
- `contexto_adicional`, `nudge` (retry do supervisor) e `effort` iam no JSON e não
  entravam no prompt;
- com `--output-format stream-json` (necessário para custo) o stdout vira NDJSON e
  `parse_llm_json` não achava a resposta;
- a montagem do prompt vivia num heredoc Python dentro do `.sh`, sem teste.

Resultado provável: com perfis CLI via wrapper, triagem, discovery, spec e revisão caíam
silenciosamente em heurística ou `necessita_humano`.

## Opções consideradas

- **Remendar o heredoc** para mais `kind`s. Continua implícito, sem versão e sem teste.
- **Perfil com `command_ask`** separado (sem flags de streaming) para perguntas. Duplica a
  configuração de cada executor e perde custo/uso das perguntas.
- **Envelope versionado + renderizador testável + extração do texto final do NDJSON.**
  Adotada.

## Decisão

1. **Contrato** em `src/aso/agents/contract.py`: `TaskEnvelope` v1 (`schema_version`,
   `kind` = `execute`|`ask`, `task_type`, `system`, `request`, `card` (`CardBrief`:
   título, tipo, descrição, critérios, correções, contexto adicional), `nudge`, `effort`,
   `validation_command`, `commit_subject`, `output_schema`, `phase`, `target_path`).
   `ler_envelope` recusa versão desconhecida, pergunta sem `system` ("schema ausente") e
   execução com `task_type` fora de `card|docs` (`ContratoInvalido`). O `task_type` de
   pergunta é rótulo livre do serviço (ex.: `revisao_documental`).
2. **Compatibilidade:** o dicionário da tarefa mantém o formato antigo (`content`, `kind`)
   e ganha a chave `envelope`. `_build_task`, `_docs_task`, `_docs_heal_task` e
   `agent_ask._rodar_cli` a preenchem. Wrappers antigos continuam funcionando; o novo
   converte tarefas sem envelope (pergunta = `kind` + `content.system`).
3. **Renderizador** `src/aso/agents/render_prompt.py`, **só biblioteca padrão** (roda com o
   `python3` do ambiente do agente, fora da venv). `ask` → `system` completo + `request`
   + (schema) + instrução "responda somente o JSON, não altere arquivos"; `execute` →
   card, critérios, correções, contexto adicional, `nudge`, effort, assunto de commit e
   comando de aceite. `nudge`/`effort` do topo da tarefa (injetados pelo supervisor depois
   do envelope) vencem. Versão desconhecida → exit 2 com mensagem pt-BR e o agente não é
   chamado. O `.sh` virou um adaptador de poucas linhas.
4. **Streaming × JSON:** `_rodar_cli` extrai a resposta final com
   `agent_stream.extrair_resposta_final` (último envelope `result` do Claude; senão última
   fala de `assistant`/Codex; senão saída crua) antes de `parse_llm_json`. Não se cria
   `command_ask`.
5. O motivo real da falha continua no `fallback_reason` dos serviços (`Tipo: mensagem`),
   agora com a mensagem do contrato ou do JSON extraído.

## Consequências

- Perguntas via CLI passam a funcionar com perfis `stream-json` (inclusive os Codex
  gerenciados) — a origem da ficha/veredito é o executor, não a heurística.
- Mudança de campo do envelope exige subir `SCHEMA_VERSION` nos dois lados; um teste
  garante que `contract.SCHEMA_VERSION == render_prompt.SCHEMA_VERSION`.
- O formato antigo do stdin deve ser removido numa versão futura (depois que
  `.aso/executors.json` e cópias do wrapper fora do repositório forem atualizados).
- Structured outputs nativos (MEL-42) e mapeamento de effort por provider (MEL-43) usam
  `output_schema`/`effort` deste envelope.
