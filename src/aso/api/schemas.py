"""Corpos de requisição da API v1 (MEL-32 passo 10): modelos Pydantic das rotas.

Separados de `app.py` para que cada router importe só o que usa; os nomes das classes
são os mesmos (o contrato OpenAPI referencia os schemas por nome).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from aso.control.routing_rules import RoutingAction, RoutingCondition
from aso.shared.types import CardType, ExecutionMode, PatchType, Phase, RiskLevel


class CreateOrchestrationBody(BaseModel):
    user_request: str
    project_id: str | None = None
    # Pasta de trabalho (workspace) desta orquestração; validada/normalizada no create.
    target_path: str | None = None
    execution_mode: ExecutionMode | None = None
    executor: str | None = None
    effort: str | None = None
    validation_command: str | None = None
    # Tela 03 (Cadastro completo, wf §5.2, ADR-0039): quando presente, a ficha é
    # usada tal como enviada — SEM re-triagem (o solicitante já preencheu a ficha
    # à mão; rodar o agente de triagem por cima descartaria isso). Ausente
    # (comportamento de sempre, ex. `nova.html`): a demanda em texto livre passa
    # pela triagem normalmente (`create_with_triage`).
    demand_brief: dict[str, Any] | None = None
    # Tela 03: orçamento definido já na criação, em vez de só depois via
    # `PUT .../budget`. `None` preserva o default de ambiente de sempre.
    orcamento_usd: float | None = None


class AnalyzeFolderBody(BaseModel):
    executor: str | None = None
    effort: str | None = None
    # `git init` na pasta do usuário exige confirmação explícita (ADR-0062).
    inicializar_git: bool = False


class ExecutionSettingsBody(BaseModel):
    executor: str | None = None
    effort: str | None = None
    validation_command: str | None = None


class AgentAssignmentBody(BaseModel):
    """Executor de uma etapa da esteira (ou do nomeador). Effort vazio = o do perfil."""

    executor: str
    effort: str | None = None


class RetriageBody(BaseModel):
    """Re-triagem (POST .../brief): agente opcional, cai na resolução padrão sem ele."""

    executor: str | None = None
    effort: str | None = None


class ClassificationBody(BaseModel):
    """Edição pontual da classificação (Tela 05, wf §7, ADR-0044) — todos os campos
    opcionais, só os informados mudam."""

    tipo: str | None = None
    risco: RiskLevel | None = None
    complexidade: str | None = None
    impactos: list[str] | None = None
    dominios: list[str] | None = None


class DiscoveryRunBody(BaseModel):
    """Roda o discovery (POST .../discovery/run); tudo opcional."""

    executor: str | None = None
    effort: str | None = None


class DiscoveryDecideBody(BaseModel):
    """Decide a aprovação humana do discovery (ADR-0020, §4)."""

    approved: bool
    comentario: str = ""


class SpecRunBody(BaseModel):
    """Gera/regenera a especificação (POST .../spec/run); tudo opcional."""

    executor: str | None = None
    effort: str | None = None


class SpecReviewBody(BaseModel):
    """Roda a revisão documental sobre a especificação corrente (ADR-0021, §6)."""

    executor: str | None = None


class SpecApproveBody(BaseModel):
    """Decisão humana da especificação quando o ciclo do §6 escalou (ADR-0021, §4.4)."""

    approved: bool
    comentario: str = ""


class DocumentoSaveBody(BaseModel):
    """Salva uma nova versão de um documento (Tela 08, wf §10.3, ADR-0046)."""

    conteudo_markdown: str
    autor: str
    referencias_codigo: list[str] = []
    referencias_cards: list[str] = []
    referencias_documentos: list[str] = []


class DocumentoReviewBody(BaseModel):
    """Roda o checklist do revisor sobre a versão corrente (wf §11, ADR-0046)."""

    executor: str | None = None


class DocumentoCommentBody(BaseModel):
    """Comentário ancorado num documento — os 8 campos do wf §10.3/§11.3."""

    autor: str
    tipo: str
    severidade: str
    descricao: str
    trecho_relacionado: str = ""
    acao_solicitada: str = ""


class DocumentoCommentResolveBody(BaseModel):
    resposta_do_autor: str = ""


class ValidationCheckBody(BaseModel):
    """Uma verificação nomeada da bateria do §12 (ADR-0022)."""

    nome: str
    comando: str
    categoria: str = "testes"
    bloqueante: bool = True


class ValidationChecksBody(BaseModel):
    """Substitui a bateria inteira (PUT .../validation-checks)."""

    checks: list[ValidationCheckBody]


class DeployConfigBody(BaseModel):
    """Configura a implantação (ADR-0023, §18-22); tudo opcional — só altera o
    que for enviado, mesmo padrão de `ExecutionSettingsBody`."""

    command: str | None = None
    environment: str | None = None
    health_checks: list[ValidationCheckBody] | None = None
    rollback_command: str | None = None


class DeployRunBody(BaseModel):
    """Roda a implantação (POST .../deploy/run); tudo opcional.

    `estagio` só tem efeito com pipeline configurado (§19, ADR-0029): nomeia qual
    estágio rodar; omitido, resolve para o primeiro pendente (avanço governado).
    """

    environment: str | None = None
    estagio: str | None = None
    versao_app: str = ""
    commit: str = ""
    branch: str = ""


class EnvironmentBody(BaseModel):
    """Um estágio do pipeline de implantação (§19, wf §25, ADR-0029)."""

    chave: str
    nome: str = ""
    ordem: int = 1
    comando: str | None = None
    health_checks: list[ValidationCheckBody] = []
    rollback_command: str | None = None
    requer_aprovacao_humana: bool = False


class DeployPipelineBody(BaseModel):
    """Configura o pipeline inteiro (PUT .../deploy/pipeline) — lista vazia volta
    ao monoambiente legado (ADR-0023)."""

    estagios: list[EnvironmentBody] = []


class DeployApproveBody(BaseModel):
    """Aceite final da implantação (ADR-0023, §22) — ação crítica, exige admin."""

    approved: bool
    comentario: str = ""
    # Sub-tipo do aceite humano (Tela 26, wf §28.2, ADR-0050) — opcional.
    tipo_aceite: str = ""


class DeployRollbackBody(BaseModel):
    """Reverte a última implantação (ADR-0023, §21) — ação crítica, exige admin."""

    reason: str
    # Estratégia escolhida (Tela 25, wf §27.1, ADR-0050) — opcional, descritiva.
    estrategia: str = ""


class IncidentInvestigateBody(BaseModel):
    """Marca um incidente como em investigação (§21, ADR-0032)."""

    detalhe: str = ""


class IncidentResolveBody(BaseModel):
    """Resolve um incidente com a causa raiz identificada (§21, ADR-0032)."""

    causa_raiz: str


class BudgetBody(BaseModel):
    """Eleva (ou remove) o teto de gasto (ADR-0026) — ação crítica, exige admin."""

    teto_usd: float | None = None


class QaCheckBody(BaseModel):
    """Registra uma verificação manual de QA (§16, plano de teste do wf §22.1,
    ADR-0049)."""

    cenario: str
    titulo: str = ""
    pre_condicoes: str = ""
    passos: list[str] = []
    ambiente: str = ""
    resultado_esperado: str = ""
    resultado_obtido: str = ""
    evidencias: list[str] = []
    gravidade: str = "media"
    status: str = "pendente"
    tipo_responsavel: str = "humano"


class QaFailBody(BaseModel):
    """Reprova uma verificação de QA já registrada (§17) — cria o bug vinculado."""

    resultado_obtido: str = ""
    evidencias: list[str] = []
    gravidade: str | None = None


class BugReportBody(BaseModel):
    """Registro manual de bug (Tela 21, wf §23, ADR-0049)."""

    titulo: str
    cenario: str = ""
    passos_para_reproduzir: list[str] = []
    ambiente: str = ""
    resultado_atual: str = ""
    resultado_esperado: str = ""
    evidencias: list[str] = []
    gravidade: str = "media"
    impacto: str = ""
    frequencia: str = ""
    agente_sugerido: str = ""
    retorno_de_fluxo: str = "retornar_implementacao"


class RunReviewBody(BaseModel):
    """Roda o agente revisor sobre o diff da PR (POST .../review/run); tudo opcional."""

    executor: str | None = None
    effort: str | None = None


class ReviewStatusBody(BaseModel):
    """Reporta o resultado da revisão (ADR-0017): `justificativa` exige papel admin."""

    status: str
    justificativa: str = ""


class CreateProjectBody(BaseModel):
    name: str
    description: str = ""
    target_path: str


class UpdateProjectBody(BaseModel):
    name: str | None = None
    description: str | None = None
    target_path: str | None = None


class RestoreProjectBody(BaseModel):
    target_path: str | None = None


class PlanBody(BaseModel):
    idea: str


class RunGateBody(BaseModel):
    phase: Phase | None = None


class RunPhaseBody(BaseModel):
    phase: Phase | None = None
    executor: str | None = None
    effort: str | None = None


class AutopilotBody(BaseModel):
    executor: str | None = None
    effort: str | None = None
    inicializar_git: bool = False  # ADR-0062: autopilot pode rodar o docs-first


class ExecutorBody(BaseModel):
    name: str
    kind: str = "cli"  # mock | llm | cli
    provider: str = ""
    model: str = ""
    effort: str = "medium"
    command: str = ""
    base_url: str = ""
    api_key_env: str = ""
    is_default: bool = False
    # ADR-0076: campos estruturados em vez de flags digitadas no comando.
    streaming: bool = False
    permissao_escrita: str = ""  # "" | nenhuma | edicoes | total
    candidato: bool = False


class RaceBody(BaseModel):
    """Corrida de candidatos (§26A.6): perfis do catálogo; vazio = perfis `candidato`."""

    executores: list[str] | None = None


class RoutingRuleBody(BaseModel):
    """Corpo de criação/edição de uma regra de roteamento (§33, ADR-0028)."""

    nome: str
    descricao: str = ""
    ativa: bool = True
    precedencia: int = 100
    condicoes: list[RoutingCondition] = []
    acao: RoutingAction = RoutingAction()


class RoutingRulePreviewBody(BaseModel):
    """Corpo da pré-visualização (Tela 31, wf §33.2, ADR-0042) — regra ainda não
    salva, só as condições (e opcionalmente a ação, ignorada pelo match)."""

    condicoes: list[RoutingCondition] = []
    acao: RoutingAction = RoutingAction()


class RoutingRuleReorderBody(BaseModel):
    """Nova ordem visual das regras (Tela 31, ADR-0042) — lista de ids."""

    ordem: list[str]


class AgentDefinitionBody(BaseModel):
    """Corpo de criação/edição de uma definição de agente (Tela 30, wf §32,
    ADR-0053) — ação crítica (fonte de verdade das permissões reais), exige
    papel admin.

    Os campos de lista usam `None` (ausente/omitido no JSON), não `[]`, como
    default — bug real (code-review ultra): com default `[]`, um PUT que só
    queria mudar `nome`/`ativo` e omitiu `ferramentas`/`permissoes` revogava
    silenciosamente as permissões reais do papel (`AgentRegistry.seed_from_catalog`
    aplica exatamente o que está aqui). `create_agent_definition` continua
    tratando `None` como lista vazia (definição nova sem nada configurado ainda);
    `update_agent_definition` trata `None` como "não mude este campo" — só uma
    lista explícita (inclusive `[]` explícito) substitui o valor atual.
    """

    nome: str
    tipo: str = ""
    funcao: str = ""
    plataforma: str = ""
    role: str = ""
    modelos_permitidos: list[str] | None = None
    efforts_permitidos: list[str] | None = None
    ferramentas: list[str] | None = None
    permissoes: list[str] | None = None
    projetos: list[str] | None = None
    categorias_tarefa: list[str] | None = None
    limite_custo_usd: float | None = None
    limite_tentativas: int | None = None
    exige_supervisao: bool = False
    ativo: bool = True


class FeedbackBody(BaseModel):
    text: str
    card_type: str = "Improvement"


class RollbackBody(BaseModel):
    to_snapshot: str


class RestoreSectionBody(BaseModel):
    section: str


class ApprovalBody(BaseModel):
    action: str
    risk: str = "medium"
    reason: str = ""


class CreateCardBody(BaseModel):
    """Tela 10 (Estrutura da demanda, wf §12, ADR-0040): cria um item em
    qualquer nível da hierarquia."""

    title: str
    type: CardType = CardType.TASK
    parent_id: str | None = None
    description: str = ""


class AssignAgentBody(BaseModel):
    agent: str


class MoveBody(BaseModel):
    to_column: str


class BlockBody(BaseModel):
    reason: str = ""


class PauseBody(BaseModel):
    """Pausar/retomar (Tela 15, wf §17.2, ADR-0048)."""

    pausado: bool = True


class AddContextBody(BaseModel):
    """Adicionar contexto (Tela 15, wf §17.2, ADR-0048)."""

    texto: str


class RequestHelpBody(BaseModel):
    """Solicitar ajuda (Tela 15, wf §17.2, ADR-0048)."""

    reason: str = ""


class OpenPrBody(BaseModel):
    branch: str | None = None
    title: str = ""


class StatusBody(BaseModel):
    status: str


class CIStatusBody(BaseModel):
    """CI declarada (ADR-0056): `passed` exige papel admin e `justificativa`."""

    status: str
    justificativa: str = ""


class ContextPatchBody(BaseModel):
    agent: str
    phase: Phase
    patch_type: PatchType
    target_path: str
    content: Any = None
    requires_adr: bool = False
    requires_approval: bool = False
    linked_adrs: list[str] = []
    card_id: str | None = None
