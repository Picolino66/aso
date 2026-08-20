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
from aso.control.models import Environment, ValidationCheck
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

# ------------------------------------------------------------- pipeline (§19, ADR-0029)

ESTAGIO_DESENVOLVIMENTO = "desenvolvimento"
ESTAGIO_TESTES = "testes"
ESTAGIO_HOMOLOGACAO = "homologacao"
ESTAGIO_STAGING = "staging"
ESTAGIO_PRODUCAO = "producao"

# Sugestão pronta para `PUT deploy/pipeline` — staging/produção exigem aceite humano
# por padrão (mesmo espírito de `exige_aceite_humano`: quanto mais perto de produção,
# menos a esteira decide sozinha). O operador pode substituir por um pipeline próprio.
PIPELINE_PADRAO: list[Environment] = [
    Environment(chave=ESTAGIO_DESENVOLVIMENTO, nome="Desenvolvimento", ordem=1),
    Environment(chave=ESTAGIO_TESTES, nome="Testes", ordem=2),
    Environment(chave=ESTAGIO_HOMOLOGACAO, nome="Homologação", ordem=3),
    Environment(chave=ESTAGIO_STAGING, nome="Staging", ordem=4, requer_aprovacao_humana=True),
    Environment(chave=ESTAGIO_PRODUCAO, nome="Produção", ordem=5, requer_aprovacao_humana=True),
]


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
    # Estágio do pipeline a que esta tentativa pertence (§19, ADR-0029) — vazio =
    # implantação monoambiente legada, comportamento idêntico a antes desta ADR.
    estagio: str = ""
    # Preenchidos só quando `status == STATUS_FALHOU` e a orquestração tem pipeline
    # configurado — ver `classificar_falha_deploy`/`proxima_acao_deploy` abaixo.
    diagnostico_falha: str = ""
    proxima_acao_falha: str = ""
    # Estratégia de rollback escolhida pelo operador (Tela 25, wf §27.2,
    # ADR-0050) — descritiva: o runtime já roda `deploy_rollback_command`
    # (best-effort) independente da estratégia, não existe execução
    # diferenciada por estratégia hoje. Vazia = rollback sem estratégia
    # selecionada (comportamento idêntico a antes desta ADR).
    rollback_estrategia: str = ""
    # Sub-tipo do aceite humano (Tela 26, wf §28.2, ADR-0050) — só tem sentido
    # quando `origem_decisao == "humano"`; vazio = aceite humano genérico (o
    # operador não detalhou produto/técnico/negócio) ou aceite automático.
    tipo_aceite_humano: str = ""
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


# ---------------------------------------------------------------- pipeline (§19)


def _ultima_execucao(chave: str, deploy_runs: list[dict[str, object]]) -> dict[str, object] | None:
    """Última tentativa registrada para o estágio `chave` — o ring é append-order,
    então a última ocorrência na lista é a mais recente."""
    for run in reversed(deploy_runs):
        if run.get("estagio") == chave:
            return run
    return None


def _estagio_concluido(estagio: Environment, deploy_runs: list[dict[str, object]]) -> bool:
    """Sucesso registrado e, se o estágio exige, aceite humano aprovado."""
    run = _ultima_execucao(estagio.chave, deploy_runs)
    if run is None or run.get("status") != STATUS_SUCESSO:
        return False
    if estagio.requer_aprovacao_humana:
        return run.get("aceite_status") == ACEITE_APROVADO
    return True


def proximo_estagio_pendente(
    pipeline: list[Environment], deploy_runs: list[dict[str, object]]
) -> Environment | None:
    """Primeiro estágio (por `ordem`) ainda não concluído — `None` = pipeline completo."""
    for estagio in sorted(pipeline, key=lambda e: e.ordem):
        if not _estagio_concluido(estagio, deploy_runs):
            return estagio
    return None


def pode_avancar_estagio(
    estagio: Environment, pipeline: list[Environment], deploy_runs: list[dict[str, object]]
) -> bool:
    """§19: avanço governado — um estágio só roda depois do imediatamente anterior
    (por `ordem`) concluir. O primeiro estágio nunca tem predecessor a checar."""
    anteriores = [e for e in pipeline if e.ordem < estagio.ordem]
    if not anteriores:
        return True
    predecessor = max(anteriores, key=lambda e: e.ordem)
    return _estagio_concluido(predecessor, deploy_runs)


