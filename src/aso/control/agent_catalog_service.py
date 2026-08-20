"""Catálogo de agentes (Tela 30, wf §32, ADR-0053).

Definições de agente são configuração do runtime, não estado de uma
orquestração específica — mesmo raciocínio de `RoutingRuleService`:
persistidas por porta própria (`AgentDefinitionRepository`), fora do
ContextBus. Diferente das regras de roteamento, porém, este catálogo É a
fonte de verdade das permissões reais (ver `AgentRegistry.seed_from_catalog`,
`agents/registry.py`) — validação aqui é o único guarda-chuva antes de uma
definição alterar o que um agente pode escrever via ContextBus.
"""

from __future__ import annotations

import threading

from aso.agents.models import AgentDefinition, AgentDefinitionError
from aso.agents.registry import AgentRegistry
from aso.control.decision_engine import _DOMAIN_AGENT
from aso.persistence.ports import AgentDefinitionRepository
from aso.shared.ids import now_iso

# Vocabulário fechado, mesmo cuidado de `triage.py::_DOMINIOS_VALIDOS` — nunca
# redefinir com valores próprios, ou "categorias de tarefa" perde qualquer
# relação com o vocabulário que o resto do runtime já usa para roteamento.
_CATEGORIAS_VALIDAS = frozenset(_DOMAIN_AGENT)
# Derivado do próprio AgentRegistry (nunca uma lista duplicada à mão — isso já
# causou um bug real nesta ADR: `RequirementsAgent` ficou de fora de uma
# curadoria manual e toda definição vinculada a ele era recusada).
_ROLES_REGISTRY = AgentRegistry()
_ROLES_REGISTRY.seed_defaults()
_ROLES_VALIDOS = frozenset(spec.role for spec in _ROLES_REGISTRY.list_all())


def validar_definicao(definicao: AgentDefinition) -> None:
    """Recusa definição sem nome, com `role` que não existe no `AgentRegistry`
    real, ou com categoria de tarefa fora do vocabulário — nunca persistida
    "meio inválida" para ser descoberta só quando falhar em produção."""
    if not definicao.nome.strip():
        raise AgentDefinitionError("Informe um nome para o agente.")
    if definicao.role and definicao.role not in _ROLES_VALIDOS:
        raise AgentDefinitionError(
            f"'{definicao.role}' não é um papel real do AgentRegistry — "
            "definições não podem inventar um papel novo, só vincular um existente."
        )
    fora_do_vocabulario = set(definicao.categorias_tarefa) - _CATEGORIAS_VALIDAS
    if fora_do_vocabulario:
        raise AgentDefinitionError(
            f"Categoria(s) de tarefa fora do vocabulário: {sorted(fora_do_vocabulario)}."
        )
    if definicao.limite_custo_usd is not None and definicao.limite_custo_usd < 0:
        raise AgentDefinitionError("Limite de custo não pode ser negativo.")
    if definicao.limite_tentativas is not None and definicao.limite_tentativas < 1:
        raise AgentDefinitionError("Limite de tentativas precisa ser pelo menos 1.")


