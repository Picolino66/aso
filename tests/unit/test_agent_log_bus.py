"""Ring buffer da saída ao vivo dos agentes (ADR-0015).

O que estes testes protegem: o produtor é a thread do agente e o consumidor é o handler
HTTP, então (a) o cursor tem que ser monotônico para a tela não repetir nem perder linha,
(b) a escrita concorrente não pode perder nada, e (c) uma sessão que termina em exceção
não pode deixar `running: true` órfão — a UI ficaria consultando para sempre.
"""

from __future__ import annotations

import threading

import pytest

from aso.observability.agent_log import AgentLogBus, AgentLogSession
from aso.shared.agent_output import KIND_MARCO, KIND_TEXTO, STREAM_STDERR, STREAM_STDOUT


def _bus(*, max_linhas: int | None = None) -> AgentLogBus:
    return AgentLogBus() if max_linhas is None else AgentLogBus(max_linhas=max_linhas)


def _abrir(bus: AgentLogBus, oid: str = "orch_1", card: str = "card_1") -> AgentLogSession:
    return bus.open(
        oid, card_id=card, agent="BackendDevelopmentAgent", executor="claude", branch="feat/x"
    )


# ------------------------------------------------------------------ cursor


def test_abertura_registra_marco_de_inicio() -> None:
    bus = _bus()
    _abrir(bus)
    linhas = bus.lines("orch_1")
    assert len(linhas) == 1
    assert linhas[0].kind == KIND_MARCO
    assert "iniciou" in linhas[0].text
    assert linhas[0].detail == "feat/x"


def test_cursor_e_monotonico_e_after_devolve_so_o_novo() -> None:
    bus = _bus()
    sessao = _abrir(bus)
    sessao.write(STREAM_STDOUT, "primeira", kind=KIND_TEXTO)
    primeiras = bus.lines("orch_1")
    ultimo = primeiras[-1].seq
    assert [linha.seq for linha in primeiras] == list(range(1, len(primeiras) + 1))

    sessao.write(STREAM_STDOUT, "segunda", kind=KIND_TEXTO)
    novas = bus.lines("orch_1", after=ultimo)
    assert [linha.text for linha in novas] == ["segunda"]


def test_orquestracao_sem_log_devolve_vazio_sem_explodir() -> None:
    bus = _bus()
    assert bus.lines("orch_inexistente") == []
    assert bus.state("orch_inexistente") == {
        "running": False,
        "sessions": [],
        "last_seq": 0,
        "retained": 0,
    }


def test_limit_devolve_a_cauda() -> None:
    bus = _bus()
    sessao = _abrir(bus)
    for i in range(20):
        sessao.write(STREAM_STDOUT, f"linha {i}", kind=KIND_TEXTO)
    ultimas = bus.lines("orch_1", limit=3)
    assert [linha.text for linha in ultimas] == ["linha 17", "linha 18", "linha 19"]


def test_linha_em_branco_nao_entra_no_log() -> None:
    # O pipe do agente cospe muitas linhas vazias; elas não podem virar ruído na tela.
    bus = _bus()
    sessao = _abrir(bus)
    antes = len(bus.lines("orch_1"))
    for vazia in ("", "\n", "   ", "  \n"):
        sessao.write(STREAM_STDOUT, vazia)
    assert len(bus.lines("orch_1")) == antes


# ------------------------------------------------------------------ retenção


def test_ring_descarta_o_mais_antigo_no_limite() -> None:
    bus = _bus(max_linhas=5)
    sessao = _abrir(bus)
    for i in range(20):
        sessao.write(STREAM_STDOUT, f"l{i}", kind=KIND_TEXTO)
    linhas = bus.lines("orch_1")
    assert len(linhas) == 5
    assert linhas[-1].text == "l19"
    # O cursor NÃO reinicia com o descarte: seq continua crescendo.
    assert linhas[-1].seq == 21  # 1 marco de abertura + 20 escritas


