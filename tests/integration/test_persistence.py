"""Teste de integração da persistência (SQLAlchemy/SQLite) — estado sobrevive.

Prova que o estado de uma orquestração persiste entre instâncias diferentes do
OrchestrationService apontando para o mesmo banco (o objetivo da persistência).
"""

from __future__ import annotations

from pathlib import Path

from aso.control.orchestration_service import OrchestrationService
from aso.db.repository import SqlAlchemyOrchestrationRepository
from aso.persistence.memory import InMemoryOrchestrationRepository
from aso.shared.types import Phase


def test_state_survives_new_service_instance(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'aso.db'}"

    # Instância 1: cria, executa e roda o gate.
    svc1 = OrchestrationService(repository=SqlAlchemyOrchestrationRepository(url))
    orch = svc1.create_orchestration("Implementar módulo X no backend")
    card = svc1.get_cards(orch.id)[0]
    svc1.run_card(orch.id, card.id)
    svc1.run_quality_gate(orch.id, Phase.F5)

    # Instância 2: novo service + novo repositório sobre o MESMO banco.
    svc2 = OrchestrationService(repository=SqlAlchemyOrchestrationRepository(url))

    assert svc2.get(orch.id).id == orch.id
    assert svc2.get(orch.id).snapshot_version == "O5"
    assert svc2.get_context(orch.id)["version"] == 1
    assert len(svc2.get_cards(orch.id)) == 1
    assert svc2.get_cards(orch.id)[0].status.value == "Testing"
    assert len(svc2.list_snapshots(orch.id)) == 1
    assert len(svc2.list_adrs(orch.id)) >= 1
    assert orch.id in [o.id for o in svc2.list_all()]

    # Timeline e histórico do contexto preservados.
    event_types = {e.type for e in svc2.timeline(orch.id)}
    assert {"OrchestrationCreated", "ContextPatchApplied", "SnapshotCreated"} <= event_types


def test_sql_repository_roundtrip(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'rt.db'}"
    svc = OrchestrationService(repository=SqlAlchemyOrchestrationRepository(url))
    orch = svc.create_orchestration("demo")
    assert svc.list_all()[0].id == orch.id


def test_two_orchestrations_share_adr_id_no_collision(tmp_path: Path) -> None:
    # Regressão: ADR-0001 é sequencial por orquestração; PK composta evita colisão.
    url = f"sqlite:///{tmp_path / 'multi.db'}"
    svc = OrchestrationService(repository=SqlAlchemyOrchestrationRepository(url))
    o1 = svc.create_orchestration("primeira")
    o2 = svc.create_orchestration("segunda")
    assert o1.id != o2.id
    assert svc.list_adrs(o1.id)[0].id == "ADR-0001"
    assert svc.list_adrs(o2.id)[0].id == "ADR-0001"
    assert len(svc.list_all()) == 2

    # Recarrega em instância nova: ambas as ADR-0001 coexistem.
    svc2 = OrchestrationService(repository=SqlAlchemyOrchestrationRepository(url))
    assert {a.id for a in svc2.list_adrs(o1.id)} == {"ADR-0001"}
    assert {a.id for a in svc2.list_adrs(o2.id)} == {"ADR-0001"}


def test_inmemory_repository_roundtrip() -> None:
    svc = OrchestrationService(repository=InMemoryOrchestrationRepository())
    orch = svc.create_orchestration("demo")
    # Limpa o cache para forçar carga a partir do repositório.
    svc._bundles.clear()  # noqa: SLF001
    assert svc.get(orch.id).id == orch.id
    assert svc.get_context(orch.id)["version"] == 0
