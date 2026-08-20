"""TriageService — transforma o texto livre da demanda numa ficha estruturada (§1/§2).

Hoje `MultiAgentDecisionEngine` decide sempre sobre a mesma constante
(`domains=["backend"]`, `risk_level=LOW`) porque nada preenche `decision_input` na
criação da orquestração. Este módulo fecha essa lacuna: interpreta a demanda e produz
um `DemandBrief` que alimenta o motor de decisão de verdade.

Espelha `aso.control.naming` na estrutura e, principalmente, na filosofia de
fallback: **triar nunca pode impedir a criação de uma orquestração.** Uma demanda
mal triada ainda é executável pelo caminho heurístico determinístico; uma demanda que
não entra no sistema está perdida. Qualquer falha do agente (timeout, JSON inválido,
executor removido do catálogo, sandbox sem permissão) cai no caminho heurístico e
registra o motivo.
"""

from __future__ import annotations

import unicodedata

from pydantic import BaseModel, Field

from aso.control.agent_ask import ERROS_DE_AGENTE, perguntar_ao_agente
from aso.control.decision_engine import _APPROVAL_IMPACTS, _DOMAIN_AGENT, _SENSITIVE_IMPACTS
from aso.control.models import AgentAssignment, DecisionInput
from aso.execution.branch_naming import tem_texto_util
from aso.execution.catalog import ExecutorCatalog
from aso.shared.types import RiskLevel

TIMEOUT_PADRAO = 45.0  # acima dos 30s do naming (texto maior); bem abaixo do timeout de execução

# Vocabulário fechado, copiado do decision_engine (§14) — não redefinir com valores
# próprios, ou a ficha perde efeito sobre a decisão: um domínio/impacto fora daqui
# faria o motor montar equipe errada ou nunca elevar risco/aprovação.
_DOMINIOS_VALIDOS = frozenset(_DOMAIN_AGENT)
_IMPACTOS_VALIDOS = frozenset(_SENSITIVE_IMPACTS | _APPROVAL_IMPACTS)
_TIPOS_VALIDOS = frozenset(
    {
        "funcionalidade",
        "correcao",
        "refatoracao",
        "arquitetura",
        "infraestrutura",
        "investigacao",
        "documentacao",
        "seguranca",
        "desempenho",
        "produto",
    }
)
_COMPLEXIDADES_VALIDAS = frozenset({"simples", "intermediaria", "complexa", "estrategica"})

_TRIAGE_SYSTEM = (
    "Você faz a triagem de demandas de um runtime de engenharia autônoma.\n"
    "Responda SOMENTE com um objeto JSON válido, sem cercas de código, na forma:\n"
    '{"tipo": "...", "objetivo": "...", "problema": "...", "resultado_esperado": "...",\n'
    ' "modulos_afetados": ["..."], "dominios": ["..."], "impactos": ["..."],\n'
    ' "riscos": ["..."], "criterios_de_aceite": ["..."], "risco": "...",\n'
    ' "complexidade": "...", "perguntas_abertas": ["..."]}\n'
    "Tudo em português do Brasil. Valores aceitos (não use outros):\n"
    "- tipo: funcionalidade|correcao|refatoracao|arquitetura|infraestrutura|investigacao|"
    "documentacao|seguranca|desempenho|produto\n"
    "- dominios (um ou mais): backend|frontend|database|architecture|contract|security|"
    "tests|docs|devops\n"
    "- impactos (zero ou mais): architecture|contract|security|database|deploy|secrets|"
    "database_reset|branch_main\n"
    "- risco: low|medium|high|critical\n"
    "- complexidade: simples|intermediaria|complexa|estrategica\n"
    "Se a demanda não disser algo, não invente — registre a lacuna em `perguntas_abertas`."
)


