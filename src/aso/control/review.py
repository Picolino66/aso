"""ReviewService — revisão independente de código a partir do diff (§14/§15).

Fecha a lacuna descrita na ADR-0017: hoje `report_review` grava uma string sem
checar quem revisou nem exigir que alguém tenha olhado o diff, e o `ReviewAgent`
roda pelo `_build_task` genérico, que não passa diff nenhum — ele "revisa" sem
ver código. Este módulo produz um `ReviewVerdict` a partir do diff real de um
card, no mesmo molde de `aso.control.triage`: prompt de sistema constante, duplo
caminho `kind == "llm"` / `kind == "cli"`, saneamento contra vocabulário fechado.

**Diferença crítica em relação a `naming`/`triage`**: não existe revisão de
código determinística. `NamingService` cai num slug e `TriageService` cai numa
heurística por palavra-chave — ambos continuam funcionando sem agente. Uma PR
sem revisor não pode "continuar funcionando" da mesma forma: o fallback deste
serviço é **sempre** `necessita_humano`, nunca `aprovado`. Qualquer indisponibi-
lidade do agente (timeout, JSON inválido, executor removido do catálogo, sandbox
sem permissão) escala para revisão humana — inverter isso transformaria toda
falha do revisor numa aprovação automática, o oposto do que o §14 pede.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from aso.control.agent_ask import ERROS_DE_AGENTE, perguntar_ao_agente
from aso.control.models import SPEC_KEY, AgentAssignment
from aso.control.triage import DemandBrief
from aso.execution.catalog import ExecutorCatalog
from aso.shared.ids import now_iso
from aso.shared.types import RiskLevel

TIMEOUT_PADRAO = 180.0  # revisar um diff é mais caro que nomear/triar; bem abaixo da execução

# Diff acima disto é truncado antes de ir ao prompt — um revisor que "aprova" sem
# ressalva depois de ver metade do diff é pior que nenhum revisor.
DIFF_MAX = 60_000

# Os cinco desfechos do fluxo.md §14, na ordem em que ele os lista.
VEREDITO_APROVADO = "aprovado"
VEREDITO_APROVADO_COM_SUGESTOES = "aprovado_com_sugestoes"
VEREDITO_ALTERACOES_OBRIGATORIAS = "alteracoes_obrigatorias"
VEREDITO_REPROVADO = "reprovado"
VEREDITO_NECESSITA_HUMANO = "necessita_humano"

_VEREDITOS_VALIDOS = frozenset(
    {
        VEREDITO_APROVADO,
        VEREDITO_APROVADO_COM_SUGESTOES,
        VEREDITO_ALTERACOES_OBRIGATORIAS,
        VEREDITO_REPROVADO,
        VEREDITO_NECESSITA_HUMANO,
    }
)
_CATEGORIAS_VALIDAS = frozenset(
    {"correcao", "teste", "seguranca", "clareza", "escopo", "documentacao", "performance"}
)
_SEVERIDADES_VALIDAS = frozenset({"obrigatoria", "sugestao"})

# Impactos da ficha da demanda que exigem confirmação humana mesmo com veredito
# aprovado (§4 do fluxo.md aplicado ao code review).
_IMPACTOS_QUE_EXIGEM_HUMANO = frozenset({"security", "database", "deploy"})

# Os QUATRO desfechos do §6 (revisão documental) — não são os cinco do §14: não há
# "alteracoes_obrigatorias" aqui, e não reaproveitamos o enum do code review por
# preguiça (ADR-0021, plano4.md §4.4).
VEREDITO_DOC_APROVADO = "aprovado"
VEREDITO_DOC_APROVADO_COM_OBSERVACOES = "aprovado_com_observacoes"
VEREDITO_DOC_REPROVADO = "reprovado"
VEREDITO_DOC_NECESSITA_HUMANO = "necessita_humano"

_VEREDITOS_DOC_VALIDOS = frozenset(
    {
        VEREDITO_DOC_APROVADO,
        VEREDITO_DOC_APROVADO_COM_OBSERVACOES,
        VEREDITO_DOC_REPROVADO,
        VEREDITO_DOC_NECESSITA_HUMANO,
    }
)

_DOC_REVIEW_SYSTEM = (
    "Você revisa documentos de um runtime de engenharia autônoma antes da "
    "implementação (§6 do fluxo.md) — o documento pode ser uma especificação técnica "
    "ou um relatório de discovery.\n"
    "Responda SOMENTE com um objeto JSON válido, sem cercas de código, na forma:\n"
    '{"veredito": "...", "resumo": "...", '
    '"acoes": [{"descricao": "...", "categoria": "...", "severidade": "..."}], '
    '"pontos_verificados": ["..."]}\n'
    "Tudo em português do Brasil. Valores aceitos para veredito (não use outros, e "
    "note que NÃO existe 'alteracoes_obrigatorias' aqui — isso é do code review): "
    "aprovado|aprovado_com_observacoes|reprovado|necessita_humano\n"
    "Avalie os nove eixos do §6: consistência, completude, viabilidade, segurança, "
    "compatibilidade com o projeto, clareza dos critérios de aceite, presença de "
    "plano de testes, presença de plano de rollback e ausência de contradições — "
    "registre em `pontos_verificados` quais você checou.\n"
    "Na dúvida, use `necessita_humano` — nunca `aprovado`."
)

_REVIEW_SYSTEM = (
    "Você revisa código de forma independente num runtime de engenharia autônoma "
    "(§14 do fluxo.md). Você NÃO tem acesso ao restante do repositório — só ao diff "
    "fornecido; se algo depender de código que você não vê, registre a limitação em "
    "vez de supor.\n"
    "Responda SOMENTE com um objeto JSON válido, sem cercas de código, na forma:\n"
    '{"veredito": "...", "resumo": "...", '
    '"acoes": [{"descricao": "...", "categoria": "...", "severidade": "..."}], '
    '"pontos_verificados": ["..."]}\n'
    "Tudo em português do Brasil. Valores aceitos (não use outros):\n"
    "- veredito: aprovado|aprovado_com_sugestoes|alteracoes_obrigatorias|reprovado|"
    "necessita_humano\n"
    "- categoria de cada ação: correcao|teste|seguranca|clareza|escopo|documentacao|"
    "performance\n"
    "- severidade de cada ação: obrigatoria|sugestao\n"
    "Avalie os doze eixos do §14: correção, aderência aos requisitos, qualidade, "
    "clareza, manutenibilidade, segurança, tratamento de erros, performance, padrões, "
    "cobertura de testes, risco de regressão e mudanças fora de escopo — registre em "
    "`pontos_verificados` quais você checou.\n"
    "Cada crítica vira uma AÇÃO OBJETIVA E ACIONÁVEL (ex.: 'Adicionar teste para o "
    "cenário de token expirado'), nunca um comentário genérico ('melhorar os testes') "
    "— é o §15.\n"
    "Na dúvida, use `necessita_humano` — nunca `aprovado`."
)


class ReviewAction(BaseModel):
    """Comentário do revisor já convertido em ação objetiva (§15)."""

    descricao: str
    categoria: str = "correcao"
    severidade: str = "obrigatoria"  # obrigatoria | sugestao


class ReviewVerdict(BaseModel):
    """Resultado de uma revisão independente de código (§14/§15).

    O default de `veredito` é `necessita_humano`: uma instância "vazia" desta
    classe (sem agente rodado) já é, por construção, o estado mais conservador.
    """

    veredito: str = VEREDITO_NECESSITA_HUMANO
    resumo: str = ""
    acoes: list[ReviewAction] = Field(default_factory=list)
    pontos_verificados: list[str] = Field(default_factory=list)
    revisor: str = ""  # nome do executor que revisou
    origem: str = "indisponivel"  # agente | indisponivel
    fallback_reason: str = ""
    at: str = Field(default_factory=now_iso)


class DocReviewVerdict(BaseModel):
    """Resultado de uma revisão documental (§6) — mesma forma de `ReviewVerdict`, com
    o vocabulário de veredito próprio do §6 (quatro desfechos, não cinco)."""

    veredito: str = VEREDITO_DOC_NECESSITA_HUMANO
    resumo: str = ""
    acoes: list[ReviewAction] = Field(default_factory=list)
    pontos_verificados: list[str] = Field(default_factory=list)
    revisor: str = ""  # nome do executor que revisou
    origem: str = "indisponivel"  # agente | indisponivel | checagem_deterministica
    fallback_reason: str = ""
    at: str = Field(default_factory=now_iso)


def exige_confirmacao_humana(brief: DemandBrief) -> bool:
    """§4 do fluxo.md aplicado ao code review: risco alto ou impacto sensível não
    fecha a revisão sozinho, mesmo com o agente aprovando."""
    return brief.risco in (RiskLevel.HIGH, RiskLevel.CRITICAL) or bool(
        set(brief.impactos) & _IMPACTOS_QUE_EXIGEM_HUMANO
    )


def _indisponivel(motivo: str) -> ReviewVerdict:
    """O único fallback deste serviço: sempre pede humano, nunca aprova sozinho."""
    return ReviewVerdict(
        veredito=VEREDITO_NECESSITA_HUMANO, origem="indisponivel", fallback_reason=motivo
    )


class ReviewService:
    """Produz um `ReviewVerdict` a partir do diff real de um card."""

    def __init__(
        self, catalog: ExecutorCatalog | None = None, *, timeout: float = TIMEOUT_PADRAO
    ) -> None:
        self._catalog = catalog
        self._timeout = timeout

    def revisar(
        self,
        assignment: AgentAssignment | None,
        *,
        diff: str,
        card_title: str,
        card_description: str = "",
        acceptance_criteria: list[str] | None = None,
        riscos: list[str] | None = None,
    ) -> ReviewVerdict:
        """Veredito da revisão. Sem agente (ou com falha), `necessita_humano`."""
        if assignment is None or self._catalog is None:
            return _indisponivel("nenhum agente revisor configurado")
        diff_truncado, aviso_truncamento = _truncar_diff(diff)
        try:
            bruto = self._perguntar(
                assignment,
                diff=diff_truncado,
                aviso=aviso_truncamento,
                card_title=card_title,
                card_description=card_description,
                acceptance_criteria=acceptance_criteria or [],
                riscos=riscos or [],
            )
        except ERROS_DE_AGENTE as exc:
            return _indisponivel(f"{type(exc).__name__}: {exc}"[:200])
        verdito = _sanear(bruto)
        if verdito is None:
            return _indisponivel("resposta do revisor sem veredito utilizável")
        if aviso_truncamento:
            verdito = verdito.model_copy(
                update={"pontos_verificados": [*verdito.pontos_verificados, aviso_truncamento]}
            )
        return verdito.model_copy(update={"revisor": assignment.executor, "origem": "agente"})

    def _perguntar(
        self,
        assignment: AgentAssignment,
        *,
        diff: str,
        aviso: str,
        card_title: str,
        card_description: str,
        acceptance_criteria: list[str],
        riscos: list[str],
    ) -> dict[str, object]:
        assert self._catalog is not None  # noqa: S101 - garantido pelo chamador
        pedido = _pedido(diff, aviso, card_title, card_description, acceptance_criteria, riscos)
        return perguntar_ao_agente(
            self._catalog,
            assignment,
            system=_REVIEW_SYSTEM,
            pedido=pedido,
            kind="revisao",
            timeout=self._timeout,
        )

    # ---------------------------------------------------------- revisão documental

    def revisar_documento(
        self,
        assignment: AgentAssignment | None,
        *,
        documento: BaseModel,
        tipo: str,
        brief: DemandBrief,
    ) -> DocReviewVerdict:
        """Revisão documental (§6) — antes da implementação, não do código.

        Dois dos nove eixos são fatos, não opinião, e reprovam **sem gastar um
        agente**: presença de plano de testes e de plano de rollback (só se aplicam a
        `SpecDocument`; um `DiscoveryReport` não tem esses campos)."""
        faltando = _campos_obrigatorios_faltando(documento, tipo)
        if faltando:
            return DocReviewVerdict(
                veredito=VEREDITO_DOC_REPROVADO,
                resumo="Documento reprovado sem revisão: campo obrigatório vazio.",
                pontos_verificados=faltando,
                origem="checagem_deterministica",
            )
        if assignment is None or self._catalog is None:
            return DocReviewVerdict(fallback_reason="nenhum agente revisor documental configurado")
        try:
            bruto = self._perguntar_documento(
                assignment, documento=documento, tipo=tipo, brief=brief
            )
        except ERROS_DE_AGENTE as exc:
            return DocReviewVerdict(fallback_reason=f"{type(exc).__name__}: {exc}"[:200])
        verdito = _sanear_doc(bruto)
        if verdito is None:
            return DocReviewVerdict(fallback_reason="resposta do revisor sem veredito utilizável")
        return verdito.model_copy(update={"revisor": assignment.executor, "origem": "agente"})

    def _perguntar_documento(
        self, assignment: AgentAssignment, *, documento: BaseModel, tipo: str, brief: DemandBrief
    ) -> dict[str, object]:
        assert self._catalog is not None  # noqa: S101 - garantido pelo chamador
        pedido = _pedido_documento(documento, tipo, brief)
        return perguntar_ao_agente(
            self._catalog,
            assignment,
            system=_DOC_REVIEW_SYSTEM,
            pedido=pedido,
            kind="revisao_documental",
            timeout=self._timeout,
        )


def _campos_obrigatorios_faltando(documento: BaseModel, tipo: str) -> list[str]:
    """Checagem determinística (§6): campo vazio é fato, não opinião. Só se aplica a
    `SpecDocument` — `getattr` com default evita acoplar este módulo ao `spec.py`."""
    faltando: list[str] = []
    if tipo == SPEC_KEY:
        if not str(getattr(documento, "estrategia_de_testes", "")).strip():
            faltando.append("plano de testes ausente")
        if not str(getattr(documento, "plano_de_rollback", "")).strip():
            faltando.append("plano de rollback ausente")
    return faltando


def _pedido_documento(documento: BaseModel, tipo: str, brief: DemandBrief) -> str:
    linhas = [f"Tipo de documento: {tipo}", f"Risco da demanda: {brief.risco.value}"]
    if brief.riscos:
        linhas.append("Riscos conhecidos: " + "; ".join(brief.riscos[:10])[:500])
    linhas.append("Documento (JSON):\n" + documento.model_dump_json(indent=2))
    linhas.append("Produza o veredito JSON.")
    return "\n".join(linhas)


def _sanear_doc(bruto: dict[str, object]) -> DocReviewVerdict | None:
    """Mesmo saneamento de `_sanear`, com o vocabulário de veredito do §6."""
    veredito_bruto = bruto.get("veredito")
    resumo = str(bruto.get("resumo") or "").strip()
    acoes_brutas = bruto.get("acoes")
    pontos = _lista_texto(bruto.get("pontos_verificados"))
    if not (veredito_bruto or resumo or acoes_brutas or pontos):
        return None
    veredito = str(veredito_bruto or "").strip().lower()
    if veredito not in _VEREDITOS_DOC_VALIDOS:
        veredito = VEREDITO_DOC_NECESSITA_HUMANO
    return DocReviewVerdict(
        veredito=veredito,
        resumo=resumo,
        acoes=_sanear_acoes(acoes_brutas),
        pontos_verificados=pontos,
    )


def _truncar_diff(diff: str) -> tuple[str, str]:
    """Corta o diff em `DIFF_MAX` caracteres e devolve o aviso a incluir no prompt."""
    if len(diff) <= DIFF_MAX:
        return diff, ""
    truncado = diff[:DIFF_MAX]
    aviso = f"[diff truncado em {DIFF_MAX} de {len(diff)} caracteres — revisão parcial]"
    return truncado, aviso


def _pedido(
    diff: str,
    aviso: str,
    card_title: str,
    card_description: str,
    acceptance_criteria: list[str],
    riscos: list[str],
) -> str:
    linhas = [f"Card em revisão: {card_title}"]
    if card_description:
        linhas.append(f"Descrição: {card_description[:500]}")
    if acceptance_criteria:
        linhas.append("Critérios de aceite: " + "; ".join(acceptance_criteria[:10])[:500])
    if riscos:
        linhas.append("Riscos conhecidos da demanda: " + "; ".join(riscos[:10])[:500])
    if aviso:
        linhas.append(aviso)
    linhas.append("Diff a revisar:\n" + diff)
    linhas.append("Produza o veredito JSON.")
    return "\n".join(linhas)


# --------------------------------------------------------------------- saneamento


def _lista_texto(valor: object, *, limite: int = 20) -> list[str]:
    if not isinstance(valor, list):
        return []
    return [str(v).strip() for v in valor if str(v).strip()][:limite]


def _sanear_acoes(valor: object) -> list[ReviewAction]:
    """Aceita ações do agente saneando categoria/severidade — nunca propaga lixo."""
    if not isinstance(valor, list):
        return []
    resultado: list[ReviewAction] = []
    for item in valor[:20]:
        if not isinstance(item, dict):
            continue
        descricao = str(item.get("descricao") or "").strip()
        if not descricao:
            continue
        categoria = str(item.get("categoria") or "").strip().lower()
        if categoria not in _CATEGORIAS_VALIDAS:
            categoria = "correcao"
        severidade = str(item.get("severidade") or "").strip().lower()
        if severidade not in _SEVERIDADES_VALIDAS:
            severidade = "obrigatoria"
        resultado.append(
            ReviewAction(descricao=descricao, categoria=categoria, severidade=severidade)
        )
    return resultado


def _sanear(bruto: dict[str, object]) -> ReviewVerdict | None:
    """Aceita a resposta do agente saneando contra o vocabulário fechado.

    Veredito, categoria e severidade fora do vocabulário caem no padrão (o mais
    conservador: `necessita_humano`) — nunca são descartados por completo, nem
    propagam um valor inventado. Devolve `None` só quando não sobra NENHUM campo
    de conteúdo: aí quem chama cai no fallback `_indisponivel`.
    """
    veredito_bruto = bruto.get("veredito")
    resumo = str(bruto.get("resumo") or "").strip()
    acoes_brutas = bruto.get("acoes")
    pontos = _lista_texto(bruto.get("pontos_verificados"))
    if not (veredito_bruto or resumo or acoes_brutas or pontos):
        return None
    veredito = str(veredito_bruto or "").strip().lower()
    if veredito not in _VEREDITOS_VALIDOS:
        veredito = VEREDITO_NECESSITA_HUMANO
    return ReviewVerdict(
        veredito=veredito,
        resumo=resumo,
        acoes=_sanear_acoes(acoes_brutas),
        pontos_verificados=pontos,
    )
