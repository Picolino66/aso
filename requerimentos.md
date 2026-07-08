# ASO Runtime — Requisitos do Produto e Engenharia

## 1. Nome do projeto

**ASO Runtime — Autonomous Software Orchestrator Runtime**

## 2. Objetivo

Criar um runtime multiagente de engenharia de software capaz de transformar uma intenção de produto, feature, melhoria técnica, refatoração, incidente ou demanda de evolução em um fluxo rastreável de ponta a ponta.

O sistema deve coordenar múltiplos agentes especializados, distribuir tarefas em um quadro Kanban, executar trabalhos em paralelo quando cabível, manter contexto canônico do projeto, registrar decisões arquiteturais, validar quality gates, gerar snapshots e acompanhar a entrega até revisão, testes, documentação, deploy e evolução contínua.

## 3. Visão resumida

O ASO Runtime deve atuar como uma combinação de:

* CTO agentic;
* Tech Lead agentic;
* Product/Engineering Manager agentic;
* Orquestrador multiagente;
* Kanban operacional;
* Runtime de execução de agentes;
* Governança de arquitetura;
* Rastreador de decisões, tarefas, contexto, qualidade e evolução.

Em uma frase:

> Um runtime multiagente de engenharia de software com Kanban operacional, capaz de decompor demandas, distribuir tarefas entre agentes especializados, executar em paralelo, validar por quality gates, registrar ADRs, gerar snapshots e conduzir o ciclo completo da ideia à produção.

## 4. Problema que o projeto resolve

Hoje, ferramentas de agentes de código conseguem implementar tarefas, mas geralmente falham em:

* manter contexto global do produto;
* preservar decisões arquiteturais;
* evitar conflitos entre múltiplos agentes;
* organizar trabalho em Kanban;
* conectar discovery, arquitetura, contrato, UX, código, testes, deploy e operação;
* garantir quality gates antes de avançar;
* rastrear requisito → decisão → task → implementação → teste → deploy;
* impedir que agentes alterem contratos, arquitetura ou escopo sem validação;
* coordenar múltiplas tarefas paralelas com segurança;
* saber quando usar um agente, vários agentes, execução paralela, handoff ou aprovação humana.

O ASO Runtime deve resolver isso criando uma camada de governança e execução agentic de ponta a ponta.

## 5. Referências conceituais

O sistema deve considerar como inspiração operacional:

* AgentWrapper/agent-orchestrator: execução paralela de agentes de código, worktrees isolados, PR/CI/review feedback e gerenciamento de agentes.
* OpenAI Agents SDK: agentes com tools, handoffs, guardrails e structured outputs.
* LangGraph: workflows stateful, persistência, streaming, debugging e padrões de workflow/agentes.
* Microsoft Agent Framework: padrões multiagente como sequential, concurrent, handoff, group chat e magentic.

Importante:

O ASO Runtime não deve começar copiando diretamente o código do AgentWrapper. O AgentWrapper deve ser usado primeiro como referência funcional e operacional. O ASO deve nascer como projeto próprio, com possibilidade futura de integração, provider, fork controlado ou reaproveitamento seletivo.

## 6. Escopo principal

O ASO Runtime deve entregar três pilares principais:

### 6.1 Multiagentes atuando em multitarefas

O sistema deve permitir que vários agentes trabalhem em várias tarefas ao mesmo tempo, com isolamento, rastreabilidade, permissões e controle central.

### 6.2 Quadro Kanban para gerenciamento

O sistema deve possuir um quadro Kanban onde cada card representa uma unidade de trabalho rastreável, podendo ser executada por humano, agente ou grupo de agentes.

### 6.3 Orquestração ponta a ponta da engenharia

O sistema deve cobrir o ciclo completo:

1. Discovery & Strategy;
2. Architecture & Design;
3. Data & API Contracts;
4. UX/UI & Planning;
5. Engineering Execution;
6. Quality, Docs & Deploy;
7. Operate & Evolve.

## 7. Não escopo inicial

No MVP inicial, o sistema não deve tentar resolver tudo.

Fora do MVP 1:

* SaaS multiempresa;
* marketplace de agentes;
* billing;
* deploy automático em produção;
* execução remota distribuída;
* permissões avançadas por organização;
* integração obrigatória com todos os agentes CLI;
* fork profundo do AgentWrapper;
* UI complexa estilo Jira completo;
* execução autônoma destrutiva;
* alteração de secrets;
* provisionamento cloud automático;
* agentes modificando banco de produção.

## 8. Princípios do sistema

### 8.1 O orquestrador controla o fluxo

Agentes especialistas ajudam, mas não mandam no fluxo global.

### 8.2 Multiagente quando fizer sentido

O sistema deve usar múltiplos agentes quando houver ganho de:

* paralelismo;
* especialização;
* revisão independente;
* segurança;
* qualidade;
* rastreabilidade;
* decomposição de trabalho.

O sistema não deve criar múltiplos agentes sem necessidade.

### 8.3 Contexto central é soberano

Nenhum agente deve alterar diretamente a verdade central do projeto.

Agentes produzem propostas, patches, artefatos e evidências. O `ContextBus` valida e aplica.

### 8.4 Toda decisão relevante deve ser rastreável

Mudanças importantes devem ter origem clara:

* quem propôs;
* qual agente executou;
* qual requisito motivou;
* qual ADR sustenta;
* qual task implementou;
* qual teste validou;
* qual gate aprovou.

### 8.5 Quality gates bloqueiam avanço

O sistema não deve avançar fase se o quality gate da fase falhar.

### 8.6 Execução crítica exige aprovação humana

Ações de alto risco devem exigir aprovação humana.

### 8.7 Kanban é parte do runtime

O Kanban não é apenas visual. Ele é o mecanismo de controle operacional das tarefas.

### 8.8 Worktrees e isolamento são recomendados

Quando houver execução real de código por múltiplos agentes, cada agente ou task deve trabalhar em branch/worktree isolado.

## 9. Glossário

### Orchestration

Execução completa de uma demanda dentro do ASO Runtime.

### Phase

Fase da esteira F1–F7.

### Agent

Executor especializado com papel, permissões, tools e contrato de saída.

### Skill

Capacidade reutilizável, checklist, prompt module ou procedimento especializado.

### Tool

Ação concreta executável, como ler arquivo, escrever arquivo, rodar teste, criar PR ou validar OpenAPI.

### Kanban Card

Unidade de trabalho rastreável, vinculada a fase, agente, contexto, artefatos e status.

### OrchestratorContext

Estado canônico versionado do produto/projeto.

### ContextPatch

Proposta de alteração no contexto, produzida por agente ou skill.

### ContextBus

Único componente autorizado a aplicar alterações no `OrchestratorContext`.

### Quality Gate

Validação objetiva que aprova ou bloqueia avanço.

### ADR

Architecture Decision Record. Registro formal de decisão arquitetural.

### Snapshot

Versão congelada do contexto após uma fase aprovada.

### Execution Provider

Mecanismo capaz de executar agentes ou tarefas. Exemplos: executor local, AgentWrapper provider, CLI agent provider.

## 10. Arquitetura conceitual

```txt
ASO Runtime
  ├── Control Plane
  │   ├── OrchestratorRuntime
  │   ├── PhaseController
  │   ├── MultiAgentDecisionEngine
  │   ├── AgentSupervisor
  │   ├── AgentRouter
  │   ├── ExecutionPlanner
  │   ├── DependencyGraph
  │   └── HumanApprovalEngine
  │
  ├── Kanban Plane
  │   ├── BoardService
  │   ├── CardService
  │   ├── SwimlaneService
  │   ├── CardDependencyService
  │   ├── CardAssignmentService
  │   └── CardEventService
  │
  ├── Agent Plane
  │   ├── AgentRegistry
  │   ├── AgentSupervisor
  │   ├── AgentExecutor
  │   ├── AgentAdapterRegistry
  │   ├── SkillRegistry
  │   ├── SkillResolver
  │   └── ToolPermissionEngine
  │
  ├── Execution Plane
  │   ├── ExecutionProvider
  │   ├── LocalExecutionProvider
  │   ├── AgentWrapperExecutionProvider
  │   ├── WorktreeManager
  │   ├── TerminalRuntime
  │   ├── PullRequestManager
  │   ├── CIObserver
  │   └── ReviewObserver
  │
  ├── Governance Plane
  │   ├── OrchestratorContext
  │   ├── ContextBus
  │   ├── ContextPatchValidator
  │   ├── ConflictDetector
  │   ├── QualityGateEngine
  │   ├── ADRRegistry
  │   ├── SnapshotEngine
  │   └── ContractValidator
  │
  └── Observability Plane
      ├── TraceService
      ├── EventLog
      ├── CostTracker
      ├── TokenUsageTracker
      ├── AgentRunTimeline
      └── AuditLog
```

