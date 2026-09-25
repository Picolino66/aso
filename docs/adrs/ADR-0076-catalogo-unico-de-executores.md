# ADR-0076 — Catálogo único de executores (e flags como campo do perfil)

- **Status:** ACCEPTED
- **Fase:** F5 (limpeza — MEL-54, origem `feedback.md` §1, §5, §7)
- **Data:** 2026-09-24
- **Atualiza:** [ADR-0007](ADR-0007-llm-provider-and-autopilot.md) (o cliente LLM do
  planejamento e o roteamento por fase saem do ambiente),
  [ADR-0011](ADR-0011-descoberta-de-capacidades-cli.md) e
  [ADR-0014](ADR-0014-agente-por-etapa-e-nomes-semanticos.md) (o catálogo de executores passa a ser
  a **única** fonte em tempo de execução, e a escolha por etapa é a única roteadora)
- **Relaciona-se com:** [ADR-0015](ADR-0015-observabilidade-ao-vivo-da-execucao.md) (NDJSON do
  painel ao vivo),
  [ADR-0019](ADR-0019-roteamento-de-falha.md) (diff vazio por falta de permissão),
  [ADR-0069](ADR-0069-leitura-do-repositorio-por-agentes-de-pergunta.md) (pergunta somente
  leitura),
  [ADR-0073](ADR-0073-effort-mapeado-por-executor.md) (esforço por executor)

## Contexto

Um executor podia ser configurado em cinco lugares com precedências diferentes:
`ASO_CLI_COMMAND` + `ASO_TARGET_REPO` (provider global do bootstrap), `ASO_LLM_*` (provider global
e o cliente de planejamento montado em `app.py`), `ASO_EXECUTORS` (seed do catálogo),
`.aso/executors.json` (catálogo salvo pela tela ⚙ Config) e `ASO_CANDIDATE_COMMANDS` (candidatos da
corrida, fora do catálogo). Responder "qual agente roda este card?" exigia ler bootstrap, `app.py`,
catálogo, arquivo e ambiente — e o `RoutingExecutionProvider` (planner F1–F4 / coder F5–F6)
duplicava, por fase, a escolha que `agent_assignments` já fazia por etapa.

Pior: ligar o NDJSON do painel ao vivo ou dar permissão de escrita ao agente era feito por dois
scripts (`enable-agent-stream.sh`, `fix-executor-permissions.sh`) que **editavam a string do
comando** por substituição de texto. O perfil não dizia o que estava ligado, a UI não tinha como
mostrar, e a flag de autonomia total (`--dangerously-skip-permissions`) entrava em conflito com o
modo somente leitura das perguntas (ADR-0069), que só forçava `--permission-mode plan`.

## Decisão

1. **O catálogo é a única fonte em tempo de execução.** `ASO_EXECUTORS`, `ASO_CLI_COMMAND`,
   `ASO_LLM_*` e `ASO_CANDIDATE_COMMANDS` são lidos **apenas** em
   `execution/catalog.py::build_catalog_from_env`, que semeia o catálogo enquanto não existe
   arquivo salvo (`ASO_EXECUTORS_FILE`, default `.aso/executors.json`). Um teste varre `src/aso`
   por AST e falha se alguém voltar a ler essas variáveis fora do seed.
2. **Sem provider global.** O bootstrap não monta mais provider nenhum e o
   `RoutingExecutionProvider` foi removido. A escolha por etapa é `agent_assignments` → padrão da
   orquestração → padrão do catálogo (ADR-0014). Orquestração sem pasta própria usa o padrão do
   catálogo quando ele roda sem pasta (LLM, mock, ou CLI com `ASO_TARGET_REPO`); senão, mock.
3. **Planejamento pelo catálogo.** Nova etapa `planejamento` em `agent_assignments`; sem
   atribuição, vale o LLM padrão (primeiro perfil LLM **com chave no ambiente**, o `is_default`
   primeiro). A etapa só aceita executor `kind == "llm"`. Injeção de `llm_client` em `create_app`
   continua, para os testes.
4. **Corrida de candidatos com perfis do catálogo.** `POST …/cards/{id}/race` aceita
   `{"executores": [...]}`; sem lista, competem os perfis marcados `candidato`. Só `kind == "cli"`:
   a corrida compara diffs de worktree. Nome inválido, perfil indisponível ou não-CLI → 409.
