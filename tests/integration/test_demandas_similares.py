"""MEL-45 — recomendações por similaridade de demandas (ADR-0079).

Cobre o ranqueamento puro (BM25), o desfecho citado como evidência, a recusa honesta quando o
histórico não sustenta recomendação, a rota e a paridade SQLite × Postgres.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.application.orchestration_service import OrchestrationService
from aso.control.similaridade import (
    DemandaIndexada,
    ranquear,
    texto_da_demanda,
    tokenizar,
)
from aso.control.triage import DemandBrief
from aso.db.repository import SqlAlchemyOrchestrationRepository
from aso.persistence.memory import InMemoryOrchestrationRepository

# ------------------------------------------------------------------ ranqueamento puro


def test_tokenizar_normaliza_e_descarta_o_que_nao_discrimina() -> None:
    assert tokenizar("Validação de PAGAMENTO no checkout") == ["validacao", "pagamento", "checkout"]
    # paradas, jargão de toda demanda e fragmentos curtos ficam fora
    assert tokenizar("a nova demanda do sistema é de um card") == []


def test_ranquear_coloca_a_demanda_do_mesmo_assunto_na_frente() -> None:
    candidatas = [
        DemandaIndexada(
            "o1", "Relatório de vendas", "relatorio mensal de vendas em pdf", "2026-01"
        ),
        DemandaIndexada(
            "o2", "Pagamento pix", "corrigir conciliacao de pagamento pix no checkout", "2026-02"
        ),
        DemandaIndexada("o3", "Cadastro", "tela de cadastro de usuario", "2026-03"),
    ]
    resultado = ranquear("erro na conciliacao de pagamento pix", candidatas)
    assert [s.orchestration_id for s in resultado][0] == "o2"
    assert "pagamento" in resultado[0].termos_em_comum
    assert resultado[0].score > 0


def test_ranquear_nao_devolve_coincidencia_fraca_nem_consulta_vazia() -> None:
    candidatas = [DemandaIndexada("o1", "x", "relatorio mensal de vendas em pdf")]
    assert ranquear("", candidatas) == []
    assert ranquear("assunto completamente diferente", candidatas) == []
    assert ranquear("relatorio", []) == []


def test_ranquear_e_deterministico_e_desempata_pela_mais_recente() -> None:
    iguais = [
        DemandaIndexada("antiga", "t", "pagamento pix conciliacao", "2026-01-01"),
        DemandaIndexada("nova", "t", "pagamento pix conciliacao", "2026-06-01"),
    ]
    primeira = ranquear("pagamento pix conciliacao", iguais)
    segunda = ranquear("pagamento pix conciliacao", list(reversed(iguais)))
    assert [s.orchestration_id for s in primeira] == [s.orchestration_id for s in segunda]
    assert primeira[0].orchestration_id == "nova"


def test_texto_da_demanda_usa_conteudo_e_ignora_rotulos_fechados() -> None:
    ficha = {
        "objetivo": "corrigir conciliação",
        "modulos_afetados": ["pagamentos"],
        "tipo": "bug",
        "risco": "high",
        "complexidade": "complexa",
        "dominios": ["backend"],
    }
    texto = texto_da_demanda("erro no pix", ficha)
    assert "conciliação" in texto and "pagamentos" in texto
    # rótulo de vocabulário fechado entraria em toda demanda e ranquearia por rótulo
    for rotulo in ("bug", "high", "complexa", "backend"):
        assert rotulo not in texto, rotulo


# ------------------------------------------------------------------ serviço


def _demanda_com_execucao(
    svc: OrchestrationService, pedido: str, *, objetivo: str = "", executor: str = "claude"
) -> str:
    orch = svc.create_orchestration(pedido)
    if objetivo:
        svc.set_demand_brief(orch.id, DemandBrief(objetivo=objetivo))
    b = svc._bundle(orch.id)  # noqa: SLF001 - simula o desfecho que o runtime grava
    for card in b.board_service.cards_of(b.board.id)[:1]:
        card.executor = executor
        card.tentativa_atual = 2
        card.uso = {"custo_usd": 0.5, "execucoes": 1, "execucoes_sem_custo": 0}
        card.failures = [{"diagnostico": "teste_falhou", "etapa": "execucao"}]
    svc._persist(b)  # noqa: SLF001
    return orch.id


def test_demandas_similares_cita_a_fonte_de_cada_recomendacao() -> None:
    svc = OrchestrationService()
    antigas = [
        _demanda_com_execucao(svc, "corrigir conciliação de pagamento pix no checkout"),
        _demanda_com_execucao(svc, "conciliação de pagamento pix duplicado no extrato"),
        _demanda_com_execucao(svc, "importar relatório de estoque em csv", executor="codex"),
    ]
    nova = svc.create_orchestration("erro na conciliação do pagamento pix").id

    resultado = svc.demandas_similares(nova)

    ids = [s["orchestration_id"] for s in resultado["similares"]]
    # as duas de pix entram (a ordem entre duas igualmente parecidas não é uma propriedade a
    # fixar); a de estoque não compartilha termo e não compete
    assert set(ids) == set(antigas[:2])
    assert antigas[2] not in ids
    assert resultado["candidatas_avaliadas"] == 3
    assert "baseado em 2 demanda(s)" in resultado["fonte"]

    tipos = {r["tipo"]: r for r in resultado["recomendacoes"]}
    assert "claude" in tipos["executor"]["texto"]
    assert set(tipos["executor"]["fonte"]) == set(antigas[:2])
    assert "teste_falhou" in tipos["falha"]["texto"]
    assert tipos["custo"]["texto"].startswith("Custo observado")
    assert "tentativas" in tipos  # 2 tentativas por card > 1.5
    primeira = resultado["similares"][0]
    assert primeira["executor"] == "claude"
    assert primeira["tentativas"] == 2.0
    assert primeira["custo_usd"] == 0.5
    assert primeira["falhas"] == ["teste_falhou"]


def test_sem_demanda_parecida_o_painel_diz_isso() -> None:
    svc = OrchestrationService()
    svc.create_orchestration("importar relatório de estoque em csv")
    nova = svc.create_orchestration("configurar autenticação por certificado").id

    resultado = svc.demandas_similares(nova)

    assert resultado["similares"] == []
    assert resultado["recomendacoes"] == []
    assert "sem demanda parecida" in resultado["fonte"]


def test_historico_insuficiente_nao_vira_recomendacao() -> None:
    """Uma demanda parecida com execução é coincidência, não padrão (MINIMO_DE_HISTORICO)."""
    svc = OrchestrationService()
    _demanda_com_execucao(svc, "corrigir conciliação de pagamento pix")
    svc.create_orchestration("conciliação de pagamento pix no extrato")  # parecida, sem execução
    nova = svc.create_orchestration("erro de conciliação no pagamento pix").id

    resultado = svc.demandas_similares(nova)

    assert len(resultado["similares"]) == 2
    assert resultado["recomendacoes"] == []
    assert "histórico insuficiente" in resultado["fonte"]
    # a demanda sem execução aparece, mas declarada como sem número
    sem_execucao = [s for s in resultado["similares"] if s["cards_executados"] == 0]
    assert sem_execucao and sem_execucao[0]["custo_usd"] is None


def test_custo_ausente_nunca_vira_zero() -> None:
    svc = OrchestrationService()
    for pedido in ("conciliação de pagamento pix", "pagamento pix no extrato"):
        orch = svc.create_orchestration(pedido)
        b = svc._bundle(orch.id)  # noqa: SLF001
        for card in b.board_service.cards_of(b.board.id)[:1]:
            card.executor = "claude"
            card.tentativa_atual = 1
            card.uso = {"execucoes": 1, "execucoes_sem_custo": 1}  # rodou sem informar custo
        svc._persist(b)  # noqa: SLF001
    nova = svc.create_orchestration("erro no pagamento pix").id

    resultado = svc.demandas_similares(nova)

    assert all(s["custo_usd"] is None for s in resultado["similares"])
    assert not [r for r in resultado["recomendacoes"] if r["tipo"] == "custo"]


def test_recorte_por_projeto_restringe_o_historico(tmp_path: Path) -> None:
    svc = OrchestrationService()
    projeto = svc.create_project(
        name="pagamentos", description="", target_path=str(tmp_path), actor="teste"
    )
    fora = _demanda_com_execucao(svc, "conciliação de pagamento pix no checkout")
    dentro = svc.create_orchestration(
        "conciliação de pagamento pix no extrato", project_id=projeto.id
    ).id
    nova = svc.create_orchestration(
        "erro de conciliação de pagamento pix", project_id=projeto.id
    ).id

    global_ = svc.demandas_similares(nova)
    do_projeto = svc.demandas_similares(nova, do_projeto=True)

    assert fora in [s["orchestration_id"] for s in global_["similares"]]
    assert [s["orchestration_id"] for s in do_projeto["similares"]] == [dentro]


# ------------------------------------------------------------------ rota


def test_rota_de_demandas_similares() -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    _demanda_com_execucao(svc, "corrigir conciliação de pagamento pix")
    _demanda_com_execucao(svc, "conciliação de pagamento pix no extrato")
    nova = svc.create_orchestration("erro de conciliação no pagamento pix").id

    resposta = client.get(f"/v1/orchestrations/{nova}/similar-demands")

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert len(corpo["similares"]) == 2
    assert corpo["recomendacoes"]

    # `limite` é a janela de evidência: pedindo uma só demanda, o histórico visível fica abaixo
    # do mínimo e a rota devolve os dados sem recomendar nada — em vez de recomendar por uma.
    estreita = client.get(f"/v1/orchestrations/{nova}/similar-demands", params={"limite": 1}).json()
    assert len(estreita["similares"]) == 1
    assert estreita["recomendacoes"] == []
    assert "histórico insuficiente" in estreita["fonte"]

    assert client.get("/v1/orchestrations/orch_fantasma/similar-demands").status_code == 404


def test_painel_de_recomendacao_mostra_as_demandas_parecidas() -> None:
    pagina = TestClient(create_app(OrchestrationService())).get("/ui/demanda-detalhe").text
    assert "/similar-demands?limite=5" in pagina
    assert "Demandas parecidas" in pagina
    assert "BM25" in pagina
    assert "não informado" in pagina  # custo ausente aparece como ausente


# ------------------------------------------------------------------ SQLite × Postgres


@pytest.fixture(params=["memoria", "sqlite", "postgres"])
def repositorio(request: pytest.FixtureRequest, tmp_path: Path) -> object:
    if request.param == "memoria":
        return InMemoryOrchestrationRepository()
    if request.param == "sqlite":
        return SqlAlchemyOrchestrationRepository(f"sqlite:///{tmp_path / 'aso.db'}")
    url = os.environ.get("ASO_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("ASO_TEST_POSTGRES_URL não definida")
    return SqlAlchemyOrchestrationRepository(url)


def test_textos_de_demandas_tem_o_mesmo_contrato_nos_adapters(repositorio: object) -> None:
    svc = OrchestrationService(repository=repositorio)  # type: ignore[arg-type]
    primeira = svc.create_orchestration("conciliação de pagamento pix")
    svc.set_demand_brief(primeira.id, DemandBrief(objetivo="corrigir o extrato"))
    segunda = svc.create_orchestration("importar relatório de estoque")

    textos = repositorio.textos_de_demandas(limite=10)  # type: ignore[attr-defined]
    por_id = {t["id"]: t for t in textos}

    assert {primeira.id, segunda.id} <= set(por_id)
    assert por_id[primeira.id]["user_request"] == "conciliação de pagamento pix"
    assert por_id[primeira.id]["demand_brief"]["objetivo"] == "corrigir o extrato"
    assert por_id[primeira.id]["created_at"]
    # O recorte e a exclusão valem igual nos três. O banco de teste Postgres é reaproveitado
    # entre execuções, então a afirmação é sobre presença/ausência, não sobre a lista inteira.
    sem_a_primeira = {
        t["id"]
        for t in repositorio.textos_de_demandas(  # type: ignore[attr-defined]
            limite=100, excluir=primeira.id
        )
    }
    assert primeira.id not in sem_a_primeira
    assert segunda.id in sem_a_primeira
    assert repositorio.textos_de_demandas(limite=10, project_id="projeto_fantasma") == []  # type: ignore[attr-defined]


def test_similaridade_funciona_no_repositorio_real(repositorio: object) -> None:
    svc = OrchestrationService(repository=repositorio)  # type: ignore[arg-type]
    antiga = _demanda_com_execucao(svc, "conciliação de pagamento pix no checkout")
    _demanda_com_execucao(svc, "pagamento pix duplicado na conciliação do extrato")
    nova = svc.create_orchestration("erro na conciliação de pagamento pix").id

    resultado = svc.demandas_similares(nova)

    assert antiga in [s["orchestration_id"] for s in resultado["similares"]]
    assert [r for r in resultado["recomendacoes"] if r["tipo"] == "executor"]
