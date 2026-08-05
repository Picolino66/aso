"""Bateria de validações nomeada (§12 do fluxo.md) — ADR-0022.

`checks_efetivos` é a função pura que resolve compatibilidade com o
`validation_command` legado. O restante cobre `run_quality_gate` rodando um
`Criterion` por verificação — a armadilha clássica é a closure em laço capturar a
última variável e todo critério acabar rodando o MESMO comando.
"""

from __future__ import annotations

from aso.control.models import Orchestration, ValidationCheck
from aso.control.orchestration_service import OrchestrationService
from aso.control.validation import checks_efetivos
from aso.execution.gate_validation import GateCommandError
from aso.shared.types import Phase

# --------------------------------------------------------------- checks_efetivos


def test_sem_bateria_e_sem_comando_devolve_lista_vazia() -> None:
    assert checks_efetivos(Orchestration()) == []


def test_sem_bateria_com_validation_command_legado_vira_check_unico() -> None:
    orch = Orchestration(validation_command="pytest -q")
    checks = checks_efetivos(orch)
    assert len(checks) == 1
    assert checks[0].nome == "testes"
    assert checks[0].comando == "pytest -q"


def test_com_bateria_configurada_ignora_o_legado() -> None:
    orch = Orchestration(
        validation_command="pytest -q",
        validation_checks=[ValidationCheck(nome="lint", comando="ruff check .", categoria="lint")],
    )
    checks = checks_efetivos(orch)
    assert [c.nome for c in checks] == ["lint"]


# --------------------------------------------------------- set_validation_checks


def test_set_validation_checks_valida_cada_comando(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = OrchestrationService()
    orch = svc.create_orchestration("backend", target_path=str(tmp_path))
    try:
        svc.set_validation_checks(
            orch.id,
            [
                ValidationCheck(nome="ok", comando="pytest -q"),
                ValidationCheck(nome="ruim", comando="npm run dev"),
            ],
        )
    except GateCommandError:
        pass
    else:
        raise AssertionError("comando contínuo deveria ser recusado")
    # Recusado por inteiro: a bateria não fica parcialmente aplicada.
    assert svc.get_validation_checks(orch.id) == []


def test_set_validation_checks_substitui_a_bateria_inteira(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = OrchestrationService()
    orch = svc.create_orchestration("backend", target_path=str(tmp_path))
    svc.set_validation_checks(orch.id, [ValidationCheck(nome="testes", comando="pytest -q")])
    assert [c.nome for c in svc.get_validation_checks(orch.id)] == ["testes"]
    svc.set_validation_checks(orch.id, [ValidationCheck(nome="lint", comando="ruff check .")])
    assert [c.nome for c in svc.get_validation_checks(orch.id)] == ["lint"]


# --------------------------------------------------------------- run_quality_gate


def _svc_com_bateria(
    tmp_path: object, checks: list[ValidationCheck]
) -> tuple[OrchestrationService, str]:
    """`seed_cards=False`: sem cards, `context_has_output`/`cards_entregues` ficam
    vacuamente ok (mesma regra dos dois já existentes) — isola o teste na bateria."""
    svc = OrchestrationService()
    orch = svc.create_orchestration("backend", target_path=str(tmp_path), seed_cards=False)
    svc.set_validation_checks(orch.id, checks)
    return svc, orch.id


def test_dois_checks_com_comandos_diferentes_rodam_comandos_diferentes(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Regressão da armadilha de closure em laço (§4.2/§5 do plano5.md): sem
    `comando=check.comando` como default arg, os dois critérios rodariam o mesmo
    (o último) comando do laço."""
    svc, oid = _svc_com_bateria(
        tmp_path,
        [
            ValidationCheck(nome="a", comando="bash -c 'echo MARCA_A'"),
            ValidationCheck(nome="b", comando="bash -c 'echo MARCA_B'"),
        ],
    )
    result = svc.run_quality_gate(oid, Phase.F5)
    por_nome = {c.name: c for c in result.criteria}
    assert "MARCA_A" in por_nome["a"].evidence[0]
    assert "MARCA_B" in por_nome["b"].evidence[0]


def test_bateria_roda_inteira_mesmo_quando_o_primeiro_falha(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc, oid = _svc_com_bateria(
        tmp_path,
        [
            ValidationCheck(nome="quebra", comando="bash -c 'exit 1'"),
            ValidationCheck(nome="passa", comando="bash -c 'exit 0'"),
        ],
    )
    result = svc.run_quality_gate(oid, Phase.F5)
    nomes = {c.name for c in result.criteria}
    assert {"quebra", "passa"} <= nomes
    por_nome = {c.name: c for c in result.criteria}
    assert por_nome["quebra"].status.value == "FAILED"
    assert por_nome["passa"].status.value == "PASSED"


def test_check_nao_bloqueante_que_falha_nao_reprova_o_gate(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc, oid = _svc_com_bateria(
        tmp_path,
        [ValidationCheck(nome="aviso", comando="bash -c 'exit 1'", bloqueante=False)],
    )
    result = svc.run_quality_gate(oid, Phase.F5)
    assert result.status.value == "PASSED"
    assert "aviso" in (result.warnings or [])


def test_check_bloqueante_que_falha_reprova_o_gate(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc, oid = _svc_com_bateria(
        tmp_path,
        [ValidationCheck(nome="critico", comando="bash -c 'exit 1'", bloqueante=True)],
    )
    result = svc.run_quality_gate(oid, Phase.F5)
    assert result.status.value == "FAILED"
    assert "critico" in result.blocking_issues


def test_legado_validation_command_continua_funcionando_no_gate(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Orquestração criada antes deste incremento (só `validation_command`, sem
    bateria) — comportamento inalterado no gate."""
    svc = OrchestrationService()
    orch = svc.create_orchestration(
        "backend",
        target_path=str(tmp_path),
        validation_command="bash -c 'exit 0'",
        seed_cards=False,
    )
    result = svc.run_quality_gate(orch.id, Phase.F5)
    assert result.status.value == "PASSED"
    assert any(c.name == "testes" for c in result.criteria)
