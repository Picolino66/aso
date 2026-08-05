"""DiscoveryService — relatório de discovery e regra de aprovação (§3/§4, ADR-0020).

Espelha `aso.control.triage` na estrutura e na filosofia de fallback: **discovery
nunca pode travar por falta de agente configurado.** Sem agente (ou com falha), um
relatório determinístico é montado a partir do `WorkspaceReport` (scan estrutural já
existente, `execution/workspace.py`) e da `DemandBrief` já triada (ADR-0016) — nunca
levanta exceção.

A regra de aprovação automática vs. humana (§4) espelha `exige_confirmacao_humana`
de `aso.control.review` (ADR-0017): reaproveita o vocabulário de impactos sensíveis
de `decision_engine.py`, não inventa um novo.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from aso.control.agent_ask import ERROS_DE_AGENTE, perguntar_ao_agente
from aso.control.decision_engine import _SENSITIVE_IMPACTS
from aso.control.models import AgentAssignment
from aso.control.triage import DemandBrief
from aso.execution.catalog import ExecutorCatalog
from aso.execution.workspace import WorkspaceReport
from aso.shared.ids import now_iso
from aso.shared.types import RiskLevel

TIMEOUT_PADRAO = 60.0  # discovery lê mais contexto que a triagem; timeout um degrau acima

STATUS_RASCUNHO = "rascunho"
STATUS_AGUARDANDO_APROVACAO = "aguardando_aprovacao"
STATUS_APROVADO = "aprovado"
STATUS_REPROVADO = "reprovado"

_CONFIANCAS_VALIDAS = frozenset({"alta", "media", "baixa"})

_DISCOVERY_SYSTEM = (
    "Você é o agente de discovery de um runtime de engenharia autônoma — analisa o "
    "contexto de uma demanda antes de qualquer implementação (§3 do fluxo).\n"
    "Responda SOMENTE com um objeto JSON válido, sem cercas de código, na forma:\n"
    '{"situacao_atual": "...", "problema": "...", "componentes_afetados": ["..."],\n'
    ' "restricoes": ["..."], "riscos": ["..."], "alternativas": ["..."],\n'
    ' "recomendacao_tecnica": "...", "pontos_decisao": ["..."], "confianca": "..."}\n'
    "Tudo em português do Brasil. `confianca` aceita só: alta|media|baixa — baixa "
    "quando a recomendação depende de informação que você não tem certeza. Se não "
    "houver alternativas reais, deixe a lista vazia — não invente."
)


class DiscoveryReport(BaseModel):
    """O que o §3 manda produzir + o estado de aprovação do §4."""

    situacao_atual: str = ""
    problema: str = ""
    componentes_afetados: list[str] = Field(default_factory=list)
    restricoes: list[str] = Field(default_factory=list)
    riscos: list[str] = Field(default_factory=list)
    alternativas: list[str] = Field(default_factory=list)
    recomendacao_tecnica: str = ""
    pontos_decisao: list[str] = Field(default_factory=list)
    confianca: str = "alta"  # alta | media | baixa
    status: str = STATUS_RASCUNHO
    revisao_comentarios: str = ""
    origem: str = "heuristica"  # nome do executor, ou "heuristica"
    fallback_reason: str = ""
    # Versão dentro do ring (§4.2 do plano4.md, ADR-0021) — 1-based, monotônica.
    versao: int = 1
    at: str = Field(default_factory=now_iso)


def exige_aprovacao_discovery(report: DiscoveryReport, brief: DemandBrief) -> bool:
    """§4 do fluxo.md: quando a aprovação do discovery precisa ser humana.

    Cobre "altera arquitetura"/"mais de uma solução viável"/"afeta segurança,
    privacidade ou permissões"/"risco de perda de dados" via `_SENSITIVE_IMPACTS`
    (mesmo vocabulário do motor de decisão) e "baixa confiança na recomendação" via
    `report.confianca`.
    """
    return (
        report.confianca == "baixa"
        or brief.risco in (RiskLevel.HIGH, RiskLevel.CRITICAL)
        or bool(set(brief.impactos) & _SENSITIVE_IMPACTS)
    )


class DiscoveryService:
    """Produz um `DiscoveryReport` a partir do workspace e da ficha da demanda."""

    def __init__(
        self, catalog: ExecutorCatalog | None = None, *, timeout: float = TIMEOUT_PADRAO
    ) -> None:
        self._catalog = catalog
        self._timeout = timeout

    def investigar(
        self,
        assignment: AgentAssignment | None,
        *,
        user_request: str,
        demand_brief: DemandBrief,
        workspace_report: WorkspaceReport,
        comentarios_anteriores: str = "",
    ) -> DiscoveryReport:
        """Relatório de discovery. Sem agente configurado (ou com falha), heurística."""
        base = _heuristica(user_request, demand_brief, workspace_report)
        if assignment is None or self._catalog is None:
            return base
        try:
            bruto = self._perguntar(
                assignment,
                user_request=user_request,
                demand_brief=demand_brief,
                workspace_report=workspace_report,
                comentarios_anteriores=comentarios_anteriores,
            )
        except ERROS_DE_AGENTE as exc:
            return base.model_copy(update={"fallback_reason": f"{type(exc).__name__}: {exc}"[:200]})
        relatorio = _sanear(bruto)
        if relatorio is None:
            return base.model_copy(
                update={"fallback_reason": "resposta do agente sem campos utilizáveis"}
            )
        return relatorio.model_copy(update={"origem": assignment.executor})

    def _perguntar(
        self,
        assignment: AgentAssignment,
        *,
        user_request: str,
        demand_brief: DemandBrief,
        workspace_report: WorkspaceReport,
        comentarios_anteriores: str,
    ) -> dict[str, object]:
        assert self._catalog is not None  # noqa: S101 - garantido pelo chamador
        pedido = _montar_pedido(
            user_request, demand_brief, workspace_report, comentarios_anteriores
        )
        return perguntar_ao_agente(
            self._catalog,
            assignment,
            system=_DISCOVERY_SYSTEM,
            pedido=pedido,
            kind="discovery",
            timeout=self._timeout,
        )


def _montar_pedido(
    user_request: str,
    demand_brief: DemandBrief,
    workspace_report: WorkspaceReport,
    comentarios_anteriores: str,
) -> str:
    partes = [
        f"Demanda:\n{user_request}",
        f"Ficha já triada — objetivo: {demand_brief.objetivo or '(vazio)'}; "
        f"problema: {demand_brief.problema or '(vazio)'}; "
        f"módulos afetados: {', '.join(demand_brief.modulos_afetados) or '(nenhum)'}; "
        f"riscos conhecidos: {', '.join(demand_brief.riscos) or '(nenhum)'}.",
        f"Workspace — módulos detectados: "
        f"{', '.join(workspace_report.detected_modules) or '(nenhum)'}; "
        f"repositório git: {'sim' if workspace_report.is_git else 'não'}; "
        f"docs-first já existe: {'sim' if workspace_report.has_aso_docs else 'não'}.",
    ]
    if comentarios_anteriores:
        partes.append(
            f"Uma versão anterior deste discovery foi reprovada com o comentário: "
            f'"{comentarios_anteriores}" — ajuste o documento considerando isto.'
        )
    partes.append("Produza o relatório de discovery em JSON.")
    return "\n\n".join(partes)


def _heuristica(
    user_request: str, demand_brief: DemandBrief, workspace_report: WorkspaceReport
) -> DiscoveryReport:
    """Monta um relatório determinístico a partir do que já se sabe — sem I/O novo,
    sem LLM, nunca falha. Confiança sempre baixa: sem investigação real de um agente,
    o relatório é só um resumo do que a triagem e o scan estrutural já enxergavam."""
    situacao = "Repositório git existente" if workspace_report.is_git else "Pasta sem git"
    if workspace_report.detected_modules:
        situacao += f"; módulos detectados: {', '.join(workspace_report.detected_modules)}"
    return DiscoveryReport(
        situacao_atual=situacao,
        problema=demand_brief.problema or user_request,
        componentes_afetados=list(demand_brief.modulos_afetados),
        riscos=list(demand_brief.riscos),
        confianca="baixa",
        origem="heuristica",
    )


# --------------------------------------------------------------------- saneamento


def _lista_texto(valor: object, *, limite: int = 12) -> list[str]:
    if not isinstance(valor, list):
        return []
    return [str(v).strip() for v in valor if str(v).strip()][:limite]


def _sanear(bruto: dict[str, object]) -> DiscoveryReport | None:
    """Aceita a resposta do agente só depois de validar `confianca` contra o
    vocabulário fechado. Devolve `None` quando não sobra nenhum campo de conteúdo
    utilizável — aí quem chama cai no fallback heurístico com o motivo registrado.
    """
    confianca = str(bruto.get("confianca") or "").strip().lower()
    if confianca not in _CONFIANCAS_VALIDAS:
        confianca = "media"
    situacao_atual = str(bruto.get("situacao_atual") or "").strip()
    problema = str(bruto.get("problema") or "").strip()
    recomendacao = str(bruto.get("recomendacao_tecnica") or "").strip()
    componentes = _lista_texto(bruto.get("componentes_afetados"))
    riscos = _lista_texto(bruto.get("riscos"))
    if not (situacao_atual or problema or recomendacao or componentes or riscos):
        return None
    return DiscoveryReport(
        situacao_atual=situacao_atual,
        problema=problema,
        componentes_afetados=componentes,
        restricoes=_lista_texto(bruto.get("restricoes")),
        riscos=riscos,
        alternativas=_lista_texto(bruto.get("alternativas")),
        recomendacao_tecnica=recomendacao,
        pontos_decisao=_lista_texto(bruto.get("pontos_decisao")),
        confianca=confianca,
    )
