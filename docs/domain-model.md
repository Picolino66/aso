# Modelo de Domínio — ASO Runtime

> Fase F3. Entidades canônicas, atributos e relacionamentos. Base para schemas Pydantic e tabelas (§29). Consistência **forte** (ver [ADR-0005](adrs/ADR-0005-data-consistency-and-api-versioning.md)).
> Convenções: todo agregado tem `id` (UUID) e `created_at`/`updated_at` (ISO8601, UTC).

## Mapa de agregados por plane

| Plane | Agregados |
|---|---|
| Control | `Orchestration`, `ExecutionPlan`, `Phase`, `AgentExecutionSelection` |
| Governance | `OrchestratorContext`, `ContextPatch`, `Conflict`, `QualityGateResult`, `Snapshot`, `ADR`, `HumanApproval` |
| Kanban | `Board`, `BoardColumn`, `KanbanCard`, `CardDependency`, `CardEvent` |
| Agent | `Agent`, `AgentRun`, `AgentMessage`, `AgentToolCall`, `AgentOutput`, `ProviderConfig`, `CliAgentConfig`, `AgentRoleBinding` |
| Execution | `Worktree`, `PullRequest`, `CIEvent`, `ReviewEvent` |
| Observability | `AuditEvent`, `CostRecord` |
| Raiz | `Project` |

## Entidades principais

### Project
`id, name, description, repo_path, created_at, updated_at`
Relaciona-se com N `Orchestration`.

### Orchestration
`id, project_id, execution_mode(full-pipeline|feature-evolution|architecture-review|code-execution|incident-response|phase-resume), current_phase(F1..F7), snapshot_version(O0..O7), status(created|running|blocked|waiting_human|completed|cancelled|rolled_back), user_request, created_at, updated_at`
Possui 1 `OrchestratorContext`, 1 `ExecutionPlan`, N `Phase`, N `Board`, N `Snapshot`, N `ADR`, N `HumanApproval`.

### OrchestratorContext
Estado canônico versionado (§17). Persistido como **JSONB** com `version` incremental e histórico append-only.
`id, orchestration_id, version, current_phase, snapshot_version, payload(jsonb: product|market|business|requirements|scope|feasibility|architecture|ux|contracts|engineering|agentic|quality|operations|kanban|adrs|snapshots|conflicts|approvals|orchestration|metadata), context_hash, created_at`

### ExecutionPlan
`id, orchestration_id, execution_mode, strategy(single_agent|sequential_agents|parallel_agents|agents_as_tools|handoff|supervisor_worker|group_chat_controlled|evaluator_optimizer|hybrid), reason, risk_level(low|medium|high|critical), requires_human_approval, agents(list<PlannedAgent>), success_criteria, fallback_strategy, created_at`
`PlannedAgent = { agent, role, reason, allowed_tools, depends_on, parallel_group }`

### Phase
`id, orchestration_id, code(F1..F7), status(pending|running|passed|failed|rolled_back), quality_gate_result_id, snapshot_id, started_at, finished_at`

### Board / BoardColumn
`Board = { id, orchestration_id, project_id, scope(project|orchestration|phase|release|feature), name, created_at }`
`BoardColumn = { id, board_id, key(Backlog|Ready|Planning|InProgress|WaitingAgent|WaitingHuman|Review|Testing|Blocked|Failed|Done|Archived), order, wip_limit? }`

### KanbanCard  (§16.5)
`id, board_id, orchestration_id, phase, type(Epic|Feature|Task|Bug|TechDebt|ADRTask|Research|Review|Test|Documentation|Deploy|Incident|Improvement), title, description, status, priority(low|medium|high|critical), assignee_type(human|agent|multi_agent), assignee, agents[], dependencies[], blocked_by[], acceptance_criteria[], linked_requirements[], linked_adrs[], linked_contracts[], linked_files[], linked_prs[], worktree, branch, quality_gate, context_snapshot, created_at, updated_at`

### CardDependency / CardEvent
`CardDependency = { id, card_id, depends_on_card_id, type(blocks|relates|subtask) }`
`CardEvent = { id, card_id, type, from_status, to_status, actor, payload, created_at }` — dirige a automação de colunas (§16.7).