class DemandBrief(BaseModel):
    """Ficha estruturada da demanda (§1/§2 do fluxo.md).

    Existe para alimentar o `MultiAgentDecisionEngine`, que hoje decide sobre uma
    constante. Os campos `dominios` e `impactos` usam deliberadamente o vocabulário de
    `decision_engine.py` (`_DOMAIN_AGENT` e `_SENSITIVE_IMPACTS`/`_APPROVAL_IMPACTS`) —
    não invente rótulos novos, ou a ficha não terá efeito sobre a decisão.
    """

    tipo: str = "funcionalidade"
    objetivo: str = ""
    problema: str = ""
    resultado_esperado: str = ""
    modulos_afetados: list[str] = Field(default_factory=list)
    dominios: list[str] = Field(default_factory=list)
    impactos: list[str] = Field(default_factory=list)
    riscos: list[str] = Field(default_factory=list)
    criterios_de_aceite: list[str] = Field(default_factory=list)
    risco: RiskLevel = RiskLevel.LOW
    complexidade: str = "intermediaria"
    perguntas_abertas: list[str] = Field(default_factory=list)
    origem: str = "heuristica"  # nome do executor, ou "heuristica"
    fallback_reason: str = ""

    # Tela 03 (Cadastro de demanda completo, wf §5.2, ADR-0039) — preenchidos
    # manualmente no formulário, NÃO pelo agente de triagem (fora do vocabulário
    # de `_TRIAGE_SYSTEM` acima): a triagem interpreta texto livre para os campos
    # de decisão; estes são informação estrutural que só o solicitante sabe.
    solicitante: str = ""
    # Canal/fonte da demanda (ex.: "ticket #123", "reunião de sprint") — distinto
    # de `origem` acima, que é técnico (nome do executor que triou, ou "heuristica").
    origem_da_demanda: str = ""
    sistemas_afetados: list[str] = Field(default_factory=list)
    apis_afetadas: list[str] = Field(default_factory=list)
    banco_de_dados_afetado: list[str] = Field(default_factory=list)
    infraestrutura_afetada: list[str] = Field(default_factory=list)
    dependencias_conhecidas: list[str] = Field(default_factory=list)
    restricoes: list[str] = Field(default_factory=list)
    evidencias_esperadas: list[str] = Field(default_factory=list)
    # Força aprovação humana independente do que o motor decidiria sozinho — mesmo
    # efeito que `RoutingRuleAction.aprovacao_humana` já tem (ADR-0028), agora
    # acionável por demanda individual, não só por regra de sistema.
    aprovacao_humana_obrigatoria: bool = False
    # Sem nenhum uso no motor hoje (nenhum gate/freio lê isto) — inerte de
    # propósito: documentado assim em vez de fingir um efeito que não existe
    # (mesma honestidade da ausência de "variação" no Dashboard, ADR-0037).
    prazo: str | None = None

    def to_decision_input(self, user_request: str) -> DecisionInput:
        """Traduz a ficha para a entrada do motor de decisão.

        `parallelizable` e `needs_independent_review` são derivados aqui — não são
        perguntados ao agente, porque são decisões de estratégia do runtime, não fatos
        sobre a demanda. Sem nenhum domínio informado, cai em `["backend"]`: é o
        comportamento de hoje, o que garante que a ficha vazia não regride nada.
        """
        dominios = list(self.dominios) or ["backend"]
        impactos = set(self.impactos)
        # Domínios independentes só rodam em paralelo se não houver contrato/arquitetura
        # compartilhados a coordenar entre eles.
        parallelizable = len(dominios) > 1 and not (impactos & {"architecture", "contract"})
        needs_independent_review = (
            self.risco in (RiskLevel.HIGH, RiskLevel.CRITICAL) or "security" in impactos
        )
        return DecisionInput(
            user_request=user_request,
            risk_level=self.risco,
            domains=dominios,
            parallelizable=parallelizable,
            needs_independent_review=needs_independent_review,
            impacts=list(self.impactos),
            tipo=self.tipo,
            complexidade=self.complexidade,
        )


class TriageService:
    """Produz um `DemandBrief` a partir do texto livre da demanda."""

    def __init__(
        self, catalog: ExecutorCatalog | None = None, *, timeout: float = TIMEOUT_PADRAO
    ) -> None:
        self._catalog = catalog
        self._timeout = timeout

    def analisar(self, assignment: AgentAssignment | None, *, user_request: str) -> DemandBrief:
        """Ficha da demanda. Sem agente configurado (ou com falha), usa a heurística."""
        base = _heuristica(user_request)
        if assignment is None or self._catalog is None:
            return base
        try:
            bruto = self._perguntar(assignment, user_request)
        except ERROS_DE_AGENTE as exc:
            return base.model_copy(update={"fallback_reason": f"{type(exc).__name__}: {exc}"[:200]})
        ficha = _sanear(bruto)
        if ficha is None:
            return base.model_copy(
                update={"fallback_reason": "resposta do agente sem campos utilizáveis"}
            )
        return ficha.model_copy(update={"origem": assignment.executor})

    def _perguntar(self, assignment: AgentAssignment, user_request: str) -> dict[str, object]:
        assert self._catalog is not None  # noqa: S101 - garantido pelo chamador
        pedido = f"Demanda:\n{user_request}\n\nProduza a ficha JSON."
        return perguntar_ao_agente(
            self._catalog,
            assignment,
            system=_TRIAGE_SYSTEM,
            pedido=pedido,
            kind="triagem",
            timeout=self._timeout,
        )


# ---------------------------------------------------------------- fallback heurístico

_MIN_CHARS_UTEIS = 40

_RISK_RANK = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2, RiskLevel.CRITICAL: 3}


def _eleva(atual: RiskLevel, minimo: RiskLevel) -> RiskLevel:
    """Sobe o risco para `minimo` se ele for maior que o atual; nunca desce."""
    return minimo if _RISK_RANK[minimo] > _RISK_RANK[atual] else atual


