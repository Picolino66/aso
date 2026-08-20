"""Funções puras das Telas 22/24/25 (aprovação, saúde, rollback — wf §24/§26/§27,
ADR-0050)."""

from __future__ import annotations

from aso.control.deploy import (
    DECISAO_CONCLUIR_IMPLANTACAO,
    DECISAO_EXECUTAR_ROLLBACK,
    DECISAO_INICIAR_CORRECAO,
    DECISAO_MANTER_MONITORAMENTO,
    DECISAO_SOLICITAR_ANALISE_HUMANA,
    DIAG_CRITICA,
    DIAG_POS_DEPLOY,
    ESTRATEGIAS_ROLLBACK,
    ITEM_APROVACAO_HUMANA,
    ITEM_MIGRATIONS_VALIDADAS,
    ITEM_PLANO_ROLLBACK,
    ITEM_PR_APROVADO,
    ITEM_TESTES_APROVADOS,
    SAUDE_FALHA_CRITICA,
    SAUDE_INSTAVEL,
    SAUDE_SAUDAVEL,
    SAUDE_SAUDAVEL_COM_ALERTAS,
    STATUS_FALHOU,
    VALIDACAO_APROVADA,
    VALIDACAO_PENDENTE,
    VALIDACAO_REPROVADA,
    DeployRun,
    avaliacao_de_risco_implantacao,
    checklist_aprovacao_implantacao,
    checklist_rollback,
    decisao_sugerida_pos_deploy,
    saude_pos_deploy,
)
from aso.control.triage import DemandBrief
from aso.shared.types import RiskLevel

# ------------------------------------------------------- Tela 22: aprovação (wf §24)


def test_checklist_aprovacao_tem_nove_itens() -> None:
    checklist = checklist_aprovacao_implantacao(
        pr_aprovada=True, testes_aprovados=True, rollback_configurado=True, aceite_humano=True
    )
    assert len(checklist) == 9


def test_checklist_aprovacao_itens_reais_refletem_sinal() -> None:
    checklist = checklist_aprovacao_implantacao(
        pr_aprovada=True, testes_aprovados=False, rollback_configurado=True, aceite_humano=False
    )
    por_item = {c["item"]: c["ok"] for c in checklist}
    assert por_item[ITEM_PR_APROVADO] is True
    assert por_item[ITEM_TESTES_APROVADOS] is False
    assert por_item[ITEM_PLANO_ROLLBACK] is True
    assert por_item[ITEM_APROVACAO_HUMANA] is False


def test_checklist_aprovacao_itens_sem_sinal_ficam_none() -> None:
    """5 dos 9 itens não têm fonte no domínio hoje — nunca fabricados."""
    checklist = checklist_aprovacao_implantacao(
        pr_aprovada=True, testes_aprovados=True, rollback_configurado=True, aceite_humano=True
    )
    por_item = {c["item"]: c["ok"] for c in checklist}
    assert por_item[ITEM_MIGRATIONS_VALIDADAS] is None


def test_avaliacao_de_risco_omite_campos_sem_sinal() -> None:
    brief = DemandBrief(risco=RiskLevel.HIGH, impactos=["security"])
    risco = avaliacao_de_risco_implantacao(brief, None, rollback_configurado=False)
    assert risco["risco"] == "high"
    assert risco["impacto_potencial"] == ["security"]
    assert risco["possibilidade_de_rollback"] is False
    assert risco["aprovacao"] == "pendente"
    assert "probabilidade_de_falha" not in risco
    assert "janela_de_manutencao" not in risco


def test_avaliacao_de_risco_reflete_origem_da_decisao() -> None:
    brief = DemandBrief()
    deploy = DeployRun(origem_decisao="automatico")
    risco = avaliacao_de_risco_implantacao(brief, deploy, rollback_configurado=True)
    assert risco["aprovacao"] == "automatica"
    deploy.origem_decisao = "humano"
    risco2 = avaliacao_de_risco_implantacao(brief, deploy, rollback_configurado=True)
    assert risco2["aprovacao"] == "humana"


# ------------------------------------------------- Tela 24: saúde pós-deploy (wf §26)


