"""`ReleaseService` — implantação, rollback e incidentes (ADR-0066).

MEL-32, passo 6b: implantação governada e pipeline (ADR-0023/0029), validação pós-implantação,
aceite, rollback de deploy e incidentes (ADR-0050).
"""

from __future__ import annotations

import os
import threading
from typing import Any

from aso.application.bundles import BundleStore, OrchestrationBundle
from aso.control.deploy import (
    ACEITE_AGUARDANDO_HUMANO,
    ACEITE_APROVADO,
    ACEITE_REPROVADO,
    STATUS_FALHOU,
    STATUS_REVERTIDO,
    STATUS_SUCESSO,
    VALIDACAO_APROVADA,
    VALIDACAO_PENDENTE,
    VALIDACAO_REPROVADA,
    DeployRun,
    avaliacao_de_risco_implantacao,
    checklist_aprovacao_implantacao,
    checklist_rollback,
    classificar_falha_deploy,
    decisao_sugerida_pos_deploy,
    executar_deploy,
    exige_aceite_humano,
    pode_avancar_estagio,
    proxima_acao_deploy,
    proximo_estagio_pendente,
    saude_pos_deploy,
    status_do_pipeline,
    validar_pos_deploy,
)
from aso.control.documentos import acrescentar_versao, proxima_versao, versao_atual
from aso.control.models import Environment, Orchestration, ValidationCheck
from aso.control.triage import DemandBrief
from aso.execution.gate_validation import validate_gate_command
from aso.governance.models import Incident, IncidentTimelineEntry
from aso.kanban.models import KanbanCard
from aso.shared.ids import now_iso
from aso.shared.types import CardType, ColumnKey, GateStatus, RiskLevel


def _estagio_configurado(pipeline: list[dict[str, Any]], chave: str) -> dict[str, Any] | None:
    """Busca a configuração bruta (dict) de um estágio pelo `chave` no pipeline
    (§19, ADR-0029) — usado por `validate_deploy`/`rollback_deploy` para resolver a
    precedência "estágio → padrão da orquestração" sem reconstruir `Environment`."""
    return next((e for e in pipeline if e.get("chave") == chave), None)


# Inverso de `_GRAVIDADE_PARA_PRIORIDADE` — deriva a gravidade de um `Incident`
# (§21, ADR-0032) do risco já triado da demanda, em vez de perguntar de novo ou
# inventar um valor fixo. Sem ficha triada, `RiskLevel.LOW` (default do modelo)
# cai em "media" — mesmo comportamento conservador de `QaCheck.gravidade`.
_RISCO_PARA_GRAVIDADE: dict[RiskLevel, str] = {
    RiskLevel.LOW: "media",
    RiskLevel.MEDIUM: "media",
    RiskLevel.HIGH: "alta",
    RiskLevel.CRITICAL: "critica",
}