### Agent / AgentRun
`Agent = { id, role(§15), capabilities[], allowed_tools[], requires_approval_for[], default_executor(llm_provider|cli_agent), created_at }`
`AgentRun = { id, orchestration_id, card_id, agent_role, executor_type(llm_provider|cli_agent), executor_id, model, provider, worktree, branch, status(running|completed|failed|cancelled), started_at, finished_at, token_usage, estimated_cost, logs_ref, diff_ref, error }`
`AgentMessage`, `AgentToolCall`, `AgentOutput` — detalhamento da execução (rastreabilidade §33).

### ContextPatch  (§18)
`id, orchestration_id, card_id, agent, phase, patch_type(add|update|propose|remove), target_path, content, evidence[], risks[], requires_adr, requires_approval, status(pending|applied|rejected|queued_conflict), created_at`

### Conflict  (§20)
`id, orchestration_id, type(ARCHITECTURE_CONFLICT|CONTRACT_CONFLICT|SECURITY_CONFLICT|DATA_MODEL_CONFLICT|SCOPE_CONFLICT|SNAPSHOT_LOCK_CONFLICT|QUALITY_GATE_CONFLICT|TOOL_PERMISSION_CONFLICT|AGENT_OUTPUT_CONFLICT|KANBAN_DEPENDENCY_CONFLICT|PR_CONFLICT|CI_CONFLICT|REVIEW_CONFLICT), source_patch_ids[], description, resolution, status(open|resolved|escalated), created_at`

### QualityGateResult  (§22)
`id, orchestration_id, phase, status(PASSED|FAILED|WARNING), criteria[{name,status,evidence,failure_reason}], blocking_issues[], warnings[], required_actions[], approved_by, human_approval_required, human_approval_status, created_at`

### Snapshot  (§23)
`id, orchestration_id, snapshot_version(O0..O7), phase, context_hash, frozen_sections[], quality_gate_result_id, adrs[], cards[], created_at`

### ADR  (§21)
`id(ADR-XXXX), orchestration_id, title, status(proposed|accepted|superseded|rejected|deprecated), context, options_considered[], decision, rationale, tradeoffs[], consequences[], phase, created_by_agent, reviewed_by_agent, supersedes, superseded_by, linked_cards[], linked_requirements[], timestamp`

### HumanApproval  (§24)
`id, orchestration_id, card_id, requested_by_agent, action, risk(medium|high|critical), payload, reason, status(pending|approved|rejected), approved_by, created_at`

### Configuração de execução  (§26A.7)
`ProviderConfig = { id, name, type(openai|anthropic|openai_compatible|local|custom), base_url, api_key_env, enabled, default_model, models[], limits{}, created_at, updated_at }`
`CliAgentConfig = { id, name, command, enabled, capabilities[], requires_worktree, supports_resume, supports_nudge, permissions{}, created_at, updated_at }`
`AgentRoleBinding = { id, role, executor_type(llm_provider|cli_agent|strategy), provider_id, model, cli_agent_id, strategy, fallbacks[], enabled }`
`AgentExecutionSelection = { id, orchestration_id, card_id, agent_role, selected_executor_type, selected_executor_id, reason, fallbacks[], created_at }`

### Execução real (MVP 3+)
`Worktree = { id, card_id, path, branch, created_at }`
`PullRequest`, `CIEvent`, `ReviewEvent` — observadores diferidos.

### Observabilidade
`AuditEvent = { id, orchestration_id, actor, agent, action, payload, created_at }`
`CostRecord = { id, orchestration_id, card_id, provider, model, input_tokens, output_tokens, estimated_cost, created_at }`

## Relacionamentos-chave

- `Orchestration 1—1 OrchestratorContext` (versionado) · `1—N Snapshot` · `1—N ADR`
- `Board 1—N BoardColumn` · `Board 1—N KanbanCard`
- `KanbanCard N—N ADR/Contract/Requirement` (rastreabilidade) · `1—N AgentRun`
- `AgentRun N—1 Agent` · `1—N ContextPatch`
- `ContextPatch N—1 Conflict` (quando enfileirado) · aplicado pelo ContextBus incrementa `OrchestratorContext.version`
