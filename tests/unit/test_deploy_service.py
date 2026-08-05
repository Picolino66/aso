"""Implantação governada — funções puras (§18-22 do fluxo.md, ADR-0023).

`executar_deploy`/`validar_pos_deploy` só rodam comandos configurados (nunca
provisionam infraestrutura); `exige_aceite_humano` decide auto-vs-humano no
mesmo molde de `exige_aprovacao_discovery` (ADR-0020).
"""

from __future__ import annotations

from aso.control.deploy import (
    VALIDACAO_REPROVADA,
    DeployRun,
    executar_deploy,
    exige_aceite_humano,
    validar_pos_deploy,
)
from aso.control.models import ValidationCheck
from aso.control.triage import DemandBrief
from aso.shared.types import RiskLevel

# ------------------------------------------------------------- executar_deploy


def test_executar_deploy_sucesso(tmp_path) -> None:  # type: ignore[no-untyped-def]
    ok, logs, duracao = executar_deploy("bash -c 'echo implantado; exit 0'", str(tmp_path))
    assert ok is True
    assert "implantado" in logs
    assert duracao >= 0


def test_executar_deploy_falha_nunca_lanca(tmp_path) -> None:  # type: ignore[no-untyped-def]
    ok, logs, _duracao = executar_deploy("bash -c 'exit 1'", str(tmp_path))
    assert ok is False
    assert "exit=1" in logs


# ---------------------------------------------------------- validar_pos_deploy


def test_validar_pos_deploy_sem_health_checks_aprova_vacuamente(tmp_path) -> None:  # type: ignore[no-untyped-def]
    aprovado, resultados = validar_pos_deploy([], str(tmp_path))
    assert aprovado is True
    assert resultados == []


def test_validar_pos_deploy_bloqueante_que_falha_reprova(tmp_path) -> None:  # type: ignore[no-untyped-def]
    checks = [ValidationCheck(nome="health", comando="bash -c 'exit 1'", bloqueante=True)]
    aprovado, resultados = validar_pos_deploy(checks, str(tmp_path))
    assert aprovado is False
    assert resultados[0]["ok"] is False


def test_validar_pos_deploy_nao_bloqueante_que_falha_nao_reprova(tmp_path) -> None:  # type: ignore[no-untyped-def]
    checks = [ValidationCheck(nome="smoke", comando="bash -c 'exit 1'", bloqueante=False)]
    aprovado, resultados = validar_pos_deploy(checks, str(tmp_path))
    assert aprovado is True
    assert resultados[0]["ok"] is False


def test_validar_pos_deploy_todos_passam(tmp_path) -> None:  # type: ignore[no-untyped-def]
    checks = [
        ValidationCheck(nome="a", comando="bash -c 'exit 0'"),
        ValidationCheck(nome="b", comando="bash -c 'exit 0'"),
    ]
    aprovado, resultados = validar_pos_deploy(checks, str(tmp_path))
    assert aprovado is True
    assert [r["nome"] for r in resultados] == ["a", "b"]


# ------------------------------------------------------------ exige_aceite_humano


def test_exige_aceite_humano_risco_baixo_sem_impacto_e_automatico() -> None:
    deploy = DeployRun()
    brief = DemandBrief(risco=RiskLevel.LOW)
    assert exige_aceite_humano(deploy, brief) is False


def test_exige_aceite_humano_risco_alto() -> None:
    deploy = DeployRun()
    brief = DemandBrief(risco=RiskLevel.HIGH)
    assert exige_aceite_humano(deploy, brief) is True


def test_exige_aceite_humano_risco_critico() -> None:
    deploy = DeployRun()
    brief = DemandBrief(risco=RiskLevel.CRITICAL)
    assert exige_aceite_humano(deploy, brief) is True


def test_exige_aceite_humano_impacto_sensivel() -> None:
    deploy = DeployRun()
    brief = DemandBrief(risco=RiskLevel.LOW, impactos=["security"])
    assert exige_aceite_humano(deploy, brief) is True


def test_exige_aceite_humano_validacao_reprovada() -> None:
    deploy = DeployRun(validacao_status=VALIDACAO_REPROVADA)
    brief = DemandBrief(risco=RiskLevel.LOW)
    assert exige_aceite_humano(deploy, brief) is True
