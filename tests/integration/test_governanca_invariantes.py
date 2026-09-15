"""MEL-34 — invariantes de governança: cada teste TENTA violar uma regra inviolável.

Caminho feliz não prova governança: os bypasses encontrados na revisão (avanço sem gate,
estratégia crítica sem aprovação, CI declarada, execução duplicada, operator rodando
comando no host) passaram porque nada tentava burlá-los. Aqui tudo passa pela API, com
`AuthService` de chaves reais (viewer/operator/admin), e o esperado é a recusa.

Mapa regra → teste: [docs/GOVERNANCE.md](../../docs/GOVERNANCE.md). Arquivo obrigatório no CI.
"""

from __future__ import annotations

import ast
import json
import subprocess
import threading
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from aso.agents.executor import LocalMockExecutionProvider
from aso.agents.models import AgentOutput, AgentSpec
from aso.api.app import create_app
from aso.api.auth import AuthService, Principal
from aso.application.orchestration_service import OrchestrationService
from aso.control.models import DecisionInput
from aso.control.review import ReviewCommentDraft, ReviewVerdict
from aso.db.repository import SqlAlchemyOrchestrationRepository
from aso.execution.cli_provider import CliAgentExecutionProvider
from aso.execution.settings_store import ExecutorSettingsStore
from aso.shared.types import ColumnKey, Phase

RAIZ = Path(__file__).resolve().parents[2]
_TOKENS = {
    "v": Principal(actor="leitor", role="viewer"),
    "o": Principal(actor="operador", role="operator"),
    "a": Principal(actor="admin", role="admin"),
}
OP = {"Authorization": "Bearer o"}
ADM = {"Authorization": "Bearer a"}


def _client(svc: OrchestrationService) -> TestClient:
    return TestClient(create_app(svc, auth=AuthService(_TOKENS, dev_mode=False)))


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for args in (
        ["init", "-q", "-b", "main"],
        ["config", "user.email", "t@t"],
        ["config", "user.name", "t"],
    ):
        subprocess.run(["git", *args], cwd=path, check=True, capture_output=True)
    (path / "README.md").write_text("base\n")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True, capture_output=True)


