"""SpecService — especificação da solução com fallback determinístico (§5, ADR-0021).

A regra que estes testes protegem: gerar spec **exige discovery aprovado** — sem
isso, `especificar` recusa. E, uma vez aceita a entrada, especificar nunca falha
por indisponibilidade de agente: toda falha vira o esqueleto heurístico + motivo
registrado, e nunca sai daqui com status `aprovado` (nem do agente, nem do fallback).
"""

from __future__ import annotations

import json
import shlex
from pathlib import Path

import pytest

from aso.control.discovery import STATUS_APROVADO, STATUS_RASCUNHO, DiscoveryReport
from aso.control.models import AgentAssignment
from aso.control.spec import STATUS_AGUARDANDO_REVISAO, SpecDocument, SpecService
from aso.control.triage import DemandBrief
from aso.execution.catalog import ExecutorCatalog, ExecutorProfile


def _cli(saida: str, *, exit_code: int = 0) -> ExecutorCatalog:
    script = f'cat > /dev/null; printf %s "$1"; exit {exit_code}'
    comando = shlex.join(["bash", "-c", script, "_", saida])
    return ExecutorCatalog([ExecutorProfile(name="especificador", kind="cli", command=comando)])


def _discovery_aprovado(**kwargs: object) -> DiscoveryReport:
    base: dict[str, object] = {
        "status": STATUS_APROVADO,
        "situacao_atual": "monólito Django",
        "recomendacao_tecnica": "corrigir a fórmula de frete",
        "componentes_afetados": ["checkout"],
    }
    base.update(kwargs)
    return DiscoveryReport(**base)  # type: ignore[arg-type]


def _especificar(
    service: SpecService, assignment: AgentAssignment | None, **kwargs: object
) -> SpecDocument:
    defaults: dict[str, object] = {
        "demand_brief": DemandBrief(problema="frete errado", criterios_de_aceite=["frete correto"]),
        "discovery": _discovery_aprovado(),
    }
    defaults.update(kwargs)
    return service.especificar(assignment, **defaults)  # type: ignore[arg-type]


# --------------------------------------------------------- discovery não aprovado


def test_recusa_sem_discovery_aprovado() -> None:
    service = SpecService(None)
    with pytest.raises(ValueError, match="discovery aprovado"):
        service.especificar(
            None,
            demand_brief=DemandBrief(),
            discovery=DiscoveryReport(status=STATUS_RASCUNHO),
        )


def test_recusa_com_discovery_reprovado() -> None:
    service = SpecService(None)
    with pytest.raises(ValueError, match="discovery aprovado"):
        service.especificar(
            None,
            demand_brief=DemandBrief(),
            discovery=DiscoveryReport(status="reprovado"),
        )


# --------------------------------------------------------------- caminho feliz (agente)


def test_resposta_valida_do_agente_e_aceita_com_origem_do_executor() -> None:
    bruto = (
        '{"o_que_sera_construido": "corrigir a fórmula", '
        '"fora_de_escopo": ["frete internacional"], '
        '"como_funciona": "recalcula no checkout", "criterios_de_aceite": ["frete correto"], '
        '"estrategia_de_testes": "testes unitários da fórmula", '
        '"plano_de_rollback": "reverter o commit", '
        '"itens_de_trabalho": [{"titulo": "corrigir fórmula", "fase": "F5", "dominio": "backend"}]}'
    )
    spec = _especificar(SpecService(_cli(bruto)), AgentAssignment(executor="especificador"))
    assert spec.o_que_sera_construido == "corrigir a fórmula"
    assert spec.fora_de_escopo == ["frete internacional"]
    assert spec.estrategia_de_testes == "testes unitários da fórmula"
    assert spec.plano_de_rollback == "reverter o commit"
    assert len(spec.itens_de_trabalho) == 1
    assert spec.itens_de_trabalho[0].titulo == "corrigir fórmula"
    assert spec.origem == "especificador"
    assert spec.status == STATUS_AGUARDANDO_REVISAO  # nunca aprovado direto


def test_resposta_sem_nenhum_campo_util_cai_no_fallback() -> None:
    bruto = '{"regras_de_negocio": []}'
    spec = _especificar(SpecService(_cli(bruto)), AgentAssignment(executor="especificador"))
    assert spec.origem == "heuristica"
    assert spec.fallback_reason == "resposta do agente sem campos utilizáveis"


