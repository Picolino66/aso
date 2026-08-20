"""Catálogo de agentes (Tela 30, wf §32, ADR-0053)."""

from __future__ import annotations

import pytest

from aso.agents.models import AgentDefinition, AgentDefinitionError
from aso.agents.registry import AgentRegistry
from aso.control.agent_catalog_service import validar_definicao
from aso.control.orchestration_service import OrchestrationService


def test_validar_definicao_recusa_sem_nome() -> None:
    with pytest.raises(AgentDefinitionError, match="nome"):
        validar_definicao(AgentDefinition(nome="  "))


def test_validar_definicao_recusa_role_inventado() -> None:
    with pytest.raises(AgentDefinitionError, match="não é um papel real"):
        validar_definicao(AgentDefinition(nome="X", role="AgenteFalso"))


def test_validar_definicao_recusa_categoria_fora_do_vocabulario() -> None:
    with pytest.raises(AgentDefinitionError, match="fora do vocabulário"):
        validar_definicao(AgentDefinition(nome="X", categorias_tarefa=["fabricado"]))


def test_validar_definicao_recusa_limites_invalidos() -> None:
    with pytest.raises(AgentDefinitionError, match="custo"):
        validar_definicao(AgentDefinition(nome="X", limite_custo_usd=-1.0))
    with pytest.raises(AgentDefinitionError, match="tentativas"):
        validar_definicao(AgentDefinition(nome="X", limite_tentativas=0))


def test_validar_definicao_aceita_role_real_e_categoria_valida() -> None:
    validar_definicao(
        AgentDefinition(nome="X", role="BackendDevelopmentAgent", categorias_tarefa=["backend"])
    )  # não levanta


# --------------------------------------------------- update parcial (bug real, ADR-0053)


def test_update_com_ferramentas_none_preserva_as_existentes() -> None:
    """Code-review ultra: `AgentCatalogService.update` tratava `None` (campo
    omitido) igual a lista vazia, zerando `ferramentas`/`permissoes` reais de um
    PUT que só queria mudar outro campo — revogação silenciosa de permissão."""
    svc = OrchestrationService()
    criada = svc.create_agent_definition(
        nome="Especialista",
        role="ConflictResolutionAgent",
        ferramentas=["read_file", "write_file"],
        permissoes=["engineering"],
        actor="op",
    )

    atualizada = svc.update_agent_definition(
        criada["id"], nome="Especialista renomeado", role="ConflictResolutionAgent"
    )

    assert atualizada["nome"] == "Especialista renomeado"
    assert atualizada["ferramentas"] == ["read_file", "write_file"]
    assert atualizada["permissoes"] == ["engineering"]


def test_update_com_ferramentas_lista_explicita_substitui_de_verdade() -> None:
    svc = OrchestrationService()
    criada = svc.create_agent_definition(
        nome="Especialista",
        role="ConflictResolutionAgent",
        ferramentas=["read_file"],
        permissoes=["engineering"],
        actor="op",
    )

    atualizada = svc.update_agent_definition(
        criada["id"],
        nome="Especialista",
        role="ConflictResolutionAgent",
        ferramentas=[],
    )

    assert atualizada["ferramentas"] == []
    assert atualizada["permissoes"] == ["engineering"]  # não tocado, preservado


# ------------------------------------------------- AgentRegistry.seed_from_catalog


def test_seed_from_catalog_sem_definicoes_e_identico_ao_hardcoded() -> None:
    com_catalogo = AgentRegistry()
    com_catalogo.seed_from_catalog([])
    baseline = AgentRegistry()
    baseline.seed_defaults()
    assert com_catalogo.permission_map() == baseline.permission_map()


def test_seed_from_catalog_definicao_ativa_sobrescreve_o_papel() -> None:
    registry = AgentRegistry()
    definicao = AgentDefinition(
        nome="Backend customizado",
        role="BackendDevelopmentAgent",
        ferramentas=["read_file"],
        permissoes=["engineering_only"],
    )
    registry.seed_from_catalog([definicao])
    spec = registry.get("BackendDevelopmentAgent")
    assert spec is not None
    assert spec.allowed_tools == ["read_file"]
    assert spec.context_sections == ["engineering_only"]


def test_seed_from_catalog_definicao_inativa_e_ignorada() -> None:
    registry = AgentRegistry()
    definicao = AgentDefinition(
        nome="Backend desativado",
        role="BackendDevelopmentAgent",
        permissoes=["engineering_only"],
        ativo=False,
    )
    registry.seed_from_catalog([definicao])
    spec = registry.get("BackendDevelopmentAgent")
    assert spec is not None
    assert spec.context_sections == ["engineering"]  # hardcoded original, não sobrescrito


def test_seed_from_catalog_definicao_sem_role_nao_afeta_registry() -> None:
    registry = AgentRegistry()
    definicao = AgentDefinition(nome="Discovery técnico", permissoes=["algo"])
    registry.seed_from_catalog([definicao])
    baseline = AgentRegistry()
    baseline.seed_defaults()
    assert registry.permission_map() == baseline.permission_map()


# -------------------------------------------------------------- seed dos 14 exemplos


def test_seed_examples_produz_quatorze_agentes_e_e_idempotente() -> None:
    svc = OrchestrationService()
    primeira = svc.list_agent_definitions()
    assert len(primeira) == 14
    svc._agent_catalog.seed_examples_if_empty()  # noqa: SLF001 — idempotência
    assert len(svc.list_agent_definitions()) == 14


def test_seed_examples_nao_muda_o_permission_map_original() -> None:
    """O catálogo pré-provisionado é não-destrutivo: primeiro boot produz o
    MESMO mapa de permissões de antes desta ADR."""
    svc = OrchestrationService()
    orch = svc.create_orchestration("demanda qualquer")
    b = svc._bundle(orch.id)  # noqa: SLF001
    baseline = AgentRegistry()
    baseline.seed_defaults()
    assert b.agent_registry.permission_map() == baseline.permission_map()


def test_seed_examples_mapeia_onze_dos_catorze_para_papeis_reais() -> None:
    svc = OrchestrationService()
    definicoes = svc.list_agent_definitions()
    com_papel = [d for d in definicoes if d["role"]]
    sem_papel = [d for d in definicoes if not d["role"]]
    assert len(com_papel) == 11
    assert {d["nome"] for d in sem_papel} == {"Discovery técnico", "Deploy", "Incidentes"}
