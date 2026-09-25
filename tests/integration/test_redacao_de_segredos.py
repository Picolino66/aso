"""MEL-58 — nenhum segredo sobrevive na saída de agente persistida (ADR-0080, regra 9).

Teste de governança no espírito das MEL P0: em vez de "a redação funciona", ele tenta **burlar** —
um agente que imprime o valor de uma variável sensível, falha com o segredo na mensagem e escreve
o segredo no motivo do bloqueio. O segredo não pode aparecer em evento, card, log ao vivo,
`agent_runs` nem em resposta da API.
"""

from __future__ import annotations

import dataclasses
import json
import shlex
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.application.orchestration_service import OrchestrationService
from aso.control.failure import FailureRecord
from aso.execution.catalog import ExecutorCatalog, ExecutorProfile
from aso.observability.agent_log import AgentLogBus
from aso.shared.events import EventLog
from aso.shared.segredos import MASCARA, mascarar_json, mascarar_segredos, mascarar_valor

SEGREDO = "sk-segredo-de-verdade-1234567890"


@pytest.fixture(autouse=True)
def _ambiente_com_segredo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASO_LLM_API_KEY", SEGREDO)


# ------------------------------------------------------------------ primitiva


def test_valor_do_ambiente_e_padroes_conhecidos_saem() -> None:
    assert mascarar_segredos(f"usando {SEGREDO} agora") == f"usando {MASCARA} agora"
    for texto in (
        "Authorization: Bearer abcdefghij1234567890",
        "ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "AKIAIOSFODNN7EXAMPLE",
        "api_key=zzzzzzzzzzzz",
        "senha: umaSenhaLonga",
    ):
        assert MASCARA in mascarar_segredos(texto), texto


