"""Dependências no caminho padrão do backlog gerado por LLM (§4.6 do plano4.md).

`populate_from_plan` (M2) é o caminho que `full-pipeline` — o modo default de
`CreateOrchestrationBody` — usa de verdade. Antes, `BacklogItem` não tinha
`depends_on`: quase nenhum card nascia com dependência, e o trabalho de
`dependencies`/`blocked_by` (ADR-0018) ficava adormecido. Estes testes protegem a
segunda passada título→id (mesmo padrão de `PlannedAgent.depends_on` em
`create_orchestration`) e a regra de dependência pendente (ADR-0018) continuando
válida para os cards resultantes.
"""

from __future__ import annotations

from pathlib import Path

from aso.control.orchestration_service import OrchestrationService
from aso.control.planning import BacklogItem, PlannedAdr, ProductSummary, ProjectPlan
from aso.shared.types import CardType


def _plan(**kwargs: object) -> ProjectPlan:
    defaults: dict[str, object] = {
        "product": ProductSummary(name="Frete Certo", domain="e-commerce"),
        "adrs": [PlannedAdr(title="Usar fila para recálculo", decision="RabbitMQ")],
        "backlog": [
            BacklogItem(title="Definir contrato de frete", phase="F3", domain="contract"),
            BacklogItem(
                title="Implementar cálculo de frete",
                phase="F5",
                domain="backend",
                depends_on=["Definir contrato de frete"],
            ),
            BacklogItem(
                title="Testar cálculo de frete",
                phase="F6",
                domain="tests",
                depends_on=["Implementar cálculo de frete", "item fantasma"],
            ),
        ],
    }
    defaults.update(kwargs)
    return ProjectPlan(**defaults)  # type: ignore[arg-type]


def test_depends_on_vira_dependencies_via_titulo(tmp_path: Path) -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("montar backlog", target_path=str(tmp_path), seed_cards=False)
    resultado = svc.populate_from_plan(orch.id, _plan())
    assert resultado["cards_created"]

    cards = svc.get_cards(orch.id)
    por_titulo = {c.title: c for c in cards}
    contrato = por_titulo["Definir contrato de frete"]
    calculo = por_titulo["Implementar cálculo de frete"]
    teste = por_titulo["Testar cálculo de frete"]

    assert calculo.dependencies == [contrato.id]
    # Título desconhecido ("item fantasma") é descartado, não quebra a criação.
    assert teste.dependencies == [calculo.id]


def test_backlog_item_type_vira_card_type(tmp_path: Path) -> None:
    """§7/§16.4 (ADR-0025): `BacklogItem.type` deixa o LLM marcar épicos — antes
    disso nenhum caminho de criação produzia card que não fosse `Task`."""
    svc = OrchestrationService()
    orch = svc.create_orchestration("montar backlog", target_path=str(tmp_path), seed_cards=False)
    plano = _plan(
        backlog=[BacklogItem(title="Épico de frete", phase="F5", domain="backend", type="Epic")]
    )
    svc.populate_from_plan(orch.id, plano)
    card = svc.get_cards(orch.id)[0]
    assert card.type == CardType.EPIC


def test_backlog_item_type_desconhecido_vira_task(tmp_path: Path) -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("montar backlog", target_path=str(tmp_path), seed_cards=False)
    plano = _plan(
        backlog=[BacklogItem(title="Item solto", phase="F5", domain="backend", type="Inventado")]
    )
    svc.populate_from_plan(orch.id, plano)
    card = svc.get_cards(orch.id)[0]
    assert card.type == CardType.TASK


def test_item_sem_depends_on_nao_tem_dependencia(tmp_path: Path) -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("montar backlog", target_path=str(tmp_path), seed_cards=False)
    plano = _plan(backlog=[BacklogItem(title="Item solto", phase="F5", domain="backend")])
    svc.populate_from_plan(orch.id, plano)
    card = svc.get_cards(orch.id)[0]
    assert card.dependencies == []


def test_card_com_dependencia_pendente_nao_roda(tmp_path: Path) -> None:
    """A regra da ADR-0018 continua valendo para cards nascidos deste caminho: rodar
    um card com dependência ainda não `Done` recusa e o move para `Blocked`."""
    svc = OrchestrationService()
    orch = svc.create_orchestration("montar backlog", target_path=str(tmp_path), seed_cards=False)
    svc.populate_from_plan(orch.id, _plan())
    cards = svc.get_cards(orch.id)
    calculo = next(c for c in cards if c.title == "Implementar cálculo de frete")
    calculo.assignee = "BackendDevelopmentAgent"

    try:
        svc.run_card(orch.id, calculo.id)
        raised = False
    except ValueError:
        raised = True
    assert raised

    bloqueado = svc.get_cards(orch.id)
    calculo_apos = next(c for c in bloqueado if c.id == calculo.id)
    assert calculo_apos.status.value == "Blocked"