class AgentCatalogService:
    """Coordena validação, persistência e concorrência do catálogo de agentes."""

    def __init__(self, repository: AgentDefinitionRepository) -> None:
        self._repo = repository
        self._lock = threading.RLock()

    def _get(self, definition_id: str) -> AgentDefinition:
        definicao = self._repo.get_definition(definition_id)
        if definicao is None:
            raise LookupError("Definição de agente inexistente.")
        return definicao

    def _verificar_role_unico(self, role: str, *, excluir_id: str | None) -> None:
        """Cada `role` real só pode ter UMA definição ATIVA por vez (Tela 30,
        ADR-0053) — sem isto, `AgentRegistry.seed_from_catalog` teria que
        escolher "a última na ordem de iteração" em silêncio quando duas
        definições disputassem o mesmo papel, o que é surpreendente e nunca
        o que o operador pretendia ao criar uma segunda definição."""
        if not role:
            return
        conflito = next(
            (
                d
                for d in self._repo.list_definitions(only_active=True)
                if d.role == role and d.id != excluir_id
            ),
            None,
        )
        if conflito is not None:
            raise AgentDefinitionError(
                f"O papel '{role}' já está vinculado à definição ativa "
                f"'{conflito.nome}' — desative-a antes de vincular outra."
            )

    def list_definitions(self, *, only_active: bool = False) -> list[AgentDefinition]:
        return self._repo.list_definitions(only_active=only_active)

    def get(self, definition_id: str) -> AgentDefinition:
        return self._get(definition_id)

    def create(
        self,
        *,
        nome: str,
        tipo: str = "",
        funcao: str = "",
        plataforma: str = "",
        role: str = "",
        modelos_permitidos: list[str] | None = None,
        efforts_permitidos: list[str] | None = None,
        ferramentas: list[str] | None = None,
        permissoes: list[str] | None = None,
        projetos: list[str] | None = None,
        categorias_tarefa: list[str] | None = None,
        limite_custo_usd: float | None = None,
        limite_tentativas: int | None = None,
        exige_supervisao: bool = False,
        ativo: bool = True,
        actor: str,
    ) -> AgentDefinition:
        with self._lock:
            definicao = AgentDefinition(
                nome=nome,
                tipo=tipo,
                funcao=funcao,
                plataforma=plataforma,
                role=role,
                modelos_permitidos=list(modelos_permitidos or []),
                efforts_permitidos=list(efforts_permitidos or []),
                ferramentas=list(ferramentas or []),
                permissoes=list(permissoes or []),
                projetos=list(projetos or []),
                categorias_tarefa=list(categorias_tarefa or []),
                limite_custo_usd=limite_custo_usd,
                limite_tentativas=limite_tentativas,
                exige_supervisao=exige_supervisao,
                ativo=ativo,
                created_by=actor,
            )
            validar_definicao(definicao)
            if ativo:
                self._verificar_role_unico(role, excluir_id=None)
            self._repo.save_definition(definicao)
            return definicao

    def update(
        self,
        definition_id: str,
        *,
        nome: str,
        tipo: str = "",
        funcao: str = "",
        plataforma: str = "",
        role: str = "",
        modelos_permitidos: list[str] | None = None,
        efforts_permitidos: list[str] | None = None,
        ferramentas: list[str] | None = None,
        permissoes: list[str] | None = None,
        projetos: list[str] | None = None,
        categorias_tarefa: list[str] | None = None,
        limite_custo_usd: float | None = None,
        limite_tentativas: int | None = None,
        exige_supervisao: bool = False,
        ativo: bool = True,
    ) -> AgentDefinition:
        with self._lock:
            atual = self._get(definition_id)
            # Bug real (code-review ultra): `list(x or [])` tratava tanto "campo
            # omitido" (None) quanto "lista vazia enviada de propósito" como a
            # MESMA coisa — um PUT que só queria mudar `nome`/`ativo` e nem
            # tocava `ferramentas`/`permissoes` na UI acabava zerando as duas,
            # revogando a permissão real do papel (`seed_from_catalog` aplica
            # isto direto no ContextBus). `None` agora preserva o valor atual —
            # só uma lista explícita (mesmo `[]`) substitui.
            atualizada = atual.model_copy(
                update={
                    "nome": nome,
                    "tipo": tipo,
                    "funcao": funcao,
                    "plataforma": plataforma,
                    "role": role,
                    "modelos_permitidos": (
                        list(modelos_permitidos)
                        if modelos_permitidos is not None
                        else atual.modelos_permitidos
                    ),
                    "efforts_permitidos": (
                        list(efforts_permitidos)
                        if efforts_permitidos is not None
                        else atual.efforts_permitidos
                    ),
                    "ferramentas": (
                        list(ferramentas) if ferramentas is not None else atual.ferramentas
                    ),
                    "permissoes": (
                        list(permissoes) if permissoes is not None else atual.permissoes
                    ),
                    "projetos": list(projetos) if projetos is not None else atual.projetos,
                    "categorias_tarefa": (
                        list(categorias_tarefa)
                        if categorias_tarefa is not None
                        else atual.categorias_tarefa
                    ),
                    "limite_custo_usd": limite_custo_usd,
                    "limite_tentativas": limite_tentativas,
                    "exige_supervisao": exige_supervisao,
                    "ativo": ativo,
                    "updated_at": now_iso(),
                }
            )
            validar_definicao(atualizada)
            if ativo:
                self._verificar_role_unico(role, excluir_id=definition_id)
            self._repo.save_definition(atualizada, before_updated_at=atual.updated_at)
            return atualizada

    def delete(self, definition_id: str) -> None:
        with self._lock:
            self._get(definition_id)
            self._repo.delete_definition(definition_id)

    def seed_examples_if_empty(self) -> None:
        """14 agentes-exemplo do wf §32.2 (Tela 30, ADR-0053) — só roda quando
        o catálogo está vazio (idempotente: nunca sobrescreve edição do
        operador). `ferramentas`/`permissoes` dos 11 vinculados a um `role`
        real são copiadas VERBATIM do hardcoded de `agents/registry.py`, para
        o primeiro boot não mudar nenhuma permissão em relação a antes desta
        ADR — só passa a existir um catálogo editável por cima."""
        with self._lock:
            if self._repo.list_definitions():
                return
            for dados in _AGENTES_EXEMPLO:
                definicao = AgentDefinition(created_by="system", **dados)  # type: ignore[arg-type]
                validar_definicao(definicao)
                self._repo.save_definition(definicao)


