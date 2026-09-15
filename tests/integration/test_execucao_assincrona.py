"""MEL-31 — rotas de execução assíncronas: 202 + job, polling, cancelamento e boot (ADR-0067)."""

from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from aso.agents.executor import LocalMockExecutionProvider
from aso.agents.models import AgentOutput, AgentSpec
from aso.api.app import create_app
from aso.api.auth import AuthService, Principal
from aso.application.orchestration_service import OrchestrationService
from aso.control.models import DecisionInput
from aso.execution.cli_provider import CliAgentExecutionProvider
from aso.execution.jobs import (
    MOTIVO_REINICIO,
    STATUS_CANCELADO,
    STATUS_CONCLUIDO,
    STATUS_FALHOU,
    STATUS_RODANDO,
    InMemoryJobRepository,
    Job,
)
from aso.governance.models import HumanApproval
from aso.shared.types import Phase

_TOKENS = {
    "v": Principal(actor="leitor", role="viewer"),
    "o": Principal(actor="operador", role="operator"),
    "a": Principal(actor="admin", role="admin"),
}
OP = {"Authorization": "Bearer o"}
ADM = {"Authorization": "Bearer a"}
LEITOR = {"Authorization": "Bearer v"}


class _ProviderLento:
    """Provider fake que demora — a requisição não pode esperar por ele."""

    id = "lento"

    def __init__(self, segundos: float) -> None:
        self._segundos = segundos
        self._mock = LocalMockExecutionProvider()
        self.chamadas = 0

    def execute(self, agent: AgentSpec, task: dict[str, Any]) -> AgentOutput:
        self.chamadas += 1
        time.sleep(self._segundos)
        return self._mock.execute(agent, task)


def _cliente(svc: OrchestrationService, **kwargs: Any) -> TestClient:
    app = create_app(
        svc, auth=AuthService(_TOKENS, dev_mode=False), execucao_assincrona=True, **kwargs
    )
    return TestClient(app)


def _aguardar(client: TestClient, job_id: str, timeout: float = 20.0) -> dict[str, Any]:
    limite = time.monotonic() + timeout
    while time.monotonic() < limite:
        job = client.get(f"/v1/jobs/{job_id}", headers=OP).json()
        if job["status"] in (STATUS_CONCLUIDO, STATUS_FALHOU, STATUS_CANCELADO):
            return dict(job)
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} não terminou")


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=path, check=True, capture_output=True)
    (path / "README.md").write_text("base\n")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True, capture_output=True)


def test_run_card_responde_202_na_hora_e_conclui_por_polling() -> None:
    provider = _ProviderLento(1.5)
    svc = OrchestrationService(provider=provider)
    oid = svc.create_orchestration("implementar no backend").id
    card = svc.get_cards(oid)[0]
    client = _cliente(svc)

    inicio = time.monotonic()
    resp = client.post(f"/v1/orchestrations/{oid}/cards/{card.id}/run", headers=OP)
    assert time.monotonic() - inicio < 1.0  # não esperou o provider lento
    assert resp.status_code == 202
    corpo = resp.json()
    assert corpo["status"] == "queued" and corpo["acompanhar"] == f"/v1/jobs/{corpo['job_id']}"

    job = _aguardar(client, corpo["job_id"])
    assert job["status"] == STATUS_CONCLUIDO
    assert job["ator"] == "operador" and job["card_id"] == card.id
    assert isinstance(job["resultado"], list) and job["resultado"]
    assert provider.chamadas == 1
    assert svc.get_cards(oid)[0].em_execucao_desde is None  # claim liberado
    listados = client.get(f"/v1/orchestrations/{oid}/jobs", headers=LEITOR).json()
    assert [j["id"] for j in listados] == [corpo["job_id"]]


