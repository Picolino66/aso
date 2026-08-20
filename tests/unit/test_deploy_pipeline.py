"""Funções puras do pipeline de implantação (§19 do fluxo.md, wf §25) — ADR-0029."""

from __future__ import annotations

from aso.control.deploy import (
    ACEITE_AGUARDANDO_HUMANO,
    ACEITE_APROVADO,
    DIAG_BUILD,
    DIAG_CONFIGURACAO,
    DIAG_CRITICA,
    DIAG_DEPLOY_DESCONHECIDO,
    DIAG_MIGRATION,
    DIAG_POS_DEPLOY,
    ESTAGIO_PRODUCAO,
    PIPELINE_PADRAO,
    STATUS_FALHOU,
    STATUS_SUCESSO,
    classificar_falha_deploy,
    pipeline_aprovado,
    pode_avancar_estagio,
    proxima_acao_deploy,
    proximo_estagio_pendente,
    status_do_pipeline,
)
from aso.control.models import Environment


def _pipeline_simples() -> list[Environment]:
    return [
        Environment(chave="dev", nome="Dev", ordem=1),
        Environment(chave="testes", nome="Testes", ordem=2),
        Environment(chave="producao", nome="Produção", ordem=3, requer_aprovacao_humana=True),
    ]


def _run(chave: str, status: str, aceite: str = "") -> dict[str, object]:
    return {"estagio": chave, "status": status, "aceite_status": aceite}


# --------------------------------------------------------------- avanço governado


def test_proximo_estagio_pendente_sem_execucoes_devolve_o_primeiro() -> None:
    pipeline = _pipeline_simples()
    alvo = proximo_estagio_pendente(pipeline, [])
    assert alvo is not None
    assert alvo.chave == "dev"


def test_proximo_estagio_pendente_avanca_apos_sucesso() -> None:
    pipeline = _pipeline_simples()
    runs = [_run("dev", STATUS_SUCESSO)]
    alvo = proximo_estagio_pendente(pipeline, runs)
    assert alvo is not None
    assert alvo.chave == "testes"


def test_proximo_estagio_pendente_respeita_aprovacao_humana() -> None:
    pipeline = _pipeline_simples()
    runs = [
        _run("dev", STATUS_SUCESSO),
        _run("testes", STATUS_SUCESSO),
        _run("producao", STATUS_SUCESSO, ACEITE_AGUARDANDO_HUMANO),
    ]
    alvo = proximo_estagio_pendente(pipeline, runs)
    assert alvo is not None
    assert alvo.chave == "producao"  # sucesso não basta sem aceite aprovado


def test_proximo_estagio_pendente_pipeline_completo_devolve_none() -> None:
    pipeline = _pipeline_simples()
    runs = [
        _run("dev", STATUS_SUCESSO),
        _run("testes", STATUS_SUCESSO),
        _run("producao", STATUS_SUCESSO, ACEITE_APROVADO),
    ]
    assert proximo_estagio_pendente(pipeline, runs) is None


def test_pode_avancar_primeiro_estagio_sempre_pode() -> None:
    pipeline = _pipeline_simples()
    assert pode_avancar_estagio(pipeline[0], pipeline, []) is True


def test_pode_avancar_recusa_sem_predecessor_concluido() -> None:
    pipeline = _pipeline_simples()
    assert pode_avancar_estagio(pipeline[1], pipeline, []) is False


def test_pode_avancar_libera_apos_predecessor_concluido() -> None:
    pipeline = _pipeline_simples()
    runs = [_run("dev", STATUS_SUCESSO)]
    assert pode_avancar_estagio(pipeline[1], pipeline, runs) is True


def test_pode_avancar_estagio_final_exige_aceite_do_predecessor() -> None:
    pipeline = _pipeline_simples()
    runs = [
        _run("dev", STATUS_SUCESSO),
        _run("testes", STATUS_SUCESSO),
    ]
    assert pode_avancar_estagio(pipeline[2], pipeline, runs) is True
    # "producao" em si exige aprovação humana, mas isso é checado sobre O PRÓPRIO
    # estágio (via `_estagio_concluido`), não sobre o predecessor "testes".


def test_pode_avancar_falha_no_predecessor_bloqueia() -> None:
    pipeline = _pipeline_simples()
    runs = [_run("dev", STATUS_FALHOU)]
    assert pode_avancar_estagio(pipeline[1], pipeline, runs) is False


