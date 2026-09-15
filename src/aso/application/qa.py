"""`QaService` — QA humano, bugs e encerramento da demanda (ADR-0066).

MEL-32, passo 6a: verificações de QA e bug vinculado (ADR-0025), relatório de bug e
relatório de encerramento da demanda (ADR-0050).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from aso.application.bundles import BundleStore, OrchestrationBundle
from aso.control.attempts import RESULTADO_FALHOU, TentativaRegistro, registrar_tentativa
from aso.control.deploy import STATUS_SUCESSO
from aso.control.failure import (
    ACAO_ESCALAR_HUMANO,
    ETAPA_QA,
    FailureRecord,
    decidir,
    diagnosticar,
    registrar,
)
from aso.control.models import Orchestration
from aso.control.qa import STATUS_FALHOU as QA_STATUS_FALHOU
from aso.control.qa import STATUS_PENDENTE as QA_STATUS_PENDENTE
from aso.control.qa import QaCheck
from aso.control.triage import DemandBrief
from aso.execution.catalog import ExecutorCatalog
from aso.governance.models import BugReport
from aso.kanban.models import KanbanCard
from aso.shared.types import CardType, ColumnKey, RiskLevel

# Ring de verificações de QA por card (§16, ADR-0025) — mesmo raciocínio de
# `_max_races_per_card`/ring de discovery/spec: histórico limitado, não ilimitado.
_QA_RING = 10


_GRAVIDADE_PARA_PRIORIDADE: dict[str, RiskLevel] = {
    "baixa": RiskLevel.LOW,
    "media": RiskLevel.MEDIUM,
    "alta": RiskLevel.HIGH,
    "critica": RiskLevel.CRITICAL,
}


def _descricao_bug_de_qa(check: QaCheck) -> str:
    """Monta a descrição do bug do §17 a partir do `QaCheck` reprovado — como
    reproduzir, ambiente, evidências, resultado atual e esperado, gravidade."""
    linhas = [f"Cenário: {check.cenario}"]
    if check.ambiente:
        linhas.append(f"Ambiente: {check.ambiente}")
    if check.passos:
        passos = "\n".join(f"{i + 1}. {p}" for i, p in enumerate(check.passos))
        linhas.append(f"Como reproduzir:\n{passos}")
    if check.resultado_esperado:
        linhas.append(f"Resultado esperado: {check.resultado_esperado}")
    if check.resultado_obtido:
        linhas.append(f"Resultado obtido: {check.resultado_obtido}")
    if check.evidencias:
        linhas.append("Evidências: " + "; ".join(check.evidencias))
    linhas.append(f"Gravidade: {check.gravidade}")
    return "\n".join(linhas)


# 13 blocos do §23 do fluxo.md (Tela 27, wf §29.1, ADR-0050) — a wireframe tem um
# 14º bloco ("Cards concluídos") que o fluxo.md não lista; fica de fora daqui e
# vira métrica de resumo (`_demand_closure_metricas`), não bloco de relatório —
# ver ADR-0050 para o raciocínio completo.
_BLOCOS_ENCERRAMENTO_DEMANDA: list[tuple[str, str]] = [
    ("resumo", "Resumo da entrega"),
    ("agentes_utilizados", "Agentes utilizados"),
    ("modelos_utilizados", "Modelos utilizados"),
    ("effort_utilizado", "Effort utilizado"),
    ("commits", "Commits"),
    ("pull_requests", "Pull requests"),
    ("documentos_produzidos", "Documentos produzidos"),
    ("testes_executados", "Testes executados"),
    ("evidencias", "Evidências"),
    ("data_implantacao", "Data da implantação"),
    ("decisoes_tecnicas", "Decisões técnicas"),
    ("riscos_residuais", "Riscos residuais"),
    ("pendencias_futuras", "Pendências futuras"),
]


def _build_demand_closure(b: OrchestrationBundle) -> dict[str, Any]:
    """Relatório de encerramento da demanda (Tela 27, wf §29, ADR-0050) — os 13
    blocos do §23 do fluxo.md, no nível da demanda inteira (`_build_card_closure`
    é o mesmo relatório por CARD). Mesma disciplina de só montar o que o runtime
    já tem à mão: sem tabela central de commits, "commits" vira a lista de
    branches mescladas (fato real, não uma contagem inventada); "decisões
    técnicas" reaproveita os ADRs já registrados, sem taxonomia nova.
    """
    cards = b.board_service.cards_of(b.board.id)
    done = [c for c in cards if c.status == ColumnKey.DONE]
    abertos = [c for c in cards if c.status not in (ColumnKey.DONE, ColumnKey.CANCELLED)]
    prs = list(b.pull_requests)
    merged = [p for p in prs if p.status == "merged"]

    agentes = sorted({c.executor for c in cards if c.executor})
    modelos = sorted({c.uso["modelo"] for c in cards if c.uso.get("modelo")})
    efforts = sorted({str(t["effort"]) for c in cards for t in c.tentativas if t.get("effort")})

    documentos_produzidos: list[str] = []
    if b.orchestration.discovery_reports:
        n = len(b.orchestration.discovery_reports)
        documentos_produzidos.append(f"Discovery ({n} versão(ões))")
    if b.orchestration.spec_documents:
        n = len(b.orchestration.spec_documents)
        documentos_produzidos.append(f"Especificação ({n} versão(ões))")
    for tipo, ring in b.orchestration.documentos.items():
        if ring:
            documentos_produzidos.append(f"{tipo} ({len(ring)} versão(ões))")

    testes_manuais = sum(len(c.qa_checks) for c in cards)
    gates_rodados = len(b.gate_results)

    evidencias: list[str] = []
    riscos_residuais_cards: list[str] = []
    for c in done:
        if isinstance(c.closure, dict):
            evidencias.extend(str(e) for e in c.closure.get("evidencias", []))
            riscos_residuais_cards.extend(str(r) for r in c.closure.get("riscos_residuais", []))

    brief = DemandBrief.model_validate(b.orchestration.demand_brief)
    # dict.fromkeys preserva ordem e remove duplicatas (risco da demanda repetido
    # em vários cards não deve virar entradas repetidas no relatório).
    riscos_residuais = list(dict.fromkeys([*brief.riscos, *riscos_residuais_cards]))

    deploys_sucesso = [d for d in b.orchestration.deploy_runs if d.get("status") == STATUS_SUCESSO]
    data_implantacao = str(deploys_sucesso[-1].get("at", "")) if deploys_sucesso else ""

    return {
        "resumo": b.orchestration.user_request,
        "agentes_utilizados": agentes,
        "modelos_utilizados": modelos,
        "effort_utilizado": efforts,
        "commits": [p.branch for p in merged],
        "pull_requests": [f"{p.title or p.branch} — {p.status}" for p in prs],
        "documentos_produzidos": documentos_produzidos,
        "testes_executados": (
            f"{testes_manuais} verificação(ões) de QA manual · "
            f"{gates_rodados} quality gate(s) rodado(s)"
        ),
        "evidencias": evidencias,
        "data_implantacao": data_implantacao,
        "decisoes_tecnicas": [f"{a.id}: {a.title}" for a in b.adr_registry.list_all()],
        "riscos_residuais": riscos_residuais,
        "pendencias_futuras": [c.title for c in abertos],
    }


def _demand_closure_metricas(b: OrchestrationBundle) -> dict[str, int]:
    """Tira estatística (Tela 27, wf §29.2, ADR-0050) — "Cards concluídos" mora
    aqui, não como bloco do relatório (ver `_BLOCOS_ENCERRAMENTO_DEMANDA`)."""
    cards = b.board_service.cards_of(b.board.id)
    done = [c for c in cards if c.status == ColumnKey.DONE]
    agentes = {c.executor for c in cards if c.executor}
    return {
        "cards_concluidos": len(done),
        "agentes_utilizados": len(agentes),
        "execucoes": sum(len(c.tentativas) for c in cards),
        # Card que sofreu falha e MESMO ASSIM chegou a Done = falha corrigida
        # pelo roteamento automático (fato: sobreviveu ao ring de failures).
        "falhas_corrigidas": sum(1 for c in done if c.failures),
        "intervencoes_humanas": len(b.approvals),
        "deploys": len(b.orchestration.deploy_runs),
    }


def _render_demand_closure_markdown(
    orch: Orchestration, relatorio: dict[str, Any], metricas: dict[str, int]
) -> str:
    """Markdown exportável (botão 'Exportar relatório', wf §29.2, ADR-0050)."""
    linhas = [f"# Encerramento da demanda — {orch.user_request}", "", "## Resumo da execução", ""]
    linhas.append(
        f"- Cards: {metricas['cards_concluidos']} concluído(s)\n"
        f"- Agentes: {metricas['agentes_utilizados']} utilizado(s)\n"
        f"- Execuções: {metricas['execucoes']}\n"
        f"- Falhas corrigidas: {metricas['falhas_corrigidas']}\n"
        f"- Intervenções humanas: {metricas['intervencoes_humanas']}\n"
        f"- Deploys: {metricas['deploys']}"
    )
    linhas.append("")
    for chave, titulo in _BLOCOS_ENCERRAMENTO_DEMANDA:
        valor = relatorio.get(chave)
        linhas.append(f"## {titulo}")
        if isinstance(valor, list):
            texto = "\n".join(f"- {item}" for item in valor)
            linhas.append(texto if valor else "_Nenhum registro._")
        else:
            linhas.append(str(valor) if valor else "_Nenhum registro._")
        linhas.append("")
    return "\n".join(linhas)


class QaService:
    """QA humano, bugs vinculados e relatório de encerramento da demanda."""

    def __init__(
        self,
        store: BundleStore,
        *,
        max_escalonamentos: int,
        catalogo: Callable[[], ExecutorCatalog | None],
    ) -> None:
        self._bundle_store = store
        self._max_escalonamentos = max_escalonamentos
        self._catalogo = catalogo

    @property
    def _catalog(self) -> ExecutorCatalog | None:
        return self._catalogo()

    def _bundle(self, orchestration_id: str) -> OrchestrationBundle:
        return self._bundle_store.get(orchestration_id)

    def _persist(self, b: OrchestrationBundle) -> None:
        self._bundle_store.persist(b)

    def _lock_for(self, orchestration_id: str) -> threading.RLock:
        return self._bundle_store.lock_for(orchestration_id)

    def register_qa_check(
        self,
        orchestration_id: str,
        card_id: str,
        *,
        cenario: str,
        titulo: str = "",
        pre_condicoes: str = "",
        passos: list[str] | None = None,
        ambiente: str = "",
        resultado_esperado: str = "",
        resultado_obtido: str = "",
        evidencias: list[str] | None = None,
        gravidade: str = "media",
        status: str = QA_STATUS_PENDENTE,
        tipo_responsavel: str = "humano",
        actor: str = "system",
    ) -> QaCheck:
        """Registra uma verificação manual de QA (§16, plano de teste do wf §22.1)
        no ring do card (10 últimas)."""
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            card = b.board_service.get_card(card_id)
            if card is None:
                raise KeyError(f"Card inexistente: {card_id}")
            check = QaCheck(
                titulo=titulo,
                pre_condicoes=pre_condicoes,
                cenario=cenario,
                passos=list(passos or []),
                ambiente=ambiente,
                resultado_esperado=resultado_esperado,
                resultado_obtido=resultado_obtido,
                evidencias=list(evidencias or []),
                gravidade=gravidade,
                status=status,
                responsavel=actor,
                tipo_responsavel=tipo_responsavel,
            )
            card.qa_checks = [*card.qa_checks, check.model_dump(mode="json")][-_QA_RING:]
            b.event_log.append(
                "QaCheckRegistered",
                {"card_id": card_id, "cenario": cenario, "status": status, "actor": actor},
            )
            self._persist(b)
            return check

    def get_qa_checks(self, orchestration_id: str, card_id: str) -> list[QaCheck]:
        b = self._bundle(orchestration_id)
        card = b.board_service.get_card(card_id)
        if card is None:
            raise KeyError(f"Card inexistente: {card_id}")
        return [QaCheck.model_validate(c) for c in card.qa_checks]

    def fail_qa_check(
        self,
        orchestration_id: str,
        card_id: str,
        index: int,
        *,
        resultado_obtido: str = "",
        evidencias: list[str] | None = None,
        gravidade: str | None = None,
        actor: str = "system",
    ) -> KanbanCard:
        """§17: reprovação de QA cria um bug vinculado ao card original e devolve o
        card ao ponto certo do fluxo — via a mesma tabela de roteamento de falha
        (ADR-0019, `diagnosticar`/`decidir`), sem taxonomia nova."""
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            card = b.board_service.get_card(card_id)
            if card is None:
                raise KeyError(f"Card inexistente: {card_id}")
            if not 0 <= index < len(card.qa_checks):
                raise KeyError(f"Verificação de QA inexistente: índice {index}")
            check = QaCheck.model_validate(card.qa_checks[index])
            check.status = QA_STATUS_FALHOU
            if resultado_obtido:
                check.resultado_obtido = resultado_obtido
            if evidencias:
                check.evidencias = list(evidencias)
            if gravidade:
                check.gravidade = gravidade
            card.qa_checks[index] = check.model_dump(mode="json")

            bug = self._criar_bug_de_qa(b, card, check)

            card.tentativa_atual += 1  # §36.4, ADR-0031: contador autoritativo, não o ring
            card.tentativa_falha_atual += (
                1  # §13, ADR-0019: só falha consecutiva, decidir() usa este
            )
            record = FailureRecord(
                etapa=ETAPA_QA,
                tentativa=card.tentativa_atual,
                comando="qa",
                mensagem=f"QA reprovado: {check.cenario}",
                saida=check.resultado_obtido,
                categoria="qa",
            )
            card.failures = registrar(card.failures, record)
            diagnostico = diagnosticar(record)
            decisao = decidir(
                diagnostico,
                card.tentativa_falha_atual,
                catalogo=self._catalog,
                max_escalonamentos=(
                    card.max_tentativas
                    if card.max_tentativas is not None
                    else self._max_escalonamentos
                ),
            )
            card.tentativas = registrar_tentativa(
                card.tentativas,
                TentativaRegistro(
                    numero=card.tentativa_atual,
                    executor=card.executor or "",
                    resultado=RESULTADO_FALHOU,
                    diagnostico=diagnostico,
                ),
            )
            card.correction_actions = [decisao.nudge] if decisao.nudge else []
            detalhe = f"QA reprovado: {check.cenario} — {decisao.motivo}"
            b.event_log.append(
                "QaCheckFailed",
                {
                    "card_id": card_id,
                    "cenario": check.cenario,
                    "bug_id": bug.id,
                    "diagnostico": diagnostico,
                    "acao": decisao.acao,
                    "actor": actor,
                },
            )
            destino = (
                ColumnKey.FAILED if decisao.acao == ACAO_ESCALAR_HUMANO else ColumnKey.NEEDS_FIX
            )
            b.board_service.move_card(
                card_id, destino, reason=detalhe, result="falhou", next_action=decisao.acao
            )
            self._persist(b)
            atualizado = b.board_service.get_card(card_id)
            assert atualizado is not None  # noqa: S101 - card acabou de ser lido/movido acima
            return atualizado

    def _criar_bug_de_qa(
        self, b: OrchestrationBundle, card: KanbanCard, check: QaCheck
    ) -> KanbanCard:
        """Cria o card `Bug` do §17, vinculado por `dependencies` (para o observador
        de `blocked_by` da ADR-0018/0022) e por `parent_id` quando a hierarquia (§7)
        permitir — card original já no nível mais profundo cai sem `parent_id`, a
        dependência sozinha já vincula."""
        bug = KanbanCard(
            board_id=b.board.id,
            orchestration_id=b.orchestration.id,
            phase=card.phase,
            type=CardType.BUG,
            title=f"QA reprovado: {check.cenario}"[:200],
            description=_descricao_bug_de_qa(check),
            priority=_GRAVIDADE_PARA_PRIORIDADE.get(check.gravidade, RiskLevel.MEDIUM),
            assignee_type=card.assignee_type,
            assignee=card.assignee,
            status=ColumnKey.BACKLOG,
            dependencies=[card.id],
            parent_id=card.id,
        )
        try:
            b.board_service.add_card(bug)
        except ValueError:
            bug.parent_id = None
            b.board_service.add_card(bug)
        b.event_log.append("BugCreatedFromQa", {"card_id": card.id, "bug_id": bug.id})
        return bug

    def create_bug_report(
        self,
        orchestration_id: str,
        card_original_id: str,
        *,
        titulo: str,
        cenario: str = "",
        passos_para_reproduzir: list[str] | None = None,
        ambiente: str = "",
        resultado_atual: str = "",
        resultado_esperado: str = "",
        evidencias: list[str] | None = None,
        gravidade: str = "media",
        impacto: str = "",
        frequencia: str = "",
        agente_sugerido: str = "",
        retorno_de_fluxo: str = "retornar_implementacao",
        actor: str = "system",
    ) -> BugReport:
        """Registro manual de bug (Tela 21, wf §23) — cria o `KanbanCard(type=Bug)`
        (mesmo tipo que `_criar_bug_de_qa` já cria automaticamente na reprovação
        de QA, ADR-0025) e o `BugReport` estruturado companion (ADR-0049).

        `retorno_de_fluxo == "card_independente"` é a única das 6 opções do wf
        §23.2 com efeito real no backend: o card nasce SEM vínculo de
        dependência com o original. As outras 5 ("retornar para X") são
        metadado descritivo — o runtime não tem mecanismo de roteamento
        automático entre disciplinas/times, então fabricar esse roteamento
        mentiria sobre o que o sistema faz; a intenção do operador fica
        registrada e visível, não escondida.
        """
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            card = b.board_service.get_card(card_original_id)
            if card is None:
                raise KeyError(f"Card inexistente: {card_original_id}")
            linhas = [f"Cenário: {cenario}"] if cenario else []
            if ambiente:
                linhas.append(f"Ambiente: {ambiente}")
            if passos_para_reproduzir:
                passos = "\n".join(f"{i + 1}. {p}" for i, p in enumerate(passos_para_reproduzir))
                linhas.append(f"Como reproduzir:\n{passos}")
            if resultado_esperado:
                linhas.append(f"Resultado esperado: {resultado_esperado}")
            if resultado_atual:
                linhas.append(f"Resultado atual: {resultado_atual}")
            if evidencias:
                linhas.append("Evidências: " + "; ".join(evidencias))
            linhas.append(f"Gravidade: {gravidade}")
            independente = retorno_de_fluxo == "card_independente"
            bug_card = KanbanCard(
                board_id=b.board.id,
                orchestration_id=b.orchestration.id,
                phase=card.phase,
                type=CardType.BUG,
                title=titulo[:200],
                description="\n".join(linhas),
                priority=_GRAVIDADE_PARA_PRIORIDADE.get(gravidade, RiskLevel.MEDIUM),
                assignee_type=card.assignee_type,
                assignee=agente_sugerido or card.assignee,
                status=ColumnKey.BACKLOG,
                dependencies=[] if independente else [card.id],
                parent_id=None if independente else card.id,
            )
            try:
                b.board_service.add_card(bug_card)
            except ValueError:
                bug_card.parent_id = None
                b.board_service.add_card(bug_card)
            report = BugReport(
                orchestration_id=b.orchestration.id,
                card_original_id=card_original_id,
                card_id=bug_card.id,
                titulo=titulo,
                cenario=cenario,
                passos_para_reproduzir=list(passos_para_reproduzir or []),
                ambiente=ambiente,
                resultado_atual=resultado_atual,
                resultado_esperado=resultado_esperado,
                evidencias=list(evidencias or []),
                gravidade=gravidade,
                impacto=impacto,
                frequencia=frequencia,
                agente_sugerido=agente_sugerido,
                retorno_de_fluxo=retorno_de_fluxo,
                reportado_por=actor,
            )
            b.bug_reports.append(report)
            b.event_log.append(
                "BugReportCreated",
                {
                    "card_original_id": card_original_id,
                    "bug_card_id": bug_card.id,
                    "bug_report_id": report.id,
                    "actor": actor,
                },
            )
            self._persist(b)
            return report

    def get_bug_report(self, orchestration_id: str, bug_report_id: str) -> BugReport | None:
        return next(
            (r for r in self._bundle(orchestration_id).bug_reports if r.id == bug_report_id),
            None,
        )

    def get_demand_closure(self, orchestration_id: str) -> dict[str, Any]:
        """Tela 27 (wf §29, ADR-0050): relatório de encerramento da demanda —
        13 blocos + métricas de resumo."""
        b = self._bundle(orchestration_id)
        return {
            "relatorio": _build_demand_closure(b),
            "metricas": _demand_closure_metricas(b),
        }

    def export_demand_closure(self, orchestration_id: str) -> str:
        """Markdown pronto para download (botão 'Exportar relatório', wf §29.2)."""
        b = self._bundle(orchestration_id)
        relatorio = _build_demand_closure(b)
        metricas = _demand_closure_metricas(b)
        return _render_demand_closure_markdown(b.orchestration, relatorio, metricas)