def status_do_pipeline(
    pipeline: list[Environment], deploy_runs: list[dict[str, object]]
) -> list[dict[str, object]]:
    """Status derivado por estágio (tela 23, wf §25) — nunca guardado, só calculado
    a partir do ring de tentativas."""
    resultado: list[dict[str, object]] = []
    for estagio in sorted(pipeline, key=lambda e: e.ordem):
        run = _ultima_execucao(estagio.chave, deploy_runs)
        resultado.append(
            {
                "chave": estagio.chave,
                "nome": estagio.nome or estagio.chave,
                "ordem": estagio.ordem,
                "requer_aprovacao_humana": estagio.requer_aprovacao_humana,
                "status": run.get("status") if run else STATUS_PENDENTE,
                "aceite_status": run.get("aceite_status") if run else None,
                "diagnostico_falha": run.get("diagnostico_falha") if run else "",
                "proxima_acao_falha": run.get("proxima_acao_falha") if run else "",
                "concluido": _estagio_concluido(estagio, deploy_runs),
                "pode_avancar": pode_avancar_estagio(estagio, pipeline, deploy_runs),
            }
        )
    return resultado


def pipeline_aprovado(pipeline: list[Environment], deploy_runs: list[dict[str, object]]) -> bool:
    """Critério `deploy_aprovado` do gate F6 quando há pipeline configurado: só
    aprova com TODOS os estágios concluídos, não só a última tentativa do ring
    (que pode ser um estágio intermediário)."""
    return bool(pipeline) and all(_estagio_concluido(e, deploy_runs) for e in pipeline)


# ------------------------------------------------ classificação de falha (§19, ADR-0019)

DIAG_BUILD = "build"
DIAG_CONFIGURACAO = "configuracao"
DIAG_MIGRATION = "migration"
DIAG_POS_DEPLOY = "pos_deploy"
DIAG_CRITICA = "critica"
DIAG_DEPLOY_DESCONHECIDO = "desconhecido"

_PALAVRAS_MIGRATION = ("migration", "migrate", "alembic", "schema", "banco de dados")
_PALAVRAS_CONFIGURACAO = (
    "config",
    "variavel de ambiente",
    "env var",
    ".env",
    "secret",
    "credencial",
)
_PALAVRAS_BUILD = ("build", "compil", "webpack", "docker build", "npm run build", "bundling")

_PROXIMA_ACAO_DEPLOY: dict[str, str] = {
    DIAG_BUILD: (
        "Falha de build — volta para implementação (corrigir o código antes de reimplantar)."
    ),
    DIAG_CONFIGURACAO: (
        "Falha de configuração — volta para infraestrutura "
        "(revisar variáveis/segredos do ambiente)."
    ),
    DIAG_MIGRATION: "Falha de migration — volta para banco de dados (revisar o schema).",
    DIAG_POS_DEPLOY: (
        "Falha em teste pós-implantação — abre correção e reimplanta o mesmo estágio."
    ),
    DIAG_CRITICA: (
        "Falha crítica em produção — executar rollback (POST deploy/rollback, papel admin)."
    ),
    DIAG_DEPLOY_DESCONHECIDO: "Causa não identificada — revise os logs antes de reimplantar.",
}


def classificar_falha_deploy(
    *, origem: str, estagio_chave: str, comando: str = "", saida: str = ""
) -> str:
    """Classifica a falha de implantação nos cinco diagnósticos do §19.

    A distinção pós-deploy/crítica é por FATO, não heurística: `origem="validacao"`
    (health check reprovado depois que o deploy já sucedeu) em `producao` é sempre
    `critica` — o §19 isola produção como o único caso que aciona rollback; a mesma
    falha em qualquer outro estágio é só "volta para correção". `origem="deploy"` (o
    próprio comando de implantação falhou, antes de qualquer validação rodar) é
    classificada por palavra-chave entre build/configuração/migration — mesma
    limitação aceita de `failure.py::diagnosticar` sem categoria estruturada
    disponível (aqui não há bateria nomeada equivalente para deploy).
    """
    if origem == "validacao":
        return DIAG_CRITICA if estagio_chave == ESTAGIO_PRODUCAO else DIAG_POS_DEPLOY
    texto = f"{comando} {saida}".lower()
    if any(p in texto for p in _PALAVRAS_MIGRATION):
        return DIAG_MIGRATION
    if any(p in texto for p in _PALAVRAS_CONFIGURACAO):
        return DIAG_CONFIGURACAO
    if any(p in texto for p in _PALAVRAS_BUILD):
        return DIAG_BUILD
    return DIAG_DEPLOY_DESCONHECIDO


def proxima_acao_deploy(diagnostico: str) -> str:
    """Texto pronto para `next_step`/UI — nunca deixa uma falha sem próxima ação
    (Princípio central do fluxo.md)."""
    return _PROXIMA_ACAO_DEPLOY.get(diagnostico, _PROXIMA_ACAO_DEPLOY[DIAG_DEPLOY_DESCONHECIDO])


# ---------------------------------------------- aprovação de implantação (§18, wf §24, ADR-0050)