## 11. Fases obrigatórias

O runtime deve suportar as seguintes fases.

### F1 — Discovery & Strategy

Objetivo:

Entender o problema, o produto, o público, o escopo inicial, restrições e métricas.

Saídas esperadas:

* visão do produto;
* objetivo;
* público-alvo;
* personas;
* problemas;
* hipóteses;
* requisitos iniciais;
* escopo;
* não escopo;
* métricas de sucesso;
* riscos iniciais.

Agentes possíveis:

* ProductStrategyAgent;
* RequirementsAgent;
* MarketResearchAgent;
* ScopeDefinitionAgent;
* ReviewAgent.

Quality gate F1:

* objetivo claro;
* problema definido;
* escopo e não escopo definidos;
* requisitos iniciais documentados;
* métricas de sucesso definidas;
* riscos iniciais mapeados.

Snapshot gerado:

* O1.

### F2 — Architecture & Design

Objetivo:

Definir arquitetura técnica, padrões, stack, módulos, integrações, segurança e decisões arquiteturais.

Saídas esperadas:

* arquitetura macro;
* desenho de módulos;
* stack técnica;
* padrões arquiteturais;
* estratégia de segurança;
* estratégia de storage;
* estratégia de autenticação/autorização;
* estratégia de observabilidade;
* ADRs;
* riscos técnicos.

Agentes possíveis:

* ArchitectureDesignAgent;
* SecurityAgent;
* InfrastructureAgent;
* DatabaseAgent;
* ReviewAgent.

Quality gate F2:

* arquitetura definida;
* stack definida;
* decisões relevantes registradas em ADR;
* riscos técnicos documentados;
* modelo de segurança inicial definido;
* sem contradições com F1.

Snapshot gerado:

* O2.

### F3 — Data & API Contracts

Objetivo:

Definir contratos de API, schemas, modelos de dados, versionamento, consistência e integrações.

Saídas esperadas:

* OpenAPI;
* JSON Schemas;
* entidades;
* DTOs;
* contratos de entrada e saída;
* eventos, se houver;
* regras de idempotência;
* estratégia de versionamento;
* estratégia de migrations;
* modelo de consistência.

Agentes possíveis:

* DataApiContractsAgent;
* BackendDevelopmentAgent;
* DatabaseAgent;
* IntegrationAgent;
* ReviewAgent.

Quality gate F3:

* contratos definidos;
* schemas versionados;
* endpoints descritos;
* entidades principais definidas;
* sem campos genéricos sem explicação;
* compatível com arquitetura F2.

Snapshot gerado:

* O3.

### F4 — UX/UI & Planning

Objetivo:

Transformar requisitos e contratos em backlog, Kanban, jornada, telas, critérios de aceite e plano de execução.

Saídas esperadas:

* jornadas;
* fluxos;
* telas ou wireframes, se houver UI;
* backlog;
* épicos;
* tasks;
* critérios de aceite;
* dependências;
* plano de execução;
* estrutura inicial do Kanban.

Agentes possíveis:

* UxPlanningAgent;
* ProductStrategyAgent;
* FrontendDevelopmentAgent;
* TestingAgent;
* DocumentationAgent;
* ReviewAgent.

Quality gate F4:

* backlog criado;
* tasks rastreáveis;
* critérios de aceite definidos;
* dependências explícitas;
* cards Kanban criados;
* escopo compatível com F1–F3.

Snapshot gerado:

* O4.

### F5 — Engineering Execution

Objetivo:

Executar implementação com agentes especializados.

Saídas esperadas:

* código implementado;
* branches/worktrees;
* commits;
* PRs;
* testes criados;
* documentação técnica inicial;
* logs de execução;
* evidências de build/lint/test.

Agentes possíveis:

* BackendDevelopmentAgent;
* FrontendDevelopmentAgent;
* MobileDevelopmentAgent;
* DatabaseAgent;
* DevOpsAgent;
* TestingAgent;
* DocumentationAgent;
* SecurityAgent;
* ReviewAgent.

Quality gate F5:

* código compila;
* testes relevantes passam;
* contratos respeitados;
* implementação rastreada para cards;
* sem alteração indevida de ADR/snapshot;
* documentação mínima atualizada.

Snapshot gerado:

* O5.

### F6 — Quality, Docs & Deploy

Objetivo:

Validar qualidade, segurança, documentação, CI, deploy e rollback.

Saídas esperadas:

* testes finais;
* relatório de QA;
* relatório de segurança;
* documentação atualizada;
* changelog;
* resultado de CI;
* plano de deploy;
* plano de rollback;
* evidências de smoke test.

Agentes possíveis:

* TestingAgent;
* SecurityAgent;
* DocumentationAgent;
* DevOpsAgent;
* ReviewAgent;
* ReleaseAgent.

Quality gate F6:

* CI passou;
* testes passaram;
* review aprovado;
* documentação atualizada;
* riscos conhecidos aceitos;
* plano de rollback definido;
* deploy validado, se aplicável.

Snapshot gerado:

* O6.

### F7 — Operate & Evolve

Objetivo:

Monitorar operação, incidentes, feedback, métricas, custo, performance e evolução contínua.

Saídas esperadas:

* plano de observabilidade;
* métricas;
* alertas;
* feedback de usuários;
* incidentes;
* melhorias futuras;
* débitos técnicos;
* novas demandas;
* reavaliações arquiteturais.

Agentes possíveis:

* OperateEvolveAgent;
* DevOpsAgent;
* SecurityAgent;
* ProductStrategyAgent;
* ArchitectureDesignAgent;
* ReviewAgent.

Quality gate F7:

* métricas definidas;
* alertas definidos;
* operação documentada;
* riscos operacionais mapeados;
* feedback convertido em backlog;
* incidentes rastreáveis.

Snapshot gerado:

* O7.

## 12. Modos de execução

O sistema deve suportar os seguintes modos.

### 12.1 full-pipeline

Executa F1 até F7.

Uso:

* criar produto do zero;
* criar sistema completo;
* validar ideia até produção.

### 12.2 feature-evolution

Executa evolução de feature em projeto existente.

Fluxo comum:

* consulta F1/F2/F3 existentes;
* revisita arquitetura ou contratos se necessário;
* cria cards em F4;
* executa F5/F6;
* registra evolução em F7.

### 12.3 architecture-review

Executa revisão arquitetural.

Fluxo comum:

* F2;
* ADRs;
* SecurityAgent;
* InfrastructureAgent;
* ReviewAgent;
* relatório final.

### 12.4 code-execution

Executa implementação de tasks já planejadas.

Fluxo comum:

* F5;
* F6;
* PR;
* CI;
* review;
* documentação.

### 12.5 incident-response

Executa resposta a incidente.

Fluxo comum:

* F7;
* análise de causa raiz;
* possível retorno a F2/F3/F5/F6;
* correção;
* postmortem;
* backlog de prevenção.

### 12.6 phase-resume

Retoma execução a partir de fase, snapshot ou card.

## 13. Padrões multiagente obrigatórios

O sistema deve implementar ou preparar arquitetura para os padrões abaixo.

### 13.1 single_agent

Uso:

* tarefa simples;
* baixo risco;
* sem necessidade de paralelismo;
* um domínio técnico apenas.

### 13.2 sequential_agents

Uso:

* dependência clara entre etapas.

Exemplo:

```txt
ArchitectureDesignAgent
  ↓
DataApiContractsAgent
  ↓
BackendDevelopmentAgent
  ↓
TestingAgent
  ↓
ReviewAgent
```

### 13.3 parallel_agents

Uso:

* tarefas independentes.

Exemplo:

```txt
BackendDevelopmentAgent ─┐
FrontendDevelopmentAgent ├── ReviewAgent
DocumentationAgent ──────┘
```

### 13.4 agents_as_tools

Uso:

* o OrchestratorAgent mantém controle;
* especialistas respondem como capacidades internas.

### 13.5 handoff

Uso:

* uma etapa precisa ser assumida por especialista;
* controle retorna ao orquestrador após conclusão.

### 13.6 supervisor_worker

Uso:

* demanda grande;
* orquestrador decompondo e distribuindo múltiplas tasks.

### 13.7 group_chat_controlled

Uso:

* conflito arquitetural;
* decisão de alto impacto;
* análise multi-perspectiva.

Regras:

* limite de rodadas;
* agente moderador;
* síntese obrigatória;
* decisão registrada em ADR.

### 13.8 evaluator_optimizer

Uso:

* gerar, revisar, corrigir, revisar novamente.

Exemplo:

```txt
CodeAgent gera
TestingAgent testa
ReviewAgent critica
CodeAgent corrige
ReviewAgent aprova
```

