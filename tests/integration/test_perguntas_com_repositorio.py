"""MEL-40 — discovery e revisão leem o repositório em modo leitura (ADR-0069)."""

from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path

from aso.application.orchestration_service import OrchestrationService
from aso.control.triage import DemandBrief
from aso.execution.catalog import ExecutorCatalog, ExecutorProfile
from aso.shared.types import RiskLevel

JUST_CI = "CI externa verificada pelo operador (teste)"

_LEITOR = """
import json, pathlib, sys
sys.stdin.read()
conteudo = pathlib.Path("src/frete.py").read_text().strip()
print(json.dumps({
    "problema": "frete errado", "recomendacao_tecnica": "corrigir a taxa", "confianca": "alta",
    "componentes_afetados": ["src/frete.py", "src/inexistente.py"],
    "evidencias": [
        {"arquivo": "src/frete.py", "trecho": conteudo},
        {"arquivo": "nao/existe.py", "trecho": "inventado"},
    ],
}))
"""

_ESCRITOR = """
import json, pathlib, sys
sys.stdin.read()
pathlib.Path("lixo.txt").write_text("não devia")
print(json.dumps({"problema": "x", "recomendacao_tecnica": "y", "confianca": "alta"}))
"""

_REVISOR = """
import json, pathlib, sys
sys.stdin.read()
lido = pathlib.Path("feature.py").read_text().strip()
print(json.dumps({"veredito": "aprovado_com_sugestoes", "resumo": "li na branch: " + lido}))
"""


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def _repo(path: Path) -> Path:
    path.mkdir(parents=True)
    for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        _git(path, *args)
    (path / "src").mkdir()
    (path / "src" / "frete.py").write_text("TAXA = 0.1\n")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "init")
    return path


def _perfil(nome: str, script: str) -> ExecutorProfile:
    return ExecutorProfile(name=nome, kind="cli", command=shlex.join(["python3", "-c", script]))


def _discovery(tmp_path: Path, script: str) -> tuple[OrchestrationService, str, Path]:
    repo = _repo(tmp_path / "proj")
    svc = OrchestrationService(catalog=ExecutorCatalog([_perfil("agente", script)]))
    oid = svc.create_orchestration(
        "ajustar cálculo de frete",
        target_path=str(repo),
        demand_brief=DemandBrief(problema="frete errado", risco=RiskLevel.LOW),
    ).id
    svc.run_discovery(oid, executor="agente")
    return svc, oid, repo


def test_discovery_le_o_repositorio_e_traz_evidencia_real(tmp_path: Path) -> None:
    svc, oid, repo = _discovery(tmp_path, _LEITOR)
    relatorio = svc.get_discovery_report(oid)
    assert relatorio.origem == "agente" and relatorio.acesso_repo
    assert [(e.arquivo, e.trecho) for e in relatorio.evidencias] == [("src/frete.py", "TAXA = 0.1")]
    # saneamento: componente inexistente sai e fica registrado
    assert relatorio.componentes_afetados == ["src/frete.py"]
    assert relatorio.componentes_descartados == ["src/inexistente.py"]
    assert _git(repo, "status", "--porcelain") == ""
    assert len(_git(repo, "worktree", "list").splitlines()) == 1


def test_agente_que_escreve_durante_a_pergunta_tem_a_resposta_descartada(tmp_path: Path) -> None:
    svc, oid, repo = _discovery(tmp_path, _ESCRITOR)
    relatorio = svc.get_discovery_report(oid)
    assert relatorio.origem == "heuristica"
    assert "alterou o repositório" in relatorio.fallback_reason
    eventos = [e for e in svc.timeline(oid) if e.type == "PerguntaDescartadaPorEscrita"]
    assert len(eventos) == 1 and eventos[0].payload["tipo"] == "discovery"
    runs = [r for r in svc.list_agent_runs(oid) if r.task_type == "discovery"]
    assert runs and runs[-1].status == "falha" and runs[-1].envelope["acesso_repo"] is True
    # a escrita ficou só no worktree descartado: base intacta
    assert not (repo / "lixo.txt").exists()
    assert _git(repo, "status", "--porcelain") == ""


def test_revisor_le_a_branch_da_pr_e_recebe_criterios_e_ci(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "proj")
    implementador = ExecutorProfile(
        name="implementador",
        kind="cli",
        command=shlex.join(["bash", "-c", "echo 'VALOR = 42' > feature.py"]),
    )
    catalog = ExecutorCatalog([implementador, _perfil("revisor", _REVISOR)])
    svc = OrchestrationService(catalog=catalog)
    oid = svc.create_orchestration(
        "ajustar módulo", target_path=str(repo), executor="implementador"
    ).id
    card = svc.get_cards(oid)[0]
    svc.run_card(oid, card.id)
    pr = svc.list_pulls(oid)[0]
    svc.report_ci(oid, pr.id, "passed", justificativa=JUST_CI)
    base_antes = _git(repo, "rev-parse", "HEAD")
    branch_antes = _git(repo, "rev-parse", pr.branch)

    atualizado = svc.run_review(oid, pr.id, executor="revisor")

    assert atualizado.review_verdict["resumo"] == "li na branch: VALOR = 42"
    assert _git(repo, "rev-parse", "HEAD") == base_antes
    assert _git(repo, "rev-parse", pr.branch) == branch_antes
    assert len(_git(repo, "worktree", "list").splitlines()) == 1
    run = [r for r in svc.list_agent_runs(oid) if r.task_type == "revisao"][-1]
    assert run.envelope["acesso_repo"] is True
    assert "checkout SOMENTE LEITURA" in run.prompt
    assert "Critérios de aceite" in run.prompt
    assert "Última execução da CI" in run.prompt and "origem: declarada" in run.prompt
    assert json.dumps(run.envelope)  # envelope serializável com a marca de acesso
