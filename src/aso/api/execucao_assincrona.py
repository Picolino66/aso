"""Execução assíncrona das rotas que acionam agentes (ADR-0067, MEL-31).

Com `ASO_EXECUCAO_ASSINCRONA=1`, as rotas de execução enfileiram um `Job` e respondem
`202 Accepted` com o `job_id`; os workers da `FilaDeJobs` chamam exatamente o mesmo método
do serviço que a rota síncrona chamaria. Sem a flag (padrão durante a transição), nada muda.

Os handlers ficam no adaptador HTTP porque só a API decide entre síncrono e assíncrono — a
camada de aplicação continua chamada do mesmo jeito pela CLI e pelos testes.
"""

from __future__ import annotations

import os
from typing import Any

from aso.application.orchestration_service import OrchestrationService
from aso.bootstrap import build_candidate_providers
from aso.execution.jobs import FilaDeJobs, Job, JobRepository
from aso.execution.workspace import WorkspaceError
from aso.observability.agent_runs import mascarar_segredos
from aso.observability.broker import EventBroker
from aso.persistence.ports import ConcurrentModificationError
from aso.shared.types import Phase

# Operações assíncronas e o método do serviço que cada uma chama.
OP_RUN_CARD = "run_card"
OP_RUN_PLAN = "run_plan"
OP_RUN_PHASE = "run_phase"
OP_AUTOPILOT = "autopilot"
OP_RACE = "race_card"
OP_DISCOVERY = "discovery_run"
OP_SPEC = "spec_run"
OP_SPEC_REVIEW = "spec_review"
OP_REVIEW = "review_run"
OP_ANALYZE_FOLDER = "analyze_folder"
OP_DOCS_HEAL = "docs_heal"


def execucao_assincrona_ativa() -> bool:
    return os.environ.get("ASO_EXECUCAO_ASSINCRONA", "0") == "1"


def classificar_erro(exc: Exception) -> int | None:
    """Mesmo mapeamento de erro das rotas síncronas (404/400/409), gravado no job."""
    from aso.control.documento import DocumentoError

    if isinstance(exc, KeyError):
        return 404
    if isinstance(exc, ConcurrentModificationError):
        return 409
    if isinstance(exc, DocumentoError):
        return 400
    if isinstance(exc, ValueError | WorkspaceError):
        return 409
    return None


def _p(job: Job, chave: str) -> Any:
    return job.parametros.get(chave)


def criar_fila(
    svc: OrchestrationService,
    repository: JobRepository,
    *,
    broker: EventBroker | None = None,
    workers: int | None = None,
) -> FilaDeJobs:
    def _avisar_console(job: Job) -> None:
        if broker is not None:
            broker.publish(job.orchestration_id)  # o console (SSE) recarrega ao fim do job

    fila = FilaDeJobs(
        repository,
        instancia_id=svc._instancia_id,  # noqa: SLF001 — mesma identidade dos claims (ADR-0058)
        workers=workers,
        classificar_erro=classificar_erro,
        mascarar=mascarar_segredos,
        ao_terminar=_avisar_console,
    )

    def _run_card(job: Job) -> Any:
        return svc.run_card(job.orchestration_id, str(job.card_id))

    def _run_phase(job: Job) -> Any:
        fase = _p(job, "phase")
        return svc.run_phase(
            job.orchestration_id,
            Phase(fase) if fase else None,
            executor=_p(job, "executor"),
            effort=_p(job, "effort"),
            autopilot=bool(_p(job, "autopilot")),
        )

    def _autopilot(job: Job) -> Any:
        return svc.start_autopilot(
            job.orchestration_id,
            executor=_p(job, "executor"),
            effort=_p(job, "effort"),
            inicializar_git=bool(_p(job, "inicializar_git")),
        )

    def _race(job: Job) -> Any:
        providers = build_candidate_providers(svc.get(job.orchestration_id).target_path)
        return svc.race_card(job.orchestration_id, str(job.card_id), providers)

    def _review(job: Job) -> Any:
        return svc.run_review(
            job.orchestration_id,
            str(_p(job, "pr_id")),
            executor=_p(job, "executor"),
            effort=_p(job, "effort"),
            actor=job.ator,
        )

    def _pasta(metodo: str) -> Any:
        def handler(job: Job) -> Any:
            return getattr(svc, metodo)(
                job.orchestration_id,
                executor=_p(job, "executor"),
                effort=_p(job, "effort"),
                inicializar_git=bool(_p(job, "inicializar_git")),
            )

        return handler

    def _agendar_fase(
        orchestration_id: str, fase: Phase, executor: str | None, effort: str | None
    ) -> str:
        parametros = {
            "phase": fase.value,
            "executor": executor,
            "effort": effort,
            "autopilot": True,
        }
        fila.iniciar()
        return fila.enfileirar(OP_RUN_PHASE, orchestration_id, parametros=parametros).id

    # Aprovar `fase_gate` enfileira a próxima fase e a requisição de aprovação volta na hora.
    svc.definir_agendador_de_fase(_agendar_fase)

    fila.registrar(OP_RUN_CARD, _run_card)
    fila.registrar(OP_RUN_PLAN, lambda job: svc.run_plan(job.orchestration_id))
    fila.registrar(OP_RUN_PHASE, _run_phase)
    fila.registrar(OP_AUTOPILOT, _autopilot)
    fila.registrar(OP_RACE, _race)
    fila.registrar(
        OP_DISCOVERY,
        lambda job: svc.run_discovery(
            job.orchestration_id, executor=_p(job, "executor"), effort=_p(job, "effort")
        ),
    )
    fila.registrar(
        OP_SPEC,
        lambda job: svc.run_spec(
            job.orchestration_id, executor=_p(job, "executor"), effort=_p(job, "effort")
        ),
    )
    fila.registrar(
        OP_SPEC_REVIEW,
        lambda job: svc.run_spec_review(
            job.orchestration_id, executor=_p(job, "executor"), actor=job.ator
        ),
    )
    fila.registrar(OP_REVIEW, _review)
    fila.registrar(OP_ANALYZE_FOLDER, _pasta("analyze_folder"))
    fila.registrar(OP_DOCS_HEAL, _pasta("heal_docs"))
    return fila
