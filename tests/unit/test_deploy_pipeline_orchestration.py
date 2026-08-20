"""Pipeline de implantação multi-estágio via `OrchestrationService` (§19, ADR-0029).

Cobre: regressão do monoambiente legado (pipeline vazio = comportamento idêntico
à ADR-0023), configuração do pipeline (`set_deploy_pipeline`), avanço governado
(`run_deploy` com/sem `estagio` explícito), classificação de falha nos cinco
diagnósticos do §19, critério `deploy_aprovado` do gate F6 com pipeline, status
derivado (`get_deploy_pipeline`) e o bloqueio de `next_step` nomeando o estágio.
"""

from __future__ import annotations

import pytest

from aso.control.deploy import (
    ACEITE_AGUARDANDO_HUMANO,
    ACEITE_APROVADO,
    DIAG_CRITICA,
    STATUS_SUCESSO,
)
from aso.control.models import Environment, ValidationCheck
from aso.control.orchestration_service import OrchestrationService
from aso.control.triage import DemandBrief
from aso.shared.types import Phase, RiskLevel

_PIPELINE = [
    Environment(chave="desenvolvimento", nome="Dev", ordem=1, comando="true"),
    Environment(chave="testes", nome="Testes", ordem=2, comando="true"),
    Environment(
        chave="producao",
        nome="Produção",
        ordem=3,
        comando="true",
        requer_aprovacao_humana=True,
    ),
]


def _orch_pronta(
    svc: OrchestrationService, tmp_path: object, *, risco: RiskLevel = RiskLevel.LOW
) -> str:
    """Orquestração com pasta + gate F5 PASSED — mesmo helper de test_deploy_orchestration."""
    orch = svc.create_orchestration(
        "ajustar cálculo de frete",
        target_path=str(tmp_path),
        seed_cards=False,
        demand_brief=DemandBrief(risco=risco),
    )
    svc.run_quality_gate(orch.id, Phase.F5)
    return orch.id


# --------------------------------------------------------------------- regressão