def test_erro_de_governanca_vira_job_failed_com_o_mesmo_status_http() -> None:
    """Estratégia pendente (regra 4) continua bloqueando — agora registrada no job."""
    provider = _ProviderLento(0.0)
    svc = OrchestrationService(provider=provider)
    oid = svc.create_orchestration("backend").id
    # Estratégia crítica pendente de decisão humana (o mesmo registro que o plano cria).
    pendente = HumanApproval(orchestration_id=oid, action="estratégia", tipo="estrategia")
    svc._bundle(oid).approvals.append(pendente)  # noqa: SLF001
    card = svc.get_cards(oid)[0]
    client = _cliente(svc)

    resp = client.post(f"/v1/orchestrations/{oid}/cards/{card.id}/run", headers=OP)
    assert resp.status_code == 202
    job = _aguardar(client, resp.json()["job_id"])
    assert job["status"] == STATUS_FALHOU
    assert job["erro_status"] == 409 and "aprovação humana" in job["erro"]
    assert provider.chamadas == 0


def test_cancelar_run_em_andamento_encerra_o_subprocess_e_libera_o_card(tmp_path: Path) -> None:
    repo = tmp_path / "proj"
    _init_repo(repo)
    marcador = tmp_path / "agente-rodando"
    comando = ["bash", "-c", f"touch {marcador}; sleep 30"]
    svc = OrchestrationService(provider=CliAgentExecutionProvider(comando, str(repo)))
    oid = svc.create_orchestration("implementar no backend").id
    card = svc.get_cards(oid)[0]
    client = _cliente(svc)

    job_id = client.post(f"/v1/orchestrations/{oid}/cards/{card.id}/run", headers=OP).json()[
        "job_id"
    ]
    limite = time.monotonic() + 10
    while not marcador.exists() and time.monotonic() < limite:
        time.sleep(0.05)
    assert marcador.exists(), "o agente CLI não chegou a rodar"
    assert client.get(f"/v1/jobs/{job_id}", headers=OP).json()["status"] == STATUS_RODANDO

    inicio = time.monotonic()
    cancel = client.post(f"/v1/jobs/{job_id}/cancel", headers=OP)
    assert cancel.status_code == 200 and cancel.json()["cancelamento_solicitado"] is True
    job = _aguardar(client, job_id, timeout=15)
    assert job["status"] == STATUS_CANCELADO
    assert time.monotonic() - inicio < 10  # não esperou os 30 s do sleep
    atual = svc.get_cards(oid)[0]
    assert atual.em_execucao_desde is None and atual.execution_id is None
    assert client.post(f"/v1/jobs/{job_id}/cancel", headers=OP).status_code == 409


def test_viewer_nao_cancela_job() -> None:
    svc = OrchestrationService(provider=_ProviderLento(0.0))
    oid = svc.create_orchestration("backend").id
    card = svc.get_cards(oid)[0]
    client = _cliente(svc)
    job_id = client.post(f"/v1/orchestrations/{oid}/cards/{card.id}/run", headers=OP).json()[
        "job_id"
    ]
    assert client.post(f"/v1/jobs/{job_id}/cancel", headers=LEITOR).status_code == 403
    _aguardar(client, job_id)


def test_boot_marca_running_orfao_failed_e_executa_os_da_fila() -> None:
    svc = OrchestrationService()
    oid = svc.create_orchestration("backend").id
    card = svc.get_cards(oid)[0]
    repo = InMemoryJobRepository()
    orfao = Job(
        orchestration_id=oid,
        operacao="run_card",
        card_id=card.id,
        status=STATUS_RODANDO,
        dono="runtime_que_morreu",
    )
    na_fila = Job(orchestration_id=oid, operacao="run_card", card_id=card.id)
    repo.salvar(orfao)
    repo.salvar(na_fila)

    with _cliente(svc, job_repository=repo) as client:  # lifespan = boot do runtime
        executado = _aguardar(client, na_fila.id)
        recuperado = client.get(f"/v1/jobs/{orfao.id}", headers=OP).json()
    assert executado["status"] == STATUS_CONCLUIDO
    assert recuperado["status"] == STATUS_FALHOU and recuperado["erro"] == MOTIVO_REINICIO