def _normalizar(texto: str) -> str:
    """Minúsculas sem acento, para casar palavra-chave sem depender de ortografia."""
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii").lower()


def _heuristica(user_request: str) -> DemandBrief:
    """Classifica a demanda por palavra-chave — sem I/O, sem LLM, nunca falha.

    Sem nenhum sinal no texto: `dominios=["backend"]`, `risco=LOW` — o comportamento de
    hoje. É o que garante que o fallback não regride nada.
    """
    texto = _normalizar(user_request)
    tipo = "funcionalidade"
    dominios: list[str] = []
    impactos: list[str] = []
    risco = RiskLevel.LOW

    if any(p in texto for p in ("corrigir", "bug", "erro", "falha", "quebrado")):
        tipo = "correcao"
    if any(p in texto for p in ("banco", "tabela", "migration", "schema", "sql")):
        dominios.append("database")
        impactos.append("database")
    if any(p in texto for p in ("api", "endpoint", "contrato", "rota")):
        dominios.append("contract")
        impactos.append("contract")
    if any(
        p in texto for p in ("login", "senha", "token", "permissao", "seguranca", "autenticacao")
    ):
        dominios.append("security")
        impactos.append("security")
        risco = _eleva(risco, RiskLevel.HIGH)
    if any(p in texto for p in ("deploy", "publicar", "producao")):
        impactos.append("deploy")
    if any(p in texto for p in ("tela", "ui", "front", "componente", "css")):
        dominios.append("frontend")
    if any(p in texto for p in ("teste", "cobertura")):
        dominios.append("tests")
    if any(p in texto for p in ("documentar", "readme", "docs")):
        dominios.append("docs")
        tipo = "documentacao"
    if any(p in texto for p in ("arquitetura", "refatorar", "reestruturar")):
        impactos.append("architecture")
        risco = _eleva(risco, RiskLevel.MEDIUM)

    perguntas: list[str] = []
    if not tem_texto_util(user_request) or len(texto.strip()) < _MIN_CHARS_UTEIS:
        perguntas = [
            "Qual é o objetivo final desta demanda?",
            "Qual é o resultado esperado, em termos observáveis?",
            "Quais módulos ou áreas do sistema são afetados?",
        ]

    return DemandBrief(
        tipo=tipo,
        dominios=dominios or ["backend"],
        impactos=sorted(set(impactos)),
        risco=risco,
        perguntas_abertas=perguntas,
        origem="heuristica",
    )


# --------------------------------------------------------------------- saneamento


def _lista_texto(valor: object, *, limite: int = 10) -> list[str]:
    if not isinstance(valor, list):
        return []
    return [str(v).strip() for v in valor if str(v).strip()][:limite]


def _lista_saneada(valor: object, validos: frozenset[str]) -> list[str]:
    """Descarta rótulo fora do vocabulário do decision_engine — nunca propaga lixo."""
    return [v for v in _lista_texto(valor) if v in validos]


def _risco_valido(valor: object) -> RiskLevel:
    try:
        return RiskLevel(str(valor))
    except ValueError:
        return RiskLevel.LOW


def _sanear(bruto: dict[str, object]) -> DemandBrief | None:
    """Aceita a resposta do agente só depois de validar contra o vocabulário fechado.

    Devolve `None` quando não sobra nenhum campo de conteúdo utilizável — aí quem chama
    cai no fallback heurístico com o motivo registrado.
    """
    tipo = str(bruto.get("tipo") or "").strip().lower()
    if tipo not in _TIPOS_VALIDOS:
        tipo = "funcionalidade"
    complexidade = str(bruto.get("complexidade") or "").strip().lower()
    if complexidade not in _COMPLEXIDADES_VALIDAS:
        complexidade = "intermediaria"
    dominios = _lista_saneada(bruto.get("dominios"), _DOMINIOS_VALIDOS)
    impactos = _lista_saneada(bruto.get("impactos"), _IMPACTOS_VALIDOS)
    objetivo = str(bruto.get("objetivo") or "").strip()
    problema = str(bruto.get("problema") or "").strip()
    resultado = str(bruto.get("resultado_esperado") or "").strip()
    if not (objetivo or problema or resultado or dominios or impactos):
        return None
    return DemandBrief(
        tipo=tipo,
        objetivo=objetivo,
        problema=problema,
        resultado_esperado=resultado,
        modulos_afetados=_lista_texto(bruto.get("modulos_afetados")),
        dominios=dominios or ["backend"],
        impactos=impactos,
        riscos=_lista_texto(bruto.get("riscos")),
        criterios_de_aceite=_lista_texto(bruto.get("criterios_de_aceite")),
        risco=_risco_valido(bruto.get("risco")),
        complexidade=complexidade,
        perguntas_abertas=_lista_texto(bruto.get("perguntas_abertas")),
    )