def test_forget_apaga_o_canal() -> None:
    bus = _bus()
    _abrir(bus)
    bus.forget("orch_1")
    assert bus.lines("orch_1") == []


# ------------------------------------------------------------------ sessões


def test_estado_reflete_execucao_em_andamento_e_encerrada() -> None:
    bus = _bus()
    sessao = _abrir(bus)
    assert bus.state("orch_1")["running"] is True

    sessao.close(ok=True, detail="42 linhas de diff")
    estado = bus.state("orch_1")
    assert estado["running"] is False
    (registro,) = estado["sessions"]
    assert registro["ok"] is True
    assert registro["detail"] == "42 linhas de diff"
    assert registro["elapsed_ms"] >= 0
    assert "concluiu" in bus.lines("orch_1")[-1].text


def test_fechar_duas_vezes_nao_duplica_o_marco() -> None:
    bus = _bus()
    sessao = _abrir(bus)
    sessao.close(ok=True)
    total = len(bus.lines("orch_1"))
    sessao.close(ok=False, detail="tardio")
    assert len(bus.lines("orch_1")) == total
    assert bus.state("orch_1")["sessions"][0]["ok"] is True


def test_context_manager_fecha_na_excecao() -> None:
    """Sem isto, um agente que explode deixaria `running: true` e a UI consultando à toa."""
    bus = _bus()
    with pytest.raises(RuntimeError):
        with _abrir(bus) as sessao:
            sessao.write(STREAM_STDERR, "quebrou")
            raise RuntimeError("falha do agente")
    estado = bus.state("orch_1")
    assert estado["running"] is False
    assert estado["sessions"][0]["ok"] is False
    assert "falha do agente" in estado["sessions"][0]["detail"]


def test_duas_sessoes_na_mesma_orquestracao_convivem() -> None:
    bus = _bus()
    a = bus.open("orch_1", card_id="card_a", agent="Backend", executor="claude")
    b = bus.open("orch_1", card_id="card_b", agent="Frontend", executor="codex")
    a.write(STREAM_STDOUT, "do A", kind=KIND_TEXTO)
    b.write(STREAM_STDOUT, "do B", kind=KIND_TEXTO)
    a.close(ok=True)
    estado = bus.state("orch_1")
    assert estado["running"] is True  # B continua
    assert len(estado["sessions"]) == 2
    porCard = {linha.text: linha.card_id for linha in bus.lines("orch_1")}
    assert porCard["do A"] == "card_a"
    assert porCard["do B"] == "card_b"


def test_orquestracoes_diferentes_nao_se_misturam() -> None:
    bus = _bus()
    _abrir(bus, "orch_1").write(STREAM_STDOUT, "da um", kind=KIND_TEXTO)
    _abrir(bus, "orch_2").write(STREAM_STDOUT, "da dois", kind=KIND_TEXTO)
    assert "da dois" not in [linha.text for linha in bus.lines("orch_1")]
    assert "da um" not in [linha.text for linha in bus.lines("orch_2")]


# ------------------------------------------------------------------ concorrência


def test_escrita_de_varias_threads_nao_perde_linha() -> None:
    """A execução real roda em ThreadPoolExecutor; perder linha aqui seria silencioso."""
    bus = _bus(max_linhas=5000)
    sessoes = [
        bus.open("orch_1", card_id=f"card_{i}", agent=f"Agente{i}", executor="claude")
        for i in range(4)
    ]

    def trabalhar(indice: int) -> None:
        for n in range(150):
            sessoes[indice].write(STREAM_STDOUT, f"t{indice}-{n}", kind=KIND_TEXTO)

    threads = [threading.Thread(target=trabalhar, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    linhas = bus.lines("orch_1", limit=5000)
    escritas = [linha for linha in linhas if linha.kind == KIND_TEXTO]
    assert len(escritas) == 4 * 150
    assert len({linha.seq for linha in linhas}) == len(linhas)  # nenhum seq repetido
    for i in range(4):
        assert sum(1 for linha in escritas if linha.card_id == f"card_{i}") == 150