def test_autopilot_assincrono_de_ponta_a_ponta_e_aprovacao_enfileira_a_proxima_fase() -> None:
    svc = OrchestrationService()
    oid = svc.create_orchestration(
        "arquitetura e backend",
        decision_input=DecisionInput(user_request="x", domains=["architecture", "backend"]),
    ).id
    client = _cliente(svc)

    partida = client.post(f"/v1/orchestrations/{oid}/autopilot", json={}, headers=OP)
    assert partida.status_code == 202
    job = _aguardar(client, partida.json()["job_id"])
    assert job["status"] == STATUS_CONCLUIDO and job["resultado"]["phase"] == "F2"
    approval_id = job["resultado"]["approval_id"]

    inicio = time.monotonic()
    aprovado = client.post(f"/v1/approvals/{approval_id}/approve", headers=ADM)
    assert aprovado.status_code == 200
    assert time.monotonic() - inicio < 1.0

    fases = [
        j
        for j in client.get(f"/v1/orchestrations/{oid}/jobs", headers=OP).json()
        if j["operacao"] == "run_phase"
    ]
    assert len(fases) == 1 and fases[0]["parametros"]["autopilot"] is True
    proxima = _aguardar(client, fases[0]["id"])
    assert proxima["status"] == STATUS_CONCLUIDO
    assert svc.get(oid).current_phase == Phase.F5
    eventos = [e.type for e in svc.timeline(oid)]
    assert "PhaseScheduled" in eventos
    pendentes = [
        a
        for a in svc.list_approvals(oid)
        if a.status == "pending" and a.payload.get("kind") == "phase_gate"
    ]
    assert pendentes  # parou na aprovação da fase seguinte, como no modo síncrono


def test_rotas_de_execucao_ficam_sincronas_sem_a_flag() -> None:
    svc = OrchestrationService()
    oid = svc.create_orchestration("backend").id
    card = svc.get_cards(oid)[0]
    client = TestClient(create_app(svc, auth=AuthService(_TOKENS, dev_mode=False)))
    resp = client.post(f"/v1/orchestrations/{oid}/cards/{card.id}/run", headers=OP)
    assert resp.status_code == 200 and isinstance(resp.json(), list)
    assert client.get("/v1/jobs/job_x", headers=OP).status_code == 404


def test_cancelar_job_na_fila_antes_do_worker_nunca_executa(monkeypatch: Any) -> None:
    monkeypatch.setenv("ASO_WORKERS", "1")
    liberar = threading.Event()

    class _Bloqueado(_ProviderLento):
        def execute(self, agent: AgentSpec, task: dict[str, Any]) -> AgentOutput:
            liberar.wait(10)
            return super().execute(agent, task)

    provider = _Bloqueado(0.0)
    svc = OrchestrationService(provider=provider)
    oid = svc.create_orchestration("backend").id
    card = svc.get_cards(oid)[0]
    client = _cliente(svc)
    ocupando = client.post(f"/v1/orchestrations/{oid}/cards/{card.id}/run", headers=OP).json()
    esperando = client.post(f"/v1/orchestrations/{oid}/run-plan", headers=OP).json()

    cancelado = client.post(f"/v1/jobs/{esperando['job_id']}/cancel", headers=OP).json()
    assert cancelado["status"] == STATUS_CANCELADO  # estava na fila: cancela na hora
    liberar.set()
    assert _aguardar(client, ocupando["job_id"])["status"] == STATUS_CONCLUIDO
    time.sleep(0.2)
    assert client.get(f"/v1/jobs/{esperando['job_id']}", headers=OP).json()["status"] == (
        STATUS_CANCELADO
    )
    assert provider.chamadas == 1  # o run-plan cancelado nunca chamou o agente
