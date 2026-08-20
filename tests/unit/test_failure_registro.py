"""Registro de falha — `FailureRecord` e o ring `card.failures` (§13, ADR-0019)."""

from __future__ import annotations

from aso.control.failure import (
    ETAPA_CI,
    ETAPA_EXECUCAO,
    FailureRecord,
    confianca_diagnostico,
    registrar,
)


def test_failure_record_captura_comando_saida_executor_effort() -> None:
    record = FailureRecord(
        etapa=ETAPA_EXECUCAO,
        tentativa=1,
        comando="codex-default",
        mensagem="comando falhou",
        saida="stack trace completo aqui",
        executor="codex-default",
        effort="high",
    )
    dump = record.model_dump(mode="json")
    assert dump["comando"] == "codex-default"
    assert dump["saida"] == "stack trace completo aqui"
    assert dump["executor"] == "codex-default"
    assert dump["effort"] == "high"
    assert dump["etapa"] == ETAPA_EXECUCAO
    assert "at" in dump


def test_ring_descarta_o_mais_antigo_alem_do_limite() -> None:
    falhas: list[dict[str, object]] = []
    for i in range(1, 7):  # 6 falhas, ring limitado a 5
        falhas = registrar(falhas, FailureRecord(tentativa=i, mensagem=f"falha {i}"), limite=5)
    assert len(falhas) == 5
    mensagens = [f["mensagem"] for f in falhas]
    assert mensagens == ["falha 2", "falha 3", "falha 4", "falha 5", "falha 6"]


def test_ring_abaixo_do_limite_mantem_tudo() -> None:
    falhas: list[dict[str, object]] = []
    for i in range(1, 4):
        falhas = registrar(falhas, FailureRecord(tentativa=i), limite=5)
    assert len(falhas) == 3


def test_ring_aceita_etapas_diferentes_no_mesmo_card() -> None:
    """`card.failures` é um ring único por card — falhas de execução e de CI
    convivem na mesma lista, cada uma com sua `etapa`."""
    falhas: list[dict[str, object]] = []
    falhas = registrar(falhas, FailureRecord(etapa=ETAPA_EXECUCAO, mensagem="execução"))
    falhas = registrar(falhas, FailureRecord(etapa=ETAPA_CI, mensagem="ci"))
    assert [f["etapa"] for f in falhas] == [ETAPA_EXECUCAO, ETAPA_CI]


# --------------------------------------------- confiança do diagnóstico (ADR-0048)


def test_confianca_alta_quando_categoria_veio_da_bateria_nomeada() -> None:
    record = FailureRecord(categoria="lint", mensagem="erro de formatação")
    assert confianca_diagnostico(record) == "alta"


def test_confianca_baixa_sem_categoria_cai_na_heuristica() -> None:
    record = FailureRecord(mensagem="algo deu errado")
    assert confianca_diagnostico(record) == "baixa"
