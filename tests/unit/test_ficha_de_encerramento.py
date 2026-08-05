"""Ficha de encerramento do card (§23 do fluxo.md, ADR-0021).

Preenchida em `merge_pr` — o ponto em que o card chega a Done. Cobre: campos
disponíveis aparecem; campos sem dado no runtime não aparecem inventados; ações de
severidade `sugestao` do veredito viram riscos residuais.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from aso.control.orchestration_service import OrchestrationService
from aso.execution.cli_provider import CliAgentExecutionProvider


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    run = lambda *a: subprocess.run(["git", *a], cwd=path, check=True, capture_output=True)  # noqa: E731
    run("init", "-q")
    run("config", "user.email", "t@t")
    run("config", "user.name", "t")
    (path / "README.md").write_text("base\n")
    run("add", "-A")
    run("commit", "-q", "-m", "init")


def _merge_governado(tmp_path: Path) -> tuple[OrchestrationService, str, str]:
    repo = tmp_path / "proj"
    _init_repo(repo)
    provider = CliAgentExecutionProvider(["bash", "-c", "echo 'gerado' > feature.py"], str(repo))
    svc = OrchestrationService(provider=provider)
    orch = svc.create_orchestration("implementar no backend")
    card = svc.get_cards(orch.id)[0]
    svc.run_card(orch.id, card.id)  # já abre a PR sozinho (branch presente no output)
    pr = svc.list_pulls(orch.id)[0]
    svc.report_ci(orch.id, pr.id, "passed")
    svc.report_review(orch.id, pr.id, "approved", justificativa="revisão manual do teste")
    svc.merge_pr(orch.id, pr.id)
    return svc, orch.id, card.id


def test_merge_preenche_a_ficha_de_encerramento(tmp_path: Path) -> None:
    svc, oid, card_id = _merge_governado(tmp_path)
    card = svc.get_cards(oid)[0]
    assert card.status.value == "Done"
    assert card.closure  # não vazio
    assert card.closure["resumo"]
    assert card.closure["executor"] == card.executor
    assert card.closure["branch"] == card.branch
    assert card.closure["pr_id"]
    # `report_review` é o caminho manual (sem agente revisor rodando de verdade) —
    # `review_rounds` só sobe em `run_review`/`_apply_review_verdict`.
    assert card.closure["rodadas_revisao"] == 0
    assert "encerrado_em" in card.closure

    # A ficha também é acessível pela API dedicada.
    ficha = svc.get_card_closure(oid, card_id)
    assert ficha == card.closure


def test_campo_sem_dado_no_runtime_nao_aparece_inventado(tmp_path: Path) -> None:
    """Sem discovery/spec rodados, `documentos` fica vazio — não inventa versão 0."""
    svc, oid, _card_id = _merge_governado(tmp_path)
    card = svc.get_cards(oid)[0]
    assert card.closure["documentos"] == {}


def test_acoes_de_severidade_sugestao_viram_riscos_residuais(tmp_path: Path) -> None:
    repo = tmp_path / "proj"
    _init_repo(repo)
    provider = CliAgentExecutionProvider(["bash", "-c", "echo 'gerado' > feature.py"], str(repo))
    svc = OrchestrationService(provider=provider)
    orch = svc.create_orchestration("implementar no backend")
    card = svc.get_cards(orch.id)[0]
    svc.run_card(orch.id, card.id)  # já abre a PR sozinho (branch presente no output)
    pr_ref = svc.list_pulls(orch.id)[0]
    svc.report_ci(orch.id, pr_ref.id, "passed")
    # Simula um veredito já aprovado, com uma ação de severidade `sugestao` pendente
    # (não bloqueou a aprovação, mas fica registrada como risco residual no §23).
    pr_ref.review_verdict = {
        "veredito": "aprovado_com_sugestoes",
        "acoes": [
            {"descricao": "considerar cache", "categoria": "performance", "severidade": "sugestao"},
            {"descricao": "corrigir X", "categoria": "correcao", "severidade": "obrigatoria"},
        ],
        "revisor": "revisor-x",
        "origem": "agente",
    }
    pr_ref.review_status = "approved"
    svc.merge_pr(orch.id, pr_ref.id)
    card = svc.get_cards(orch.id)[0]
    assert card.closure["riscos_residuais"] == ["considerar cache"]
