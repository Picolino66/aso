# ADR-0073 — Esforço (effort) mapeado por tipo de executor

- **Status:** ACCEPTED
- **Fase:** F5 (inteligência — MEL-43, origem `feedback.md` §2 item 26, §4)
- **Data:** 2026-09-15
- **Atualiza:** [ADR-0022](ADR-0022-bateria-de-validacoes-e-effort-automatico.md) — matriz de
  suporte a esforço por executor
- **Relaciona-se com:** [ADR-0019](ADR-0019-roteamento-de-falha.md) (`aumentar_effort`),
  [ADR-0011](ADR-0011-descoberta-de-capacidades-cli.md) (Codex gerenciado),
  [ADR-0072](ADR-0072-respostas-estruturadas-json-schema.md) (saída estruturada)

## Contexto

O esforço é resolvido com cuidado (explícito → card → etapa → orquestração → sugestão da ficha →
perfil), mas só tinha efeito no Codex gerenciado (`-c model_reasoning_effort`). No Claude CLI ia no
JSON e o wrapper ignorava; os clientes de API não o recebiam. A sugestão automática e a ação
`aumentar_effort` do roteamento de falha pareciam funcionar sem mudar nada.

## Decisão

1. **Matriz de suporte** (`execution/effort.py::suporte_de_effort`), exposta no perfil
   (`suporta_effort`, `effort_como`):

   | Executor | Suporta | Como |
   |---|---|---|
   | Codex (`codex exec`, gerenciado ou não) | sim | `-c model_reasoning_effort=<nível>` |
   | Claude Code (`claude`) | sim | `--effort <nível>` — confirmado no `claude --help` 2.1.215 (`low…max`) |
   | API OpenAI, modelos de raciocínio (`o1`/`o3`/`o4`/`gpt-5…`) | sim | `reasoning_effort` |
   | API Anthropic, modelos com pensamento estendido | sim | `thinking.budget_tokens` por nível (2k/8k/24k) |
   | API OpenAI sem raciocínio, DeepSeek, mock, CLI sem mapeamento | não | registrado como não suportado |

2. **Aplicação:** `ExecutorCatalog.cli_command` acrescenta (ou substitui) a opção do CLI; os
   clientes de API recebem o esforço do perfil/etapa. Na Anthropic, pensamento estendido não vai
   junto com ferramenta forçada: quando a pergunta usa saída estruturada (ADR-0072), o schema vence
   e o esforço não é aplicado.
3. **Roteamento de falha:** `decidir` pula `aumentar_effort` quando o perfil conhecido não suporta
   esforço e segue a política (trocar executor). Executor fora do catálogo mantém a escada padrão.
4. **Registro:** `agent_runs.effort` (solicitado) e `agent_runs.effort_aplicado` (`true`/`false`,
   `null` sem esforço pedido).
5. **Console:** a escolha de esforço indica "sem efeito neste executor" quando não há suporte.
6. O `TaskEnvelope.effort` continua texto livre (Codex e Claude aceitam níveis além de
   `low|medium|high`); a tipagem que importa é a da matriz acima.

## Consequências

- Perfis Claude passam a receber `--effort` (o default do perfil é `medium`).
- Os padrões de modelo de raciocínio/pensamento são heurísticos por nome; modelo novo fora do
  padrão aparece como "sem suporte" até a regra ser atualizada.
- Parâmetros de API não foram exercitados contra os provedores reais (testes com HTTP simulado).