def test_saude_sem_validacao_e_saudavel() -> None:
    assert saude_pos_deploy(DeployRun(validacao_status=VALIDACAO_PENDENTE)) == SAUDE_SAUDAVEL


def test_saude_aprovada_sem_alertas_e_saudavel() -> None:
    deploy = DeployRun(validacao_status=VALIDACAO_APROVADA, validacao_resultados=[])
    assert saude_pos_deploy(deploy) == SAUDE_SAUDAVEL


def test_saude_aprovada_com_item_nao_bloqueante_falho_e_alerta() -> None:
    deploy = DeployRun(
        validacao_status=VALIDACAO_APROVADA,
        validacao_resultados=[{"nome": "métricas", "ok": False, "bloqueante": False}],
    )
    assert saude_pos_deploy(deploy) == SAUDE_SAUDAVEL_COM_ALERTAS


def test_saude_reprovada_fora_de_producao_e_instavel() -> None:
    deploy = DeployRun(validacao_status=VALIDACAO_REPROVADA, diagnostico_falha=DIAG_POS_DEPLOY)
    assert saude_pos_deploy(deploy) == SAUDE_INSTAVEL


def test_saude_com_comando_de_deploy_falhou_e_falha_critica_mesmo_com_validacao_pendente() -> None:
    """Bug real (code-review ultra): quando o comando de implantação em si falha,
    `validacao_status` fica em `pendente` (a validação pós-deploy nunca chegou a
    rodar) — o código antigo lia isso como "nada reprovado ainda" e reportava
    `SAUDE_SAUDAVEL` com `decisao_sugerida = concluir_implantacao`, escondendo uma
    implantação que quebrou."""
    deploy = DeployRun(status=STATUS_FALHOU, validacao_status=VALIDACAO_PENDENTE)
    assert saude_pos_deploy(deploy) == SAUDE_FALHA_CRITICA


def test_saude_reprovada_em_producao_e_falha_critica() -> None:
    deploy = DeployRun(validacao_status=VALIDACAO_REPROVADA, diagnostico_falha=DIAG_CRITICA)
    assert saude_pos_deploy(deploy) == SAUDE_FALHA_CRITICA


def test_decisao_sugerida_mapeia_uma_por_saude() -> None:
    assert (
        decisao_sugerida_pos_deploy(SAUDE_SAUDAVEL, rollback_configurado=True)
        == DECISAO_CONCLUIR_IMPLANTACAO
    )
    assert (
        decisao_sugerida_pos_deploy(SAUDE_SAUDAVEL_COM_ALERTAS, rollback_configurado=True)
        == DECISAO_MANTER_MONITORAMENTO
    )
    assert (
        decisao_sugerida_pos_deploy(SAUDE_INSTAVEL, rollback_configurado=True)
        == DECISAO_INICIAR_CORRECAO
    )
    assert (
        decisao_sugerida_pos_deploy(SAUDE_FALHA_CRITICA, rollback_configurado=True)
        == DECISAO_EXECUTAR_ROLLBACK
    )


def test_decisao_sugerida_falha_critica_sem_rollback_escala_para_humano() -> None:
    assert (
        decisao_sugerida_pos_deploy(SAUDE_FALHA_CRITICA, rollback_configurado=False)
        == DECISAO_SOLICITAR_ANALISE_HUMANA
    )


# ---------------------------------------------------------- Tela 25: rollback (wf §27)


def test_estrategias_de_rollback_tem_seis_opcoes() -> None:
    assert len(ESTRATEGIAS_ROLLBACK) == 6


def test_checklist_rollback_tem_seis_itens() -> None:
    checklist = checklist_rollback(
        versao_anterior_conhecida=True,
        rollback_executado=True,
        smoke_tests_rodados=True,
        incidente_aberto=True,
    )
    assert len(checklist) == 6
    assert all(c["ok"] is not None or c["item"] for c in checklist)


def test_checklist_rollback_itens_sem_sinal_ficam_none() -> None:
    checklist = checklist_rollback(
        versao_anterior_conhecida=True,
        rollback_executado=True,
        smoke_tests_rodados=True,
        incidente_aberto=True,
    )
    valores_none = [c for c in checklist if c["ok"] is None]
    assert len(valores_none) == 2  # "validar compatibilidade" + "suspender execuções"
