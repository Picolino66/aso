"""MEL-15 — segurança por padrão (ADR-0057).

Cada teste tenta um dos atalhos que a revisão encontrou: subir sem tokens como admin
anônimo, operator configurando/disparando comandos no host, navegar fora das raízes
de workspace, token na query string fora do SSE e `/metrics` hidratando agregados.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.api.auth import AuthService, Principal, required_role
from aso.application.orchestration_service import OrchestrationService
from aso.db.repository import SqlAlchemyOrchestrationRepository
from aso.execution.workspace import WorkspaceRootError, WorkspaceService
from aso.observability.metrics import MetricsService

_TOKENS = {
    "v": Principal(actor="viewer", role="viewer"),
    "o": Principal(actor="op", role="operator"),
    "a": Principal(actor="adm", role="admin"),
}


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _client(svc: OrchestrationService | None = None) -> tuple[TestClient, OrchestrationService]:
    svc = svc or OrchestrationService()
    return TestClient(create_app(svc, auth=AuthService(_TOKENS, dev_mode=False))), svc


# ---------------------------------------------------------------- 1. modo dev explícito
def test_sem_tokens_e_sem_dev_mode_falha_no_boot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ASO_API_KEYS", raising=False)
    monkeypatch.delenv("ASO_DEV_MODE", raising=False)
    with pytest.raises(RuntimeError, match="ASO_DEV_MODE=1"):
        AuthService.from_env()
    monkeypatch.setenv("ASO_DEV_MODE", "true")  # só "1" liga: sem valores ambíguos
    with pytest.raises(RuntimeError, match="ASO_API_KEYS não configurada"):
        AuthService.from_env()


def test_dev_mode_explicito_vira_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ASO_API_KEYS", raising=False)
    monkeypatch.setenv("ASO_DEV_MODE", "1")
    auth = AuthService.from_env()
    assert auth.dev_mode
    principal = auth.authenticate(None)
    assert principal is not None and principal.role == "admin"


def test_tokens_configurados_ignoram_dev_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASO_API_KEYS", '{"t": {"actor": "x", "role": "viewer"}}')
    monkeypatch.setenv("ASO_DEV_MODE", "1")
    auth = AuthService.from_env()
    assert not auth.dev_mode
    assert auth.authenticate(None) is None


# ------------------------------------------------------------- 2. comandos no host = admin
@pytest.mark.parametrize(
    ("method", "suffix"),
    [
        ("PUT", "/validation-checks"),
        ("PUT", "/deploy/config"),
        ("PUT", "/deploy/pipeline"),
        ("POST", "/deploy/run"),
    ],
)
def test_matriz_papel_rotas_de_comando(method: str, suffix: str) -> None:
    path = f"/v1/orchestrations/o1{suffix}"
    assert required_role(method, path) == "admin"
    # Leitura das mesmas configurações continua aberta a viewer.
    if method == "PUT":
        assert required_role("GET", path) == "viewer"


def test_operator_recebe_403_nas_rotas_de_comando() -> None:
    client, svc = _client()
    oid = svc.create_orchestration("backend").id
    base = f"/v1/orchestrations/{oid}"
    chamadas = [
        ("put", "/validation-checks", {"checks": [{"nome": "t", "comando": "true"}]}),
        ("put", "/deploy/config", {"command": "true"}),
        ("put", "/deploy/pipeline", {"estagios": []}),
        ("post", "/deploy/run", {}),
        ("patch", "/execution-settings", {"validation_command": "true"}),
    ]
    for metodo, sufixo, corpo in chamadas:
        resposta = getattr(client, metodo)(base + sufixo, json=corpo, headers=_h("o"))
        assert resposta.status_code == 403, sufixo
    # Sem comando no corpo, execution-settings segue sendo de operator.
    assert (
        client.patch(base + "/execution-settings", json={"effort": "low"}, headers=_h("o"))
    ).status_code != 403
    # Admin passa pelo RBAC (o resultado de negócio pode variar, mas não é 403).
    admin = client.put(
        base + "/validation-checks",
        json={"checks": [{"nome": "t", "comando": "true"}]},
        headers=_h("a"),
    )
    assert admin.status_code != 403


def test_operator_nao_cria_orquestracao_com_comando_de_validacao() -> None:
    client, _svc = _client()
    corpo = {"user_request": "x", "execution_mode": "code-execution", "validation_command": "rm"}
    assert client.post("/v1/orchestrations", json=corpo, headers=_h("o")).status_code == 403
    assert (
        client.post("/v1/orchestrations", json={"user_request": "x"}, headers=_h("o"))
    ).status_code == 201


# ------------------------------------------------------------- 3. raízes de workspace
def test_raiz_padrao_e_o_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("ASO_WORKSPACE_ROOTS", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "proj").mkdir()
    ws = WorkspaceService()
    assert ws.validate(str(tmp_path / "proj")) == tmp_path / "proj"
    with pytest.raises(WorkspaceRootError):
        ws.validate("/etc")
    with pytest.raises(WorkspaceRootError):
        ws.list_dirs("/etc")


def test_symlink_e_ponto_ponto_nao_escapam_da_raiz(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    raiz = tmp_path / "raiz"
    fora = tmp_path / "fora"
    raiz.mkdir()
    fora.mkdir()
    (raiz / "atalho").symlink_to(fora)
    monkeypatch.setenv("ASO_WORKSPACE_ROOTS", str(raiz))
    ws = WorkspaceService()
    with pytest.raises(WorkspaceRootError):
        ws.validate(str(raiz / "atalho"))
    with pytest.raises(WorkspaceRootError):
        ws.validate(str(raiz / ".." / "fora"))
    # Na raiz, "subir" não sai dela.
    assert ws.list_dirs(str(raiz))["parent"] is None


def test_multiplas_raizes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    monkeypatch.setenv("ASO_WORKSPACE_ROOTS", f"{a}:{b}")
    ws = WorkspaceService()
    assert ws.validate(str(b)) == b
    assert ws.list_dirs()["path"] == str(a)  # sem path: primeira raiz


def test_api_fs_e_criacao_recusam_fora_da_raiz(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ASO_WORKSPACE_ROOTS", str(tmp_path))
    client, _svc = _client()
    assert client.get("/v1/fs/dirs", params={"path": "/etc"}, headers=_h("v")).status_code == 400
    assert (
        client.get("/v1/fs/analyze/stream", params={"path": "/etc"}, headers=_h("v"))
    ).status_code == 400
    criar = client.post(
        "/v1/orchestrations", json={"user_request": "x", "target_path": "/etc"}, headers=_h("o")
    )
    assert criar.status_code == 400
    projeto = client.post(
        "/v1/projects", json={"name": "p", "target_path": "/etc"}, headers=_h("o")
    )
    assert projeto.status_code == 400
    assert client.get("/v1/fs/dirs", params={"path": str(tmp_path)}, headers=_h("v")).is_success


# ------------------------------------------------------------- 4. token só no SSE
def test_token_na_query_so_vale_no_sse() -> None:
    client, svc = _client()
    oid = svc.create_orchestration("backend").id
    assert client.get("/v1/orchestrations", params={"token": "a"}).status_code == 401
    assert client.get(f"/v1/orchestrations/{oid}", params={"token": "a"}).status_code == 401
    assert client.get("/v1/orchestrations", headers=_h("v")).status_code == 200


def test_token_na_query_e_aceito_no_sse() -> None:
    from aso.api import app as app_module

    # O gerador SSE é infinito (CLAUDE.md: não consumir no TestClient). Aqui só importa
    # o gateway: com token válido na query, a rota é alcançada e responde 404 para
    # orquestração inexistente, em vez de 401 do gateway.
    client, _svc = _client()
    resposta = client.get("/v1/orchestrations/inexistente/events/stream", params={"token": "v"})
    assert resposta.status_code != 401
    assert app_module is not None


# ------------------------------------------------------------- 5. /metrics sem hidratar
@pytest.mark.parametrize("sql", [False, True])
def test_metrics_nao_hidrata_orquestracoes(
    sql: bool, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo = SqlAlchemyOrchestrationRepository(f"sqlite:///{tmp_path / 'm.db'}") if sql else None
    svc = OrchestrationService(repository=repo)
    orch = svc.create_orchestration("backend")
    m = MetricsService(svc)
    from aso.governance.models import SloEvaluation

    svc.record_slo_evaluation(
        orch.id,
        SloEvaluation(orchestration_id=orch.id, burn_rate=0.5, consumed_pct=12.5, severity="ok"),
    )
    # Instância nova sobre o mesmo repositório: nenhum bundle em cache.
    leitor = OrchestrationService(repository=repo) if sql else svc

    def _proibido(*_a: object, **_k: object) -> object:
        raise AssertionError("/metrics não pode hidratar orquestração")

    monkeypatch.setattr(leitor, "_bundle", _proibido)
    corpo = MetricsService(leitor).prometheus()
    assert f'aso_slo_burn_rate{{orchestration_id="{orch.id}"}} 0.5' in corpo
    assert f'aso_error_budget_consumed_pct{{orchestration_id="{orch.id}"}} 12.5' in corpo
    assert m is not None