def _head(repo: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


class _ProviderContador(LocalMockExecutionProvider):
    def __init__(self, *, bloquear: bool = False) -> None:
        self.chamadas = 0
        self.entrou = threading.Event()
        self.liberar = threading.Event()
        if not bloquear:
            self.liberar.set()

    def execute(self, agent: AgentSpec, task: dict[str, Any]) -> AgentOutput:
        self.chamadas += 1
        self.entrou.set()
        assert self.liberar.wait(timeout=10)
        return super().execute(agent, task)


# =============================================================== Regra 1 — ContextBus
_MUTADORES_DO_STORE = {"apply_patch", "restore_from", "restore_section"}
# Únicos pontos autorizados a mutar o contexto canônico, cada um por um motivo registrado:
# o bus (pipeline de 6 etapas) e os dois protocolos de restauração admin + ADR (§23).
_CHAMADORES_AUTORIZADOS = {
    ("src/aso/governance/contextbus.py", "apply_patch"),
    ("src/aso/governance/snapshot_engine.py", "restore_from"),
    # Restauração seletiva governada (admin + ADR); vive no ApprovalService (MEL-32).
    ("src/aso/application/approvals.py", "restore_section"),
}


def _receptor_e_store(receptor: ast.expr) -> bool:
    """`store.x(...)`, `self.store.x(...)`, `b.store.x(...)` — o contexto canônico em si."""
    if isinstance(receptor, ast.Name):
        return receptor.id == "store"
    return isinstance(receptor, ast.Attribute) and receptor.attr == "store"


def test_regra1_so_o_bus_e_as_restauracoes_governadas_mutam_o_contexto() -> None:
    encontrados: set[tuple[str, str]] = set()
    for arquivo in (RAIZ / "src/aso").rglob("*.py"):
        if arquivo.name == "context_store.py":
            continue  # a própria definição
        arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
        for no in ast.walk(arvore):
            if (
                isinstance(no, ast.Call)
                and isinstance(no.func, ast.Attribute)
                and no.func.attr in _MUTADORES_DO_STORE
                and _receptor_e_store(no.func.value)
            ):
                encontrados.add((str(arquivo.relative_to(RAIZ)), no.func.attr))
    assert encontrados == _CHAMADORES_AUTORIZADOS


def test_regra1_patch_pela_api_passa_pelo_bus_e_restauracoes_exigem_admin() -> None:
    svc = OrchestrationService()
    client = _client(svc)
    oid = client.post("/v1/orchestrations", json={"user_request": "x"}, headers=OP).json()["id"]
    corpo = {
        "agent": "ArchitectureDesignAgent",
        "phase": "F2",
        "patch_type": "update",
        "target_path": "architecture.pattern",
        "content": "modular-monolith",
    }
    r = client.post(f"/v1/orchestrations/{oid}/context-patches", json=corpo, headers=OP).json()
    assert r["status"] == "applied"
    auditoria = client.get(f"/v1/orchestrations/{oid}/audit", headers=OP).json()
    assert auditoria["patches_applied"] == 1  # a escrita ficou registrada no bus
    for rota in (
        f"/v1/orchestrations/{oid}/rollback",
        f"/v1/orchestrations/{oid}/snapshots/O1/restore-section",
    ):
        assert client.post(rota, json={}, headers=OP).status_code == 403


# =========================================================== Regra 2 — deny-by-default
@pytest.mark.parametrize(
    ("agente", "alvo"),
    [
        ("DocumentationAgent", "architecture.pattern"),  # agente real, seção alheia
        ("AgenteInventado", "engineering.backlog"),  # agente sem política nenhuma
    ],
)
def test_regra2_patch_sem_permissao_e_rejeitado_com_conflito(agente: str, alvo: str) -> None:
    svc = OrchestrationService()
    client = _client(svc)
    oid = client.post("/v1/orchestrations", json={"user_request": "x"}, headers=OP).json()["id"]
    corpo = {
        "agent": agente,
        "phase": "F2",
        "patch_type": "update",
        "target_path": alvo,
        "content": "x",
    }
    r = client.post(f"/v1/orchestrations/{oid}/context-patches", json=corpo, headers=OP).json()
    assert r["status"] == "rejected"
    assert client.get(f"/v1/orchestrations/{oid}/conflicts", headers=OP).json()
    assert client.get(f"/v1/orchestrations/{oid}/audit", headers=OP).json()["patches_applied"] == 0


# ======================================================================= Regra 3 — gate
def test_regra3_avanco_sem_gate_e_com_gate_reprovado_devolve_409() -> None:
    svc = OrchestrationService()
    client = _client(svc)
    oid = client.post("/v1/orchestrations", json={"user_request": "x"}, headers=OP).json()["id"]
    base = f"/v1/orchestrations/{oid}"
    assert client.post(f"{base}/advance-phase", headers=ADM).status_code == 409

    # F1…F4 sem cards: gate vacuamente aprovado, avanço governado.
    for _ in range(4):
        assert client.post(f"{base}/quality-gates/run", json={}, headers=OP).status_code == 200
        assert client.post(f"{base}/advance-phase", headers=ADM).status_code == 200
    assert svc.get(oid).current_phase == Phase.F5
    # F5 tem cards e nenhum output: gate reprova e o avanço continua recusado.
    gate = client.post(f"{base}/quality-gates/run", json={}, headers=OP).json()
    assert gate["status"] == "FAILED"
    recusa = client.post(f"{base}/advance-phase", headers=ADM)
    assert recusa.status_code == 409
    assert "não aprovado" in recusa.json()["detail"]
    assert svc.get(oid).current_phase == Phase.F5


# ================================================= Regra 4 — aprovação humana crítica
def test_regra4_estrategia_pendente_bloqueia_execucao_sem_chamar_agente() -> None:
    provider = _ProviderContador()
    svc = OrchestrationService(provider=provider)
    orch = svc.create_orchestration(
        "deploy em produção",
        decision_input=DecisionInput(user_request="deploy", domains=["devops"], impacts=["deploy"]),
    )
    client = _client(svc)
    card_id = svc.get_cards(orch.id)[0].id
    base = f"/v1/orchestrations/{orch.id}"
    for rota in (
        f"{base}/cards/{card_id}/run",
        f"{base}/run-plan",
        f"{base}/run-phase",
        f"{base}/autopilot",
    ):
        assert client.post(rota, json={}, headers=ADM).status_code == 409, rota
    assert provider.chamadas == 0


_ROTAS_ADMIN = [
    ("post", "/v1/orchestrations/{oid}/pulls/pr_x/merge", {}),
    ("post", "/v1/approvals/ap_x/approve", {}),
    ("post", "/v1/approvals/ap_x/reject", {}),
    ("post", "/v1/orchestrations/{oid}/rollback", {}),
    ("post", "/v1/orchestrations/{oid}/advance-phase", {}),
    ("post", "/v1/orchestrations/{oid}/pulls/pr_x/ci", {"status": "passed", "justificativa": "x"}),
    ("put", "/v1/orchestrations/{oid}/validation-checks", {"checks": []}),
    ("put", "/v1/orchestrations/{oid}/deploy/config", {"command": "true"}),
    ("put", "/v1/orchestrations/{oid}/deploy/pipeline", {"estagios": []}),
    ("post", "/v1/orchestrations/{oid}/deploy/run", {}),
    ("patch", "/v1/orchestrations/{oid}/execution-settings", {"validation_command": "true"}),
    ("post", "/v1/orchestrations", {"user_request": "x", "validation_command": "rm -rf /"}),
    ("post", "/v1/executors", {"name": "novo", "kind": "cli", "command": "bash"}),
    ("put", "/v1/orchestrations/{oid}/budget", {"orcamento_usd": 1}),
    ("post", "/v1/orchestrations/{oid}/worktrees/prune", {}),
]


@pytest.mark.parametrize(("metodo", "rota", "corpo"), _ROTAS_ADMIN)
def test_regra4_operator_recebe_403_em_acoes_criticas(
    metodo: str, rota: str, corpo: dict[str, Any]
) -> None:
    svc = OrchestrationService()
    client = _client(svc)
    oid = svc.create_orchestration("x").id
    resposta = getattr(client, metodo)(rota.format(oid=oid), json=corpo, headers=OP)
    assert resposta.status_code == 403, resposta.text


# ======================================================== Regra 5 — worktree isolado
def test_regra5_execucao_do_card_nao_toca_a_branch_base_ate_o_merge(tmp_path: Path) -> None:
    repo = tmp_path / "proj"
    _init_repo(repo)
    provider = CliAgentExecutionProvider(["bash", "-c", "echo 'gerado' > feature.py"], str(repo))
    svc = OrchestrationService(provider=provider)
    client = _client(svc)
    oid = client.post(
        "/v1/orchestrations",
        json={"user_request": "implementar no backend", "validation_command": "true"},
        headers=ADM,
    ).json()["id"]
    base_antes = _head(repo)
    card_id = svc.get_cards(oid)[0].id

    assert client.post(f"/v1/orchestrations/{oid}/cards/{card_id}/run", headers=OP).is_success
    assert _head(repo) == base_antes  # o agente escreveu no worktree, não na base
    assert not (repo / "feature.py").exists()

    pr_id = svc.list_pulls(oid)[0].id
    assert client.post(f"/v1/orchestrations/{oid}/pulls/{pr_id}/ci/run", headers=OP).is_success
    client.post(
        f"/v1/orchestrations/{oid}/pulls/{pr_id}/review",
        json={"status": "approved", "justificativa": "revisão humana do teste"},
        headers=ADM,
    )
    assert client.post(f"/v1/orchestrations/{oid}/pulls/{pr_id}/merge", headers=ADM).is_success
    assert _head(repo) != base_antes  # só o merge governado muda a base
    assert (repo / "feature.py").exists()


# ======================================================== Regra 6 — merge governado
def _pr_aberta(tmp_path: Path) -> tuple[OrchestrationService, TestClient, str, str]:
    repo = tmp_path / "proj"
    _init_repo(repo)
    provider = CliAgentExecutionProvider(["bash", "-c", "echo x > f.py"], str(repo))
    svc = OrchestrationService(provider=provider)
    client = _client(svc)
    oid = client.post(
        "/v1/orchestrations",
        json={"user_request": "implementar no backend", "validation_command": "true"},
        headers=ADM,
    ).json()["id"]
    client.post(f"/v1/orchestrations/{oid}/cards/{svc.get_cards(oid)[0].id}/run", headers=OP)
    return svc, client, oid, svc.list_pulls(oid)[0].id


def test_regra6_merge_sem_ci_executada_ou_sem_review_aprovada_devolve_409(tmp_path: Path) -> None:
    svc, client, oid, pr_id = _pr_aberta(tmp_path)
    base = f"/v1/orchestrations/{oid}/pulls/{pr_id}"
    assert client.post(f"{base}/merge", headers=ADM).status_code == 409  # nada aprovado
    client.post(f"{base}/review", json={"status": "approved", "justificativa": "ok"}, headers=ADM)
    assert client.post(f"{base}/merge", headers=ADM).status_code == 409  # CI pendente
    # Operator não consegue "declarar" a CI para destravar o merge.
    assert client.post(f"{base}/ci", json={"status": "passed"}, headers=OP).status_code == 403
    assert client.post(f"{base}/merge", headers=ADM).status_code == 409


def test_regra6_merge_sem_review_aprovada_devolve_409(tmp_path: Path) -> None:
    svc, client, oid, pr_id = _pr_aberta(tmp_path)
    base = f"/v1/orchestrations/{oid}/pulls/{pr_id}"
    assert client.post(f"{base}/ci/run", headers=OP).json()["ci_origem"] == "executada"
    # Aprovar review sem veredito nem justificativa não existe (ADR-0017).
    assert client.post(f"{base}/review", json={"status": "approved"}, headers=OP).status_code == 409
    assert client.post(f"{base}/merge", headers=ADM).status_code == 409


def test_regra6_merge_com_comentario_obrigatorio_pendente_devolve_409(tmp_path: Path) -> None:
    svc, client, oid, pr_id = _pr_aberta(tmp_path)
    b = svc._bundle(oid)  # noqa: SLF001 - produz o comentário como o revisor produziria
    pr = next(p for p in b.pull_requests if p.id == pr_id)
    card = b.board_service.get_card(str(pr.card_id))
    assert card is not None
    veredito = ReviewVerdict(
        # Veredito que NÃO aprova sozinho: o comentário obrigatório não é auto-resolvido.
        veredito="alteracoes_obrigatorias",
        comentarios=[
            ReviewCommentDraft(arquivo="f.py", linha=1, descricao="validar", obrigatorio=True)
        ],
    )
    svc._apply_review_verdict(b, pr, card, veredito, actor="revisor")  # noqa: SLF001
    base = f"/v1/orchestrations/{oid}/pulls/{pr_id}"
    client.post(f"{base}/ci/run", headers=OP)
    client.post(f"{base}/review", json={"status": "approved", "justificativa": "ok"}, headers=ADM)
    resposta = client.post(f"{base}/merge", headers=ADM)
    assert resposta.status_code == 409
    assert "comentário obrigatório" in resposta.json()["detail"]


# ======================================================= Execução única (claim, ADR-0058)
def test_execucao_concorrente_do_mesmo_card_roda_o_agente_uma_vez() -> None:
    provider = _ProviderContador(bloquear=True)
    svc = OrchestrationService(provider=provider)
    client = _client(svc)
    oid = svc.create_orchestration("backend").id
    card_id = next(c.id for c in svc.get_cards(oid) if c.status == ColumnKey.READY)
    rota = f"/v1/orchestrations/{oid}/cards/{card_id}/run"
    thread = threading.Thread(target=lambda: client.post(rota, headers=OP))
    thread.start()
    assert provider.entrou.wait(timeout=10)
    assert client.post(rota, headers=OP).status_code == 409
    provider.liberar.set()
    thread.join(timeout=10)
    assert provider.chamadas == 1


# ======================================================================= Regra 9 — secrets
def test_regra9_valor_de_chave_nunca_e_persistido(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    segredo = "sk-segredo-que-nao-pode-vazar-123"
    monkeypatch.setenv("MINHA_CHAVE_LLM", segredo)
    arquivo_executores = tmp_path / "executors.json"
    banco = tmp_path / "aso.db"
    svc = OrchestrationService(
        repository=SqlAlchemyOrchestrationRepository(f"sqlite:///{banco}"),
        executor_store=ExecutorSettingsStore(str(arquivo_executores)),
    )
    client = _client(svc)
    # Tentativa: mandar o VALOR da chave no cadastro do executor.
    criado = client.post(
        "/v1/executors",
        json={
            "name": "llm-teste",
            "kind": "llm",
            "provider": "openai",
            "model": "gpt",
            "api_key_env": "MINHA_CHAVE_LLM",
            "api_key": segredo,
        },
        headers=ADM,
    )
    assert criado.status_code < 400, criado.text
    oid = client.post("/v1/orchestrations", json={"user_request": "x"}, headers=OP).json()["id"]
    client.post(f"/v1/orchestrations/{oid}/run-plan", headers=OP)

    assert segredo not in json.dumps(client.get("/v1/executors", headers=ADM).json())
    assert segredo not in arquivo_executores.read_text(encoding="utf-8")
    assert segredo.encode() not in banco.read_bytes()
