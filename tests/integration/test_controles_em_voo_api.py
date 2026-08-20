"""API dos controles em voo (Tela 15/16/17, wf §17/§18/§19) — ADR-0048."""

from __future__ import annotations

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService
from aso.execution.catalog import ExecutorCatalog, ExecutorProfile


def _catalogo() -> ExecutorCatalog:
    return ExecutorCatalog(
        [
            ExecutorProfile(
                name="claude-baixo",
                kind="cli",
                command="true",
                supported_efforts=["low", "medium", "high"],
            ),
            ExecutorProfile(
                name="claude-alto",
                kind="cli",
                command="true",
                supported_efforts=["low", "medium", "high"],
            ),
        ]
    )


def _seed_card(client: TestClient) -> tuple[str, str]:
    oid = client.post("/v1/orchestrations", json={"user_request": "demanda"}).json()["id"]
    card_id = client.get(f"/v1/orchestrations/{oid}/cards").json()[0]["id"]
    return oid, card_id


def test_pausar_e_retomar() -> None:
    client = TestClient(create_app(OrchestrationService()))
    oid, card_id = _seed_card(client)

    pausado = client.post(f"/v1/orchestrations/{oid}/cards/{card_id}/pause", json={"pausado": True})
    assert pausado.status_code == 200
    assert pausado.json()["pausado"] is True

    execucao = client.post(f"/v1/orchestrations/{oid}/cards/{card_id}/run")
    assert execucao.status_code == 409
    assert "pausado" in execucao.json()["detail"]

    retomado = client.post(
        f"/v1/orchestrations/{oid}/cards/{card_id}/pause", json={"pausado": False}
    )
    assert retomado.json()["pausado"] is False


def test_adicionar_contexto() -> None:
    client = TestClient(create_app(OrchestrationService()))
    oid, card_id = _seed_card(client)

    resposta = client.post(
        f"/v1/orchestrations/{oid}/cards/{card_id}/add-context",
        json={"texto": "considerar o cache de sessão"},
    )
    assert resposta.status_code == 200
    assert resposta.json()["contexto_adicional"] == ["considerar o cache de sessão"]


def test_aumentar_effort() -> None:
    """A partir do effort efetivo atual (já pode não ser "low" — a ficha da
    demanda pode sugerir um effort inicial mais alto, §9 do fluxo.md), cada
    chamada sobe um degrau até o topo, onde passa a recusar com 409."""
    svc = OrchestrationService(catalog=_catalogo())
    client = TestClient(create_app(svc))
    oid, card_id = _seed_card(client)

    efforts_vistos = []
    for _ in range(3):
        resposta = client.post(f"/v1/orchestrations/{oid}/cards/{card_id}/increase-effort")
        if resposta.status_code == 409:
            break
        efforts_vistos.append(resposta.json()["effort_override"])
    assert efforts_vistos[-1] == "high"
    esgotado = client.post(f"/v1/orchestrations/{oid}/cards/{card_id}/increase-effort")
    assert esgotado.status_code == 409


def test_trocar_modelo() -> None:
    svc = OrchestrationService(catalog=_catalogo())
    client = TestClient(create_app(svc))
    oid, card_id = _seed_card(client)
    client.post(
        f"/v1/orchestrations/{oid}/cards/{card_id}/assign-agent",
        json={"agent": "BackendDevelopmentAgent"},
    )

    resposta = client.post(f"/v1/orchestrations/{oid}/cards/{card_id}/transfer-model")
    assert resposta.status_code == 200
    assert resposta.json()["executor_override"] in ("claude-baixo", "claude-alto")


def test_trocar_modelo_sem_catalogo_devolve_409() -> None:
    client = TestClient(create_app(OrchestrationService()))
    oid, card_id = _seed_card(client)
    resposta = client.post(f"/v1/orchestrations/{oid}/cards/{card_id}/transfer-model")
    assert resposta.status_code == 409


def test_solicitar_ajuda_cria_aprovacao_vinculada_ao_card() -> None:
    client = TestClient(create_app(OrchestrationService()))
    oid, card_id = _seed_card(client)

    resposta = client.post(
        f"/v1/orchestrations/{oid}/cards/{card_id}/request-help",
        json={"reason": "não sei como prosseguir"},
    )
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["card_id"] == card_id
    assert corpo["action"] == "solicitar_ajuda"

    aprovacoes = client.get(f"/v1/orchestrations/{oid}/approvals").json()
    assert any(a["card_id"] == card_id for a in aprovacoes)


def test_arquivos_alterados_vazio_sem_branch() -> None:
    client = TestClient(create_app(OrchestrationService()))
    oid, card_id = _seed_card(client)
    resposta = client.get(f"/v1/orchestrations/{oid}/cards/{card_id}/changed-files")
    assert resposta.status_code == 200
    assert resposta.json() == []


def test_diagnostico_de_falhas_calculado_na_leitura() -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    oid, card_id = _seed_card(client)
    b = svc._bundle(oid)  # noqa: SLF001
    card = b.board_service.get_card(card_id)
    card.failures = [
        {"etapa": "execucao", "tentativa": 1, "mensagem": "timeout ao rodar", "categoria": ""},
        {"etapa": "execucao", "tentativa": 2, "mensagem": "falhou", "categoria": "lint"},
    ]

    resposta = client.get(f"/v1/orchestrations/{oid}/cards/{card_id}/failure-diagnostics")
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert len(corpo) == 2
    assert corpo[0]["confianca"] == "baixa"
    assert corpo[1]["confianca"] == "alta"
    assert "diagnostico" in corpo[0]


def test_controles_em_card_inexistente_devolvem_404() -> None:
    client = TestClient(create_app(OrchestrationService()))
    oid = client.post("/v1/orchestrations", json={"user_request": "demanda"}).json()["id"]
    for path, metodo in [
        ("pause", "post"),
        ("add-context", "post"),
        ("increase-effort", "post"),
        ("transfer-model", "post"),
        ("changed-files", "get"),
        ("failure-diagnostics", "get"),
    ]:
        corpo = (
            {"pausado": True}
            if path == "pause"
            else {"texto": "x"}
            if path == "add-context"
            else {}
        )
        chamada = client.get if metodo == "get" else client.post
        kwargs = {} if metodo == "get" else {"json": corpo}
        resposta = chamada(f"/v1/orchestrations/{oid}/cards/card_fantasma/{path}", **kwargs)
        assert resposta.status_code == 404, path
