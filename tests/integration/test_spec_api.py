"""Especificação e revisão documental pela API (§5/§6 do fluxo.md, ADR-0021)."""

from __future__ import annotations

import shlex
from pathlib import Path

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.api.auth import AuthService, Principal
from aso.control.orchestration_service import OrchestrationService
from aso.control.triage import DemandBrief
from aso.execution.catalog import ExecutorCatalog, ExecutorProfile
from aso.shared.types import RiskLevel


def _script(bruto: str) -> str:
    script = 'cat > /dev/null; printf %s "$1"; exit 0'
    return shlex.join(["bash", "-c", script, "_", bruto])


def _catalogo() -> ExecutorCatalog:
    """Um agente de especificação (completo, com testes/rollback/itens de trabalho
    com dependência) e um revisor documental (sempre aprova) — nomes distintos para
    escolher cada um explicitamente."""
    spec_bruto = (
        '{"o_que_sera_construido": "corrigir frete", '
        '"estrategia_de_testes": "testes unitários", '
        '"plano_de_rollback": "reverter o commit", '
        '"itens_de_trabalho": ['
        '  {"titulo": "ajustar formula", "fase": "F5", "dominio": "backend"},'
        '  {"titulo": "cobrir com testes", "fase": "F6", "dominio": "tests", '
        '   "depende_de": ["ajustar formula"]}'
        "]}"
    )
    review_aprovado = '{"veredito": "aprovado", "resumo": "documento completo"}'
    return ExecutorCatalog(
        [
            ExecutorProfile(name="especificador", kind="cli", command=_script(spec_bruto)),
            ExecutorProfile(name="revisor-doc", kind="cli", command=_script(review_aprovado)),
        ]
    )


def _catalogo_hierarquia() -> ExecutorCatalog:
    """Um agente de especificação cujo `itens_de_trabalho` tem um épico com uma
    história filha (§7 do fluxo.md, ADR-0025) — só um nível de `itens_filhos`."""
    spec_bruto = (
        '{"o_que_sera_construido": "corrigir frete", '
        '"estrategia_de_testes": "testes unitários", '
        '"plano_de_rollback": "reverter o commit", '
        '"itens_de_trabalho": ['
        '  {"titulo": "Calculo de frete", "fase": "F5", "dominio": "backend", '
        '   "tipo": "Epic", "itens_filhos": ['
        '     {"titulo": "ajustar formula", "fase": "F5", "dominio": "backend", "tipo": "Task"}'
        "  ]}"
        "]}"
    )
    review_aprovado = '{"veredito": "aprovado", "resumo": "documento completo"}'
    return ExecutorCatalog(
        [
            ExecutorProfile(name="especificador", kind="cli", command=_script(spec_bruto)),
            ExecutorProfile(name="revisor-doc", kind="cli", command=_script(review_aprovado)),
        ]
    )


def _orch(svc: OrchestrationService, tmp_path: Path) -> str:
    orch = svc.create_orchestration(
        "ajustar cálculo de frete",
        target_path=str(tmp_path),
        demand_brief=DemandBrief(problema="frete errado", risco=RiskLevel.LOW),
    )
    return orch.id


def test_fluxo_completo_ate_cards_com_dependencias(tmp_path: Path) -> None:
    svc = OrchestrationService(catalog=_catalogo())
    client = TestClient(create_app(svc))
    oid = _orch(svc, tmp_path)

    # discovery: executor inválido força o fallback heurístico determinístico —
    # sem isto, o catálogo compartilhado escolheria "especificador" por default.
    client.post(f"/v1/orchestrations/{oid}/discovery/run", json={"executor": "inexistente"})

    # F5 não começa sem especificação aprovada em full-pipeline.
    bloqueado = client.post(f"/v1/orchestrations/{oid}/run-phase", json={"phase": "F5"})
    assert bloqueado.status_code == 409
    assert "especificação aprovada" in bloqueado.json()["detail"]

    client.post(f"/v1/orchestrations/{oid}/discovery/decide", json={"approved": True})

    # spec/run sem agente de verdade -> heurística sem plano de testes/rollback.
    client.post(f"/v1/orchestrations/{oid}/spec/run", json={"executor": "inexistente"})
    reprovado = client.post(f"/v1/orchestrations/{oid}/spec/review", json={})
    assert reprovado.status_code == 200
    versao1 = reprovado.json()["spec_documents"][-1]
    assert versao1["status"] == "reprovado"
    assert versao1["versao"] == 1
    assert versao1["revisao_comentarios"]

    # Regenerar com o agente de especificação completo -> versão 2.
    regen = client.post(f"/v1/orchestrations/{oid}/spec/run", json={"executor": "especificador"})
    assert regen.json()["spec_documents"][-1]["versao"] == 2
    assert regen.json()["spec_documents"][-1]["status"] == "aguardando_revisao"

    # Revisão documental com o revisor completo -> aprovado, cria os cards da spec.
    aprovado = client.post(
        f"/v1/orchestrations/{oid}/spec/review", json={"executor": "revisor-doc"}
    )
    assert aprovado.status_code == 200
    assert aprovado.json()["spec_documents"][-1]["status"] == "aprovado"

    cards = client.get(f"/v1/orchestrations/{oid}/cards").json()
    por_titulo = {c["title"]: c for c in cards}
    assert "ajustar formula" in por_titulo
    assert "cobrir com testes" in por_titulo
    assert por_titulo["cobrir com testes"]["dependencies"] == [por_titulo["ajustar formula"]["id"]]

    # Histórico das duas versões.
    historico = client.get(f"/v1/orchestrations/{oid}/spec/history").json()
    assert len(historico) == 2
    assert [d["versao"] for d in historico] == [1, 2]

    discovery_historico = client.get(f"/v1/orchestrations/{oid}/discovery/history").json()
    assert len(discovery_historico) == 1

    # F5 não recusa mais por falta de especificação.
    liberado = client.post(f"/v1/orchestrations/{oid}/run-phase", json={"phase": "F5"})
    assert liberado.status_code != 409 or "especificação aprovada" not in liberado.json().get(
        "detail", ""
    )


