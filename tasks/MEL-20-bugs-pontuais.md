# MEL-20 — Correção de bugs pontuais encontrados na revisão

| Campo | Valor |
|---|---|
| Fase do roadmap | 2 — Correção |
| Prioridade | P1 |
| Esforço | baixo |
| Status | Backlog |
| Depende de | — |
| Origem | [feedback.md](../feedback.md) §3, §6 (bugs pontuais), §14 experimentos 5 e 9 |
| Requer ADR | Não |

Cada item abaixo é independente e deve entrar com teste de regressão que falha antes da correção.

## Bug 1 — Fase do card adivinhada pelo nome do papel

`_phase_for_agent` ([orchestration_service.py:337](../src/aso/control/orchestration_service.py#L337))
faz busca de substring no nome. Resultado executado:

- `RequirementsAgent` → F4 (casa `"ui"` em "req**ui**rements"; esperado F1);
- `ProductStrategyAgent` → F5 (esperado F1);
- `DevOpsAgent` → F5 (a documentação diz F6).

**Correção:** fase padrão declarada no registro de papéis (`_DEFAULT_AGENTS` ganha `fase`),
lida por `_phase_for_agent`; substring removida.

## Bug 2 — `run_plan` perde cards do mesmo papel

`cards_by_agent = {c.assignee: c …}` ([:6301](../src/aso/control/orchestration_service.py#L6301))
mantém só o último card de cada papel. Cards do backlog LLM ou da spec com o mesmo papel
nunca executam por `run_plan`.

**Correção:** iterar sobre cards `Ready` e ondas por `dependencies` dos cards, não por
`plan.agents`.

## Bug 3 — Título e critério genéricos nos cards do motor de decisão

`create_orchestration` gera título `"<Papel>: <motivo do motor>"` e critério
`"Output do agente aplicado via ContextBus"` (executado). Isso vira nome de branch e prompt.

**Correção:** título derivado da demanda (`brief.objetivo` ou `user_request` resumido) e
critérios de `brief.criterios_de_aceite` quando existirem.

## Bug 4 — Erro no planejamento LLM após a criação

Em `POST /v1/orchestrations` com `full-pipeline` ([app.py:760](../src/aso/api/app.py#L760)),
`PlanningService.plan` e `populate_from_plan` rodam **depois** de a orquestração ser persistida,
sem tratamento de `LlmError`/`ValueError`. Provável 500 com orquestração sem backlog [H].

**Correção:** capturar o erro, registrar `PlanningFailed` na orquestração e devolver 201 com
aviso (ou 502 com o id criado); `next_step` oferece "replanejar".

## Bug 5 — Snapshot duplicado

Tratado em MEL-17; se MEL-17 atrasar, corrigir aqui a duplicação isoladamente.

## Critérios de aceite

- [ ] Os 16 papéis têm fase declarada e `_phase_for_agent` não usa substring.
- [ ] `run_plan` executa todos os cards `Ready` respeitando dependências.
- [ ] Card criado pelo motor tem título e critérios derivados da demanda.
- [ ] Falha simulada do LLM de planejamento não produz 500 e deixa evento `PlanningFailed`.

## Testes obrigatórios

- Unit: tabela papel → fase.
- Unit: `run_plan` com dois cards do mesmo papel executa ambos.
- Unit: título/critério derivados da ficha.
- Integração API: `FakeLlmClient` que lança erro.

## Arquivos prováveis

- `src/aso/agents/registry.py`
- `src/aso/control/orchestration_service.py` (`_phase_for_agent`, `run_plan`, `create_orchestration`)
- `src/aso/api/app.py`
