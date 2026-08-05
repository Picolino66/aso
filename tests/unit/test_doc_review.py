"""`ReviewService.revisar_documento` — revisão documental (§6 do fluxo.md, ADR-0021).

Protege: os QUATRO desfechos do §6 (não os cinco do §14); as duas checagens
determinísticas (plano de testes/rollback ausente reprova SEM chamar agente); e que
a checagem determinística roda mesmo quando não há revisor disponível.
"""

from __future__ import annotations

import shlex

from aso.control.models import AgentAssignment
from aso.control.review import (
    VEREDITO_DOC_APROVADO,
    VEREDITO_DOC_APROVADO_COM_OBSERVACOES,
    VEREDITO_DOC_NECESSITA_HUMANO,
    VEREDITO_DOC_REPROVADO,
    ReviewService,
)
from aso.control.spec import SpecDocument
from aso.control.triage import DemandBrief
from aso.execution.catalog import ExecutorCatalog, ExecutorProfile

_SPEC_COMPLETA = SpecDocument(
    o_que_sera_construido="corrigir o frete",
    estrategia_de_testes="testes unitários da fórmula",
    plano_de_rollback="reverter o commit",
)


def _cli(saida: str, *, exit_code: int = 0) -> ExecutorCatalog:
    script = f'cat > /dev/null; printf %s "$1"; exit {exit_code}'
    comando = shlex.join(["bash", "-c", script, "_", saida])
    return ExecutorCatalog([ExecutorProfile(name="revisor-doc", kind="cli", command=comando)])


# --------------------------------------------------------- checagens determinísticas


def test_estrategia_de_testes_vazia_reprova_sem_chamar_o_agente() -> None:
    doc = SpecDocument(plano_de_rollback="reverter o commit")  # sem estrategia_de_testes
    service = ReviewService(_cli("nunca deveria rodar"))
    verdito = service.revisar_documento(
        AgentAssignment(executor="revisor-doc"),
        documento=doc,
        tipo="especificacao",
        brief=DemandBrief(),
    )
    assert verdito.veredito == VEREDITO_DOC_REPROVADO
    assert verdito.origem == "checagem_deterministica"
    assert any("teste" in p for p in verdito.pontos_verificados)


def test_plano_de_rollback_vazio_reprova_sem_chamar_o_agente() -> None:
    doc = SpecDocument(estrategia_de_testes="testes unitários")  # sem plano_de_rollback
    service = ReviewService(_cli("nunca deveria rodar"))
    verdito = service.revisar_documento(
        AgentAssignment(executor="revisor-doc"),
        documento=doc,
        tipo="especificacao",
        brief=DemandBrief(),
    )
    assert verdito.veredito == VEREDITO_DOC_REPROVADO
    assert verdito.origem == "checagem_deterministica"
    assert any("rollback" in p for p in verdito.pontos_verificados)


def test_checagem_deterministica_ignora_documento_que_nao_e_spec() -> None:
    """`tipo != "especificacao"` não tem os campos de teste/rollback — não reprova
    por um campo que nem existe no documento (ex.: discovery)."""
    from aso.control.discovery import DiscoveryReport

    service = ReviewService(_cli('{"veredito": "aprovado"}'))
    verdito = service.revisar_documento(
        AgentAssignment(executor="revisor-doc"),
        documento=DiscoveryReport(),
        tipo="discovery",
        brief=DemandBrief(),
    )
    assert verdito.origem != "checagem_deterministica"


def test_checagem_deterministica_roda_mesmo_sem_revisor_disponivel() -> None:
    """A checagem não depende de agente — reprova mesmo com `assignment=None`."""
    doc = SpecDocument()  # sem testes nem rollback
    service = ReviewService(None)
    verdito = service.revisar_documento(
        None, documento=doc, tipo="especificacao", brief=DemandBrief()
    )
    assert verdito.veredito == VEREDITO_DOC_REPROVADO
    assert verdito.origem == "checagem_deterministica"


# --------------------------------------------------------------- caminho feliz (agente)


def test_veredito_aprovado_e_aceito_com_origem_do_executor() -> None:
    bruto = '{"veredito": "aprovado", "resumo": "Documento completo e consistente."}'
    verdito = ReviewService(_cli(bruto)).revisar_documento(
        AgentAssignment(executor="revisor-doc"),
        documento=_SPEC_COMPLETA,
        tipo="especificacao",
        brief=DemandBrief(),
    )
    assert verdito.veredito == VEREDITO_DOC_APROVADO
    assert verdito.origem == "agente"
    assert verdito.revisor == "revisor-doc"


def test_veredito_aprovado_com_observacoes_e_aceito() -> None:
    bruto = '{"veredito": "aprovado_com_observacoes", "resumo": "ok, com ressalvas"}'
    verdito = ReviewService(_cli(bruto)).revisar_documento(
        AgentAssignment(executor="revisor-doc"),
        documento=_SPEC_COMPLETA,
        tipo="especificacao",
        brief=DemandBrief(),
    )
    assert verdito.veredito == VEREDITO_DOC_APROVADO_COM_OBSERVACOES


def test_veredito_fora_do_vocabulario_do_paragrafo_14_cai_para_necessita_humano() -> None:
    """`alteracoes_obrigatorias` é do §14 (code review) — não existe no §6."""
    bruto = '{"veredito": "alteracoes_obrigatorias", "resumo": "x"}'
    verdito = ReviewService(_cli(bruto)).revisar_documento(
        AgentAssignment(executor="revisor-doc"),
        documento=_SPEC_COMPLETA,
        tipo="especificacao",
        brief=DemandBrief(),
    )
    assert verdito.veredito == VEREDITO_DOC_NECESSITA_HUMANO


def test_veredito_reprovado_do_agente_e_aceito() -> None:
    bruto = '{"veredito": "reprovado", "resumo": "Falta plano de dados."}'
    verdito = ReviewService(_cli(bruto)).revisar_documento(
        AgentAssignment(executor="revisor-doc"),
        documento=_SPEC_COMPLETA,
        tipo="especificacao",
        brief=DemandBrief(),
    )
    assert verdito.veredito == VEREDITO_DOC_REPROVADO


# --------------------------------------------------------------------- caminho de falha


def test_sem_agente_configurado_necessita_humano() -> None:
    verdito = ReviewService(None).revisar_documento(
        None, documento=_SPEC_COMPLETA, tipo="especificacao", brief=DemandBrief()
    )
    assert verdito.veredito == VEREDITO_DOC_NECESSITA_HUMANO
    assert verdito.fallback_reason != ""


def test_executor_fora_do_catalogo_necessita_humano() -> None:
    verdito = ReviewService(ExecutorCatalog([])).revisar_documento(
        AgentAssignment(executor="fantasma"),
        documento=_SPEC_COMPLETA,
        tipo="especificacao",
        brief=DemandBrief(),
    )
    assert verdito.veredito == VEREDITO_DOC_NECESSITA_HUMANO
    assert "KeyError" in verdito.fallback_reason


def test_json_invalido_necessita_humano() -> None:
    verdito = ReviewService(_cli("isto não é json")).revisar_documento(
        AgentAssignment(executor="revisor-doc"),
        documento=_SPEC_COMPLETA,
        tipo="especificacao",
        brief=DemandBrief(),
    )
    assert verdito.veredito == VEREDITO_DOC_NECESSITA_HUMANO