ITEM_PR_APROVADO = "Pull request aprovado"
ITEM_TESTES_APROVADOS = "Testes aprovados"
ITEM_MIGRATIONS_VALIDADAS = "Migrations validadas"
ITEM_VARIAVEIS_CONFIGURADAS = "Variáveis configuradas"
ITEM_DOCUMENTACAO_ATUALIZADA = "Documentação atualizada"
ITEM_PLANO_ROLLBACK = "Plano de rollback disponível"
ITEM_DEPENDENCIAS_IMPLANTADAS = "Dependências implantadas"
ITEM_JANELA_DEFINIDA = "Janela de implantação definida"
ITEM_APROVACAO_HUMANA = "Aprovação humana realizada"

_ITENS_CHECKLIST_APROVACAO = (
    ITEM_PR_APROVADO,
    ITEM_TESTES_APROVADOS,
    ITEM_MIGRATIONS_VALIDADAS,
    ITEM_VARIAVEIS_CONFIGURADAS,
    ITEM_DOCUMENTACAO_ATUALIZADA,
    ITEM_PLANO_ROLLBACK,
    ITEM_DEPENDENCIAS_IMPLANTADAS,
    ITEM_JANELA_DEFINIDA,
    ITEM_APROVACAO_HUMANA,
)


def checklist_aprovacao_implantacao(
    *, pr_aprovada: bool, testes_aprovados: bool, rollback_configurado: bool, aceite_humano: bool
) -> list[dict[str, object]]:
    """9 itens do wf §24.1. O runtime não rastreia migrations aplicadas,
    variáveis de ambiente, dependências implantadas nem janela de
    implantação — esses 5 itens ficam com `ok=None` (sem verificação
    automática, confirmação manual do operador), mesma disciplina já
    documentada na ADR-0023 para este mesmo checklist."""
    sinais_reais: dict[str, bool] = {
        ITEM_PR_APROVADO: pr_aprovada,
        ITEM_TESTES_APROVADOS: testes_aprovados,
        ITEM_PLANO_ROLLBACK: rollback_configurado,
        ITEM_APROVACAO_HUMANA: aceite_humano,
    }
    return [{"item": item, "ok": sinais_reais.get(item)} for item in _ITENS_CHECKLIST_APROVACAO]


def avaliacao_de_risco_implantacao(
    brief: DemandBrief, deploy: DeployRun | None, *, rollback_configurado: bool
) -> dict[str, object]:
    """4 dos 6 campos do wf §24.2 — "probabilidade de falha" e "necessidade de
    janela de manutenção" não têm fonte no domínio hoje e ficam de fora do
    dict (não fabricados), mesma disciplina de `_build_card_closure`."""
    aprovacao = "pendente"
    if deploy and deploy.origem_decisao == "automatico":
        aprovacao = "automatica"
    elif deploy and deploy.origem_decisao == "humano":
        aprovacao = "humana"
    return {
        "risco": brief.risco.value,
        "impacto_potencial": list(brief.impactos),
        "possibilidade_de_rollback": rollback_configurado,
        "aprovacao": aprovacao,
    }


# --------------------------------------------- validação pós-implantação (§20, wf §26, ADR-0050)

SAUDE_SAUDAVEL = "saudavel"
SAUDE_SAUDAVEL_COM_ALERTAS = "saudavel_com_alertas"
SAUDE_INSTAVEL = "instavel"
SAUDE_FALHA_CRITICA = "falha_critica"

DECISAO_CONCLUIR_IMPLANTACAO = "concluir_implantacao"
DECISAO_INICIAR_CORRECAO = "iniciar_correcao"
DECISAO_EXECUTAR_ROLLBACK = "executar_rollback"
DECISAO_SOLICITAR_ANALISE_HUMANA = "solicitar_analise_humana"
DECISAO_MANTER_MONITORAMENTO = "manter_monitoramento"

_DECISAO_POR_SAUDE: dict[str, str] = {
    SAUDE_SAUDAVEL: DECISAO_CONCLUIR_IMPLANTACAO,
    SAUDE_SAUDAVEL_COM_ALERTAS: DECISAO_MANTER_MONITORAMENTO,
    SAUDE_INSTAVEL: DECISAO_INICIAR_CORRECAO,
    SAUDE_FALHA_CRITICA: DECISAO_EXECUTAR_ROLLBACK,
}