## 14. MultiAgentDecisionEngine

Criar componente responsável por decidir estratégia de execução.

Entrada:

```json
{
  "user_request": "...",
  "current_phase": "F4",
  "orchestrator_context": {},
  "available_agents": [],
  "available_skills": [],
  "available_tools": [],
  "risk_level": "low | medium | high | critical",
  "constraints": {},
  "budget": {},
  "deadline": null
}
```

Saída:

```json
{
  "execution_mode": "single_agent | sequential_agents | parallel_agents | agents_as_tools | handoff | supervisor_worker | group_chat_controlled | evaluator_optimizer | hybrid",
  "reason": "...",
  "risk_level": "low | medium | high | critical",
  "requires_human_approval": false,
  "agents": [
    {
      "agent": "ArchitectureDesignAgent",
      "role": "primary",
      "reason": "...",
      "allowed_tools": [],
      "depends_on": [],
      "parallel_group": null
    }
  ],
  "success_criteria": [],
  "fallback_strategy": "..."
}
```

Regras de decisão:

Usar múltiplos agentes quando:

* houver múltiplos domínios;
* houver risco relevante;
* houver necessidade de revisão independente;
* houver tarefas paralelizáveis;
* houver impacto em arquitetura, contrato, segurança, banco ou deploy.

Não usar múltiplos agentes quando:

* tarefa for pequena;
* custo de coordenação for maior que benefício;
* contexto for insuficiente;
* tarefa for puramente textual e simples.

## 15. Agentes obrigatórios

### 15.1 OrchestratorAgent

Responsável por:

* entender demanda;
* escolher modo de execução;
* coordenar fases;
* coordenar agentes;
* preservar contexto;
* consolidar resultado;
* solicitar aprovação humana;
* bloquear avanço quando necessário.

Não pode:

* pular quality gates;
* permitir tool crítica sem aprovação;
* ignorar ADR;
* alterar contexto diretamente sem ContextBus.

### 15.2 ProductStrategyAgent

Responsável por:

* discovery;
* visão de produto;
* personas;
* hipóteses;
* escopo;
* métricas.

### 15.3 RequirementsAgent

Responsável por:

* requisitos funcionais;
* requisitos não funcionais;
* critérios de aceite;
* rastreabilidade.

### 15.4 ArchitectureDesignAgent

Responsável por:

* arquitetura;
* padrões;
* stack;
* módulos;
* integrações;
* ADRs;
* riscos técnicos.

### 15.5 DataApiContractsAgent

Responsável por:

* contratos de API;
* OpenAPI;
* schemas;
* entidades;
* DTOs;
* versionamento;
* consistência.

### 15.6 UxPlanningAgent

Responsável por:

* jornadas;
* fluxos;
* telas;
* backlog;
* tasks;
* Kanban.

### 15.7 BackendDevelopmentAgent

Responsável por:

* implementação backend;
* endpoints;
* services;
* domínio;
* persistência;
* integrações;
* testes backend.

### 15.8 FrontendDevelopmentAgent

Responsável por:

* UI;
* componentes;
* páginas;
* integração com API;
* estados;
* testes frontend.

### 15.9 DatabaseAgent

Responsável por:

* modelagem;
* migrations;
* índices;
* queries;
* performance;
* consistência.

### 15.10 DevOpsAgent

Responsável por:

* CI/CD;
* Docker;
* deploy;
* ambientes;
* variáveis;
* observabilidade;
* rollback.

### 15.11 TestingAgent

Responsável por:

* testes unitários;
* testes integração;
* testes contrato;
* testes e2e;
* plano de QA.

### 15.12 SecurityAgent

Responsável por:

* threat model;
* autenticação;
* autorização;
* validação de input;
* secrets;
* dependências;
* vulnerabilidades.

### 15.13 DocumentationAgent

Responsável por:

* README;
* docs técnicas;
* ADRs;
* guias de uso;
* changelog;
* documentação de API.

### 15.14 ReviewAgent

Responsável por:

* revisão independente;
* qualidade técnica;
* aderência a arquitetura;
* aderência a contratos;
* riscos;
* aprovação ou solicitação de mudanças.

Saída obrigatória:

```json
{
  "status": "approved | changes_requested | rejected",
  "findings": [],
  "risks": [],
  "required_changes": [],
  "quality_gate_impact": [],
  "recommendation": "..."
}
```

### 15.15 ConflictResolutionAgent

Responsável por:

* analisar conflitos;
* propor resolução;
* sugerir ADR;
* solicitar aprovação humana quando necessário.

### 15.16 FinalResponseAgent

Responsável por:

* consolidar execução;
* resumir decisões;
* listar entregas;
* listar pendências;
* apontar riscos;
* indicar próximos passos.

## 16. Kanban

O Kanban deve ser parte central do sistema.

### 16.1 Estrutura do board

O sistema deve suportar boards por:

* projeto;
* orquestração;
* fase;
* release;
* feature.

### 16.2 Colunas mínimas

Colunas obrigatórias:

* Backlog;
* Ready;
* Planning;
* In Progress;
* Waiting Agent;
* Waiting Human;
* Review;
* Testing;
* Blocked;
* Failed;
* Done;
* Archived.

### 16.3 Swimlanes

Swimlanes possíveis:

* por fase F1–F7;
* por agente;
* por épico;
* por prioridade;
* por tipo de trabalho;
* por release.

### 16.4 Tipos de card

Tipos obrigatórios:

* Epic;
* Feature;
* Task;
* Bug;
* Tech Debt;
* ADR Task;
* Research;
* Review;
* Test;
* Documentation;
* Deploy;
* Incident;
* Improvement.

### 16.5 Modelo do card

```json
{
  "id": "card_uuid",
  "board_id": "board_uuid",
  "orchestration_id": "orch_uuid",
  "phase": "F5",
  "type": "Task",
  "title": "...",
  "description": "...",
  "status": "In Progress",
  "priority": "low | medium | high | critical",
  "assignee_type": "human | agent | multi_agent",
  "assignee": "BackendDevelopmentAgent",
  "agents": [],
  "dependencies": [],
  "blocked_by": [],
  "acceptance_criteria": [],
  "linked_requirements": [],
  "linked_adrs": [],
  "linked_contracts": [],
  "linked_files": [],
  "linked_prs": [],
  "worktree": null,
  "branch": null,
  "quality_gate": null,
  "context_snapshot": null,
  "created_at": "...",
  "updated_at": "..."
}
```

### 16.6 Regras do Kanban

* Todo trabalho executável deve virar card.
* Todo card deve ter fase.
* Card técnico relevante deve ter critério de aceite.
* Card executado por agente deve registrar agente responsável.
* Card que altera arquitetura deve vincular ADR.
* Card que altera API deve vincular contrato.
* Card que altera código deve vincular branch/worktree/PR.
* Card bloqueado deve registrar motivo.
* Card finalizado deve ter evidência.

### 16.7 Automação do Kanban

O sistema deve mover cards automaticamente quando eventos ocorrerem.

Exemplos:

* Agent started → In Progress;
* Agent needs input → Waiting Human;
* PR opened → Review;
* CI failed → Failed ou Blocked;
* Review requested changes → Review;
* Tests passed → Testing ou Done;
* Quality gate passed → Done;
* Quality gate failed → Blocked.

## 17. OrchestratorContext

O contexto canônico deve ser versionado e validado.

### 17.1 Estrutura mínima

```json
{
  "orchestration_id": "uuid",
  "project_id": "uuid",
  "current_phase": "F1 | F2 | F3 | F4 | F5 | F6 | F7",
  "snapshot_version": "O0 | O1 | O2 | O3 | O4 | O5 | O6 | O7",
  "execution_mode": "...",
  "product": {},
  "market": {},
  "business": {},
  "requirements": {},
  "scope": {},
  "architecture": {},
  "contracts": {},
  "ux": {},
  "engineering": {},
  "quality": {},
  "operations": {},
  "kanban": {},
  "agentic": {
    "agents_map": {},
    "skills_map": {},
    "tools_map": {},
    "execution_providers": {},
    "tasks_map": {}
  },
  "adrs": [],
  "snapshots": [],
  "conflicts": [],
  "approvals": [],
  "metadata": {}
}
```

### 17.2 Regras do contexto

* Todo agente recebe contexto atualizado.
* Nenhum agente altera contexto diretamente.
* Toda alteração deve ser `ContextPatch`.
* Todo patch passa por validação.
* Contexto deve ter histórico.
* Contexto deve ser recuperável por snapshot.

## 18. ContextPatch

Agentes e skills devem retornar patches.

Modelo:

```json
{
  "id": "patch_uuid",
  "orchestration_id": "orch_uuid",
  "card_id": "card_uuid",
  "agent": "BackendDevelopmentAgent",
  "phase": "F5",
  "patch_type": "add | update | propose | remove",
  "target_path": "architecture.modules.pdf",
  "content": {},
  "evidence": [],
  "risks": [],
  "requires_adr": false,
  "requires_approval": false,
  "created_at": "..."
}
```

## 19. ContextBus

O `ContextBus` é o único componente que aplica patches ao contexto.

Antes de aplicar um patch, executar:

1. schema validation;
2. permission check;
3. conflict detection;
4. snapshot lock validation;
5. ADR consistency validation;
6. contract compatibility validation;
7. quality gate impact check.

Se aprovado:

* aplicar patch;
* incrementar versão;
* registrar evento;
* persistir histórico;
* atualizar cards relacionados.

Se reprovado:

* registrar conflito;
* mover card para Blocked ou Waiting Human;
* chamar ConflictResolutionAgent quando necessário.

## 20. ConflictDetector

Deve detectar conflitos dos seguintes tipos:

```txt
ARCHITECTURE_CONFLICT
CONTRACT_CONFLICT
SECURITY_CONFLICT
DATA_MODEL_CONFLICT
SCOPE_CONFLICT
SNAPSHOT_LOCK_CONFLICT
QUALITY_GATE_CONFLICT
TOOL_PERMISSION_CONFLICT
AGENT_OUTPUT_CONFLICT
KANBAN_DEPENDENCY_CONFLICT
PR_CONFLICT
CI_CONFLICT
REVIEW_CONFLICT
```

Exemplos:

* agente altera contrato congelado;
* implementação não respeita OpenAPI;
* banco diverge do modelo aprovado;
* task é executada antes da dependência;
* dois agentes modificam o mesmo arquivo de modo incompatível;
* agente propõe solução contra ADR aceita;
* teste falha após implementação;
* PR tem conflito de merge.

## 21. ADRRegistry

Toda decisão arquitetural relevante deve gerar ADR.

ADR obrigatória para:

* padrão arquitetural;
* stack;
* banco de dados;
* autenticação;
* autorização;
* mensageria;
* storage;
* cloud;
* cache;
* observabilidade;
* versionamento de API;
* consistência de dados;
* deploy;
* segurança;
* mudança que afete custo, escala, manutenção ou contrato público.

Modelo:

```json
{
  "id": "ADR-0001",
  "title": "...",
  "status": "proposed | accepted | superseded | rejected",
  "context": "...",
  "options_considered": [],
  "decision": "...",
  "rationale": "...",
  "tradeoffs": [],
  "consequences": [],
  "phase": "F2",
  "created_by_agent": "ArchitectureDesignAgent",
  "reviewed_by_agent": "ReviewAgent",
  "linked_cards": [],
  "linked_requirements": [],
  "timestamp": "..."
}
```

## 22. QualityGateEngine

Cada fase deve ter quality gate.

Modelo:

```json
{
  "id": "gate_result_uuid",
  "orchestration_id": "orch_uuid",
  "phase": "F3",
  "status": "PASSED | FAILED | WARNING",
  "criteria": [
    {
      "name": "...",
      "status": "PASSED | FAILED",
      "evidence": [],
      "failure_reason": null
    }
  ],
  "blocking_issues": [],
  "warnings": [],
  "required_actions": [],
  "approved_by": null,
  "created_at": "..."
}
```

Regras:

* gate falho bloqueia avanço;
* gate falho pode gerar cards automáticos;
* gate falho pode acionar agente responsável;
* gate crítico pode exigir aprovação humana;
* fase aprovada gera snapshot.

## 23. SnapshotEngine

Snapshots obrigatórios:

```txt
O1 após F1
O2 após F2
O3 após F3
O4 após F4
O5 após F5
O6 após F6
O7 após F7
```

Modelo:

```json
{
  "id": "snapshot_uuid",
  "orchestration_id": "orch_uuid",
  "snapshot_version": "O3",
  "phase": "F3",
  "context_hash": "...",
  "frozen_sections": [],
  "quality_gate_result_id": "...",
  "adrs": [],
  "cards": [],
  "created_at": "..."
}
```

Funcionalidades:

* criar snapshot;
* comparar snapshots;
* restaurar snapshot;
* bloquear alteração direta de seção congelada;
* exigir ADR/approval para override.

## 24. HumanApprovalEngine

Aprovação humana obrigatória para:

* deletar arquivos;
* alterar secrets;
* resetar banco;
* executar deploy;
* alterar branch principal;
* modificar contrato público;
* sobrescrever snapshot;
* ignorar quality gate;
* alterar ADR aceita;
* executar comando shell perigoso;
* publicar mensagem externa;
* executar ação de alto custo;
* resolver conflito crítico sem consenso.

Modelo:

```json
{
  "id": "approval_uuid",
  "orchestration_id": "orch_uuid",
  "card_id": "card_uuid",
  "requested_by_agent": "DevOpsAgent",
  "action": "...",
  "risk": "medium | high | critical",
  "payload": {},
  "reason": "...",
  "status": "pending | approved | rejected",
  "approved_by": null,
  "created_at": "..."
}
```

## 25. Tools e permissões

Criar `ToolRegistry`.

Tools iniciais:

* read_file;
* write_file;
* search_repo;
* git_status;
* git_diff;
* create_branch;
* create_worktree;
* run_tests;
* run_lint;
* run_build;
* validate_openapi;
* validate_json_schema;
* create_adr;
* update_docs;
* open_pr;
* read_ci_status;
* read_review_comments;
* security_scan.

### 25.1 Exemplo de permissão

```json
{
  "BackendDevelopmentAgent": {
    "allowed_tools": [
      "read_file",
      "write_file",
      "search_repo",
      "git_diff",
      "run_tests",
      "run_lint",
      "run_build"
    ],
    "requires_approval_for": [
      "delete_file",
      "database_reset",
      "deploy"
    ]
  },
  "SecurityAgent": {
    "allowed_tools": [
      "read_file",
      "search_repo",
      "security_scan",
      "git_diff"
    ],
    "requires_approval_for": [
      "write_file",
      "deploy"
    ]
  }
}
```

## 26. Execution Providers

O sistema deve suportar provedores de execução.

### 26.1 LocalExecutionProvider

Executa agentes internos ou scripts locais.

### 26.2 AgentWrapperExecutionProvider

Provider futuro para conversar com AgentWrapper ou executar fluxo inspirado nele.

Responsabilidades:

* criar sessão;
* criar worktree;
* iniciar agente CLI;
* enviar prompt;
* acompanhar terminal;
* coletar logs;
* acompanhar PR;
* acompanhar CI;
* receber feedback;
* retornar resultado ao ASO.

### 26.3 CliAgentExecutionProvider

Executa agentes CLI diretamente, como:

* Claude Code;
* Codex;
* Cline;
* Roo Code;
* OpenCode;
* Aider;
* Cursor CLI, se disponível;
* Kimi Code;
* outros wrappers.

## 26A. Configuração de múltiplos providers, modelos e agentes CLI

O ASO Runtime deve permitir configurar múltiplos provedores de LLM via API e múltiplos agentes CLI instalados localmente, podendo usar mais de um ao mesmo tempo em uma mesma orquestração.

Esse módulo é obrigatório porque o ASO não deve depender de um único modelo, uma única API ou um único agente de código. O runtime deve ser capaz de escolher o melhor executor para cada card, fase, agente ou tipo de tarefa.

Exemplos de uso esperado:

```txt
DeepSeek API
→ planejamento, análise, classificação, documentação, revisão leve, geração de ADRs e suporte a agentes internos.

Claude Code instalado na máquina
→ execução real de código, leitura de arquivos, edição, refatoração e comandos locais.

Codex CLI instalado na máquina
→ execução real de código, criação de testes, correções, documentação e revisão técnica.
```

Claude Code é um agente de terminal voltado a entender codebase, editar arquivos, executar comandos e operar dentro do fluxo local do desenvolvedor. O Codex CLI também é descrito como um agente de código que roda localmente no computador do usuário. A DeepSeek API pode ser usada como provider HTTP compatível para agentes internos do ASO.

---

### 26A.1 Objetivo

Permitir que o usuário configure:

* vários provedores de LLM;
* várias API keys;
* vários modelos por provider;
* vários agentes CLI instalados;
* capacidades de cada agente;
* permissões por agente;
* prioridade de uso;
* custo estimado;
* fallback entre modelos/agentes;
* execução simultânea em worktrees isolados;
* roteamento automático por tipo de tarefa.

O ASO deve conseguir executar, por exemplo:

```txt
ArchitectureAgent → DeepSeek API
BackendDevelopmentAgent → Claude Code CLI
TestingAgent → Codex CLI
DocumentationAgent → DeepSeek API
ReviewAgent → Claude Code, Codex ou outro modelo forte
```

---

### 26A.2 Diferença entre LLM Provider e CLI Agent

O sistema deve separar claramente dois conceitos.

#### LLM Provider

Um LLM Provider é um serviço de modelo acessado via API.

Exemplos:

* OpenAI;
* Anthropic;
* DeepSeek;
* OpenRouter;
* Gemini;
* Kimi;
* Ollama/local;
* LM Studio/local.

Uso típico:

* planejamento;
* classificação;
* geração de ADR;
* geração de documentação;
* revisão textual;
* análise de requisitos;
* decomposição de tarefas;
* agentes internos com tools controladas pelo ASO.

#### CLI Agent

Um CLI Agent é um agente instalado na máquina que roda no terminal e pode interagir com arquivos, comandos e repositórios.

Exemplos:

* Claude Code;
* Codex CLI;
* Cline;
* Roo Code;
* OpenCode;
* Aider;
* Kimi Code;
* wrappers customizados.

Uso típico:

* modificar código;
* criar arquivos;
* rodar comandos;
* executar testes;
* refatorar;
* corrigir bugs;
* trabalhar em branch/worktree isolado.

---

### 26A.3 Requisitos funcionais

#### RF-26A.1 — Cadastro de LLM Providers

O sistema deve permitir cadastrar provedores de LLM.

Campos mínimos:

```json
{
  "id": "deepseek",
  "name": "DeepSeek",
  "type": "openai_compatible",
  "base_url": "https://api.deepseek.com",
  "api_key_env": "DEEPSEEK_API_KEY",
  "enabled": true,
  "models": [
    {
      "id": "deepseek-chat",
      "role": "fast_generation",
      "max_context_tokens": null,
      "cost_profile": "low"
    },
    {
      "id": "deepseek-reasoner",
      "role": "reasoning",
      "max_context_tokens": null,
      "cost_profile": "medium"
    }
  ]
}
```

#### RF-26A.2 — Cadastro de CLI Agents

O sistema deve permitir cadastrar agentes CLI instalados localmente.

Campos mínimos:

```json
{
  "id": "claude_code",
  "name": "Claude Code",
  "type": "cli_agent",
  "command": "claude",
  "enabled": true,
  "capabilities": [
    "code_edit",
    "repo_analysis",
    "shell_commands",
    "refactor",
    "tests",
    "docs"
  ],
  "requires_worktree": true,
  "supports_resume": true,
  "supports_nudge": true
}
```

#### RF-26A.3 — Verificação de instalação

O ASO deve conseguir verificar se um agente CLI está instalado.

Exemplos:

```bash
claude --version
codex --version
aider --version
opencode --version
```

O resultado deve ser salvo no `AgentRegistry`.

Modelo esperado:

```json
{
  "agent_id": "codex",
  "installed": true,
  "version": "x.y.z",
  "path": "/usr/local/bin/codex",
  "last_checked_at": "2026-07-02T10:00:00Z"
}
```

#### RF-26A.4 — Teste de conexão com API

O ASO deve permitir testar se um provider de API está funcionando.

O teste deve validar:

* API key presente;
* base URL acessível;
* modelo disponível;
* chamada mínima bem-sucedida;
* erro amigável em caso de falha.

#### RF-26A.5 — Mapeamento de papéis para providers/agentes

O usuário deve poder configurar qual provider ou agente será usado por cada papel.

Exemplo:

```yaml
agent_roles:
  ProductStrategyAgent:
    provider: deepseek
    model: deepseek-chat

  ArchitectureDesignAgent:
    provider: deepseek
    model: deepseek-reasoner

  BackendDevelopmentAgent:
    cli_agent: claude_code

  TestingAgent:
    cli_agent: codex

  DocumentationAgent:
    provider: deepseek
    model: deepseek-chat

  ReviewAgent:
    strategy: best_available
    candidates:
      - claude_code
      - codex
      - openai
```

#### RF-26A.6 — Execução simultânea com múltiplos agentes

O ASO deve conseguir executar múltiplos agentes simultaneamente, desde que:

* cada agente tenha um card específico;
* cada agente tenha permissões explícitas;
* cada agente trabalhe em worktree ou sandbox isolado;
* cada execução tenha logs próprios;
* cada execução produza artefatos rastreáveis;
* os diffs sejam comparados antes do merge;
* o `ConflictDetector` valide os resultados;
* o `QualityGateEngine` aprove antes do avanço.

Exemplo:

```txt
Card 1 — Implementar domínio PDF
Executor: Claude Code
Worktree: .aso/worktrees/pdf-backend-claude

Card 2 — Criar testes do módulo PDF
Executor: Codex
Worktree: .aso/worktrees/pdf-tests-codex

Card 3 — Gerar ADR e documentação
Executor: DeepSeek API
Worktree: não necessário
```

#### RF-26A.7 — Roteamento automático de agentes

O `AgentRouter` deve decidir qual provider/agente usar com base em:

* tipo da tarefa;
* linguagem do projeto;
* fase atual;
* risco;
* custo;
* velocidade;
* qualidade esperada;
* capacidades declaradas;
* permissões;
* disponibilidade;
* fallback configurado;
* histórico de sucesso do agente.

Exemplo de decisão:

```json
{
  "card_id": "card_pdf_backend",
  "selected_executor": "claude_code",
  "executor_type": "cli_agent",
  "reason": "Tarefa exige edição real de código backend em repositório local.",
  "fallbacks": ["codex", "local_internal_code_agent"]
}
```

#### RF-26A.8 — Fallback entre agentes

Quando um agente falhar, o ASO deve permitir fallback.

Exemplo:

```txt
Claude Code falhou
↓
ASO registra erro
↓
Card volta para Failed ou Blocked
↓
AgentRouter tenta Codex, se permitido
↓
ReviewAgent valida resultado
```

O fallback não deve ocorrer automaticamente para ações críticas sem validação.

#### RF-26A.9 — Controle de custo

Cada provider deve permitir configurar limites.

Campos recomendados:

```json
{
  "provider_id": "deepseek",
  "daily_budget": 10.00,
  "monthly_budget": 100.00,
  "max_tokens_per_run": 50000,
  "max_parallel_runs": 5,
  "enabled_for_auto_execution": true
}
```

#### RF-26A.10 — Controle de concorrência

O ASO deve permitir limitar quantos agentes rodam ao mesmo tempo.

Exemplo:

```yaml
concurrency:
  max_total_agent_runs: 4
  max_cli_agents: 2
  max_api_agents: 5
  max_agents_per_project: 3
  max_agents_per_orchestration: 4
```

---

### 26A.4 Configuração sugerida

Arquivo sugerido:

```txt
.aso/providers.yaml
```

Exemplo:

```yaml
llm_providers:
  deepseek:
    type: openai_compatible
    base_url: "https://api.deepseek.com"
    api_key_env: "DEEPSEEK_API_KEY"
    enabled: true
    models:
      planner: "deepseek-chat"
      reasoning: "deepseek-reasoner"
      reviewer: "deepseek-reasoner"

  openai:
    type: openai
    api_key_env: "OPENAI_API_KEY"
    enabled: true
    models:
      planner: "gpt-5.5"
      reviewer: "gpt-5.5-thinking"

  anthropic:
    type: anthropic
    api_key_env: "ANTHROPIC_API_KEY"
    enabled: false
    models:
      default: "claude-sonnet"
      reasoning: "claude-opus"

cli_agents:
  claude_code:
    type: cli
    command: "claude"
    enabled: true
    capabilities:
      - code_edit
      - repo_analysis
      - shell_commands
      - refactor
      - tests
      - docs
    requires_worktree: true
    supports_resume: true
    supports_nudge: true

  codex:
    type: cli
    command: "codex"
    enabled: true
    capabilities:
      - code_edit
      - repo_analysis
      - shell_commands
      - tests
      - docs
      - review
    requires_worktree: true
    supports_resume: true
    supports_nudge: true

  aider:
    type: cli
    command: "aider"
    enabled: false
    capabilities:
      - code_edit
      - pair_programming
      - git_diff
    requires_worktree: true

agent_roles:
  OrchestratorAgent:
    provider: deepseek
    model: deepseek-reasoner

  ProductStrategyAgent:
    provider: deepseek
    model: deepseek-chat

  ArchitectureDesignAgent:
    provider: deepseek
    model: deepseek-reasoner

  DataApiContractsAgent:
    provider: deepseek
    model: deepseek-reasoner

  BackendDevelopmentAgent:
    cli_agent: claude_code
    fallback_cli_agents:
      - codex

  TestingAgent:
    cli_agent: codex
    fallback_cli_agents:
      - claude_code

  DocumentationAgent:
    provider: deepseek
    model: deepseek-chat

  ReviewAgent:
    strategy: best_available
    candidates:
      - claude_code
      - codex
      - openai
      - deepseek
```