class ReleaseService:
    """Implantação governada, pipeline por estágio, validação, rollback e incidentes."""

    def __init__(self, store: BundleStore) -> None:
        self._bundle_store = store

    def _bundle(self, orchestration_id: str) -> OrchestrationBundle:
        return self._bundle_store.get(orchestration_id)

    def _persist(self, b: OrchestrationBundle) -> None:
        self._bundle_store.persist(b)

    def _lock_for(self, orchestration_id: str) -> threading.RLock:
        return self._bundle_store.lock_for(orchestration_id)

    # ------------------------------------------ implantação governada (§18-22)
    def set_deploy_config(
        self,
        orchestration_id: str,
        *,
        command: str | None = None,
        environment: str | None = None,
        health_checks: list[ValidationCheck] | None = None,
        rollback_command: str | None = None,
        actor: str = "system",
    ) -> Orchestration:
        """Configura a implantação (ADR-0023) — cada comando passa por
        `validate_gate_command`, mesmo guard de `set_validation_checks`."""
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            antes = {
                "deploy_command": b.orchestration.deploy_command,
                "deploy_environment": b.orchestration.deploy_environment,
                "deploy_health_checks": [
                    c.model_dump(mode="json") for c in b.orchestration.deploy_health_checks
                ],
                "deploy_rollback_command": b.orchestration.deploy_rollback_command,
            }
            if command is not None:
                b.orchestration.deploy_command = validate_gate_command(command) if command else None
            if environment is not None:
                b.orchestration.deploy_environment = environment
            if health_checks is not None:
                b.orchestration.deploy_health_checks = [
                    c.model_copy(update={"comando": validate_gate_command(c.comando)})
                    for c in health_checks
                ]
            if rollback_command is not None:
                b.orchestration.deploy_rollback_command = (
                    validate_gate_command(rollback_command) if rollback_command else None
                )
            depois = {
                "deploy_command": b.orchestration.deploy_command,
                "deploy_environment": b.orchestration.deploy_environment,
                "deploy_health_checks": [
                    c.model_dump(mode="json") for c in b.orchestration.deploy_health_checks
                ],
                "deploy_rollback_command": b.orchestration.deploy_rollback_command,
            }
            b.orchestration.updated_at = now_iso()
            b.event_log.append(
                "DeployConfigUpdated",
                {
                    "orchestration_id": orchestration_id,
                    "actor": actor,
                    "before": antes,
                    "after": depois,
                },
            )
            self._persist(b)
            return b.orchestration

    def set_deploy_pipeline(
        self, orchestration_id: str, pipeline: list[Environment], *, actor: str = "system"
    ) -> Orchestration:
        """Configura o pipeline de estágios (§19, ADR-0029) — cada `comando`/
        `rollback_command`/health check informado passa por `validate_gate_command`,
        mesmo guard de `set_deploy_config`. Lista vazia volta ao monoambiente legado.
        """
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            chaves = [e.chave for e in pipeline]
            if len(chaves) != len(set(chaves)):
                raise ValueError("Estágios com `chave` repetida no pipeline.")
            ordens = [e.ordem for e in pipeline]
            if len(ordens) != len(set(ordens)):
                raise ValueError("Estágios com `ordem` repetida no pipeline.")
            validado: list[Environment] = []
            for estagio in pipeline:
                validado.append(
                    estagio.model_copy(
                        update={
                            "comando": (
                                validate_gate_command(estagio.comando) if estagio.comando else None
                            ),
                            "rollback_command": (
                                validate_gate_command(estagio.rollback_command)
                                if estagio.rollback_command
                                else None
                            ),
                            "health_checks": [
                                c.model_copy(update={"comando": validate_gate_command(c.comando)})
                                for c in estagio.health_checks
                            ],
                        }
                    )
                )
            antes = list(b.orchestration.deploy_pipeline)
            b.orchestration.deploy_pipeline = [e.model_dump(mode="json") for e in validado]
            b.orchestration.updated_at = now_iso()
            b.event_log.append(
                "DeployPipelineConfigured",
                {
                    "orchestration_id": orchestration_id,
                    "actor": actor,
                    "before": antes,
                    "after": b.orchestration.deploy_pipeline,
                },
            )
            self._persist(b)
            return b.orchestration

    def get_deploy_pipeline(self, orchestration_id: str) -> list[dict[str, object]]:
        """Status derivado por estágio (tela 23, wf §25) — lista vazia = monoambiente
        legado, nenhum pipeline configurado."""
        b = self._bundle(orchestration_id)
        if not b.orchestration.deploy_pipeline:
            return []
        pipeline = [Environment(**e) for e in b.orchestration.deploy_pipeline]
        return status_do_pipeline(pipeline, b.orchestration.deploy_runs)

    def run_deploy(
        self,
        orchestration_id: str,
        *,
        environment: str | None = None,
        estagio: str | None = None,
        versao_app: str = "",
        commit: str = "",
        branch: str = "",
        actor: str = "system",
    ) -> DeployRun:
        """§18 (checklist) + §19 (execução). Sempre roda o comando configurado —
        a decisão humana (§18/§22) é sobre ACEITAR o resultado, não sobre
        autorizar a tentativa (mesmo raciocínio de `DiscoveryService.investigar`).

        Com pipeline configurado (`deploy_pipeline` não vazio), `estagio` escolhe
        QUAL estágio roda — omitido, resolve para o primeiro pendente (avanço
        governado, §19: um estágio só roda depois do anterior concluir). Sem
        pipeline (lista vazia, o padrão), `estagio` é ignorado e o comportamento é
        idêntico ao de antes da ADR-0029 — implantação monoambiente.
        """
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            repo = b.orchestration.target_path or os.environ.get("ASO_TARGET_REPO")
            if not repo:
                raise ValueError("Orquestração sem pasta de trabalho (target_path).")
            if not b.gate_results or b.gate_results[-1].status != GateStatus.PASSED:
                raise ValueError(
                    "Quality gate mais recente não passou — rode-o antes de implantar (§18)."
                )

            alvo: Environment | None = None
            comando_efetivo = b.orchestration.deploy_command
            if b.orchestration.deploy_pipeline:
                pipeline = [Environment(**e) for e in b.orchestration.deploy_pipeline]
                if estagio is not None:
                    alvo = next((e for e in pipeline if e.chave == estagio), None)
                    if alvo is None:
                        raise KeyError(f"Estágio '{estagio}' não existe no pipeline.")
                else:
                    alvo = proximo_estagio_pendente(pipeline, b.orchestration.deploy_runs)
                    if alvo is None:
                        raise ValueError("Pipeline já concluído — todos os estágios passaram.")
                if not pode_avancar_estagio(alvo, pipeline, b.orchestration.deploy_runs):
                    raise ValueError(
                        f"Estágio '{alvo.chave}' ainda não pode rodar — "
                        "o estágio anterior não foi concluído (§19)."
                    )
                comando_efetivo = alvo.comando or b.orchestration.deploy_command
            if not comando_efetivo:
                raise ValueError(
                    "Configure o comando de implantação antes (PUT .../deploy/config)."
                )
            ok, logs, duracao = executar_deploy(comando_efetivo, repo)
            brief = DemandBrief.model_validate(b.orchestration.demand_brief)
            ambiente_efetivo = (
                (alvo.nome or alvo.chave)
                if alvo is not None
                else (environment or b.orchestration.deploy_environment)
            )
            deploy = DeployRun(
                ambiente=ambiente_efetivo,
                estagio=alvo.chave if alvo is not None else "",
                versao_app=versao_app,
                commit=commit,
                branch=branch,
                comando=comando_efetivo,
                responsavel=actor,
                status=STATUS_SUCESSO if ok else STATUS_FALHOU,
                logs=logs[:4000],
                resultado=logs[:500],
                duracao_segundos=duracao,
            )
            requer_aprovacao_do_estagio = alvo is not None and alvo.requer_aprovacao_humana
            if not ok:
                deploy.aceite_status = ACEITE_REPROVADO
                deploy.aceite_comentario = "implantação falhou"
                if alvo is not None:
                    diagnostico = classificar_falha_deploy(
                        origem="deploy",
                        estagio_chave=alvo.chave,
                        comando=comando_efetivo,
                        saida=logs,
                    )
                    deploy.diagnostico_falha = diagnostico
                    deploy.proxima_acao_falha = proxima_acao_deploy(diagnostico)
            elif exige_aceite_humano(deploy, brief) or requer_aprovacao_do_estagio:
                deploy.aceite_status = ACEITE_AGUARDANDO_HUMANO
            else:
                deploy.aceite_status = ACEITE_APROVADO
                deploy.origem_decisao = "automatico"
            deploy.versao = proxima_versao(b.orchestration.deploy_runs)
            b.orchestration.deploy_runs = acrescentar_versao(b.orchestration.deploy_runs, deploy)
            b.event_log.append(
                "DeployRun",
                {
                    "orchestration_id": orchestration_id,
                    "status": deploy.status,
                    "ambiente": deploy.ambiente,
                    "estagio": deploy.estagio,
                    "aceite": deploy.aceite_status,
                },
            )
            self._persist(b)
            return deploy

    def get_deploy(self, orchestration_id: str) -> DeployRun:
        b = self._bundle(orchestration_id)
        return versao_atual(b.orchestration.deploy_runs, DeployRun)

    def get_deploy_history(self, orchestration_id: str) -> list[DeployRun]:
        b = self._bundle(orchestration_id)
        return [DeployRun.model_validate(d) for d in b.orchestration.deploy_runs]

    def validate_deploy(self, orchestration_id: str, *, actor: str = "system") -> DeployRun:
        """§20: roda as verificações pós-implantação sobre a última tentativa."""
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            if not b.orchestration.deploy_runs:
                raise KeyError("Nenhuma implantação para validar.")
            repo = b.orchestration.target_path or os.environ.get("ASO_TARGET_REPO")
            if not repo:
                raise ValueError("Orquestração sem pasta de trabalho (target_path).")
            deploy = versao_atual(b.orchestration.deploy_runs, DeployRun)
            # Health checks do estágio (se houver e o estágio definir os próprios)
            # vencem os da orquestração — mesma cadeia "etapa → padrão" do comando.
            health_checks = b.orchestration.deploy_health_checks
            if deploy.estagio and b.orchestration.deploy_pipeline:
                estagio_cfg = _estagio_configurado(b.orchestration.deploy_pipeline, deploy.estagio)
                if estagio_cfg and estagio_cfg.get("health_checks"):
                    health_checks = [ValidationCheck(**c) for c in estagio_cfg["health_checks"]]
            aprovado, resultados = validar_pos_deploy(health_checks, repo)
            deploy.validacao_status = VALIDACAO_APROVADA if aprovado else VALIDACAO_REPROVADA
            deploy.validacao_resultados = resultados
            if not aprovado:
                diagnostico = classificar_falha_deploy(
                    origem="validacao", estagio_chave=deploy.estagio or deploy.ambiente
                )
                deploy.diagnostico_falha = diagnostico
                deploy.proxima_acao_falha = proxima_acao_deploy(diagnostico)
            brief = DemandBrief.model_validate(b.orchestration.demand_brief)
            # Uma validação reprovada pode reverter um aceite já automático — a
            # decisão humana reabre exatamente como no §22.
            if deploy.aceite_status == ACEITE_APROVADO and exige_aceite_humano(deploy, brief):
                deploy.aceite_status = ACEITE_AGUARDANDO_HUMANO
                deploy.origem_decisao = ""
            b.orchestration.deploy_runs = [
                *b.orchestration.deploy_runs[:-1],
                deploy.model_dump(mode="json"),
            ]
            b.event_log.append(
                "DeployValidated",
                {"orchestration_id": orchestration_id, "aprovado": aprovado, "actor": actor},
            )
            self._persist(b)
            return deploy

    def decide_deploy(
        self,
        orchestration_id: str,
        *,
        approved: bool,
        comentario: str = "",
        tipo_aceite: str = "",
        actor: str = "system",
    ) -> DeployRun:
        """§22: aceite final humano, só quando o ciclo automático escalou.

        `tipo_aceite` (Tela 26, wf §28.2, ADR-0050) é opcional — sub-tipo do
        aceite humano (produto/técnico/negócio); vazio = aceite humano
        genérico, sem detalhar. Nunca fabricado quando o operador não informa.
        """
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            if not b.orchestration.deploy_runs:
                raise KeyError("Nenhuma implantação para decidir.")
            deploy = versao_atual(b.orchestration.deploy_runs, DeployRun)
            if deploy.aceite_status != ACEITE_AGUARDANDO_HUMANO:
                raise ValueError(
                    f"Implantação não está aguardando aceite (status={deploy.aceite_status})."
                )
            deploy.aceite_status = ACEITE_APROVADO if approved else ACEITE_REPROVADO
            deploy.aceite_comentario = comentario
            deploy.origem_decisao = "humano"
            deploy.tipo_aceite_humano = tipo_aceite
            b.orchestration.deploy_runs = [
                *b.orchestration.deploy_runs[:-1],
                deploy.model_dump(mode="json"),
            ]
            b.event_log.append(
                "DeployDecided",
                {"orchestration_id": orchestration_id, "approved": approved, "actor": actor},
            )
            self._persist(b)
            return deploy

    def rollback_deploy(
        self, orchestration_id: str, *, reason: str, estrategia: str = "", actor: str = "system"
    ) -> DeployRun:
        """§21: reverte a última implantação e abre uma tarefa de análise de
        causa raiz (CardType.INCIDENT) — o runtime não reverte infraestrutura
        real; roda `deploy_rollback_command` quando configurado (best-effort).

        `estrategia` (Tela 25, wf §27.2, ADR-0050) é descritiva — registra
        qual das 6 estratégias do wireframe o operador escolheu, mas a
        execução real continua sendo sempre o mesmo `deploy_rollback_command`,
        não há lógica diferenciada por estratégia hoje.
        """
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            if not b.orchestration.deploy_runs:
                raise KeyError("Nenhuma implantação para reverter.")
            deploy = versao_atual(b.orchestration.deploy_runs, DeployRun)
            if deploy.status == STATUS_REVERTIDO:
                raise ValueError("Implantação já revertida.")
            deploy.rollback_estrategia = estrategia
            detalhe = ""
            comando_rollback = b.orchestration.deploy_rollback_command
            if deploy.estagio and b.orchestration.deploy_pipeline:
                estagio_cfg = _estagio_configurado(b.orchestration.deploy_pipeline, deploy.estagio)
                if estagio_cfg and estagio_cfg.get("rollback_command"):
                    comando_rollback = str(estagio_cfg["rollback_command"])
            repo = b.orchestration.target_path or os.environ.get("ASO_TARGET_REPO")
            if comando_rollback and repo:
                _ok, detalhe, _duracao = executar_deploy(comando_rollback, repo)
            deploy.status = STATUS_REVERTIDO
            deploy.rollback_motivo = reason
            b.orchestration.deploy_runs = [
                *b.orchestration.deploy_runs[:-1],
                deploy.model_dump(mode="json"),
            ]
            descricao = reason
            if detalhe:
                descricao += f"\n\nSaída do comando de rollback: {detalhe[:1000]}"
            card = KanbanCard(
                board_id=b.board.id,
                orchestration_id=orchestration_id,
                phase=b.orchestration.current_phase,
                type=CardType.INCIDENT,
                title=f"Causa raiz: rollback de implantação ({deploy.ambiente})",
                description=descricao,
                status=ColumnKey.BACKLOG,
                linked_requirements=["§21"],
            )
            b.board_service.add_card(card)
            incident = self._criar_incidente(b, card, deploy, reason)
            b.event_log.append(
                "DeployRolledBack",
                {
                    "orchestration_id": orchestration_id,
                    "ambiente": deploy.ambiente,
                    "reason": reason,
                    "incident_card": card.id,
                    "incident_id": incident.id,
                    "actor": actor,
                },
            )
            self._persist(b)
            return deploy

    def _criar_incidente(
        self, b: OrchestrationBundle, card: KanbanCard, deploy: DeployRun, reason: str
    ) -> Incident:
        """§21, ADR-0032: um `Incident` de primeira classe vinculado à tarefa de
        causa raiz (`card`, já `CardType.INCIDENT`) e ao deploy revertido — por
        snapshot (`DeployRun` não tem `id` próprio), não por FK real."""
        brief = DemandBrief.model_validate(b.orchestration.demand_brief)
        gravidade = _RISCO_PARA_GRAVIDADE.get(brief.risco, "media")
        incident = Incident(
            orchestration_id=b.orchestration.id,
            card_id=card.id,
            titulo=card.title,
            motivo=reason,
            gravidade=gravidade,
            deploy_ambiente=deploy.ambiente,
            deploy_estagio=deploy.estagio,
            deploy_versao=deploy.versao,
        )
        incident.timeline.append(
            IncidentTimelineEntry(evento="aberto", detalhe=reason).model_dump(mode="json")
        )
        b.incidents.append(incident)
        return incident

    def get_deploy_approval_checklist(self, orchestration_id: str) -> dict[str, object]:
        """Tela 22 (wf §24, ADR-0050): checklist de 9 itens + avaliação de risco
        da última implantação (ou do estado atual, se nenhuma rodou ainda)."""
        b = self._bundle(orchestration_id)
        deploy = (
            versao_atual(b.orchestration.deploy_runs, DeployRun)
            if b.orchestration.deploy_runs
            else None
        )
        brief = DemandBrief.model_validate(b.orchestration.demand_brief)
        rollback_configurado = bool(b.orchestration.deploy_rollback_command) or any(
            e.get("rollback_command") for e in b.orchestration.deploy_pipeline
        )
        pr_aprovada = any(p.review_status == "approved" for p in b.pull_requests)
        testes_aprovados = bool(b.gate_results) and b.gate_results[-1].status == GateStatus.PASSED
        aceite_humano = bool(
            deploy and deploy.origem_decisao == "humano" and deploy.aceite_status == ACEITE_APROVADO
        )
        checklist = checklist_aprovacao_implantacao(
            pr_aprovada=pr_aprovada,
            testes_aprovados=testes_aprovados,
            rollback_configurado=rollback_configurado,
            aceite_humano=aceite_humano,
        )
        risco = avaliacao_de_risco_implantacao(
            brief, deploy, rollback_configurado=rollback_configurado
        )
        return {"checklist": checklist, "avaliacao_de_risco": risco}

    def get_deploy_health(self, orchestration_id: str) -> dict[str, object]:
        """Tela 24 (wf §26, ADR-0050): saúde de 4 níveis + decisão sugerida da
        última implantação."""
        b = self._bundle(orchestration_id)
        if not b.orchestration.deploy_runs:
            raise KeyError("Nenhuma implantação para avaliar.")
        deploy = versao_atual(b.orchestration.deploy_runs, DeployRun)
        rollback_configurado = bool(b.orchestration.deploy_rollback_command) or any(
            e.get("rollback_command") for e in b.orchestration.deploy_pipeline
        )
        saude = saude_pos_deploy(deploy)
        decisao = decisao_sugerida_pos_deploy(saude, rollback_configurado=rollback_configurado)
        return {"saude": saude, "decisao_sugerida": decisao}

    def get_rollback_checklist(self, orchestration_id: str) -> list[dict[str, object]]:
        """Tela 25 (wf §27, ADR-0050): checklist de 6 itens da última implantação."""
        b = self._bundle(orchestration_id)
        if not b.orchestration.deploy_runs:
            raise KeyError("Nenhuma implantação para reverter.")
        deploy = versao_atual(b.orchestration.deploy_runs, DeployRun)
        anteriores = [
            d for d in b.orchestration.deploy_runs[:-1] if d.get("status") == STATUS_SUCESSO
        ]
        incidente_aberto = any(i.deploy_versao == deploy.versao for i in b.incidents)
        return checklist_rollback(
            versao_anterior_conhecida=bool(anteriores),
            rollback_executado=deploy.status == STATUS_REVERTIDO,
            smoke_tests_rodados=deploy.validacao_status != VALIDACAO_PENDENTE,
            incidente_aberto=incidente_aberto,
        )

    def get_incident(self, orchestration_id: str, incident_id: str) -> Incident | None:
        return next(
            (i for i in self._bundle(orchestration_id).incidents if i.id == incident_id), None
        )

    def investigate_incident(
        self, orchestration_id: str, incident_id: str, *, detalhe: str = "", actor: str = "system"
    ) -> Incident:
        """§21: marca o incidente como em investigação — transição intermediária
        antes da causa raiz ser identificada (`resolve_incident`)."""
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            incident = next((i for i in b.incidents if i.id == incident_id), None)
            if incident is None:
                raise KeyError(f"Incidente inexistente: {incident_id}")
            if incident.status == "resolvido":
                raise ValueError("Incidente já resolvido — não pode voltar a investigar.")
            incident.status = "investigando"
            incident.updated_at = now_iso()
            incident.timeline.append(
                IncidentTimelineEntry(
                    evento="investigando", detalhe=detalhe, actor=actor
                ).model_dump(mode="json")
            )
            self._persist(b)
            return incident

    def resolve_incident(
        self, orchestration_id: str, incident_id: str, *, causa_raiz: str, actor: str = "system"
    ) -> Incident:
        """§21: fecha o incidente com a causa raiz identificada — só a decisão em
        si; o card de causa raiz (`incident.card_id`) segue seu próprio ciclo de
        vida no kanban, independente."""
        if not causa_raiz.strip():
            raise ValueError("Informe a causa raiz para resolver o incidente.")
        with self._lock_for(orchestration_id):
            b = self._bundle(orchestration_id)
            incident = next((i for i in b.incidents if i.id == incident_id), None)
            if incident is None:
                raise KeyError(f"Incidente inexistente: {incident_id}")
            if incident.status == "resolvido":
                raise ValueError("Incidente já resolvido.")
            incident.status = "resolvido"
            incident.causa_raiz = causa_raiz
            timestamp = now_iso()
            incident.updated_at = timestamp
            incident.resolved_at = timestamp
            incident.timeline.append(
                IncidentTimelineEntry(
                    evento="resolvido", detalhe=causa_raiz, actor=actor
                ).model_dump(mode="json")
            )
            self._persist(b)
            return incident