# wf §32.2 — os 14 nomes, na ordem do wireframe. `role` vazio = sem papel real
# correspondente hoje (Discovery técnico/Deploy/Incidentes — nunca inventamos
# um role novo no AgentRegistry só para preencher isto, ADR-0053).
_AGENTES_EXEMPLO: tuple[dict[str, object], ...] = (
    {
        "nome": "Orquestrador",
        "tipo": "governanca",
        "funcao": "Coordena a esteira entre fases e agentes.",
        "role": "OrchestratorAgent",
        "permissoes": ["orchestration"],
    },
    {
        "nome": "Discovery técnico",
        "tipo": "descoberta",
        "funcao": "Investiga viabilidade técnica antes da especificação (§3/§4).",
    },
    {
        "nome": "Arquiteto",
        "tipo": "arquitetura",
        "funcao": "Decide estrutura, componentes e ADRs.",
        "role": "ArchitectureDesignAgent",
        "permissoes": ["architecture"],
        "categorias_tarefa": ["architecture"],
    },
    {
        "nome": "Analista de requisitos",
        "tipo": "descoberta",
        "funcao": "Formaliza requisitos e escopo.",
        "role": "RequirementsAgent",
        "permissoes": ["requirements", "scope"],
    },
    {
        "nome": "Desenvolvedor backend",
        "tipo": "desenvolvimento",
        "funcao": "Implementa lógica de servidor, dados e integrações.",
        "role": "BackendDevelopmentAgent",
        "ferramentas": ["read_file", "write_file", "run_tests", "run_lint", "run_build"],
        "permissoes": ["engineering"],
        "categorias_tarefa": ["backend"],
        "exige_supervisao": True,
    },
    {
        "nome": "Desenvolvedor frontend",
        "tipo": "desenvolvimento",
        "funcao": "Implementa interface e experiência do usuário.",
        "role": "FrontendDevelopmentAgent",
        "permissoes": ["engineering", "ux"],
        "categorias_tarefa": ["frontend"],
    },
    {
        "nome": "Especialista em banco",
        "tipo": "desenvolvimento",
        "funcao": "Modela dados e contratos de persistência.",
        "role": "DatabaseAgent",
        "permissoes": ["contracts", "engineering"],
        "categorias_tarefa": ["database"],
    },
    {
        "nome": "Especialista em infraestrutura",
        "tipo": "infraestrutura",
        "funcao": "Cuida de implantação, ambientes e operação.",
        "role": "DevOpsAgent",
        "permissoes": ["operations"],
        "categorias_tarefa": ["devops"],
        "exige_supervisao": True,
    },
    {
        "nome": "QA",
        "tipo": "qualidade",
        "funcao": "Valida comportamento e cobertura de testes.",
        "role": "TestingAgent",
        "permissoes": ["quality", "engineering"],
        "categorias_tarefa": ["tests"],
    },
    {
        "nome": "Code reviewer",
        "tipo": "qualidade",
        "funcao": "Revisão independente de código antes do merge (§14).",
        "role": "ReviewAgent",
        "permissoes": ["quality"],
    },
    {
        "nome": "Segurança",
        "tipo": "qualidade",
        "funcao": "Avalia risco e conformidade de segurança.",
        "role": "SecurityAgent",
        "permissoes": ["architecture", "quality"],
        "categorias_tarefa": ["security"],
        "exige_supervisao": True,
    },
    {
        "nome": "Deploy",
        "tipo": "infraestrutura",
        "funcao": "Implantação — hoje coberta por 'Especialista em infraestrutura' "
        "(DevOpsAgent); sem papel técnico dedicado ainda.",
    },
    {
        "nome": "Incidentes",
        "tipo": "operacao",
        "funcao": "Investigação de causa raiz pós-incidente (§21).",
    },
    {
        "nome": "Documentação",
        "tipo": "documentacao",
        "funcao": "Produz e mantém documentação técnica.",
        "role": "DocumentationAgent",
        "permissoes": ["engineering", "agentic"],
        "categorias_tarefa": ["docs"],
    },
)
