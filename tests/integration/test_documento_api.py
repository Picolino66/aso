"""API de documentos (Tela 08/09, wf §10/§11) — ADR-0046."""

from __future__ import annotations

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.control.orchestration_service import OrchestrationService


def _client() -> TestClient:
    return TestClient(create_app(OrchestrationService()))


def _oid(client: TestClient) -> str:
    return client.post("/v1/orchestrations", json={"user_request": "demanda"}).json()["id"]


def test_list_documentos_devolve_13_tipos() -> None:
    client = _client()
    oid = _oid(client)
    corpo = client.get(f"/v1/orchestrations/{oid}/documentos").json()
    assert len(corpo) == 13
    tipos = {d["tipo"] for d in corpo}
    assert "requisitos" in tipos
    assert "especificacao_tecnica" in tipos
    editaveis = {d["tipo"]: d["editavel"] for d in corpo}
    assert editaveis["requisitos"] is True
    assert editaveis["especificacao_tecnica"] is False


def test_get_documento_tipo_invalido_devolve_400() -> None:
    client = _client()
    oid = _oid(client)
    resposta = client.get(f"/v1/orchestrations/{oid}/documentos/tipo_fantasma")
    assert resposta.status_code == 400


def test_get_documento_tipo_da_especificacao_devolve_400_com_mensagem_de_redirecionamento() -> None:
    client = _client()
    oid = _oid(client)
    resposta = client.get(f"/v1/orchestrations/{oid}/documentos/especificacao_tecnica")
    assert resposta.status_code == 400
    assert "spec" in resposta.json()["detail"]


def test_save_documento_cria_primeira_versao() -> None:
    client = _client()
    oid = _oid(client)
    resposta = client.put(
        f"/v1/orchestrations/{oid}/documentos/requisitos",
        json={"conteudo_markdown": "# Requisitos\n\n- item 1", "autor": "ana"},
    )
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["versao"] == 1
    assert corpo["status"] == "aguardando_revisao"
    assert corpo["autor"] == "ana"


def test_save_documento_incrementa_versao() -> None:
    client = _client()
    oid = _oid(client)
    client.put(
        f"/v1/orchestrations/{oid}/documentos/arquitetura",
        json={"conteudo_markdown": "v1", "autor": "ana"},
    )
    segunda = client.put(
        f"/v1/orchestrations/{oid}/documentos/arquitetura",
        json={"conteudo_markdown": "v2", "autor": "ana"},
    )
    assert segunda.json()["versao"] == 2


def test_documento_history_e_diff() -> None:
    client = _client()
    oid = _oid(client)
    client.put(
        f"/v1/orchestrations/{oid}/documentos/arquitetura",
        json={"conteudo_markdown": "linha 1\nlinha 2", "autor": "ana"},
    )
    client.put(
        f"/v1/orchestrations/{oid}/documentos/arquitetura",
        json={"conteudo_markdown": "linha 1\nlinha 2 mudou", "autor": "ana"},
    )
    historico = client.get(f"/v1/orchestrations/{oid}/documentos/arquitetura/history").json()
    assert len(historico) == 2

    diff = client.get(
        f"/v1/orchestrations/{oid}/documentos/arquitetura/diff", params={"de": 1, "para": 2}
    ).json()
    texto = "\n".join(diff)
    assert "-linha 2" in texto
    assert "+linha 2 mudou" in texto


def test_documento_diff_versao_inexistente_devolve_404() -> None:
    client = _client()
    oid = _oid(client)
    client.put(
        f"/v1/orchestrations/{oid}/documentos/arquitetura",
        json={"conteudo_markdown": "v1", "autor": "ana"},
    )
    resposta = client.get(
        f"/v1/orchestrations/{oid}/documentos/arquitetura/diff", params={"de": 1, "para": 99}
    )
    assert resposta.status_code == 404


def test_review_documento_sem_agente_cai_em_necessita_humano() -> None:
    client = _client()
    oid = _oid(client)
    client.put(
        f"/v1/orchestrations/{oid}/documentos/requisitos",
        json={"conteudo_markdown": "# Requisitos", "autor": "ana"},
    )
    resposta = client.post(f"/v1/orchestrations/{oid}/documentos/requisitos/review", json={})
    assert resposta.status_code == 200
    assert resposta.json()["status"] == "necessita_humano"


def test_review_documento_sem_documento_devolve_404() -> None:
    client = _client()
    oid = _oid(client)
    resposta = client.post(f"/v1/orchestrations/{oid}/documentos/requisitos/review", json={})
    assert resposta.status_code == 404


def test_comentario_criado_lido_e_resolvido() -> None:
    client = _client()
    oid = _oid(client)
    client.put(
        f"/v1/orchestrations/{oid}/documentos/requisitos",
        json={"conteudo_markdown": "# Requisitos", "autor": "ana"},
    )
    criado = client.post(
        f"/v1/orchestrations/{oid}/documentos/requisitos/comments",
        json={
            "autor": "revisor",
            "tipo": "clareza",
            "severidade": "media",
            "descricao": "faltou detalhar o item 2",
            "trecho_relacionado": "item 2",
            "acao_solicitada": "detalhar",
        },
    )
    assert criado.status_code == 201
    comment_id = criado.json()["id"]
    assert criado.json()["documento_versao"] == 1

    listados = client.get(f"/v1/orchestrations/{oid}/documentos/requisitos/comments").json()
    assert len(listados) == 1

    resolvido = client.post(
        f"/v1/orchestrations/{oid}/documentos/comments/{comment_id}/resolve",
        json={"resposta_do_autor": "detalhado na v2"},
    )
    assert resolvido.status_code == 200
    assert resolvido.json()["status"] == "resolvido"
    assert resolvido.json()["resposta_do_autor"] == "detalhado na v2"


def test_comentario_tipo_invalido_devolve_400() -> None:
    client = _client()
    oid = _oid(client)
    resposta = client.post(
        f"/v1/orchestrations/{oid}/documentos/requisitos/comments",
        json={"autor": "x", "tipo": "invalido", "severidade": "media", "descricao": "y"},
    )
    assert resposta.status_code == 400


def test_resolver_comentario_ja_resolvido_devolve_409() -> None:
    client = _client()
    oid = _oid(client)
    criado = client.post(
        f"/v1/orchestrations/{oid}/documentos/requisitos/comments",
        json={"autor": "x", "tipo": "clareza", "severidade": "baixa", "descricao": "y"},
    )
    comment_id = criado.json()["id"]
    client.post(f"/v1/orchestrations/{oid}/documentos/comments/{comment_id}/resolve", json={})
    segunda = client.post(
        f"/v1/orchestrations/{oid}/documentos/comments/{comment_id}/resolve", json={}
    )
    assert segunda.status_code == 409


def test_resolver_comentario_inexistente_devolve_404() -> None:
    client = _client()
    oid = _oid(client)
    resposta = client.post(
        f"/v1/orchestrations/{oid}/documentos/comments/comment_fantasma/resolve", json={}
    )
    assert resposta.status_code == 404
