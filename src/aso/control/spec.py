"""SpecService — especificação da solução (§5 do fluxo.md, ADR-0021).

Espelha `aso.control.discovery` (o exemplar mais recente e já validado): agente (LLM
ou CLI, via `ExecutorCatalog`) que responde em JSON saneado, com fallback
determinístico que nunca falha. Diferença central: gerar spec **exige um discovery
aprovado** (§5: "Com o discovery aprovado") — sem ele, `especificar` recusa com uma
mensagem clara, porque é regra do fluxo, não detalhe de implementação.

Os artefatos opcionais do §5 (diagrama de componentes, diagrama de fluxo, modelo de
dados, contrato de API, plano de migração) são **conteúdo, não estrutura**: o agente
é instruído a colocá-los em Markdown dentro de `componentes`/`alteracoes_banco`/
`alteracoes_infra` — não ganham onze campos novos (ADR-0021).

A especificação nunca sai daqui já `aprovada` (nem vinda de agente, nem do
fallback): §6 exige revisão documental antes da implementação, sempre.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from aso.control.agent_ask import ERROS_DE_AGENTE, perguntar_ao_agente
from aso.control.discovery import STATUS_APROVADO as DISCOVERY_APROVADO
from aso.control.discovery import DiscoveryReport
from aso.control.models import AgentAssignment
from aso.control.triage import DemandBrief
from aso.execution.catalog import ExecutorCatalog
from aso.shared.ids import now_iso

TIMEOUT_PADRAO = 120.0  # especificar é mais caro que discovery: mais campos, mais contexto

STATUS_RASCUNHO = "rascunho"
STATUS_AGUARDANDO_REVISAO = "aguardando_revisao"
STATUS_APROVADO = "aprovado"
STATUS_APROVADO_COM_OBSERVACOES = "aprovado_com_observacoes"
STATUS_REPROVADO = "reprovado"
STATUS_NECESSITA_HUMANO = "necessita_humano"

# Os dois desfechos do §6 que liberam a implementação — `aprovado_com_observacoes`
# fecha o ciclo como `aprovado_com_sugestoes` fecha o code review (ADR-0017).
STATUS_APROVADOS = frozenset({STATUS_APROVADO, STATUS_APROVADO_COM_OBSERVACOES})

_SPEC_SYSTEM = (
    "Você especifica a solução de uma demanda já investigada (§5 do fluxo.md).\n"
    "Responda SOMENTE com um objeto JSON válido, sem cercas de código, na forma:\n"
    '{"o_que_sera_construido": "...", "fora_de_escopo": ["..."], "como_funciona": "...",\n'
    ' "criterios_de_aceite": ["..."], "regras_de_negocio": ["..."], "componentes": ["..."],\n'
    ' "alteracoes_codigo": ["..."], "alteracoes_banco": ["..."], "alteracoes_infra": ["..."],\n'
    ' "estrategia_de_testes": "...", "estrategia_de_implantacao": "...",\n'
    ' "plano_de_rollback": "...", "checklist_seguranca": ["..."],\n'
    ' "itens_de_trabalho": [{"titulo": "...", "descricao": "...", "fase": "F5",\n'
    '   "dominio": "backend", "tipo": "Task", "criterios_de_aceite": ["..."],\n'
    '   "depende_de": ["..."], "itens_filhos": [{"titulo": "...", "tipo": "Task", ...}]}]}\n'
    "Tudo em português do Brasil. `fora_de_escopo` é o campo que mais economiza "
    "retrabalho — não deixe vazio sem justificar por quê. Diagramas de componentes/"
    "fluxo, modelo de dados, contrato de API e plano de migração (quando existirem) "
    "vão em Markdown dentro de `componentes`/`alteracoes_banco`/`alteracoes_infra` — "
    "não invente campos novos. `estrategia_de_testes` e `plano_de_rollback` são "
    "obrigatórios: uma especificação sem eles é reprovada antes mesmo de um revisor "
    "olhar. Em `itens_de_trabalho`, `depende_de` referencia o TÍTULO de um irmão desta "
    "mesma lista, nunca um id. `tipo` aceita Epic|Feature|Task — use Epic/Feature só "
    "quando o item tiver `itens_filhos` (um único nível: história com subtarefas, não "
    "subtarefas com subtarefas)."
)


class SpecWorkItem(BaseModel):
    """Item de trabalho derivado da spec — vira card com dependências (§7/§10)."""

    titulo: str
    descricao: str = ""
    fase: str = "F5"
    dominio: str = "backend"
    # Tipo do card (§16.4/§7, ADR-0025) — "Epic"/"Feature" quando o item tem
    # `itens_filhos`; "Task" (default) é o de sempre, o único que existia até aqui.
    tipo: str = "Task"
    criterios_de_aceite: list[str] = Field(default_factory=list)
    depende_de: list[str] = Field(default_factory=list)  # títulos de irmãos (mesmo nível)
    # Hierarquia épico → história → subtarefa (§7, ADR-0025) — só um nível: cada
    # item pode ter filhos diretos, mas o runtime não desce além disso (profundidade
    # é aplicada por `BoardService.add_card`, não aqui).
    itens_filhos: list[SpecWorkItem] = Field(default_factory=list)


class SpecDocument(BaseModel):
    """A especificação da solução (§5 do fluxo.md) + o estado do ciclo do §6."""

    o_que_sera_construido: str = ""
    fora_de_escopo: list[str] = Field(default_factory=list)
    como_funciona: str = ""
    criterios_de_aceite: list[str] = Field(default_factory=list)
    regras_de_negocio: list[str] = Field(default_factory=list)
    componentes: list[str] = Field(default_factory=list)
    alteracoes_codigo: list[str] = Field(default_factory=list)
    alteracoes_banco: list[str] = Field(default_factory=list)
    alteracoes_infra: list[str] = Field(default_factory=list)
    estrategia_de_testes: str = ""
    estrategia_de_implantacao: str = ""
    plano_de_rollback: str = ""
    checklist_seguranca: list[str] = Field(default_factory=list)
    itens_de_trabalho: list[SpecWorkItem] = Field(default_factory=list)
    # Versão dentro do ring (§4.2 do plano4.md, ADR-0021) — 1-based, monotônica.
    versao: int = 1
    status: str = STATUS_RASCUNHO
    revisao_comentarios: str = ""
    # Rodadas de revisão documental já consumidas por este ciclo (carregado entre
    # regenerações pelo chamador) — cap em `ASO_MAX_RODADAS_DOC` (§4.4).
    rodadas_revisao: int = 0
    origem: str = "heuristica"  # nome do executor, ou "heuristica"
    fallback_reason: str = ""
    at: str = Field(default_factory=now_iso)


class SpecService:
    """Produz um `SpecDocument` a partir do discovery aprovado e da ficha da demanda."""

    def __init__(
        self, catalog: ExecutorCatalog | None = None, *, timeout: float = TIMEOUT_PADRAO
    ) -> None:
        self._catalog = catalog
        self._timeout = timeout

    def especificar(
        self,
        assignment: AgentAssignment | None,
        *,
        demand_brief: DemandBrief,
        discovery: DiscoveryReport,
        comentarios_anteriores: str = "",
    ) -> SpecDocument:
        """Especificação da solução. Recusa (`ValueError`) sem discovery aprovado (§5)."""
        if discovery.status != DISCOVERY_APROVADO:
            raise ValueError(
                "Especificação exige discovery aprovado (§5 do fluxo.md) — "
                f"status atual: '{discovery.status or 'nunca rodado'}'."
            )
        base = _heuristica(demand_brief, discovery)
        if assignment is None or self._catalog is None:
            return base
        try:
            bruto = self._perguntar(
                assignment,
                demand_brief=demand_brief,
                discovery=discovery,
                comentarios_anteriores=comentarios_anteriores,
            )
        except ERROS_DE_AGENTE as exc:
            return base.model_copy(update={"fallback_reason": f"{type(exc).__name__}: {exc}"[:200]})
        spec = _sanear(bruto)
        if spec is None:
            return base.model_copy(
                update={"fallback_reason": "resposta do agente sem campos utilizáveis"}
            )
        return spec.model_copy(update={"origem": assignment.executor})

    def _perguntar(
        self,
        assignment: AgentAssignment,
        *,
        demand_brief: DemandBrief,
        discovery: DiscoveryReport,
        comentarios_anteriores: str,
    ) -> dict[str, object]:
        assert self._catalog is not None  # noqa: S101 - garantido pelo chamador
        pedido = _montar_pedido(demand_brief, discovery, comentarios_anteriores)
        return perguntar_ao_agente(
            self._catalog,
            assignment,
            system=_SPEC_SYSTEM,
            pedido=pedido,
            kind="especificacao",
            timeout=self._timeout,
        )


def _montar_pedido(
    demand_brief: DemandBrief, discovery: DiscoveryReport, comentarios_anteriores: str
) -> str:
    partes = [
        f"Problema: {demand_brief.problema or '(vazio)'}",
        f"Resultado esperado: {demand_brief.resultado_esperado or '(vazio)'}",
        f"Discovery aprovado — situação atual: {discovery.situacao_atual or '(vazio)'}; "
        f"recomendação técnica: {discovery.recomendacao_tecnica or '(vazio)'}; "
        f"componentes afetados: {', '.join(discovery.componentes_afetados) or '(nenhum)'}; "
        f"riscos: {', '.join(discovery.riscos) or '(nenhum)'}; "
        f"restrições: {', '.join(discovery.restricoes) or '(nenhuma)'}.",
    ]
    if comentarios_anteriores:
        partes.append(
            f"Uma versão anterior desta especificação foi reprovada com o comentário: "
            f'"{comentarios_anteriores}" — ajuste o documento considerando isto.'
        )
    partes.append("Produza a especificação em JSON.")
    return "\n\n".join(partes)


def _heuristica(demand_brief: DemandBrief, discovery: DiscoveryReport) -> SpecDocument:
    """Esqueleto determinístico a partir do brief e do discovery — nunca falha, nunca
    aprovado (sem agente de verdade, a especificação é só um resumo do que já se
    sabia, e ainda precisa passar pela revisão documental do §6)."""
    return SpecDocument(
        o_que_sera_construido=discovery.recomendacao_tecnica or demand_brief.objetivo,
        como_funciona=discovery.situacao_atual,
        criterios_de_aceite=list(demand_brief.criterios_de_aceite),
        componentes=list(discovery.componentes_afetados),
        status=STATUS_AGUARDANDO_REVISAO,
        origem="heuristica",
    )


# --------------------------------------------------------------------- saneamento


def _lista_texto(valor: object, *, limite: int = 20) -> list[str]:
    if not isinstance(valor, list):
        return []
    return [str(v).strip() for v in valor if str(v).strip()][:limite]


def _sanear_itens(valor: object) -> list[SpecWorkItem]:
    """Aceita itens de trabalho saneando `depende_de` contra os títulos vistos —
    dependência apontando para um irmão inexistente é descartada, nunca propagada."""
    if not isinstance(valor, list):
        return []
    titulos_vistos: set[str] = set()
    resultado: list[SpecWorkItem] = []
    for item in valor[:30]:
        if not isinstance(item, dict):
            continue
        titulo = str(item.get("titulo") or "").strip()
        if not titulo:
            continue
        titulos_vistos.add(titulo)
        resultado.append(
            SpecWorkItem(
                titulo=titulo,
                descricao=str(item.get("descricao") or "").strip(),
                fase=str(item.get("fase") or "F5").strip() or "F5",
                dominio=str(item.get("dominio") or "backend").strip() or "backend",
                tipo=str(item.get("tipo") or "Task").strip() or "Task",
                criterios_de_aceite=_lista_texto(item.get("criterios_de_aceite")),
                depende_de=_lista_texto(item.get("depende_de")),
                # Só um nível (§7, ADR-0025): não recorre em `itens_filhos` do filho —
                # a mesma função aceita a lista, mas quem consome (`_materialize_spec_cards`)
                # também não desce além do primeiro nível.
                itens_filhos=_sanear_itens(item.get("itens_filhos")),
            )
        )
    for item in resultado:
        item.depende_de = [d for d in item.depende_de if d in titulos_vistos and d != item.titulo]
    return resultado


def _sanear(bruto: dict[str, object]) -> SpecDocument | None:
    """Aceita a resposta do agente. Devolve `None` quando não sobra nenhum campo de
    conteúdo utilizável — aí quem chama cai no fallback heurístico."""
    construir = str(bruto.get("o_que_sera_construido") or "").strip()
    funciona = str(bruto.get("como_funciona") or "").strip()
    fora = _lista_texto(bruto.get("fora_de_escopo"))
    criterios = _lista_texto(bruto.get("criterios_de_aceite"))
    componentes = _lista_texto(bruto.get("componentes"))
    if not (construir or funciona or fora or criterios or componentes):
        return None
    return SpecDocument(
        o_que_sera_construido=construir,
        fora_de_escopo=fora,
        como_funciona=funciona,
        criterios_de_aceite=criterios,
        regras_de_negocio=_lista_texto(bruto.get("regras_de_negocio")),
        componentes=componentes,
        alteracoes_codigo=_lista_texto(bruto.get("alteracoes_codigo")),
        alteracoes_banco=_lista_texto(bruto.get("alteracoes_banco")),
        alteracoes_infra=_lista_texto(bruto.get("alteracoes_infra")),
        estrategia_de_testes=str(bruto.get("estrategia_de_testes") or "").strip(),
        estrategia_de_implantacao=str(bruto.get("estrategia_de_implantacao") or "").strip(),
        plano_de_rollback=str(bruto.get("plano_de_rollback") or "").strip(),
        checklist_seguranca=_lista_texto(bruto.get("checklist_seguranca")),
        itens_de_trabalho=_sanear_itens(bruto.get("itens_de_trabalho")),
        status=STATUS_AGUARDANDO_REVISAO,
    )
