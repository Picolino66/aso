"""Catálogo de agentes pela API (Tela 30, wf §32, ADR-0053)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.api.auth import AuthService, Principal
from aso.control.orchestration_service import OrchestrationService


def _client() -> TestClient:
    return TestClient(create_app(OrchestrationService()))


def test_lista_vem_com_os_catorze_agentes_exemplo() -> None:
    resposta = _client().get("/v1/agent-definitions")
    assert resposta.status_code == 200
    assert len(resposta.json()) == 14


def test_roles_reais_registrada_antes_do_id_generico() -> None:
    resposta = _client().get("/v1/agent-definitions/roles")
    assert resposta.status_code == 200
    assert "BackendDevelopmentAgent" in resposta.json()


def test_criar_definicao_com_role_invalido_devolve_400() -> None:
    resposta = _client().post("/v1/agent-definitions", json={"nome": "X", "role": "Inventado"})
    assert resposta.status_code == 400


def test_fluxo_completo_criar_ler_atualizar_remover() -> None:
    client = _client()
    criada = client.post(
        "/v1/agent-definitions",
        json={
            "nome": "Especialista customizado",
            "role": "ConflictResolutionAgent",
            "ferramentas": ["read_file"],
            "permissoes": ["quality"],
            "categorias_tarefa": ["security"],
            "limite_custo_usd": 50.0,
            "limite_tentativas": 3,
            "exige_supervisao": True,
        },
    )
    assert criada.status_code == 201
    definition_id = criada.json()["id"]

    lida = client.get(f"/v1/agent-definitions/{definition_id}")
    assert lida.status_code == 200
    assert lida.json()["nome"] == "Especialista customizado"

    # Bug real (code-review ultra, ADR-0053): um PUT que só quer renomear e OMITE
    # `ferramentas`/`permissoes` não pode zerá-las — isso revogaria a permissão
    # real do papel no ContextBus por um efeito colateral do formulário.
    atualizada = client.put(
        f"/v1/agent-definitions/{definition_id}",
        json={"nome": "Renomeado", "role": "ConflictResolutionAgent"},
    )
    assert atualizada.status_code == 200
    assert atualizada.json()["nome"] == "Renomeado"
    assert atualizada.json()["ferramentas"] == ["read_file"]  # omitido preserva o valor atual
    assert atualizada.json()["permissoes"] == ["quality"]

    # Uma lista EXPLÍCITA (mesmo vazia) ainda substitui de verdade.
    limpa = client.put(
        f"/v1/agent-definitions/{definition_id}",
        json={"nome": "Renomeado", "role": "ConflictResolutionAgent", "ferramentas": []},
    )
    assert limpa.status_code == 200
    assert limpa.json()["ferramentas"] == []
    assert limpa.json()["permissoes"] == ["quality"]  # não tocado, continua preservado

    removida = client.delete(f"/v1/agent-definitions/{definition_id}")
    assert removida.status_code == 200
    assert client.get(f"/v1/agent-definitions/{definition_id}").status_code == 404


def test_update_e_delete_de_definicao_inexistente_devolvem_404() -> None:
    client = _client()
    assert (
        client.put("/v1/agent-definitions/inexistente", json={"nome": "X", "role": ""}).status_code
        == 404
    )
    assert client.delete("/v1/agent-definitions/inexistente").status_code == 404


def test_rbac_escrita_exige_admin_leitura_aberta_a_viewer() -> None:
    auth = AuthService(
        {
            "v": Principal(actor="view", role="viewer"),
            "o": Principal(actor="op", role="operator"),
            "a": Principal(actor="adm", role="admin"),
        },
        dev_mode=False,
    )
    client = TestClient(create_app(OrchestrationService(), auth=auth))

    assert (
        client.get("/v1/agent-definitions", headers={"Authorization": "Bearer v"}).status_code
        == 200
    )
    corpo = {"nome": "X", "role": "ConflictResolutionAgent"}
    assert (
        client.post(
            "/v1/agent-definitions", json=corpo, headers={"Authorization": "Bearer v"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/v1/agent-definitions", json=corpo, headers={"Authorization": "Bearer o"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/v1/agent-definitions", json=corpo, headers={"Authorization": "Bearer a"}
        ).status_code
        == 201
    )


def test_definicao_muda_permissao_real_via_bundle() -> None:
    """Confirma que o catálogo é FONTE DE VERDADE das permissões (decisão da
    ADR-0053) — editar `ferramentas`/`permissoes` de um agente vinculado a um
    `role` real muda o que ele pode escrever via ContextBus. Edita a própria
    definição pré-provisionada ("Desenvolvedor backend") em vez de criar uma
    segunda para o mesmo papel — dois ativos para o mesmo `role` são recusados
    (ver `test_criar_definicao_para_role_ja_vinculado_devolve_400`)."""
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    definicoes = client.get("/v1/agent-definitions").json()
    existente = next(d for d in definicoes if d["role"] == "BackendDevelopmentAgent")
    client.put(
        f"/v1/agent-definitions/{existente['id']}",
        json={
            "nome": "Backend restrito",
            "role": "BackendDevelopmentAgent",
            "ferramentas": ["read_file"],
            "permissoes": ["engineering_only"],
        },
    )
    oid = client.post("/v1/orchestrations", json={"user_request": "demanda"}).json()["id"]
    b = svc._bundle(oid)  # noqa: SLF001
    spec = b.agent_registry.get("BackendDevelopmentAgent")
    assert spec is not None
    assert spec.allowed_tools == ["read_file"]
    assert b.bus.permissions.can_write("BackendDevelopmentAgent", "engineering.x") is False
    assert b.bus.permissions.can_write("BackendDevelopmentAgent", "engineering_only.x") is True


def test_criar_definicao_para_role_ja_vinculado_devolve_400() -> None:
    """ "Desenvolvedor backend" (pré-provisionado) já ocupa BackendDevelopmentAgent
    — uma segunda definição ativa para o mesmo papel é recusada, não aceita em
    silêncio com resultado ambíguo (ADR-0053)."""
    client = _client()
    resposta = client.post(
        "/v1/agent-definitions", json={"nome": "Outro backend", "role": "BackendDevelopmentAgent"}
    )
    assert resposta.status_code == 400
    assert "já está vinculado" in resposta.json()["detail"]


def test_desativar_libera_o_role_para_outra_definicao() -> None:
    client = _client()
    existente = next(
        d for d in client.get("/v1/agent-definitions").json() if d["role"] == "SecurityAgent"
    )
    desativada = client.put(
        f"/v1/agent-definitions/{existente['id']}",
        json={"nome": existente["nome"], "role": "SecurityAgent", "ativo": False},
    )
    assert desativada.status_code == 200

    nova = client.post(
        "/v1/agent-definitions", json={"nome": "Segurança v2", "role": "SecurityAgent"}
    )
    assert nova.status_code == 201