def test_valor_curto_e_texto_comum_nao_sao_mascarados(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mascarar valor curto estragaria texto legítimo e não protegeria nada utilizável."""
    monkeypatch.setenv("ASO_TOKEN_CURTO", "abc")
    assert mascarar_segredos("token: 1") == "token: 1"
    assert mascarar_segredos("abc") == "abc"
    assert mascarar_segredos("") == ""


def test_redacao_recursiva_preserva_a_forma() -> None:
    entrada = {
        "texto": f"vazou {SEGREDO}",
        "numero": 7,
        "lista": [f"{SEGREDO}", 1, None],
        "aninhado": {"chave": SEGREDO},
    }
    saida = mascarar_valor(entrada)
    assert saida["numero"] == 7
    assert saida["lista"][1:] == [1, None]
    assert SEGREDO not in json.dumps(saida)
    assert SEGREDO not in json.dumps(mascarar_json(entrada))


# ------------------------------------------------------------------ pontos de entrada


def test_event_log_redige_o_payload() -> None:
    log = EventLog()
    evento = log.append("AgentFailed", {"error": f"falhou usando {SEGREDO}", "tentativa": 2})
    assert SEGREDO not in json.dumps(evento.payload)
    assert evento.payload["tentativa"] == 2  # o resto do payload continua intacto


def test_log_ao_vivo_redige_cada_linha() -> None:
    bus = AgentLogBus()
    sessao = bus.open("orch_1", card_id="card_1", agent="BackendDevelopmentAgent", executor="cli")
    sessao.write("stdout", f"echo {SEGREDO}")
    sessao.marco("terminou", detail=f"chave {SEGREDO}")
    linhas = bus.lines("orch_1")
    serializado = json.dumps([dataclasses.asdict(linha) for linha in linhas], default=str)
    assert SEGREDO not in serializado
    assert MASCARA in serializado


def test_registro_de_falha_redige_mensagem_saida_e_comando() -> None:
    record = FailureRecord(
        comando=f"curl -H 'Authorization: Bearer {SEGREDO}' http://x",
        mensagem=f"erro com {SEGREDO}",
        saida=f"stderr: {SEGREDO}",
    )
    assert SEGREDO not in record.model_dump_json()
    assert MASCARA in record.mensagem


def test_movimentacao_de_card_redige_motivo_e_evidencia() -> None:
    svc = OrchestrationService()
    orch = svc.create_orchestration("demanda com segredo")
    card = svc.get_cards(orch.id)[0]

    svc.block_card(orch.id, card.id, f"o agente falhou com {SEGREDO}")

    bloqueado = svc.get_cards(orch.id)[0]
    assert SEGREDO not in (bloqueado.block_reason or "")
    assert MASCARA in (bloqueado.block_reason or "")
    eventos = svc.get_card_events(orch.id, card.id)
    assert SEGREDO not in json.dumps([e.model_dump(mode="json") for e in eventos])


# ------------------------------------------------------------------ execução real do agente


def _catalogo_que_vaza(tmp_path: Path) -> ExecutorCatalog:
    """Agente que imprime o segredo, escreve um arquivo e falha com o segredo na mensagem."""
    script = (
        "cat > /dev/null; "
        'echo "chave em uso: $ASO_LLM_API_KEY"; '
        'echo "Authorization: Bearer $ASO_LLM_API_KEY" >&2; '
        "exit 3"
    )
    comando = shlex.join(["bash", "-c", script])
    return ExecutorCatalog(
        [ExecutorProfile(name="vazador", kind="cli", command=comando, is_default=True)]
    )


def _repo(raiz: Path) -> Path:
    import subprocess

    raiz.mkdir(parents=True, exist_ok=True)
    for args in (("init", "-q"), ("config", "user.email", "t@t"), ("config", "user.name", "t")):
        subprocess.run(["git", *args], cwd=raiz, check=True, capture_output=True)
    (raiz / "README.md").write_text("base\n")
    subprocess.run(["git", "add", "-A"], cwd=raiz, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=raiz, check=True, capture_output=True)
    return raiz


def test_agente_que_imprime_segredo_nao_deixa_rastro(tmp_path: Path) -> None:
    """O caminho completo: execução real de card com CLI que vaza o segredo em stdout e stderr."""
    raiz = _repo(tmp_path / "proj")
    svc = OrchestrationService(catalog=_catalogo_que_vaza(raiz))
    client = TestClient(create_app(svc))
    orch = svc.create_orchestration("implementar com segredo", target_path=str(raiz))
    card = svc.get_cards(orch.id)[0]

    try:
        svc.run_card(orch.id, card.id)
    except Exception:  # noqa: BLE001 - a execução falha de propósito (exit 3)
        pass

    # 1) estado governado: eventos, cards e histórico
    corpo_da_timeline = json.dumps(
        [dataclasses.asdict(e) for e in svc.timeline(orch.id)], default=str
    )
    assert SEGREDO not in corpo_da_timeline
    cards = json.dumps([c.model_dump(mode="json") for c in svc.get_cards(orch.id)], default=str)
    assert SEGREDO not in cards
    # 2) registro de execução (ADR-0065)
    runs = json.dumps(
        [r.model_dump(mode="json") for r in svc.list_agent_runs(orch.id)], default=str
    )
    assert SEGREDO not in runs
    # 3) log ao vivo
    assert SEGREDO not in json.dumps(svc.agent_log(orch.id), default=str)
    # 4) respostas da API que o operador abre depois de uma falha
    for rota in (
        f"/v1/orchestrations/{orch.id}/timeline",
        f"/v1/orchestrations/{orch.id}/cards",
        f"/v1/orchestrations/{orch.id}/agent-log",
        f"/v1/orchestrations/{orch.id}/runs",
        f"/v1/orchestrations/{orch.id}/next-step",
    ):
        resposta = client.get(rota)
        assert resposta.status_code == 200, rota
        assert SEGREDO not in resposta.text, rota
    # e a máscara aparece de fato em algum lugar — a saída do agente não foi só descartada
    assert MASCARA in corpo_da_timeline or MASCARA in cards
