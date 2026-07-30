"""Escolha de executor por etapa da esteira (ADR-0014).

Antes, um único `selected_executor` rodava F1→F7. Aqui cobrimos a precedência completa
da resolução e a regra de governança sobre QUANDO uma etapa ainda pode ser configurada.
"""

from __future__ import annotations

import pytest

from aso.control.models import NAMING_KEY
from aso.control.orchestration_service import OrchestrationService
from aso.execution.catalog import ExecutorCatalog, ExecutorProfile
from aso.shared.types import Phase


def _catalogo() -> ExecutorCatalog:
    return ExecutorCatalog(
        [
            ExecutorProfile(name="barato", kind="mock", effort="low", is_default=True),
            ExecutorProfile(name="forte", kind="mock", effort="high"),
            ExecutorProfile(name="nomeador", kind="mock", effort="medium"),
        ]
    )


def _svc() -> OrchestrationService:
    return OrchestrationService(catalog=_catalogo())


def _resolver(svc: OrchestrationService, oid: str, phase: Phase) -> tuple[str | None, str | None]:
    b = svc._bundle(oid)  # noqa: SLF001 - resolução interna é o objeto do teste
    executor = svc._effective_executor(b, None, phase=phase)  # noqa: SLF001
    effort = svc._effective_effort(b, executor, None, phase=phase)  # noqa: SLF001
    return executor, effort


# ------------------------------------------------------------------ precedência


def test_sem_nada_configurado_nao_resolve_executor() -> None:
    svc = _svc()
    orch = svc.create_orchestration("backend")  # sem pasta → sem default do catálogo
    assert _resolver(svc, orch.id, Phase.F5) == (None, None)


def test_pasta_definida_cai_no_default_do_catalogo(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = _svc()
    orch = svc.create_orchestration("backend", target_path=str(tmp_path))
    assert _resolver(svc, orch.id, Phase.F5) == ("barato", "low")


def test_padrao_da_orquestracao_vale_para_todas_as_etapas() -> None:
    svc = _svc()
    orch = svc.create_orchestration("backend", executor="forte", effort="high")
    for fase in (Phase.F1, Phase.F5, Phase.F7):
        assert _resolver(svc, orch.id, fase) == ("forte", "high")


def test_etapa_configurada_sobrescreve_o_padrao() -> None:
    svc = _svc()
    orch = svc.create_orchestration("backend", executor="barato", effort="low")
    svc.set_agent_assignment(orch.id, "F5", executor="forte", effort="high")
    assert _resolver(svc, orch.id, Phase.F5) == ("forte", "high")
    assert _resolver(svc, orch.id, Phase.F1) == ("barato", "low")  # as outras não mudam


def test_etapa_sem_esforco_usa_o_do_perfil_nao_o_global() -> None:
    # O esforço casa com o MODELO: herdar "low" do padrão global para um modelo que
    # nem aceita esse nível quebraria a validação do executor.
    svc = _svc()
    orch = svc.create_orchestration("backend", executor="barato", effort="low")
    svc.set_agent_assignment(orch.id, "F5", executor="forte")
    assert _resolver(svc, orch.id, Phase.F5) == ("forte", "high")


def test_chamada_explicita_ganha_de_tudo() -> None:
    svc = _svc()
    orch = svc.create_orchestration("backend", executor="barato")
    svc.set_agent_assignment(orch.id, "F5", executor="forte")
    b = svc._bundle(orch.id)  # noqa: SLF001
    assert svc._effective_executor(b, "nomeador", phase=Phase.F5) == "nomeador"  # noqa: SLF001


def test_limpar_a_etapa_volta_ao_padrao() -> None:
    svc = _svc()
    orch = svc.create_orchestration("backend", executor="barato", effort="low")
    svc.set_agent_assignment(orch.id, "F5", executor="forte", effort="high")
    svc.clear_agent_assignment(orch.id, "F5")
    assert _resolver(svc, orch.id, Phase.F5) == ("barato", "low")


# ------------------------------------------------------------------ governança


def test_etapa_invalida_e_recusada() -> None:
    svc = _svc()
    orch = svc.create_orchestration("backend")
    with pytest.raises(ValueError, match="Etapa inválida"):
        svc.set_agent_assignment(orch.id, "F9", executor="forte")


def test_executor_fora_do_catalogo_e_recusado() -> None:
    svc = _svc()
    orch = svc.create_orchestration("backend")
    with pytest.raises(ValueError):
        svc.set_agent_assignment(orch.id, "F5", executor="inexistente")


def test_fase_que_ja_passou_nao_aceita_troca_de_agente() -> None:
    # Reconfigurar F1 com a esteira em F3 daria a falsa impressão de que o trabalho
    # seria refeito com o novo agente.
    svc = _svc()
    orch = svc.create_orchestration("backend")
    svc.advance_phase(orch.id)
    svc.advance_phase(orch.id)  # F1 → F2 → F3
    with pytest.raises(ValueError, match="já passou"):
        svc.set_agent_assignment(orch.id, "F1", executor="forte")


def test_fase_futura_aceita_troca_com_a_esteira_andando() -> None:
    svc = _svc()
    orch = svc.create_orchestration("backend")
    svc.advance_phase(orch.id)  # F1 → F2
    svc.set_agent_assignment(orch.id, "F5", executor="forte")
    assert svc.get(orch.id).agent_assignments["F5"].executor == "forte"


def test_nomeador_e_sempre_editavel() -> None:
    # Não é fase da esteira: pode ser trocado a qualquer momento.
    svc = _svc()
    orch = svc.create_orchestration("backend")
    for _ in range(6):
        svc.advance_phase(orch.id)  # até F7
    svc.set_agent_assignment(orch.id, NAMING_KEY, executor="nomeador")
    assert svc.get(orch.id).agent_assignments[NAMING_KEY].executor == "nomeador"


def test_orquestracao_cancelada_nao_aceita_configuracao() -> None:
    svc = _svc()
    orch = svc.create_orchestration("backend")
    svc.cancel(orch.id)
    with pytest.raises(ValueError, match="cancelada"):
        svc.set_agent_assignment(orch.id, "F5", executor="forte")


def test_troca_de_agente_gera_evento_auditavel() -> None:
    svc = _svc()
    orch = svc.create_orchestration("backend")
    svc.set_agent_assignment(orch.id, "F5", executor="forte", effort="high", actor="ana")
    svc.clear_agent_assignment(orch.id, "F5", actor="ana")
    eventos = [
        e
        for e in svc._bundle(orch.id).event_log.all()
        if e.type == "AgentAssignmentUpdated"  # noqa: SLF001
    ]
    assert len(eventos) == 2
    assert eventos[0].payload["after"] == {"executor": "forte", "effort": "high"}
    assert eventos[1].payload["after"] is None
    assert all(e.payload["actor"] == "ana" for e in eventos)


def test_limpar_etapa_ja_no_padrao_nao_gera_evento() -> None:
    svc = _svc()
    orch = svc.create_orchestration("backend")
    svc.clear_agent_assignment(orch.id, "F5")
    assert not [
        e
        for e in svc._bundle(orch.id).event_log.all()
        if e.type == "AgentAssignmentUpdated"  # noqa: SLF001
    ]