def test_itens_de_trabalho_com_dependencia_para_irmao_inexistente_e_descartada() -> None:
    bruto = (
        '{"o_que_sera_construido": "x", '
        '"itens_de_trabalho": ['
        '  {"titulo": "A", "depende_de": ["irmao fantasma", "A"]},'
        '  {"titulo": "B", "depende_de": ["A"]}'
        "]}"
    )
    spec = _especificar(SpecService(_cli(bruto)), AgentAssignment(executor="especificador"))
    por_titulo = {item.titulo: item for item in spec.itens_de_trabalho}
    assert por_titulo["A"].depende_de == []  # fantasma descartado; auto-referência descartada
    assert por_titulo["B"].depende_de == ["A"]


# --------------------------------------------------------------------- caminho de falha


def test_sem_assignment_usa_heuristica_direto() -> None:
    spec = _especificar(SpecService(_cli("não deveria rodar")), None)
    assert spec.origem == "heuristica"
    assert spec.status == STATUS_AGUARDANDO_REVISAO


def test_sem_catalogo_usa_heuristica_direto() -> None:
    spec = _especificar(SpecService(None), AgentAssignment(executor="especificador"))
    assert spec.origem == "heuristica"


def test_executor_fora_do_catalogo_cai_no_fallback_com_motivo() -> None:
    spec = _especificar(SpecService(ExecutorCatalog([])), AgentAssignment(executor="fantasma"))
    assert spec.origem == "heuristica"
    assert "KeyError" in spec.fallback_reason


def test_json_invalido_cai_no_fallback_com_motivo() -> None:
    spec = _especificar(
        SpecService(_cli("isto não é json")), AgentAssignment(executor="especificador")
    )
    assert spec.origem == "heuristica"
    assert spec.fallback_reason != ""


def test_exit_diferente_de_zero_cai_no_fallback() -> None:
    spec = _especificar(
        SpecService(_cli('{"o_que_sera_construido": "x"}', exit_code=1)),
        AgentAssignment(executor="especificador"),
    )
    assert spec.origem == "heuristica"


def test_executor_sem_capacidade_de_texto_cai_no_fallback() -> None:
    catalogo = ExecutorCatalog([ExecutorProfile(name="mockador", kind="mock")])
    spec = _especificar(SpecService(catalogo), AgentAssignment(executor="mockador"))
    assert spec.origem == "heuristica"
    assert "ValueError" in spec.fallback_reason


# ------------------------------------------------------------------------- heurística


def test_heuristica_reaproveita_discovery_e_ficha() -> None:
    service = SpecService(None)
    spec = _especificar(
        service,
        None,
        demand_brief=DemandBrief(objetivo="objetivo X", criterios_de_aceite=["c1"]),
        discovery=_discovery_aprovado(
            recomendacao_tecnica="usar cache", componentes_afetados=["a"]
        ),
    )
    assert spec.o_que_sera_construido == "usar cache"
    assert spec.componentes == ["a"]
    assert spec.criterios_de_aceite == ["c1"]
    assert spec.status == STATUS_AGUARDANDO_REVISAO
    assert spec.origem == "heuristica"


def test_heuristica_nunca_aprovada() -> None:
    spec = _especificar(SpecService(None), None)
    assert spec.status != "aprovado"
    assert spec.status != "aprovado_com_observacoes"


# ------------------------------------------------------------ comentários de reprovação


def test_comentarios_anteriores_entram_no_pedido_ao_agente(tmp_path: Path) -> None:
    destino = tmp_path / "recebido.json"
    comando = ["bash", "-c", f'cat > "{destino}"; printf %s \'{{"o_que_sera_construido": "x"}}\'']
    perfil = ExecutorProfile(name="especificador", kind="cli", command=shlex.join(comando))
    service = SpecService(ExecutorCatalog([perfil]))
    _especificar(
        service,
        AgentAssignment(executor="especificador"),
        comentarios_anteriores="faltou o plano de rollback",
    )
    recebido = json.loads(destino.read_text())
    assert "faltou o plano de rollback" in recebido["content"]["request"]