---

### 26A.5 Execution strategy

O ASO deve suportar quatro estratégias de execução com providers/agentes.

#### 26A.5.1 API-only

Usa apenas providers via API.

Uso:

* planejamento;
* análise;
* documentação;
* revisão;
* decomposição de tasks;
* geração de contexto;
* geração de ADRs.

Exemplo:

```txt
DeepSeek API gera ADR e plano de tasks.
```

#### 26A.5.2 CLI-only

Usa apenas agentes CLI.

Uso:

* implementação;
* refatoração;
* correção de bug;
* testes;
* documentação no repositório.

Exemplo:

```txt
Codex CLI implementa uma task em worktree isolado.
```

#### 26A.5.3 Hybrid

Usa APIs e agentes CLI juntos.

Uso:

* fluxo principal recomendado.

Exemplo:

```txt
DeepSeek planeja
Claude Code implementa
Codex cria testes
DeepSeek documenta
ReviewAgent revisa
```

#### 26A.5.4 Human-guided

O sistema sugere agentes e plano, mas pede confirmação humana antes de executar.

Uso:

* ações críticas;
* projetos sensíveis;
* primeira execução em um repositório;
* mudanças arquiteturais;
* deploy.

---

### 26A.6 Worktree obrigatório para agentes que alteram código

Qualquer agente CLI que possa alterar arquivos deve rodar em worktree isolado, exceto se o usuário explicitamente permitir outro modo.

Exemplo:

```txt
.aso/worktrees/
  orch_123/
    backend_claude/
    tests_codex/
    docs_codex/
```

Regras:

* não executar agentes diretamente na branch principal;
* criar branch por card ou por agente;
* registrar worktree no card;
* registrar branch no card;
* coletar diff após execução;
* rodar testes antes de merge;
* passar por ReviewAgent;
* passar por QualityGateEngine;
* exigir aprovação humana antes de merge na branch principal.

Esse padrão segue a prática de orquestradores modernos de agentes de código, que usam worktrees isolados para permitir concorrência e reduzir conflitos entre execuções paralelas.

---

### 26A.7 Modelo de dados

#### ProviderConfig

```json
{
  "id": "provider_uuid",
  "name": "DeepSeek",
  "type": "openai | anthropic | openai_compatible | local | custom",
  "base_url": "...",
  "api_key_env": "...",
  "enabled": true,
  "default_model": "...",
  "models": [],
  "limits": {},
  "created_at": "...",
  "updated_at": "..."
}
```

#### CliAgentConfig

```json
{
  "id": "cli_agent_uuid",
  "name": "Claude Code",
  "command": "claude",
  "enabled": true,
  "capabilities": [],
  "requires_worktree": true,
  "supports_resume": true,
  "supports_nudge": true,
  "permissions": {},
  "created_at": "...",
  "updated_at": "..."
}
```

#### AgentRoleBinding

```json
{
  "id": "binding_uuid",
  "role": "BackendDevelopmentAgent",
  "executor_type": "llm_provider | cli_agent | strategy",
  "provider_id": null,
  "model": null,
  "cli_agent_id": "claude_code",
  "strategy": null,
  "fallbacks": [],
  "enabled": true
}
```

#### AgentExecutionSelection

```json
{
  "id": "selection_uuid",
  "orchestration_id": "orch_uuid",
  "card_id": "card_uuid",
  "agent_role": "TestingAgent",
  "selected_executor_type": "cli_agent",
  "selected_executor_id": "codex",
  "reason": "Tarefa de testes com alteração real no repositório.",
  "fallbacks": ["claude_code"],
  "created_at": "..."
}
```

---

### 26A.8 API

#### Providers

```txt
GET    /providers
POST   /providers
GET    /providers/{id}
PATCH  /providers/{id}
DELETE /providers/{id}
POST   /providers/{id}/test
GET    /providers/{id}/models
```

#### CLI Agents

```txt
GET    /cli-agents
POST   /cli-agents
GET    /cli-agents/{id}
PATCH  /cli-agents/{id}
DELETE /cli-agents/{id}
POST   /cli-agents/{id}/detect
POST   /cli-agents/{id}/test
GET    /cli-agents/{id}/capabilities
```

#### Role Bindings

```txt
GET    /agent-role-bindings
POST   /agent-role-bindings
PATCH  /agent-role-bindings/{id}
DELETE /agent-role-bindings/{id}
```

#### Routing

```txt
POST   /agent-router/preview
POST   /agent-router/select
```

Exemplo de preview:

```json
{
  "card_id": "card_pdf_tests",
  "phase": "F5",
  "task_type": "tests",
  "requires_code_edit": true
}
```

Resposta:

```json
{
  "recommended_executor": {
    "type": "cli_agent",
    "id": "codex"
  },
  "reason": "Card exige criação de testes e edição de arquivos.",
  "fallbacks": [
    {
      "type": "cli_agent",
      "id": "claude_code"
    }
  ]
}
```

---

### 26A.9 UI

A UI deve ter uma área de configuração chamada:

```txt
Settings → Providers & Agents
```

Ela deve permitir:

* cadastrar API providers;
* testar conexão;
* listar modelos;
* cadastrar agentes CLI;
* detectar instalação local;
* testar execução;
* configurar capacidades;
* configurar permissões;
* configurar papéis;
* configurar fallback;
* configurar limites de custo;
* configurar concorrência;
* visualizar status dos agentes.

A tela deve mostrar algo como:

```txt
LLM Providers

[Enabled] DeepSeek
Type: OpenAI Compatible
Models: deepseek-chat, deepseek-reasoner
Status: Connected

[Enabled] OpenAI
Type: Native
Models: gpt-5.5, gpt-5.5-thinking
Status: Connected

CLI Agents

[Enabled] Claude Code
Command: claude
Status: Installed
Capabilities: code_edit, tests, shell_commands

[Enabled] Codex
Command: codex
Status: Installed
Capabilities: code_edit, tests, docs, review
```

---

### 26A.10 Segurança

Regras obrigatórias:

1. API keys não devem ser salvas em texto puro.
2. Preferir variáveis de ambiente.
3. Nunca exibir API key completa na UI.
4. Permitir testar provider sem revelar segredo.
5. Agente CLI com permissão de escrita deve rodar em worktree.
6. Agente CLI não pode rodar comando destrutivo sem aprovação.
7. O usuário deve aprovar antes de merge na branch principal.
8. O usuário deve aprovar antes de deploy.
9. O usuário deve aprovar antes de alterar secrets.
10. O sistema deve registrar qual provider/agente foi usado em cada card.
11. O sistema deve registrar custo estimado por provider.
12. O sistema deve permitir desabilitar um provider/agente imediatamente.

---

### 26A.11 Observabilidade

Toda execução deve registrar:

```json
{
  "orchestration_id": "...",
  "card_id": "...",
  "agent_role": "BackendDevelopmentAgent",
  "executor_type": "cli_agent",
  "executor_id": "claude_code",
  "model": null,
  "provider": null,
  "worktree": ".aso/worktrees/orch_123/backend_claude",
  "branch": "aso/orch-123/backend-claude",
  "started_at": "...",
  "finished_at": "...",
  "status": "completed | failed | cancelled",
  "token_usage": null,
  "estimated_cost": null,
  "logs_ref": "...",
  "diff_ref": "...",
  "error": null
}
```

Para providers via API:

```json
{
  "orchestration_id": "...",
  "card_id": "...",
  "agent_role": "ArchitectureDesignAgent",
  "executor_type": "llm_provider",
  "provider": "deepseek",
  "model": "deepseek-reasoner",
  "input_tokens": 10000,
  "output_tokens": 2500,
  "estimated_cost": 0.12,
  "status": "completed"
}
```

---

### 26A.12 Critérios de aceite

Este módulo será aceito quando:

1. O usuário conseguir cadastrar pelo menos um provider via API.
2. O usuário conseguir cadastrar pelo menos um agente CLI.
3. O sistema conseguir testar conexão com provider.
4. O sistema conseguir detectar se um agente CLI está instalado.
5. O usuário conseguir mapear papéis para providers/agentes.
6. O `AgentRouter` conseguir recomendar executor para um card.
7. O sistema conseguir usar provider API para uma tarefa de planejamento.
8. O sistema conseguir usar agente CLI para uma tarefa simulada ou real.
9. O sistema conseguir executar dois agentes diferentes na mesma orquestração.
10. Cada agente que altera código deve rodar em worktree isolado.
11. O Kanban deve mostrar qual executor está vinculado ao card.
12. Logs devem indicar provider/agente usado.
13. Fallback deve ser configurável.
14. Permissões devem impedir ações críticas sem aprovação.
15. O usuário deve conseguir desabilitar qualquer provider ou agente.

