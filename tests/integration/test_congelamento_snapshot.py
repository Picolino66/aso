"""MEL-17 — congelamento de snapshots aplicado de verdade (ADR-0061).

Antes, `frozen_sections=[]` e `locked_paths` nunca preenchido: o bloqueio documentado não
bloqueava nada no uso real. Aqui o fluxo é o real — card → gate → snapshot → tentativa de
escrita — e as tentativas de burla precisam ser recusadas.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.api.auth import AuthService, Principal
from aso.application.orchestration_service import OrchestrationService
from aso.control.planning import PlannedAdr, ProjectPlan
from aso.db.repository import SqlAlchemyOrchestrationRepository
from aso.shared.types import ColumnKey, Phase

_TOKENS = {
    "o": Principal(actor="operador", role="operator"),
    "a": Principal(actor="admin", role="admin"),
}
OP = {"Authorization": "Bearer o"}
ADM = {"Authorization": "Bearer a"}
_ARQ = {"architecture", "backend"}


def _client(svc: OrchestrationService) -> TestClient:
    return TestClient(create_app(svc, auth=AuthService(_TOKENS, dev_mode=False)))


def _patch(target: str = "architecture.pattern", **extra: Any) -> dict[str, Any]:
    return {
        "agent": "ArchitectureDesignAgent",
        "phase": "F2",
        "patch_type": "update",
        "target_path": target,
        "content": "microservices",
        **extra,
    }


def _f2_aprovada(client: TestClient, svc: OrchestrationService) -> str:
    corpo = {"user_request": "X", "demand_brief": {"dominios": sorted(_ARQ)}}
    oid = client.post("/v1/orchestrations", json=corpo, headers=OP).json()["id"]
    card_f2 = next(c for c in svc.get_cards(oid) if c.phase == Phase.F2)
    assert client.post(f"/v1/orchestrations/{oid}/cards/{card_f2.id}/run", headers=OP).is_success
    gate = client.post(
        f"/v1/orchestrations/{oid}/quality-gates/run", json={"phase": "F2"}, headers=OP
    )
    assert gate.json()["status"] == "PASSED"
    return oid


def test_snapshot_de_f2_congela_architecture() -> None:
    svc = OrchestrationService()
    client = _client(svc)
    oid = _f2_aprovada(client, svc)
    snaps = svc.list_snapshots(oid)
    assert [(s.snapshot_version, s.frozen_sections) for s in snaps] == [("O2", ["architecture"])]


def test_escrita_em_secao_congelada_sem_override_e_rejeitada_no_fluxo_real() -> None:
    svc = OrchestrationService()
    client = _client(svc)
    oid = _f2_aprovada(client, svc)
    r = client.post(f"/v1/orchestrations/{oid}/context-patches", json=_patch(), headers=OP).json()
    assert r["status"] == "rejected"
    conflitos = client.get(f"/v1/orchestrations/{oid}/conflicts", headers=OP).json()
    assert "SNAPSHOT_LOCK_CONFLICT" in {c["type"] for c in conflitos}


def test_override_com_adr_fica_pendente_ate_aprovacao_humana() -> None:
    svc = OrchestrationService()
    client = _client(svc)
    oid = _f2_aprovada(client, svc)
    adr_id = svc.list_adrs(oid)[0].id
    corpo = _patch(requires_adr=True, linked_adrs=[adr_id])
    r = client.post(f"/v1/orchestrations/{oid}/context-patches", json=corpo, headers=OP).json()
    assert r["status"] == "pending"
    contexto = client.get(f"/v1/orchestrations/{oid}/context", headers=OP).json()["payload"]
    assert contexto["architecture"].get("pattern") != "microservices"

    aprovacao = next(a for a in svc.list_approvals(oid) if a.tipo == "patch")
    # Operator não aprova o próprio override.
    assert client.post(f"/v1/approvals/{aprovacao.id}/approve", headers=OP).status_code == 403
    assert client.post(f"/v1/approvals/{aprovacao.id}/approve", headers=ADM).is_success
    contexto = client.get(f"/v1/orchestrations/{oid}/context", headers=OP).json()["payload"]
    assert contexto["architecture"]["pattern"] == "microservices"


def test_reexecutar_o_agente_da_fase_congelada_bloqueia_o_card() -> None:
    svc = OrchestrationService()
    client = _client(svc)
    oid = _f2_aprovada(client, svc)
    card_f2 = next(c for c in svc.get_cards(oid) if c.phase == Phase.F2)
    svc._bundle(oid).board_service.move_card(card_f2.id, ColumnKey.READY)  # noqa: SLF001
    svc.run_card(oid, card_f2.id)
    card = next(c for c in svc.get_cards(oid) if c.id == card_f2.id)
    assert card.status == ColumnKey.BLOCKED
    assert card.block_reason == "conflito detectado"


def test_gate_da_mesma_fase_duas_vezes_nao_duplica_snapshot() -> None:
    svc = OrchestrationService()
    client = _client(svc)
    oid = _f2_aprovada(client, svc)
    client.post(f"/v1/orchestrations/{oid}/quality-gates/run", json={"phase": "F2"}, headers=OP)
    assert [s.snapshot_version for s in svc.list_snapshots(oid)] == ["O2"]


def test_congelamento_sobrevive_a_reidratacao(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'snap.db'}"
    svc = OrchestrationService(repository=SqlAlchemyOrchestrationRepository(url))
    oid = _f2_aprovada(_client(svc), svc)
    novo = OrchestrationService(repository=SqlAlchemyOrchestrationRepository(url))
    r = _client(novo).post(f"/v1/orchestrations/{oid}/context-patches", json=_patch(), headers=OP)
    assert r.json()["status"] == "rejected"
    assert novo.list_snapshots(oid)[0].frozen_sections == ["architecture"]


def test_adr_do_plano_com_locked_paths_exige_referencia(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'plan.db'}"
    svc = OrchestrationService(repository=SqlAlchemyOrchestrationRepository(url))
    oid = svc.create_orchestration("backend", seed_cards=False).id
    plano = ProjectPlan(
        adrs=[
            PlannedAdr(
                title="Stack Python",
                decision="FastAPI + Postgres",
                locked_paths=["engineering.stack"],
            )
        ]
    )
    svc.populate_from_plan(oid, plano)
    adr = next(a for a in svc.list_adrs(oid) if a.title == "Stack Python")
    assert adr.locked_paths == ["engineering.stack"]

    # Reidratado: a trava persiste e segue valendo.
    novo = OrchestrationService(repository=SqlAlchemyOrchestrationRepository(url))
    client = _client(novo)
    base = {
        "agent": "BackendDevelopmentAgent",
        "phase": "F5",
        "patch_type": "update",
        "target_path": "engineering.stack",
        "content": "Django",
    }
    r = client.post(f"/v1/orchestrations/{oid}/context-patches", json=base, headers=OP).json()
    assert r["status"] == "rejected"
    conflitos = client.get(f"/v1/orchestrations/{oid}/conflicts", headers=OP).json()
    assert any(adr.id in c["description"] for c in conflitos)
    ok = client.post(
        f"/v1/orchestrations/{oid}/context-patches",
        json={**base, "linked_adrs": [adr.id]},
        headers=OP,
    ).json()
    assert ok["status"] == "applied"


def test_restaurar_ledger_so_restaura_o_contexto_e_exige_admin() -> None:
    svc = OrchestrationService()
    client = _client(svc)
    oid = _f2_aprovada(client, svc)
    card_f5 = next(c for c in svc.get_cards(oid) if c.phase == Phase.F5)
    client.post(f"/v1/orchestrations/{oid}/cards/{card_f5.id}/run", headers=OP)
    versao_antes = client.get(f"/v1/orchestrations/{oid}/context", headers=OP).json()["version"]
    status_cards = {c.id: c.status for c in svc.get_cards(oid)}

    corpo = {"to_snapshot": "O2"}
    for rota in ("restaurar-ledger", "rollback"):
        assert (
            client.post(f"/v1/orchestrations/{oid}/{rota}", json=corpo, headers=OP).status_code
            == 403
        )
    r = client.post(f"/v1/orchestrations/{oid}/restaurar-ledger", json=corpo, headers=ADM)
    assert r.status_code == 202
    # O board não é revertido: só o ledger do contexto.
    assert {c.id: c.status for c in svc.get_cards(oid)} == status_cards
    contexto = client.get(f"/v1/orchestrations/{oid}/context", headers=OP).json()
    assert contexto["version"] >= versao_antes
    # O patch de F5 (posterior ao O2) saiu do ledger restaurado.
    assert contexto["payload"] == svc.list_snapshots(oid)[0].payload
    # Alias obsoleto continua funcionando por uma versão.
    assert (
        client.post(f"/v1/orchestrations/{oid}/rollback", json=corpo, headers=ADM).status_code
        == 202
    )