def test_retry_no_mesmo_estagio_usa_a_ultima_tentativa() -> None:
    """Duas tentativas do mesmo estágio no ring — só a última importa."""
    pipeline = _pipeline_simples()
    runs = [_run("dev", STATUS_FALHOU), _run("dev", STATUS_SUCESSO)]
    assert pode_avancar_estagio(pipeline[1], pipeline, runs) is True


# ------------------------------------------------------------------- status/gate


def test_status_do_pipeline_sem_execucoes_tudo_pendente() -> None:
    pipeline = _pipeline_simples()
    status = status_do_pipeline(pipeline, [])
    assert [s["status"] for s in status] == ["pendente", "pendente", "pendente"]
    assert [s["pode_avancar"] for s in status] == [True, False, False]


def test_status_do_pipeline_ordenado_por_ordem() -> None:
    # Pipeline fora de ordem na lista de entrada — o status sai ordenado.
    pipeline = [
        Environment(chave="producao", ordem=3),
        Environment(chave="dev", ordem=1),
        Environment(chave="testes", ordem=2),
    ]
    status = status_do_pipeline(pipeline, [])
    assert [s["chave"] for s in status] == ["dev", "testes", "producao"]


def test_pipeline_aprovado_falso_sem_pipeline() -> None:
    assert pipeline_aprovado([], []) is False


def test_pipeline_aprovado_falso_com_estagio_intermediario_pendente() -> None:
    pipeline = _pipeline_simples()
    runs = [_run("dev", STATUS_SUCESSO)]
    assert pipeline_aprovado(pipeline, runs) is False


def test_pipeline_aprovado_verdadeiro_com_todos_concluidos() -> None:
    pipeline = _pipeline_simples()
    runs = [
        _run("dev", STATUS_SUCESSO),
        _run("testes", STATUS_SUCESSO),
        _run("producao", STATUS_SUCESSO, ACEITE_APROVADO),
    ]
    assert pipeline_aprovado(pipeline, runs) is True


def test_pipeline_padrao_tem_cinco_estagios_em_ordem() -> None:
    assert [e.chave for e in PIPELINE_PADRAO] == [
        "desenvolvimento",
        "testes",
        "homologacao",
        "staging",
        "producao",
    ]
    assert [e.ordem for e in PIPELINE_PADRAO] == [1, 2, 3, 4, 5]
    assert PIPELINE_PADRAO[3].requer_aprovacao_humana is True  # staging
    assert PIPELINE_PADRAO[4].requer_aprovacao_humana is True  # produção
    assert PIPELINE_PADRAO[0].requer_aprovacao_humana is False  # desenvolvimento


# --------------------------------------------------------------- classificação


def test_classificar_falha_deploy_por_palavra_chave_migration() -> None:
    diag = classificar_falha_deploy(
        origem="deploy", estagio_chave="producao", comando="alembic upgrade head", saida=""
    )
    assert diag == DIAG_MIGRATION


def test_classificar_falha_deploy_por_palavra_chave_configuracao() -> None:
    diag = classificar_falha_deploy(
        origem="deploy", estagio_chave="staging", comando="", saida="variavel de ambiente ausente"
    )
    assert diag == DIAG_CONFIGURACAO


def test_classificar_falha_deploy_por_palavra_chave_build() -> None:
    diag = classificar_falha_deploy(
        origem="deploy", estagio_chave="dev", comando="npm run build", saida=""
    )
    assert diag == DIAG_BUILD


def test_classificar_falha_deploy_sem_sinal_e_desconhecida() -> None:
    diag = classificar_falha_deploy(
        origem="deploy", estagio_chave="dev", comando="./deploy.sh", saida="erro genérico"
    )
    assert diag == DIAG_DEPLOY_DESCONHECIDO


def test_classificar_falha_validacao_fora_de_producao_e_pos_deploy() -> None:
    diag = classificar_falha_deploy(origem="validacao", estagio_chave="staging")
    assert diag == DIAG_POS_DEPLOY


def test_classificar_falha_validacao_em_producao_e_sempre_critica() -> None:
    diag = classificar_falha_deploy(origem="validacao", estagio_chave=ESTAGIO_PRODUCAO)
    assert diag == DIAG_CRITICA


def test_proxima_acao_deploy_nunca_fica_vazia() -> None:
    for diag in (DIAG_BUILD, DIAG_CONFIGURACAO, DIAG_MIGRATION, DIAG_POS_DEPLOY, DIAG_CRITICA):
        assert proxima_acao_deploy(diag)
    assert proxima_acao_deploy("diagnostico-nunca-visto")  # fallback nunca vazio
