# MEL-54 — Catálogo único de executores

| Campo | Valor |
|---|---|
| Fase do roadmap | 5 — Limpeza |
| Prioridade | P2 |
| Esforço | médio |
| Status | Backlog |
| Depende de | MEL-14 |
| Origem | [feedback.md](../feedback.md) §1 (onde vive o estado), §5, §7 |
| Requer ADR | Sim, curta: catálogo como fonte única de executores (atualiza ADR-0007 e ADR-0011) |

## Problema

Executores são configurados em cinco lugares, com precedências diferentes:

1. `ASO_CLI_COMMAND` + `ASO_TARGET_REPO` → provider global do bootstrap;
2. `ASO_LLM_*` → provider global e também o cliente de planejamento em `app.py`;
3. `ASO_EXECUTORS` (JSON) → seed do catálogo;
4. `.aso/executors.json` → catálogo salvo pela tela de configuração (tem prioridade sobre o 3);
5. `ASO_CANDIDATE_COMMANDS` → candidatos da corrida (`build_candidate_providers`), fora do catálogo.

Além disso, `RoutingExecutionProvider` (planner F1–F4 / coder F5–F6) duplica a escolha por
etapa que o catálogo já faz, e scripts (`enable-agent-stream.sh`, `fix-executor-permissions.sh`)
editam comandos de perfil por substituição de texto.

## Mudança proposta

1. O catálogo é a única fonte em tempo de execução. Variáveis de ambiente só semeiam o
   catálogo no primeiro boot (documentado).
2. Remover o provider global do bootstrap e o `RoutingExecutionProvider`; a escolha por
   etapa usa `agent_assignments` + perfil padrão.
3. O planejamento LLM (`PlanningService`) usa um executor do catálogo atribuído à etapa `planejamento`.
4. Candidatos da corrida = lista de perfis do catálogo escolhida na requisição (`POST …/race` com `executores: [...]`).
5. Perfis ganham campos estruturados em vez de edição de string: `streaming: bool`,
   `permissao_escrita: "nenhuma|edicoes|total"`; o catálogo monta as flags por família de CLI.
   Os dois scripts viram migração única dos perfis existentes.

## Critérios de aceite

- [ ] Nenhuma leitura de `ASO_CLI_COMMAND`, `ASO_LLM_*` ou `ASO_CANDIDATE_COMMANDS` fora do seed do catálogo.
- [ ] Corrida de candidatos funciona com perfis do catálogo.
- [ ] Ativar streaming ou permissão de escrita é feito pelo campo do perfil, sem editar o comando à mão.
- [ ] Perfis existentes em `.aso/executors.json` são migrados sem perda.