---

### 26A.13 Exemplo de fluxo completo

Entrada do usuário:

```txt
Criar módulo de geração de PDF na API .NET com storage local e GCP.
```

Configuração:

```txt
DeepSeek API habilitado
Claude Code instalado
Codex instalado
```

Decisão do ASO:

```txt
ArchitectureDesignAgent → DeepSeek Reasoner
DataApiContractsAgent → DeepSeek Reasoner
BackendDevelopmentAgent → Claude Code
TestingAgent → Codex
DocumentationAgent → DeepSeek Chat
ReviewAgent → Claude Code ou Codex
```

Execução:

```txt
1. DeepSeek gera análise técnica e ADR.
2. ASO cria cards no Kanban.
3. ASO cria worktree para Claude Code.
4. Claude Code implementa backend.
5. ASO cria worktree para Codex.
6. Codex cria testes.
7. DeepSeek gera documentação.
8. ASO coleta diffs.
9. ConflictDetector valida conflitos.
10. ReviewAgent revisa.
11. QualityGateEngine valida.
12. Usuário aprova merge.
```

Resultado esperado:

```txt
- Cards concluídos ou bloqueados no Kanban.
- Diffs rastreados por agente.
- ADR criada.
- Testes executados.
- Quality gate aprovado ou falho.
- Snapshot gerado.
- Relatório final consolidado.
```


## 27. Agent Adapter Contract

Todo adapter de agente externo deve implementar contrato semelhante:

```ts
interface AgentAdapter {
  id: string;
  name: string;

  getCapabilities(): AgentCapabilities;

  getLaunchCommand(input: LaunchInput): LaunchCommand;

  getPromptDeliveryStrategy(): PromptDeliveryStrategy;

  startSession(input: StartSessionInput): Promise<AgentSession>;

  restoreSession(sessionId: string): Promise<AgentSession>;

  sendTask(sessionId: string, task: AgentTask): Promise<void>;

  sendNudge(sessionId: string, nudge: AgentNudge): Promise<void>;

  readOutput(sessionId: string): Promise<AgentOutput>;

  stopSession(sessionId: string): Promise<void>;

  collectArtifacts(sessionId: string): Promise<AgentArtifacts>;
}
```

## 28. API mínima

### 28.1 Orchestrations

```txt
POST   /orchestrations
GET    /orchestrations
GET    /orchestrations/{id}
GET    /orchestrations/{id}/context
GET    /orchestrations/{id}/plan
GET    /orchestrations/{id}/timeline
POST   /orchestrations/{id}/resume
POST   /orchestrations/{id}/cancel
POST   /orchestrations/{id}/rollback
POST   /orchestrations/{id}/retry
```

### 28.2 Kanban

```txt
GET    /boards
POST   /boards
GET    /boards/{id}
GET    /boards/{id}/cards
POST   /boards/{id}/cards
PATCH  /cards/{id}
POST   /cards/{id}/move
POST   /cards/{id}/assign-agent
POST   /cards/{id}/run
POST   /cards/{id}/block
POST   /cards/{id}/unblock
```

### 28.3 Agents

```txt
GET    /agents
GET    /agents/{id}
GET    /agents/{id}/runs
POST   /agents/{id}/run
POST   /agent-runs/{id}/cancel
POST   /agent-runs/{id}/nudge
```

### 28.4 Quality Gates

```txt
GET    /orchestrations/{id}/quality-gates
POST   /orchestrations/{id}/quality-gates/run
GET    /quality-gates/{id}
```

### 28.5 ADRs

```txt
GET    /orchestrations/{id}/adrs
POST   /orchestrations/{id}/adrs
GET    /adrs/{id}
PATCH  /adrs/{id}
```

### 28.6 Snapshots

```txt
GET    /orchestrations/{id}/snapshots
POST   /orchestrations/{id}/snapshots
GET    /snapshots/{id}
POST   /snapshots/{id}/restore
GET    /snapshots/{a}/diff/{b}
```

### 28.7 Approvals

```txt
GET    /approvals
GET    /approvals/{id}
POST   /approvals/{id}/approve
POST   /approvals/{id}/reject
```

## 29. Banco de dados mínimo

Tabelas sugeridas:

```txt
projects
orchestrations
orchestrator_contexts
execution_plans
phases
boards
board_columns
kanban_cards
card_dependencies
card_events
agents
agent_runs
agent_messages
agent_tool_calls
agent_outputs
context_patches
conflicts
quality_gate_results
snapshots
adrs
human_approvals
execution_providers
worktrees
pull_requests
ci_events
review_events
audit_events
cost_records
```

## 30. UI mínima

A UI deve possuir:

### 30.1 Dashboard principal

Exibir:

* projetos;
* orquestrações;
* fases F1–F7;
* progresso;
* agentes ativos;
* cards ativos;
* bloqueios;
* approvals pendentes;
* custo;
* status geral.

### 30.2 Kanban

Exibir:

* colunas;
* cards;
* responsáveis;
* agentes;
* status;
* dependências;
* bloqueios;
* PRs;
* CI;
* quality gates.

### 30.3 Tela da orquestração

Exibir:

* timeline;
* fases;
* execution plan;
* contexto;
* cards;
* agentes;
* logs;
* gates;
* snapshots;
* ADRs;
* conflitos;
* approvals.

### 30.4 Tela de agente

Exibir:

* agente;
* capacidades;
* tools permitidas;
* execuções;
* logs;
* artefatos;
* terminal, se houver;
* cards atribuídos.

### 30.5 Tela de contexto

Exibir:

* OrchestratorContext;
* histórico;
* patches;
* diffs;
* seções congeladas;
* snapshots.

### 30.6 Tela de ADRs

Exibir:

* lista de ADRs;
* status;
* fase;
* cards vinculados;
* decisões;
* trade-offs.

### 30.7 Tela de approvals

Exibir:

* ação solicitada;
* agente solicitante;
* risco;
* payload;
* motivo;
* aprovar/rejeitar.

## 31. CLI mínima

Comandos desejados:

```bash
aso init

aso run "Criar módulo PDF na API"

aso status <orchestrationId>

aso board <orchestrationId>

aso resume <orchestrationId>

aso rollback <orchestrationId> --to O3

aso approve <approvalId>

aso agents list

aso snapshots list <orchestrationId>

aso snapshots diff O3 O4

aso adrs list <orchestrationId>
```

## 32. Fluxo esperado: feature evolution

Entrada:

```txt
Criar um módulo de geração de PDF na API .NET, usando storage local e GCP, sem mensageria, com arquitetura hexagonal, baseando-se no legado apenas como referência.
```

Fluxo esperado:

```txt
1. OrchestratorAgent recebe solicitação.
2. MultiAgentDecisionEngine define modo feature-evolution.
3. PhaseController verifica impacto em F2/F3/F4/F5/F6.
4. ArchitectureDesignAgent cria decisão técnica.
5. ADRRegistry registra ADR.
6. DataApiContractsAgent define contratos.
7. Kanban cria cards.
8. BackendDevelopmentAgent implementa.
9. TestingAgent cria testes.
10. DocumentationAgent documenta.
11. ReviewAgent revisa.
12. QualityGateEngine valida.
13. SnapshotEngine gera snapshot.
14. FinalResponseAgent consolida.
```

Cards esperados:

```txt
- ADR: Decidir arquitetura do módulo PDF
- Contract: Definir endpoints de geração e download
- Backend: Implementar domínio PDF
- Backend: Implementar adapters de storage local e GCP
- Backend: Implementar geração síncrona do PDF
- Test: Criar testes unitários e integração
- Docs: Atualizar documentação do módulo
- Review: Revisar segurança, arquitetura e contratos
```

## 33. Observabilidade

Registrar:

* orchestration id;
* project id;
* phase;
* card;
* agent;
* tool;
* provider;
* prompt;
* output;
* patch;
* decision;
* gate result;
* snapshot;
* ADR;
* custo estimado;
* tokens;
* tempo;
* erro;
* retry;
* aprovação humana.

O sistema deve permitir responder:

* por que um agente foi chamado;
* qual agente executou uma task;
* qual card gerou qual PR;
* qual ADR motivou uma implementação;
* qual gate aprovou uma fase;
* qual snapshot congelou uma decisão;
* qual conflito bloqueou a entrega.

## 34. Segurança

Requisitos mínimos:

* tools com permissões por agente;
* aprovação humana para ações críticas;
* logs de auditoria;
* bloqueio de comandos destrutivos;
* proteção de secrets;
* sandbox/worktree por agente;
* validação de input;
* validação de output;
* limite de custo;
* limite de iterações;
* limite de tempo por execução;
* isolamento por projeto.