5. **Flags por campo, não por edição de string.** O perfil ganha `streaming: bool` e
   `permissao_escrita: "" | nenhuma | edicoes | total`; `execution/flags_de_cli.py` monta as flags
   por família de CLI na hora de executar:

   | Campo | Claude Code | Codex |
   |---|---|---|
   | `streaming` | `--output-format stream-json --verbose` | `--json` |
   | `nenhuma` | `--permission-mode plan` | `--sandbox read-only` |
   | `edicoes` | `--permission-mode acceptEdits` | `--sandbox workspace-write` |
   | `total` | `--dangerously-skip-permissions` | `--sandbox danger-full-access` |

   Vazio = não gerenciado (o comando decide), o que preserva comandos personalizados e famílias
   desconhecidas. Perfis Codex gerenciados nascem com `permissao_escrita="edicoes"` (o
   `--sandbox workspace-write` saiu do comando base) e `replace_managed_codex` preserva
   `streaming`/`permissao_escrita`/`candidato` escolhidos pelo operador.
6. **Migração automática e idempotente.** Validar um perfil separa as flags conhecidas do comando e
   liga os campos equivalentes — vale para `.aso/executors.json` antigo, para `ASO_EXECUTORS` e
   para o que o operador digitar no formulário. Na leitura, o store regrava o arquivo migrado e
   guarda o original em `.aso/executors.json.antes-adr-0076`. Valor sem campo equivalente (ex.:
   `--permission-mode auto`) fica no comando: removê-lo mudaria o comportamento. Os dois scripts
   foram apagados.
7. **Somente leitura vence permissão total.** `comando_somente_leitura` (ADR-0069) passa a
   remover `--dangerously-skip-permissions` e `--dangerously-bypass-approvals-and-sandbox` antes de
   forçar `plan`/`read-only` — antes, um perfil com escrita total deixava a pergunta com duas
   permissões contraditórias no mesmo comando.
8. **Chave do LLM só pelo nome da variável.** A reserva global `ASO_LLM_API_KEY` saiu do runtime
   (`llm_client`/`public`): cada perfil aponta para a env var da sua chave. Perfil LLM antigo sem
   `api_key_env` é migrado para `ASO_LLM_API_KEY`, a menos que `ASO_<NOME>_API_KEY` exista.

### Alternativas descartadas

- **Manter o provider global como fallback:** era exatamente a segunda fonte de verdade que a task
  pede para eliminar; com ele, "qual agente roda" continuaria dependendo de ordem de precedência.
- **Persistir o seed no primeiro boot** (gravar `.aso/executors.json` a partir do ambiente): o
  operador perderia a capacidade de reconfigurar por variável em ambiente efêmero (Docker sem
  volume). O seed continua valendo a cada boot **sem** arquivo salvo.
- **Enum/booleano para cada flag de cada CLI:** amarra o modelo a uma versão de CLI. Dois campos
  semânticos (streaming, permissão) traduzidos por família absorvem mudança de flag num só lugar.
- **`--permission-mode bypassPermissions` para `total`:** equivalente documentado, mas
  `--dangerously-skip-permissions` é a flag que os perfis já usavam e que o diagnóstico de
  `sem_permissao` (ADR-0019) reconhece; trocar sem verificar contra o CLI real seria adivinhação.

## Consequências

- Uma pergunta, um lugar: o catálogo (API `GET /v1/executors`, tela ⚙ Config) responde qual
  executor roda cada etapa, com streaming, permissão e candidatura visíveis por perfil.
- Ambiente deixa de reconfigurar o runtime depois que existe catálogo salvo — mudança de
  `ASO_CLI_COMMAND` num runtime já configurado não tem efeito (documentado no README e em
  `docs/operations.md`).
- O roteamento automático por fase (planner/coder) deixou de existir: quem quer LLM em F1–F4 e CLI
  em F5–F6 atribui as etapas (ADR-0014). Ganho: a escolha fica auditável no evento
  `AgentAssignmentUpdated` em vez de implícita no bootstrap.
- Pipeline completo sem nenhum LLM com chave responde 409 na criação, como antes — a mensagem agora
  aponta o catálogo, não `ASO_LLM_*`.