def saude_pos_deploy(deploy: DeployRun) -> str:
    """4 níveis do wf §26.2, derivados de FATO — `validacao_resultados` já
    distingue item bloqueante de não-bloqueante (§20); "saudável com alertas"
    é quando só um item não-bloqueante falhou, nunca heurística."""
    if deploy.status == STATUS_FALHOU:
        # Bug real (code-review ultra): o comando de implantação em si falhou —
        # `validacao_status` fica em `pendente` porque a validação pós-deploy
        # nunca chegou a rodar, e o `if` seguinte tratava isso como "nada
        # reprovado ainda" (saudável). Falha do comando é sempre crítica, nunca
        # heurística: `run_deploy` já grava `STATUS_FALHOU` como fato.
        return SAUDE_FALHA_CRITICA
    if deploy.validacao_status == VALIDACAO_PENDENTE:
        return SAUDE_SAUDAVEL  # comando de deploy OK, validação ainda não rodou
    alerta = any(not r.get("ok") and not r.get("bloqueante") for r in deploy.validacao_resultados)
    if deploy.validacao_status == VALIDACAO_APROVADA:
        return SAUDE_SAUDAVEL_COM_ALERTAS if alerta else SAUDE_SAUDAVEL
    return SAUDE_FALHA_CRITICA if deploy.diagnostico_falha == DIAG_CRITICA else SAUDE_INSTAVEL


def decisao_sugerida_pos_deploy(saude: str, *, rollback_configurado: bool) -> str:
    """5ª decisão possível do wf §26.3 — é só uma SUGESTÃO exibida ao operador,
    nunca uma ação automática: quem executa é o endpoint real correspondente
    (`run_deploy`/`rollback_deploy`/etc.), acionado manualmente. Falha crítica
    sem comando de rollback configurado escala para análise humana, já que a
    ação sugerida não teria como ser executada sozinha."""
    if saude == SAUDE_FALHA_CRITICA and not rollback_configurado:
        return DECISAO_SOLICITAR_ANALISE_HUMANA
    return _DECISAO_POR_SAUDE[saude]


# -------------------------------------------------------- rollback (§21, wf §27, ADR-0050)

ESTRATEGIA_VOLTAR_VERSAO = "voltar_versao"
ESTRATEGIA_REVERTER_CONFIGURACAO = "reverter_configuracao"
ESTRATEGIA_DESABILITAR_FEATURE_FLAG = "desabilitar_feature_flag"
ESTRATEGIA_RESTAURAR_BANCO = "restaurar_banco"
ESTRATEGIA_SUSPENDER_FILAS = "suspender_filas"
ESTRATEGIA_DESATIVAR_INTEGRACAO = "desativar_integracao"

ESTRATEGIAS_ROLLBACK = (
    ESTRATEGIA_VOLTAR_VERSAO,
    ESTRATEGIA_REVERTER_CONFIGURACAO,
    ESTRATEGIA_DESABILITAR_FEATURE_FLAG,
    ESTRATEGIA_RESTAURAR_BANCO,
    ESTRATEGIA_SUSPENDER_FILAS,
    ESTRATEGIA_DESATIVAR_INTEGRACAO,
)

ITEM_CONFIRMAR_VERSAO_ANTERIOR = "Confirmar versão anterior"
ITEM_VALIDAR_COMPATIBILIDADE_BANCO = "Validar compatibilidade do banco"
ITEM_SUSPENDER_NOVAS_EXECUCOES = "Suspender novas execuções"
ITEM_EXECUTAR_ROLLBACK = "Executar rollback"
ITEM_RODAR_SMOKE_TESTS = "Rodar smoke tests"
ITEM_ABRIR_ANALISE_CAUSA_RAIZ = "Abrir análise de causa raiz"

_ITENS_CHECKLIST_ROLLBACK = (
    ITEM_CONFIRMAR_VERSAO_ANTERIOR,
    ITEM_VALIDAR_COMPATIBILIDADE_BANCO,
    ITEM_SUSPENDER_NOVAS_EXECUCOES,
    ITEM_EXECUTAR_ROLLBACK,
    ITEM_RODAR_SMOKE_TESTS,
    ITEM_ABRIR_ANALISE_CAUSA_RAIZ,
)


def checklist_rollback(
    *,
    versao_anterior_conhecida: bool,
    rollback_executado: bool,
    smoke_tests_rodados: bool,
    incidente_aberto: bool,
) -> list[dict[str, object]]:
    """6 itens do wf §27.2. "Validar compatibilidade do banco" e "Suspender
    novas execuções" não têm nenhum mecanismo real no runtime hoje (não há
    verificação de schema nem pausa de tráfego) — ficam com `ok=None`, mesma
    disciplina do checklist de aprovação de implantação."""
    sinais_reais: dict[str, bool] = {
        ITEM_CONFIRMAR_VERSAO_ANTERIOR: versao_anterior_conhecida,
        ITEM_EXECUTAR_ROLLBACK: rollback_executado,
        ITEM_RODAR_SMOKE_TESTS: smoke_tests_rodados,
        ITEM_ABRIR_ANALISE_CAUSA_RAIZ: incidente_aberto,
    }
    return [{"item": item, "ok": sinais_reais.get(item)} for item in _ITENS_CHECKLIST_ROLLBACK]
