"""Persistência relacional e enforcement do catálogo de agentes (Tela 30,
wf §32, ADR-0053)."""

from __future__ import annotations

from pathlib import Path

from aso.control.orchestration_service import OrchestrationService
from aso.db.repository import SqlAlchemyAgentDefinitionRepository
from aso.kanban.models import KanbanCard
from aso.shared.types import CardType, ColumnKey, Phase


def _service(url: str) -> OrchestrationService:
    repo = SqlAlchemyAgentDefinitionRepository(url)
    return OrchestrationService(agent_definition_repository=repo)


def test_definicao_sobrevive_ao_reinicio(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'agents.db'}"
    first = _service(url)
    criada = first.create_agent_definition(
        nome="Conflito customizado", role="ConflictResolutionAgent", actor="op"
    )

    restarted = _service(url)
    listadas = restarted.list_agent_definitions()
    assert any(d["id"] == criada["id"] for d in listadas)
    # O seed dos 14 exemplos não roda de novo (catálogo já não está vazio).
    assert len(listadas) == 15


def test_seed_dos_catorze_exemplos_sobrevive_ao_reinicio(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'agents-seed.db'}"
    first = _service(url)
    assert len(first.list_agent_definitions()) == 14

    restarted = _service(url)
    assert len(restarted.list_agent_definitions()) == 14


def _card_para(svc: OrchestrationService, orchestration_id: str, role: str) -> KanbanCard:
    b = svc._bundle(orchestration_id)  # noqa: SLF001
    card = KanbanCard(
        board_id=b.board.id,
        orchestration_id=orchestration_id,
        phase=Phase.F5,
        type=CardType.TASK,
        title="card de teste",
        status=ColumnKey.READY,
        assignee=role,
    )
    b.board_service.add_card(card)
    svc._persist(b)  # noqa: SLF001
    return card


def test_run_card_recusa_quando_agente_atinge_limite_de_tentativas() -> None:
    svc = OrchestrationService()
    svc.create_agent_definition(
        nome="Conflito com limite", role="ConflictResolutionAgent", limite_tentativas=2, actor="op"
    )
    orch = svc.create_orchestration("demanda qualquer", seed_cards=False)
    card = _card_para(svc, orch.id, "ConflictResolutionAgent")
    card.tentativa_atual = 2

    try:
        svc.run_card(orch.id, card.id)
    except ValueError as exc:
        assert "limite de 2 tentativa" in str(exc)
    else:
        raise AssertionError("deveria ter recusado")


def test_run_card_recusa_quando_agente_atinge_limite_de_custo() -> None:
    svc = OrchestrationService()
    svc.create_agent_definition(
        nome="Conflito com teto", role="ConflictResolutionAgent", limite_custo_usd=1.0, actor="op"
    )
    orch = svc.create_orchestration("demanda qualquer", seed_cards=False)
    card = _card_para(svc, orch.id, "ConflictResolutionAgent")
    card.uso = {"custo_usd": 1.5}

    try:
        svc.run_card(orch.id, card.id)
    except ValueError as exc:
        assert "limite de custo" in str(exc)
    else:
        raise AssertionError("deveria ter recusado")


def test_run_card_sem_definicao_vinculada_nao_e_afetado() -> None:
    """Papel sem definição no catálogo continua sem nenhum freio novo — mesmo
    comportamento de antes da ADR-0053."""
    svc = OrchestrationService()
    orch = svc.create_orchestration("demanda qualquer", seed_cards=False)
    card = _card_para(svc, orch.id, "FrontendDevelopmentAgent")
    card.tentativa_atual = 50  # nenhum limite configurado — não deveria recusar por isso
    try:
        svc.run_card(orch.id, card.id)
    except KeyError:
        pass  # sem agente registrado no AgentSupervisor/provider — não é o que testamos
    except ValueError as exc:
        assert "limite" not in str(exc)