def test_itens_de_trabalho_com_hierarquia_produz_parent_id(tmp_path: Path) -> None:
    """§7 (ADR-0025): `itens_filhos` da spec vira `parent_id` no card criado."""
    svc = OrchestrationService(catalog=_catalogo_hierarquia())
    client = TestClient(create_app(svc))
    oid = _orch(svc, tmp_path)
    client.post(f"/v1/orchestrations/{oid}/discovery/run", json={"executor": "inexistente"})
    client.post(f"/v1/orchestrations/{oid}/discovery/decide", json={"approved": True})
    client.post(f"/v1/orchestrations/{oid}/spec/run", json={"executor": "especificador"})
    aprovado = client.post(
        f"/v1/orchestrations/{oid}/spec/review", json={"executor": "revisor-doc"}
    )
    assert aprovado.json()["spec_documents"][-1]["status"] == "aprovado"

    cards = client.get(f"/v1/orchestrations/{oid}/cards").json()
    por_titulo = {c["title"]: c for c in cards}
    epic = por_titulo["Calculo de frete"]
    filho = por_titulo["ajustar formula"]
    assert epic["type"] == "Epic"
    assert epic["parent_id"] is None
    assert filho["type"] == "Task"
    assert filho["parent_id"] == epic["id"]

    # O pai não fecha antes do filho (§7) — mesma regra vale pela API.
    fechar_epic = client.post(
        f"/v1/orchestrations/{oid}/cards/{epic['id']}/move", json={"to_column": "Done"}
    )
    assert fechar_epic.status_code == 409


def test_spec_sem_discovery_aprovado_devolve_409(tmp_path: Path) -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid = _orch(svc, tmp_path)
    resposta = client.post(f"/v1/orchestrations/{oid}/spec/run", json={})
    assert resposta.status_code == 409


def test_get_spec_vazio_antes_de_rodar(tmp_path: Path) -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid = _orch(svc, tmp_path)
    resposta = client.get(f"/v1/orchestrations/{oid}/spec")
    assert resposta.status_code == 200
    assert resposta.json()["status"] == "rascunho"


def test_rbac_get_viewer_run_operator_approve_admin(tmp_path: Path) -> None:
    auth = AuthService(
        {
            "v": Principal(actor="view", role="viewer"),
            "o": Principal(actor="op", role="operator"),
            "a": Principal(actor="adm", role="admin"),
        },
        dev_mode=False,
    )
    svc = OrchestrationService(catalog=_catalogo())
    client = TestClient(create_app(svc, auth=auth))
    oid = _orch(svc, tmp_path)
    client.post(
        f"/v1/orchestrations/{oid}/discovery/run",
        json={"executor": "inexistente"},
        headers={"Authorization": "Bearer a"},
    )
    client.post(
        f"/v1/orchestrations/{oid}/discovery/decide",
        json={"approved": True},
        headers={"Authorization": "Bearer a"},
    )

    # GET: viewer basta.
    assert (
        client.get(
            f"/v1/orchestrations/{oid}/spec", headers={"Authorization": "Bearer v"}
        ).status_code
        == 200
    )
    # run: viewer não pode.
    assert (
        client.post(
            f"/v1/orchestrations/{oid}/spec/run",
            json={},
            headers={"Authorization": "Bearer v"},
        ).status_code
        == 403
    )
    # run: operator pode.
    assert (
        client.post(
            f"/v1/orchestrations/{oid}/spec/run",
            json={"executor": "inexistente"},
            headers={"Authorization": "Bearer o"},
        ).status_code
        == 200
    )
    # review: operator pode (mesmo sem revisor configurado — a checagem
    # determinística reprova sozinha, já que a spec heurística não tem
    # testes/rollback).
    revisao = client.post(
        f"/v1/orchestrations/{oid}/spec/review",
        json={},
        headers={"Authorization": "Bearer o"},
    )
    assert revisao.status_code == 200
    assert revisao.json()["spec_documents"][-1]["status"] == "reprovado"

    # approve: exige admin — operator recebe 403 mesmo com estado válido para decidir.
    assert (
        client.post(
            f"/v1/orchestrations/{oid}/spec/approve",
            json={"approved": True},
            headers={"Authorization": "Bearer o"},
        ).status_code
        == 403
    )