def test_pipeline_vazio_run_deploy_ignora_estagio_e_e_identico_ao_legado(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = OrchestrationService()
    oid = _orch_pronta(svc, tmp_path)
    svc.set_deploy_config(oid, command="true")
    deploy = svc.run_deploy(oid, estagio="algum-estagio-que-nao-existe")
    assert deploy.estagio == ""
    assert deploy.ambiente == "producao"  # default legado, environment não passado
    assert deploy.status == STATUS_SUCESSO


def test_pipeline_vazio_get_deploy_pipeline_devolve_lista_vazia(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = OrchestrationService()
    oid = _orch_pronta(svc, tmp_path)
    assert svc.get_deploy_pipeline(oid) == []


def test_gate_f6_sem_pipeline_usa_a_ultima_tentativa_como_antes(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = OrchestrationService()
    oid = _orch_pronta(svc, tmp_path)
    svc.set_deploy_config(oid, command="true")
    svc.run_deploy(oid)
    gate = svc.run_quality_gate(oid, Phase.F6)
    criterio = next(c for c in gate.criteria if c.name == "deploy_aprovado")
    assert criterio.status.value == "PASSED"


# --------------------------------------------------------------- set_deploy_pipeline


def test_set_deploy_pipeline_recusa_chave_repetida(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = OrchestrationService()
    oid = _orch_pronta(svc, tmp_path)
    duplicado = [Environment(chave="dev", ordem=1), Environment(chave="dev", ordem=2)]
    with pytest.raises(ValueError, match="chave"):
        svc.set_deploy_pipeline(oid, duplicado)


def test_set_deploy_pipeline_recusa_ordem_repetida(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = OrchestrationService()
    oid = _orch_pronta(svc, tmp_path)
    duplicado = [Environment(chave="dev", ordem=1), Environment(chave="testes", ordem=1)]
    with pytest.raises(ValueError, match="ordem"):
        svc.set_deploy_pipeline(oid, duplicado)


def test_set_deploy_pipeline_valida_comando_continuo(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from aso.execution.gate_validation import GateCommandError

    svc = OrchestrationService()
    oid = _orch_pronta(svc, tmp_path)
    invalido = [Environment(chave="dev", ordem=1, comando="npm run dev")]
    with pytest.raises(GateCommandError):
        svc.set_deploy_pipeline(oid, invalido)


def test_set_deploy_pipeline_vazio_volta_ao_monoambiente(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = OrchestrationService()
    oid = _orch_pronta(svc, tmp_path)
    svc.set_deploy_pipeline(oid, _PIPELINE)
    assert svc.get_deploy_pipeline(oid) != []
    svc.set_deploy_pipeline(oid, [])
    assert svc.get_deploy_pipeline(oid) == []


# --------------------------------------------------------------------- avanço governado


def test_run_deploy_pula_estagio_e_recusado(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = OrchestrationService()
    oid = _orch_pronta(svc, tmp_path)
    svc.set_deploy_pipeline(oid, _PIPELINE)
    with pytest.raises(ValueError, match="anterior não foi concluído"):
        svc.run_deploy(oid, estagio="producao")


def test_run_deploy_estagio_inexistente_levanta_keyerror(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = OrchestrationService()
    oid = _orch_pronta(svc, tmp_path)
    svc.set_deploy_pipeline(oid, _PIPELINE)
    with pytest.raises(KeyError):
        svc.run_deploy(oid, estagio="inexistente")


def test_run_deploy_sem_estagio_explicito_resolve_o_proximo_pendente(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = OrchestrationService()
    oid = _orch_pronta(svc, tmp_path)
    svc.set_deploy_pipeline(oid, _PIPELINE)
    d1 = svc.run_deploy(oid)
    assert d1.estagio == "desenvolvimento"
    d2 = svc.run_deploy(oid)
    assert d2.estagio == "testes"


def test_run_deploy_todos_os_estagios_em_ordem(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = OrchestrationService()
    oid = _orch_pronta(svc, tmp_path)
    svc.set_deploy_pipeline(oid, _PIPELINE)
    d1 = svc.run_deploy(oid)
    d2 = svc.run_deploy(oid)
    d3 = svc.run_deploy(oid)
    assert [d.estagio for d in (d1, d2, d3)] == ["desenvolvimento", "testes", "producao"]
    assert d1.aceite_status == ACEITE_APROVADO  # sem requer_aprovacao_humana
    assert d2.aceite_status == ACEITE_APROVADO
    assert d3.aceite_status == ACEITE_AGUARDANDO_HUMANO  # producao exige


def test_pipeline_completo_gate_f6_so_aprova_apos_aceite_do_ultimo_estagio(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = OrchestrationService()
    oid = _orch_pronta(svc, tmp_path)
    svc.set_deploy_pipeline(oid, _PIPELINE)
    svc.run_deploy(oid)
    svc.run_deploy(oid)
    svc.run_deploy(oid)  # producao, aguardando aceite
    gate_antes = svc.run_quality_gate(oid, Phase.F6)
    criterio_antes = next(c for c in gate_antes.criteria if c.name == "deploy_aprovado")
    assert criterio_antes.status.value == "FAILED"

    svc.decide_deploy(oid, approved=True)
    gate_depois = svc.run_quality_gate(oid, Phase.F6)
    criterio_depois = next(c for c in gate_depois.criteria if c.name == "deploy_aprovado")
    assert criterio_depois.status.value == "PASSED"


def test_get_deploy_pipeline_reflete_o_avanco(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = OrchestrationService()
    oid = _orch_pronta(svc, tmp_path)
    svc.set_deploy_pipeline(oid, _PIPELINE)
    svc.run_deploy(oid)
    status = svc.get_deploy_pipeline(oid)
    assert status[0]["chave"] == "desenvolvimento"
    assert status[0]["concluido"] is True
    assert status[1]["chave"] == "testes"
    assert status[1]["pode_avancar"] is True
    assert status[2]["pode_avancar"] is False  # testes ainda não concluiu


# --------------------------------------------------------------- estágio → padrão


def test_run_deploy_usa_comando_do_estagio_quando_definido(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = OrchestrationService()
    oid = _orch_pronta(svc, tmp_path)
    svc.set_deploy_config(oid, command="false")  # padrão da orquestração falharia
    pipeline = [Environment(chave="dev", ordem=1, comando="true")]  # estágio vence
    svc.set_deploy_pipeline(oid, pipeline)
    deploy = svc.run_deploy(oid)
    assert deploy.status == STATUS_SUCESSO


def test_run_deploy_cai_no_comando_da_orquestracao_quando_estagio_nao_define(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = OrchestrationService()
    oid = _orch_pronta(svc, tmp_path)
    svc.set_deploy_config(oid, command="true")
    pipeline = [Environment(chave="dev", ordem=1)]  # sem comando próprio
    svc.set_deploy_pipeline(oid, pipeline)
    deploy = svc.run_deploy(oid)
    assert deploy.status == STATUS_SUCESSO
    assert deploy.comando == "true"


# ------------------------------------------------------------------- classificação


def test_run_deploy_falha_classifica_e_registra_proxima_acao(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = OrchestrationService()
    oid = _orch_pronta(svc, tmp_path)
    pipeline = [Environment(chave="dev", ordem=1, comando="npm run build")]
    svc.set_deploy_pipeline(oid, pipeline)
    deploy = svc.run_deploy(oid)
    assert deploy.diagnostico_falha == "build"
    assert deploy.proxima_acao_falha  # nunca vazio quando falha


def test_validate_deploy_falha_critica_em_producao(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = OrchestrationService()
    oid = _orch_pronta(svc, tmp_path)
    pipeline = [
        Environment(chave="producao", nome="Produção", ordem=1, comando="true"),
    ]
    svc.set_deploy_pipeline(oid, pipeline)
    svc.set_deploy_config(
        oid,
        health_checks=[
            ValidationCheck(nome="health", comando="false", categoria="testes", bloqueante=True)
        ],
    )
    svc.run_deploy(oid)
    validado = svc.validate_deploy(oid)
    assert validado.diagnostico_falha == DIAG_CRITICA
    assert "rollback" in validado.proxima_acao_falha.lower()


def test_validate_deploy_usa_health_checks_do_estagio(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = OrchestrationService()
    oid = _orch_pronta(svc, tmp_path)
    svc.set_deploy_config(
        oid,
        health_checks=[
            ValidationCheck(nome="global", comando="true", categoria="testes", bloqueante=True)
        ],
    )
    pipeline = [
        Environment(
            chave="dev",
            ordem=1,
            comando="true",
            health_checks=[
                ValidationCheck(
                    nome="estagio", comando="false", categoria="testes", bloqueante=True
                )
            ],
        )
    ]
    svc.set_deploy_pipeline(oid, pipeline)
    svc.run_deploy(oid)
    validado = svc.validate_deploy(oid)
    assert validado.validacao_resultados[0]["nome"] == "estagio"  # do estágio, não global
    assert validado.validacao_status == "reprovada"


# ------------------------------------------------------------------------ next_step


def test_next_step_nomeia_o_estagio_no_bloqueio(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = OrchestrationService()
    oid = _orch_pronta(svc, tmp_path)
    pipeline = [Environment(chave="dev", nome="Dev", ordem=1, comando="false")]
    svc.set_deploy_pipeline(oid, pipeline)
    svc.run_deploy(oid)
    b = svc._bundle(oid)  # noqa: SLF001
    b.orchestration.current_phase = Phase.F6
    ns = svc.next_step(oid)
    blocker = next(x for x in ns.blockers if x.code == "deploy_falhou")
    assert "dev" in blocker.title.lower()


# ------------------------------------------------------------------------- rollback


def test_rollback_usa_comando_do_estagio_quando_definido(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = OrchestrationService()
    oid = _orch_pronta(svc, tmp_path)
    pipeline = [
        Environment(
            chave="producao",
            ordem=1,
            comando="true",
            rollback_command="true",
            requer_aprovacao_humana=True,
        )
    ]
    svc.set_deploy_pipeline(oid, pipeline)
    svc.run_deploy(oid)
    svc.decide_deploy(oid, approved=True)
    revertido = svc.rollback_deploy(oid, reason="incidente em produção")
    assert revertido.status == "revertido"
