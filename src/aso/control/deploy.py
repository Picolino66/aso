"""Implantação governada (§18–§22 do fluxo.md) — ADR-0023.

**Não confundir com [`docs/deploy.md`](../../../docs/deploy.md)**, que documenta
como implantar o ASO Runtime em si (a imagem Docker da API). Este módulo é sobre
o runtime rastrear/governar implantações **dos projetos que ele orquestra** — o
código no `target_path` de cada orquestração.

O MVP exclui deploy automático em produção e provisionamento cloud automático
(`requerimentos.md`). Por isso este módulo não provisiona infraestrutura nenhuma:
`executar_deploy`/`validar_pos_deploy` só rodam um comando configurado pelo
operador (`run_gate_command`, mesmo executor determinístico da bateria de
validações, ADR-0022) — a mesma disciplina de "comando configurável, sem CD
próprio" já aplicada a testes/lint.

Sem classe: diferente de `DiscoveryService`/`SpecService`, não há agente/LLM
envolvido — é execução determinística de comando, mais perto do estilo de
`control/validation.py` do que do estilo agent-backed de `discovery.py`.
"""

from __future__ import annotations

import shlex
import time

from pydantic import BaseModel, Field

from aso.control.decision_engine import _SENSITIVE_IMPACTS
from aso.control.models import ValidationCheck
from aso.control.triage import DemandBrief
from aso.execution.gate_command import run_gate_command
from aso.shared.ids import now_iso
from aso.shared.types import RiskLevel

# ------------------------------------------------------------------------ status

STATUS_PENDENTE = "pendente"
STATUS_SUCESSO = "sucesso"
STATUS_FALHOU = "falhou"
STATUS_REVERTIDO = "revertido"

VALIDACAO_PENDENTE = "pendente"
VALIDACAO_APROVADA = "aprovada"
VALIDACAO_REPROVADA = "reprovada"

ACEITE_APROVADO = "aprovado"
ACEITE_AGUARDANDO_HUMANO = "aguardando_aprovacao"
ACEITE_REPROVADO = "reprovado"


class DeployRun(BaseModel):
    """Registro de uma tentativa de implantação (§18-22 do fluxo.md).

    Ring de até 5 por orquestração (`control/documentos.py`), mesmo padrão de
    `DiscoveryReport`/`SpecDocument` (ADR-0021 §4.2) — reexecutar depois de uma
    falha acrescenta uma versão nova, não apaga o histórico.
    """

    ambiente: str = "producao"
    # Informado pelo operador no corpo do POST; o runtime não inventa git log —
    # mesma disciplina do §23 (ficha de encerramento): só o que se tem à mão.
    versao_app: str = ""
    commit: str = ""
    branch: str = ""
    comando: str = ""
    responsavel: str = ""
    status: str = STATUS_PENDENTE
    logs: str = ""  # cauda do comando de deploy (run_gate_command)
    resultado: str = ""
    duracao_segundos: float = 0.0
    validacao_status: str = VALIDACAO_PENDENTE
    # [{nome, ok, evidencia, bloqueante}] por health check (§20).
    validacao_resultados: list[dict[str, object]] = Field(default_factory=list)
    aceite_status: str = ACEITE_AGUARDANDO_HUMANO
    aceite_comentario: str = ""
    origem_decisao: str = ""  # "automatico" | "humano" | ""
    rollback_motivo: str = ""
    versao: int = 1  # posição no ring (control/documentos.py)
    at: str = Field(default_factory=now_iso)


def executar_deploy(comando: str, repo: str, *, timeout: float = 300.0) -> tuple[bool, str, float]:
    """Roda o comando de implantação (§19). Nunca lança — `run_gate_command` já
    captura qualquer falha de subprocess e devolve o motivo como evidência."""
    inicio = time.monotonic()
    ok, detalhe = run_gate_command(shlex.split(comando), repo, timeout=timeout)
    duracao = time.monotonic() - inicio
    return ok, detalhe, duracao


def validar_pos_deploy(
    health_checks: list[ValidationCheck], repo: str
) -> tuple[bool, list[dict[str, object]]]:
    """Roda cada verificação pós-implantação (§20: health check, smoke test,
    teste de rota, verificação de logs/métricas...) reaproveitando o mesmo
    `ValidationCheck` da bateria (ADR-0022) — a forma "nome + comando +
    categoria + bloqueante" já é exatamente a de um health check.

    Aprovado = todo item BLOQUEANTE passou (mesmo espírito do gate: um health
    check não-bloqueante que falha vira aviso, não reprovação). Lista vazia
    (nenhum health check configurado) aprova vacuamente — "se aplicável", como
    o gate F6 do requerimentos.md já registra.
    """
    resultados: list[dict[str, object]] = []
    for check in health_checks:
        ok, detalhe = run_gate_command(shlex.split(check.comando), repo)
        resultados.append(
            {"nome": check.nome, "ok": ok, "evidencia": detalhe, "bloqueante": check.bloqueante}
        )
    aprovado = all(bool(r["ok"]) for r in resultados if r["bloqueante"])
    return aprovado, resultados


def exige_aceite_humano(deploy: DeployRun, brief: DemandBrief) -> bool:
    """§18/§22 do fluxo.md: quando o aceite final precisa ser humano.

    Mesmo raciocínio de `exige_aprovacao_discovery` (ADR-0020): reaproveita o
    vocabulário de impactos sensíveis do motor de decisão, não inventa um novo.
    Chamada só depois que a implantação já SUCEDEU (`run_deploy` reprova direto
    uma implantação que falhou, sem passar por aqui) — a decisão humana é sobre
    ACEITAR o resultado, não sobre autorizar a tentativa.
    """
    return (
        deploy.validacao_status == VALIDACAO_REPROVADA
        or brief.risco in (RiskLevel.HIGH, RiskLevel.CRITICAL)
        or bool(set(brief.impactos) & _SENSITIVE_IMPACTS)
    )
