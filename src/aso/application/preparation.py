"""`PreparationService` — discovery, especificação e documentos (ADR-0066).

MEL-32, passo 5: discovery e aprovação (ADR-0020/0045), especificação e revisão documental
(ADR-0021), documentos versionados com comentários e materialização da spec em cards.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from aso.application.bundles import BundleStore, OrchestrationBundle
from aso.application.delivery import DeliveryService
from aso.control.discovery import (
    STATUS_AGUARDANDO_APROVACAO,
    STATUS_APROVADO,
    STATUS_REPROVADO,
    DiscoveryReport,
    DiscoveryService,
    avaliar_criterios_aprovacao,
    exige_aprovacao_discovery,
)
from aso.control.documento import ROTULOS as DOCUMENTO_ROTULOS
from aso.control.documento import (
    SEVERIDADES_COMENTARIO_VALIDAS,
    TIPOS_COMENTARIO_VALIDOS,
    TIPOS_DA_ESPECIFICACAO,
    DocumentComment,
    Documento,
    DocumentoError,
    diff_versoes,
)
from aso.control.documento import TIPOS_VALIDOS as DOCUMENTO_TIPOS_VALIDOS
from aso.control.documentos import acrescentar_versao, proxima_versao, versao_atual
from aso.control.models import DISCOVERY_KEY, SPEC_KEY, AgentAssignment, Orchestration
from aso.control.review import VEREDITO_DOC_REPROVADO, ReviewService
from aso.control.spec import STATUS_AGUARDANDO_REVISAO as SPEC_STATUS_AGUARDANDO_REVISAO
from aso.control.spec import STATUS_APROVADO as SPEC_STATUS_APROVADO
from aso.control.spec import STATUS_APROVADOS as SPEC_STATUS_APROVADOS
from aso.control.spec import STATUS_NECESSITA_HUMANO as SPEC_STATUS_NECESSITA_HUMANO
from aso.control.spec import STATUS_REPROVADO as SPEC_STATUS_REPROVADO
from aso.control.spec import SpecDocument, SpecService, SpecWorkItem
from aso.control.triage import DemandBrief
from aso.execution.catalog import ExecutorCatalog
from aso.execution.repositorio_leitura import AcessoAoRepositorio
from aso.execution.workspace import WorkspaceAnalyzer, WorkspaceService
from aso.kanban.models import KanbanCard
from aso.shared.ids import now_iso
from aso.shared.types import AssigneeType, CardType, ColumnKey, Phase, RiskLevel


def prioridade_de(brief: DemandBrief) -> RiskLevel:
    """A prioridade do card acompanha o risco da demanda — hoje ela é sempre MEDIUM.

    `DemandBrief.risco` já usa `RiskLevel`, o mesmo tipo de `KanbanCard.priority`.
    """
    return brief.risco


def _tipo_de_card(valor: str) -> CardType:
    """Converte o `tipo`/`type` de um item de plano/spec num `CardType` (§7,
    ADR-0025) — valor desconhecido cai em `TASK`, o mesmo comportamento que todo
    caminho de criação de card tinha antes desta ADR."""
    try:
        return CardType(valor)
    except ValueError:
        return CardType.TASK


# Domínio (ficha da demanda / spec) → agente do registro. Reaproveitado por
# `populate_from_plan` (backlog do LLM, M2) e `_materialize_spec_cards` (itens de
# trabalho da especificação, §5/§7/§10 do fluxo.md, ADR-0021) — mesmo vocabulário.
_DOMAIN_AGENTS: dict[str, str] = {
    "backend": "BackendDevelopmentAgent",
    "frontend": "FrontendDevelopmentAgent",
    "architecture": "ArchitectureDesignAgent",
    "contract": "DataApiContractsAgent",
    "database": "DatabaseAgent",
    "tests": "TestingAgent",
    "qa": "TestingAgent",
    "docs": "DocumentationAgent",
    "devops": "DevOpsAgent",
    "security": "SecurityAgent",
}


class PreparationService:
    """Preparação da demanda: discovery, especificação, documentos e revisão documental."""

    def __init__(
        self,
        store: BundleStore,
        *,
        discovery: DiscoveryService,
        spec: SpecService,
        review: ReviewService,
        delivery: DeliveryService,
        max_rodadas_doc: int,
        catalogo: Callable[[], ExecutorCatalog | None],
        assignment: Callable[[OrchestrationBundle, str | None], AgentAssignment | None],
        max_tentativas_da_regra: Callable[..., int | None],
        perguntar_registrando: Callable[..., Any],
    ) -> None:
        self._bundle_store = store
        self._discovery = discovery
        self._spec = spec
        self._review = review
        self._delivery = delivery
        self._max_rodadas_doc = max_rodadas_doc
        self._catalogo = catalogo
        self._assignment_de = assignment
        self._max_tentativas_de = max_tentativas_da_regra
        self._perguntar = perguntar_registrando

    @property
    def _catalog(self) -> ExecutorCatalog | None:
        return self._catalogo()

    def _bundle(self, orchestration_id: str) -> OrchestrationBundle:
        return self._bundle_store.get(orchestration_id)

    def _persist(self, b: OrchestrationBundle) -> None:
        self._bundle_store.persist(b)

    def _lock_for(self, orchestration_id: str) -> threading.RLock:
        return self._bundle_store.lock_for(orchestration_id)

    def _assignment(self, b: OrchestrationBundle, key: str | None) -> AgentAssignment | None:
        return self._assignment_de(b, key)

    def _max_tentativas_da_regra(self, *args: Any, **kwargs: Any) -> int | None:
        return self._max_tentativas_de(*args, **kwargs)

    def _resolve_reviewer(self, *args: Any, **kwargs: Any) -> Any:
        return self._delivery._resolve_reviewer(*args, **kwargs)

    def _perguntar_registrando(self, *args: Any, **kwargs: Any) -> Any:
        return self._perguntar(*args, **kwargs)

    # ------------------------------------------------- discovery e aprovação (§3/§4)
    def _discovery_executor(
        self, explicit: str | None, assignment: AgentAssignment | None
    ) -> str | None:
        """Ordem de resolução do agente de discovery: parâmetro explícito → etapa
        'discovery' configurada → default do catálogo → heurística (`None`)."""
        if explicit:
            return explicit
        if assignment is not None:
            return assignment.executor
        if self._catalog is not None:
            return self._catalog.default_name()
        return None

    def run_discovery(
        self, orchestration_id: str, *, executor: str | None = None, effort: str | None = None
    ) -> Orchestration:
        """Roda o discovery (§3) e aplica a regra de aprovação automática/humana (§4).

        Reexecutar depois de uma reprovação acrescenta uma NOVA versão ao ring (§4.2,
        ADR-0021) — o comentário da reprovação anterior entra no pedido ao agente
        (ADR-0020), para ele ajustar o documento e submeter de novo (mesmo mecanismo
        do §4), e sobrevive como histórico consultável, não só no prompt seguinte.
        """
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            tp = b.orchestration.target_path
            if not tp:
                raise ValueError("Discovery exige uma pasta de trabalho (target_path) definida.")
            ws = WorkspaceService()
            root = ws.validate(tp)
            workspace_report = WorkspaceAnalyzer(ws).analyze(root)
            brief = DemandBrief.model_validate(b.orchestration.demand_brief)
            anterior = versao_atual(b.orchestration.discovery_reports, DiscoveryReport)
            comentarios = (
                anterior.revisao_comentarios if anterior.status == STATUS_REPROVADO else ""
            )
            assignment_ref = self._assignment(b, DISCOVERY_KEY)
            nome = self._discovery_executor(executor, assignment_ref)
            efetivo_effort = effort or (assignment_ref.effort if assignment_ref else None)
            assignment = AgentAssignment(executor=nome, effort=efetivo_effort) if nome else None
            report = self._perguntar_registrando(
                b.orchestration.id,
                None,
                lambda: self._discovery.investigar(
                    assignment,
                    user_request=b.orchestration.user_request,
                    demand_brief=brief,
                    workspace_report=workspace_report,
                    comentarios_anteriores=comentarios,
                    # O agente CLI lê um checkout de leitura da pasta (ADR-0069).
                    repositorio=AcessoAoRepositorio(caminho=str(root)),
                ),
            )
            report.status = (
                STATUS_AGUARDANDO_APROVACAO
                if exige_aprovacao_discovery(report, brief)
                else STATUS_APROVADO
            )
            report.versao = proxima_versao(b.orchestration.discovery_reports)
            b.orchestration.discovery_reports = acrescentar_versao(
                b.orchestration.discovery_reports, report
            )
            b.orchestration.updated_at = now_iso()
            b.event_log.append(
                "DiscoveryRun",
                {
                    "orchestration_id": orchestration_id,
                    "status": report.status,
                    "origem": report.origem,
                    "versao": report.versao,
                    "acesso_repo": report.acesso_repo,
                },
            )
            self._persist(b)
            return b.orchestration

    def get_discovery_report(self, orchestration_id: str) -> DiscoveryReport:
        """Versão corrente do discovery (vazio = discovery ainda não rodado)."""
        b = self._bundle(orchestration_id)
        return versao_atual(b.orchestration.discovery_reports, DiscoveryReport)

    def get_discovery_history(self, orchestration_id: str) -> list[DiscoveryReport]:
        """Histórico de versões do discovery (§4.2, ADR-0021) — ring de até 5."""
        b = self._bundle(orchestration_id)
        return [DiscoveryReport.model_validate(d) for d in b.orchestration.discovery_reports]

    def get_discovery_approval_criteria(self, orchestration_id: str) -> dict[str, object]:
        """Tela 07 (wf §9, ADR-0045): checklist de critérios + motivos da escalada
        humana, da versão CORRENTE do discovery."""
        b = self._bundle(orchestration_id)
        report = versao_atual(b.orchestration.discovery_reports, DiscoveryReport)
        brief = DemandBrief.model_validate(b.orchestration.demand_brief)
        return avaliar_criterios_aprovacao(report, brief)

    def decide_discovery(
        self,
        orchestration_id: str,
        *,
        approved: bool,
        comentario: str = "",
        actor: str = "system",
    ) -> Orchestration:
        """Decide a aprovação humana do discovery (§4) — ação crítica (regra 4 do
        CLAUDE.md), papel admin checado no handler da API (mesmo padrão de
        `report_review`). Atualiza a versão corrente no lugar — decidir não cria uma
        versão nova, só muda o status da que já existe."""
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            if not b.orchestration.discovery_reports:
                raise KeyError("Nenhum relatório de discovery para decidir.")
            report = versao_atual(b.orchestration.discovery_reports, DiscoveryReport)
            if report.status != STATUS_AGUARDANDO_APROVACAO:
                raise ValueError(
                    f"Discovery não está aguardando aprovação (status={report.status})."
                )
            report.status = STATUS_APROVADO if approved else STATUS_REPROVADO
            report.revisao_comentarios = comentario
            b.orchestration.discovery_reports = [
                *b.orchestration.discovery_reports[:-1],
                report.model_dump(mode="json"),
            ]
            b.orchestration.updated_at = now_iso()
            b.event_log.append(
                "DiscoveryDecided",
                {"orchestration_id": orchestration_id, "approved": approved, "actor": actor},
            )
            self._persist(b)
            return b.orchestration

    # --------------------------------------------- especificação e revisão documental (§5/§6)
    def _spec_executor(
        self, explicit: str | None, assignment: AgentAssignment | None
    ) -> str | None:
        """Ordem de resolução do agente de especificação: parâmetro explícito → etapa
        'especificacao' configurada → default do catálogo → heurística (`None`)."""
        if explicit:
            return explicit
        if assignment is not None:
            return assignment.executor
        if self._catalog is not None:
            return self._catalog.default_name()
        return None

    def run_spec(
        self, orchestration_id: str, *, executor: str | None = None, effort: str | None = None
    ) -> Orchestration:
        """Gera/regenera a especificação (§5) — exige discovery aprovado (`ValueError`
        propagado por `SpecService.especificar`, viram 409 no handler da API)."""
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            discovery = versao_atual(b.orchestration.discovery_reports, DiscoveryReport)
            brief = DemandBrief.model_validate(b.orchestration.demand_brief)
            anterior = versao_atual(b.orchestration.spec_documents, SpecDocument)
            comentarios = (
                anterior.revisao_comentarios if anterior.status == SPEC_STATUS_REPROVADO else ""
            )
            assignment_ref = self._assignment(b, SPEC_KEY)
            nome = self._spec_executor(executor, assignment_ref)
            efetivo_effort = effort or (assignment_ref.effort if assignment_ref else None)
            assignment = AgentAssignment(executor=nome, effort=efetivo_effort) if nome else None
            spec = self._perguntar_registrando(
                b.orchestration.id,
                None,
                lambda: self._spec.especificar(
                    assignment,
                    demand_brief=brief,
                    discovery=discovery,
                    comentarios_anteriores=comentarios,
                ),
            )
            spec.versao = proxima_versao(b.orchestration.spec_documents)
            # Rodadas do ciclo de revisão (§4.4) atravessam regenerações — zeram só
            # quando não há versão anterior (spec gerada pela primeira vez).
            tem_versao_anterior = bool(b.orchestration.spec_documents)
            spec.rodadas_revisao = anterior.rodadas_revisao if tem_versao_anterior else 0
            b.orchestration.spec_documents = acrescentar_versao(
                b.orchestration.spec_documents, spec
            )
            b.orchestration.updated_at = now_iso()
            b.event_log.append(
                "SpecRun",
                {
                    "orchestration_id": orchestration_id,
                    "status": spec.status,
                    "origem": spec.origem,
                    "versao": spec.versao,
                },
            )
            self._persist(b)
            return b.orchestration

    def get_spec(self, orchestration_id: str) -> SpecDocument:
        """Versão corrente da especificação (vazio = ainda não gerada)."""
        b = self._bundle(orchestration_id)
        return versao_atual(b.orchestration.spec_documents, SpecDocument)

    def get_spec_history(self, orchestration_id: str) -> list[SpecDocument]:
        """Histórico de versões da especificação (§4.2, ADR-0021) — ring de até 5."""
        b = self._bundle(orchestration_id)
        return [SpecDocument.model_validate(s) for s in b.orchestration.spec_documents]

    def run_spec_review(
        self, orchestration_id: str, *, executor: str | None = None, actor: str = "system"
    ) -> Orchestration:
        """Roda a revisão documental (§6) sobre a versão corrente da especificação.

        O revisor precisa ser diferente de quem produziu o documento (mesmo princípio
        do §14 aplicado a documentos). Esgotado `ASO_MAX_RODADAS_DOC`, uma reprovação
        vira `necessita_humano` em vez de continuar o ciclo indefinidamente.
        """
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            if not b.orchestration.spec_documents:
                raise KeyError("Nenhuma especificação para revisar.")
            spec = versao_atual(b.orchestration.spec_documents, SpecDocument)
            if spec.status != SPEC_STATUS_AGUARDANDO_REVISAO:
                raise ValueError(
                    f"Especificação não está aguardando revisão (status={spec.status})."
                )
            origem_executor = spec.origem if spec.origem != "heuristica" else None
            revisor, recusa = self._resolve_reviewer(
                b, origem_executor=origem_executor, explicit=executor
            )
            brief = DemandBrief.model_validate(b.orchestration.demand_brief)
            # A checagem determinística (§6: plano de testes/rollback) roda mesmo sem
            # revisor disponível — ela não depende de agente. Só cai no fallback
            # genérico de `recusa` quando o documento passa nela.
            assignment = (
                None if recusa else (AgentAssignment(executor=revisor) if revisor else None)
            )
            doc_verdito = self._perguntar_registrando(
                b.orchestration.id,
                None,
                lambda: self._review.revisar_documento(
                    assignment, documento=spec, tipo=SPEC_KEY, brief=brief
                ),
            )
            if recusa and doc_verdito.origem != "checagem_deterministica":
                doc_verdito = doc_verdito.model_copy(update={"fallback_reason": recusa})
            spec.rodadas_revisao += 1
            veredito = doc_verdito.veredito
            if veredito == VEREDITO_DOC_REPROVADO and spec.rodadas_revisao >= self._max_rodadas_doc:
                veredito = SPEC_STATUS_NECESSITA_HUMANO
            spec.status = veredito
            spec.revisao_comentarios = doc_verdito.resumo or (
                "; ".join(a.descricao for a in doc_verdito.acoes) if doc_verdito.acoes else ""
            )
            b.orchestration.spec_documents = [
                *b.orchestration.spec_documents[:-1],
                spec.model_dump(mode="json"),
            ]
            b.orchestration.updated_at = now_iso()
            cards_criados = (
                self._materialize_spec_cards(b, spec) if veredito in SPEC_STATUS_APROVADOS else []
            )
            b.event_log.append(
                "SpecReviewed",
                {
                    "orchestration_id": orchestration_id,
                    "actor": actor,
                    "veredito": veredito,
                    "revisor": doc_verdito.revisor,
                    "rodadas": spec.rodadas_revisao,
                    "cards_criados": len(cards_criados),
                },
            )
            self._persist(b)
            return b.orchestration

    def approve_spec(
        self,
        orchestration_id: str,
        *,
        approved: bool,
        comentario: str = "",
        actor: str = "system",
    ) -> Orchestration:
        """Decisão humana da especificação quando o ciclo do §6 escalou (§4.4) — ação
        crítica, papel admin checado no handler da API (mesmo padrão de
        `decide_discovery`)."""
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            if not b.orchestration.spec_documents:
                raise KeyError("Nenhuma especificação para decidir.")
            spec = versao_atual(b.orchestration.spec_documents, SpecDocument)
            if spec.status != SPEC_STATUS_NECESSITA_HUMANO:
                raise ValueError(
                    f"Especificação não está aguardando decisão humana (status={spec.status})."
                )
            spec.status = SPEC_STATUS_APROVADO if approved else SPEC_STATUS_REPROVADO
            spec.revisao_comentarios = comentario
            b.orchestration.spec_documents = [
                *b.orchestration.spec_documents[:-1],
                spec.model_dump(mode="json"),
            ]
            b.orchestration.updated_at = now_iso()
            cards_criados = self._materialize_spec_cards(b, spec) if approved else []
            b.event_log.append(
                "SpecDecided",
                {
                    "orchestration_id": orchestration_id,
                    "approved": approved,
                    "actor": actor,
                    "cards_criados": len(cards_criados),
                },
            )
            self._persist(b)
            return b.orchestration

    @staticmethod
    def _validar_tipo_documento(tipo: str) -> None:
        if tipo in DOCUMENTO_TIPOS_VALIDOS:
            return
        if tipo in TIPOS_DA_ESPECIFICACAO:
            raise DocumentoError(
                f"Tipo '{tipo}' é servido pelo fluxo de especificação — edite em /spec."
            )
        raise DocumentoError(f"Tipo de documento inválido: {tipo!r}.")

    def list_documentos(self, orchestration_id: str) -> list[dict[str, object]]:
        """Lista de documentos (wf §10.2: versão/documento/autor/status/ações) — os 8
        tipos novos (ring próprio, editáveis aqui) + os 5 já cobertos por
        `SpecDocument`, mostrados em modo leitura a partir do dado real já existente,
        nunca duplicado (ADR-0046)."""
        b = self._bundle(orchestration_id)
        linhas: list[dict[str, object]] = []
        for tipo in sorted(DOCUMENTO_TIPOS_VALIDOS):
            ring = b.orchestration.documentos.get(tipo, [])
            doc = versao_atual(ring, Documento)
            linhas.append(
                {
                    "tipo": tipo,
                    "rotulo": DOCUMENTO_ROTULOS[tipo],
                    "versao": doc.versao if ring else 0,
                    "autor": doc.autor,
                    "status": doc.status if ring else "nunca_criado",
                    "editavel": True,
                }
            )
        spec = versao_atual(b.orchestration.spec_documents, SpecDocument)
        for tipo, rotulo in TIPOS_DA_ESPECIFICACAO.items():
            linhas.append(
                {
                    "tipo": tipo,
                    "rotulo": rotulo,
                    "versao": spec.versao if b.orchestration.spec_documents else 0,
                    "autor": spec.origem,
                    "status": spec.status if b.orchestration.spec_documents else "nunca_criado",
                    "editavel": False,
                }
            )
        return linhas

    def get_documento(self, orchestration_id: str, tipo: str) -> Documento:
        """Versão corrente de um documento (vazio = nunca criado)."""
        self._validar_tipo_documento(tipo)
        b = self._bundle(orchestration_id)
        return versao_atual(b.orchestration.documentos.get(tipo, []), Documento)

    def get_documento_history(self, orchestration_id: str, tipo: str) -> list[Documento]:
        """Histórico de versões (ring de até 5, wf §10.3 "Histórico de versões")."""
        self._validar_tipo_documento(tipo)
        b = self._bundle(orchestration_id)
        return [Documento.model_validate(d) for d in b.orchestration.documentos.get(tipo, [])]

    def diff_documento(self, orchestration_id: str, tipo: str, *, de: int, para: int) -> list[str]:
        """Comparação de versões (wf §10.3) — diff real via `difflib`, entre duas
        versões existentes no ring."""
        self._validar_tipo_documento(tipo)
        b = self._bundle(orchestration_id)
        ring = b.orchestration.documentos.get(tipo, [])
        por_versao = {int(d.get("versao", 0)): d for d in ring}
        if de not in por_versao or para not in por_versao:
            raise KeyError(f"Versão inexistente no histórico: {de} ou {para}.")
        anterior = Documento.model_validate(por_versao[de])
        atual = Documento.model_validate(por_versao[para])
        return diff_versoes(anterior.conteudo_markdown, atual.conteudo_markdown)

    def save_documento(
        self,
        orchestration_id: str,
        tipo: str,
        *,
        conteudo_markdown: str,
        autor: str,
        referencias_codigo: list[str] | None = None,
        referencias_cards: list[str] | None = None,
        referencias_documentos: list[str] | None = None,
        actor: str = "system",
    ) -> Documento:
        """Salva uma nova versão do documento (edição manual, wf §10.3) — cria o
        próximo item do ring; status volta a `aguardando_revisao`, mesmo vocabulário
        de `SpecDocument` (`control/spec.py`)."""
        self._validar_tipo_documento(tipo)
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            ring = b.orchestration.documentos.get(tipo, [])
            doc = Documento(
                tipo=tipo,
                autor=autor,
                status=SPEC_STATUS_AGUARDANDO_REVISAO,
                conteudo_markdown=conteudo_markdown,
                versao=proxima_versao(ring),
                referencias_codigo=referencias_codigo or [],
                referencias_cards=referencias_cards or [],
                referencias_documentos=referencias_documentos or [],
            )
            b.orchestration.documentos[tipo] = acrescentar_versao(ring, doc)
            b.orchestration.updated_at = now_iso()
            b.event_log.append(
                "DocumentoSalvo",
                {
                    "orchestration_id": orchestration_id,
                    "actor": actor,
                    "tipo": tipo,
                    "versao": doc.versao,
                },
            )
            self._persist(b)
            return doc

    def review_documento(
        self,
        orchestration_id: str,
        tipo: str,
        *,
        executor: str | None = None,
        actor: str = "system",
    ) -> Documento:
        """Checklist do revisor (wf §11) — reaproveita `ReviewService.revisar_documento`/
        `DocReviewVerdict` (ADR-0021): os quatro desfechos do §6 já batem exatamente
        com os quatro do wf §11.2. Fluxo deliberadamente mais simples que o da
        especificação: sem contagem de rodadas nem exigência de revisor diferente do
        autor — os 8 tipos novos são artefatos de apoio, não o gate central de
        qualidade que a spec já é (ADR-0046)."""
        self._validar_tipo_documento(tipo)
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            ring = b.orchestration.documentos.get(tipo, [])
            if not ring:
                raise KeyError(f"Nenhum documento do tipo '{tipo}' para revisar.")
            doc = versao_atual(ring, Documento)
            brief = DemandBrief.model_validate(b.orchestration.demand_brief)
            assignment_ref = self._assignment(b, SPEC_KEY)
            nome = self._spec_executor(executor, assignment_ref)
            assignment = AgentAssignment(executor=nome) if nome else None
            verdito = self._perguntar_registrando(
                b.orchestration.id,
                None,
                lambda: self._review.revisar_documento(
                    assignment, documento=doc, tipo=tipo, brief=brief
                ),
            )
            doc.status = verdito.veredito
            doc.revisao_resumo = verdito.resumo
            doc.revisao_pontos_verificados = verdito.pontos_verificados
            doc.revisor = verdito.revisor
            b.orchestration.documentos[tipo] = [*ring[:-1], doc.model_dump(mode="json")]
            b.orchestration.updated_at = now_iso()
            b.event_log.append(
                "DocumentoRevisado",
                {
                    "orchestration_id": orchestration_id,
                    "actor": actor,
                    "tipo": tipo,
                    "veredito": verdito.veredito,
                },
            )
            self._persist(b)
            return doc

    def list_documento_comments(self, orchestration_id: str, tipo: str) -> list[DocumentComment]:
        self._validar_tipo_documento(tipo)
        b = self._bundle(orchestration_id)
        return [
            DocumentComment.model_validate(c)
            for c in b.orchestration.documento_comentarios
            if c.get("documento_tipo") == tipo
        ]

    def create_documento_comment(
        self,
        orchestration_id: str,
        tipo: str,
        *,
        autor: str,
        tipo_comentario: str,
        severidade: str,
        descricao: str,
        trecho_relacionado: str = "",
        acao_solicitada: str = "",
        actor: str = "system",
    ) -> DocumentComment:
        """Comentário ancorado num documento (wf §10.3/§11.3, ADR-0046) — os 8
        campos literais do wireframe."""
        self._validar_tipo_documento(tipo)
        if tipo_comentario not in TIPOS_COMENTARIO_VALIDOS:
            raise DocumentoError(f"Tipo de comentário inválido: {tipo_comentario!r}.")
        if severidade not in SEVERIDADES_COMENTARIO_VALIDAS:
            raise DocumentoError(f"Severidade inválida: {severidade!r}.")
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            versao_corrente = versao_atual(
                b.orchestration.documentos.get(tipo, []), Documento
            ).versao
            comentario = DocumentComment(
                orchestration_id=orchestration_id,
                documento_tipo=tipo,
                documento_versao=versao_corrente,
                autor=autor,
                tipo=tipo_comentario,
                severidade=severidade,
                trecho_relacionado=trecho_relacionado,
                descricao=descricao,
                acao_solicitada=acao_solicitada,
            )
            b.orchestration.documento_comentarios.append(comentario.model_dump(mode="json"))
            b.orchestration.updated_at = now_iso()
            b.event_log.append(
                "DocumentoComentado",
                {
                    "orchestration_id": orchestration_id,
                    "actor": actor,
                    "tipo": tipo,
                    "comment_id": comentario.id,
                },
            )
            self._persist(b)
            return comentario

    def resolve_documento_comment(
        self,
        orchestration_id: str,
        comment_id: str,
        *,
        resposta_do_autor: str = "",
        actor: str = "system",
    ) -> DocumentComment:
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            bruto = next(
                (c for c in b.orchestration.documento_comentarios if c.get("id") == comment_id),
                None,
            )
            if bruto is None:
                raise KeyError(f"Comentário inexistente: {comment_id}")
            comentario = DocumentComment.model_validate(bruto)
            if comentario.status == "resolvido":
                raise ValueError("Comentário já resolvido.")
            comentario.status = "resolvido"
            comentario.resposta_do_autor = resposta_do_autor
            comentario.resolved_at = now_iso()
            b.orchestration.documento_comentarios = [
                comentario.model_dump(mode="json") if c.get("id") == comment_id else c
                for c in b.orchestration.documento_comentarios
            ]
            b.orchestration.updated_at = now_iso()
            b.event_log.append(
                "DocumentoComentarioResolvido",
                {"orchestration_id": orchestration_id, "actor": actor, "comment_id": comment_id},
            )
            self._persist(b)
            return comentario

    def _materialize_spec_cards(self, b: OrchestrationBundle, spec: SpecDocument) -> list[str]:
        """Cria cards a partir de `spec.itens_de_trabalho` quando a especificação é
        aprovada (§5/§7/§10 do fluxo.md, ADR-0021) — mesmo padrão de
        `populate_from_plan`, com dependências resolvidas numa segunda passada.

        Domínio desconhecido é descartado (não trava a aprovação da spec por isso —
        diferente de `populate_from_plan`, que é síncrono com a criação da
        orquestração e pode recusar sem custo já pago).

        `itens_filhos` (§7, ADR-0025) vira `parent_id` — só um nível: cada item pode
        ter filhos diretos, o runtime não desce além disso. Cards-raiz nascem antes
        dos filhos para que `BoardService.add_card` encontre o pai já cadastrado.
        """
        if not spec.itens_de_trabalho:
            return []
        brief = DemandBrief.model_validate(b.orchestration.demand_brief)
        raizes: list[tuple[SpecWorkItem, KanbanCard]] = []
        filhos: list[tuple[SpecWorkItem, KanbanCard, str]] = []  # item, card, título do pai
        for item in spec.itens_de_trabalho:
            card = self._card_de_spec_item(b, brief, item)
            if card is None:
                continue
            raizes.append((item, card))
            for filho in item.itens_filhos:
                filho_card = self._card_de_spec_item(b, brief, filho)
                if filho_card is not None:
                    filhos.append((filho, filho_card, item.titulo))
        id_por_titulo = {item.titulo: card.id for item, card in raizes}
        id_por_titulo.update({item.titulo: card.id for item, card, _ in filhos})
        criados: list[str] = []
        for item, card in raizes:
            card.dependencies = [
                id_por_titulo[dep] for dep in item.depende_de if dep in id_por_titulo
            ]
            b.board_service.add_card(card)
            criados.append(card.id)
        for item, card, pai_titulo in filhos:
            card.parent_id = id_por_titulo.get(pai_titulo)
            card.dependencies = [
                id_por_titulo[dep] for dep in item.depende_de if dep in id_por_titulo
            ]
            b.board_service.add_card(card)
            criados.append(card.id)
        return criados

    def _card_de_spec_item(
        self, b: OrchestrationBundle, brief: DemandBrief, item: SpecWorkItem
    ) -> KanbanCard | None:
        """Constrói (sem persistir) o card de um item de trabalho da spec — domínio
        desconhecido devolve `None` (descartado pelo chamador)."""
        try:
            phase = Phase(item.fase)
        except ValueError:
            phase = Phase.F5
        assignee = _DOMAIN_AGENTS.get(item.dominio, item.dominio)
        if b.agent_registry.get(assignee) is None:
            return None
        return KanbanCard(
            board_id=b.board.id,
            orchestration_id=b.orchestration.id,
            phase=phase,
            type=_tipo_de_card(item.tipo),
            title=item.titulo,
            description=item.descricao,
            priority=prioridade_de(brief),
            assignee_type=AssigneeType.AGENT,
            assignee=assignee,
            status=ColumnKey.READY,
            acceptance_criteria=list(item.criterios_de_aceite),
            max_tentativas=self._max_tentativas_da_regra(b.orchestration),
        )