## 35. Critérios de aceite do MVP 1

O MVP 1 será aceito quando:

1. For possível criar uma orquestração.
2. O sistema gerar um `ExecutionPlan`.
3. O sistema criar um `OrchestratorContext`.
4. O sistema criar um Kanban board para a orquestração.
5. O sistema criar cards automaticamente.
6. O sistema decidir entre single-agent e multi-agent.
7. O sistema executar pelo menos um agente simulado ou real.
8. O agente produzir um `ContextPatch`.
9. O `ContextBus` validar e aplicar o patch.
10. O sistema registrar uma ADR.
11. O sistema rodar um quality gate simples.
12. O sistema gerar um snapshot.
13. O sistema exibir timeline da orquestração.
14. O sistema exibir Kanban.
15. O sistema registrar logs básicos.

## 36. Roadmap

### MVP 1 — Core de governança

Entregar:

* OrchestratorRuntime;
* OrchestratorContext;
* ExecutionPlan;
* Kanban básico;
* AgentRegistry;
* MultiAgentDecisionEngine básico;
* ContextPatch;
* ContextBus;
* ADRRegistry;
* QualityGateEngine básico;
* SnapshotEngine básico;
* logs;
* UI simples ou API funcional.

Não precisa executar código real ainda.

### MVP 2 — Multiagente real

Entregar:

* execução sequencial;
* execução paralela;
* AgentSupervisor;
* ReviewAgent;
* TestingAgent;
* DocumentationAgent;
* ConflictDetector;
* approvals;
* cards movendo automaticamente.

### MVP 3 — Execution Plane

Entregar:

* worktree por task/agente;
* terminal runtime;
* executor local;
* integração inicial com agentes CLI;
* git diff;
* testes;
* lint;
* build;
* PR opcional.

### MVP 4 — Provider inspirado no AgentWrapper

Entregar:

* AgentWrapperExecutionProvider ou provider equivalente;
* adapters;
* PR observer;
* CI observer;
* review observer;
* feedback/nudge para agentes.

### MVP 5 — Produto completo

Entregar:

* F1–F7 completas;
* UI completa;
* snapshots avançados;
* diff de contexto;
* operação F7;
* incident response;
* deploy controlado;
* marketplace futuro de skills/agentes.

## 37. Estrutura sugerida do repositório

```txt
aso-runtime/
  apps/
    api/
    web/
    cli/

  packages/
    core/
      orchestrator/
      phases/
      context/
      kanban/
      agents/
      skills/
      tools/
      gates/
      snapshots/
      adrs/
      conflicts/

    execution/
      providers/
      worktrees/
      terminal/
      git/
      ci/
      pr/

    shared/
      types/
      schemas/
      events/
      utils/

  docs/
    requirements.md
    architecture.md
    adr/
    phases/
    agents/
    kanban/
    api/
    mvp/

  examples/
    pdf-module/
    saas-from-zero/
    incident-response/
```

## 38. Documentos que o agente deve gerar no projeto

O agente implementador deve criar:

```txt
/docs/requirements.md
/docs/architecture.md
/docs/domain-model.md
/docs/api.md
/docs/kanban.md
/docs/agents.md
/docs/context.md
/docs/quality-gates.md
/docs/snapshots.md
/docs/adrs/ADR-0001-runtime-architecture.md
/docs/adrs/ADR-0002-kanban-as-execution-plane.md
/docs/adrs/ADR-0003-contextbus-governance.md
/docs/mvp/mvp-1.md
```

## 39. Instrução para o agente implementador

O agente deve implementar em etapas.

Regras:

1. Não implementar tudo de uma vez.
2. Começar pelo domínio.
3. Criar schemas antes da API.
4. Criar testes do core antes da UI.
5. Não acoplar ASO diretamente ao AgentWrapper no MVP 1.
6. Criar interface de `ExecutionProvider`.
7. Criar provider local/mock primeiro.
8. Criar provider AgentWrapper apenas depois.
9. Toda entidade relevante deve ter ID e timestamps.
10. Toda execução deve ser rastreável.
11. Toda decisão arquitetural relevante deve virar ADR.
12. Todo output de agente deve virar `ContextPatch`.
13. Nenhum agente deve alterar contexto diretamente.
14. Kanban deve refletir o estado real da execução.

## 40. Primeiras tarefas de desenvolvimento

### Task 1 — Criar estrutura base

Criar estrutura do projeto com API, web, CLI e packages.

### Task 2 — Criar modelos de domínio

Implementar entidades:

* Project;
* Orchestration;
* Phase;
* ExecutionPlan;
* KanbanBoard;
* KanbanCard;
* Agent;
* AgentRun;
* ContextPatch;
* QualityGateResult;
* Snapshot;
* ADR;
* Conflict;
* HumanApproval.

### Task 3 — Criar OrchestratorContext

Criar schema versionado e validação.

### Task 4 — Criar Kanban básico

Criar board, colunas e cards.

### Task 5 — Criar ExecutionPlan

Gerar plano a partir de uma solicitação.

### Task 6 — Criar MultiAgentDecisionEngine básico

Decidir single-agent ou multi-agent com justificativa.

### Task 7 — Criar AgentRegistry

Registrar agentes internos.

### Task 8 — Criar AgentExecutor mock

Executar agente simulado retornando output estruturado.

### Task 9 — Criar ContextPatch e ContextBus

Validar e aplicar patches.

### Task 10 — Criar ADRRegistry

Criar e listar ADRs.

### Task 11 — Criar QualityGateEngine básico

Validar critérios simples.

### Task 12 — Criar SnapshotEngine básico

Gerar snapshot após gate aprovado.

### Task 13 — Criar API mínima

Endpoints de orchestration, board, cards, agents, context, gates, snapshots e ADRs.

### Task 14 — Criar UI mínima

Tela com:

* lista de orquestrações;
* board Kanban;
* detalhe da orquestração;
* timeline;
* contexto;
* ADRs;
* gates.

### Task 15 — Criar documentação

Atualizar `/docs`.

## 41. Requisitos de teste

Criar testes unitários para:

* MultiAgentDecisionEngine;
* PhaseController;
* ContextBus;
* ContextPatchValidator;
* QualityGateEngine;
* SnapshotEngine;
* ADRRegistry;
* KanbanCardService;
* AgentSupervisor;
* ConflictDetector.

Criar testes de integração para:

* criar orquestração;
* gerar execution plan;
* criar board;
* criar cards;
* executar agente mock;
* aplicar patch;
* gerar ADR;
* rodar gate;
* gerar snapshot.

## 42. Definition of Done

Uma entrega só é considerada pronta se:

* compila;
* testes passam;
* lint passa;
* documentação atualizada;
* endpoints testados;
* logs mínimos presentes;
* erros tratados;
* não há tool destrutiva sem approval;
* contexto não é alterado diretamente por agente;
* Kanban reflete estado da execução;
* ADR criada quando houver decisão relevante.

## 43. Decisão estratégica inicial

A estratégia inicial deve ser:

```txt
1. Criar ASO Runtime separado.
2. Usar AgentWrapper como referência operacional.
3. Não fazer fork no início.
4. Implementar ExecutionProvider abstrato.
5. Implementar LocalMockExecutionProvider primeiro.
6. Implementar LocalCliExecutionProvider depois.
7. Implementar AgentWrapperExecutionProvider somente após validar o core.
```

## 44. Referências consultadas

* AgentWrapper/agent-orchestrator — runtime para agentes de código paralelos, worktrees, PR/CI/review feedback e adapters.
* OpenAI Agents SDK — agentes, tools, handoffs, guardrails e orquestração.
* LangGraph — workflows e agentes stateful, persistência e padrões como routing, parallelization e orchestrator-worker.
* Microsoft Agent Framework — padrões sequential, concurrent, handoff, group chat e magentic.

## 45. Resultado esperado

Ao final da primeira versão útil, o usuário deve conseguir:

1. Criar uma orquestração.
2. Descrever uma demanda de software.
3. Ver o ASO decompor a demanda.
4. Ver cards no Kanban.
5. Ver agentes atribuídos.
6. Rodar agentes simulados ou reais.
7. Ver contexto sendo atualizado por patches.
8. Ver ADRs sendo criadas.
9. Ver quality gates aprovando ou bloqueando.
10. Ver snapshots sendo gerados.
11. Ver uma resposta final consolidada da execução.

O produto final deve evoluir para um sistema onde múltiplos agentes trabalham em múltiplas tarefas, controlados por Kanban, contexto, decisões, gates e snapshots, cobrindo a engenharia de software de ponta a ponta.
