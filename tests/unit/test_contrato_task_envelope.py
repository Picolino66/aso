"""MEL-14 — contrato `TaskEnvelope` e renderização do prompt do wrapper (ADR-0059)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from aso.agents import contract, render_prompt
from aso.agents.contract import (
    CardBrief,
    ContratoInvalido,
    TaskEnvelope,
    envelope_de_pergunta,
    ler_envelope,
)
from aso.agents.render_prompt import INSTRUCAO_SO_JSON, renderizar_prompt
from aso.execution.agent_stream import extrair_resposta_final

RAIZ = Path(__file__).resolve().parents[2]
_SYSTEM = 'Responda SOMENTE com JSON na forma {"campo": "..."}\nRegra longa: ' + "x" * 500

_PERGUNTAS = ["naming", "triagem", "discovery", "especificacao", "revisao", "revisao_documental"]


@pytest.mark.parametrize("task_type", _PERGUNTAS)
def test_pergunta_leva_o_system_completo_e_nao_manda_implementar(task_type: str) -> None:
    env = envelope_de_pergunta(task_type, system=_SYSTEM, request="pedido específico")
    prompt = renderizar_prompt({"kind": task_type, "envelope": env.model_dump()})
    assert _SYSTEM in prompt  # inteiro, sem truncar
    assert "pedido específico" in prompt
    assert INSTRUCAO_SO_JSON in prompt
    assert "Implemente" not in prompt


@pytest.mark.parametrize("task_type", ["triagem", "discovery", "especificacao", "revisao"])
def test_formato_antigo_de_pergunta_nao_perde_o_system(task_type: str) -> None:
    # Regressão do wrapper antigo: só "naming" era pergunta; o resto virava implementação.
    tarefa = {"kind": task_type, "content": {"request": "pedido", "system": _SYSTEM}}
    prompt = renderizar_prompt(tarefa)
    assert _SYSTEM in prompt
    assert "Implemente" not in prompt


def _envelope_execucao(**extra: Any) -> dict[str, Any]:
    return TaskEnvelope(
        kind="execute",
        task_type="card",
        request="Criar calculadora",
        card=CardBrief(
            titulo="Somar dois números",
            descricao="Função soma",
            criterios=["soma(2, 3) == 5"],
            correcoes=["faltou teste de negativo"],
            contexto_adicional=["use apenas stdlib"],
        ),
        validation_command="pytest -q",
        commit_subject="feat: soma",
        phase="F5",
        **extra,
    ).model_dump()


def test_execucao_inclui_criterios_correcoes_contexto_e_nudge() -> None:
    tarefa = {"envelope": _envelope_execucao(), "nudge": "tentativa 1 falhou: timeout"}
    prompt = renderizar_prompt(tarefa)
    for trecho in (
        "Somar dois números",
        "soma(2, 3) == 5",
        "faltou teste de negativo",
        "use apenas stdlib",
        "tentativa 1 falhou: timeout",
        "pytest -q",
        "feat: soma",
        "Implemente",
    ):
        assert trecho in prompt


def test_nudge_e_effort_do_topo_vencem_o_envelope() -> None:
    env = _envelope_execucao(nudge="antigo", effort="low")
    prompt = renderizar_prompt({"envelope": env, "nudge": "novo", "effort": "high"})
    assert "novo" in prompt and "antigo" not in prompt
    assert "Nível de esforço solicitado: high" in prompt


def test_build_task_real_renderiza_contexto_adicional() -> None:
    from aso.control.orchestration_service import OrchestrationService

    svc = OrchestrationService()
    oid = svc.create_orchestration("backend").id
    b = svc._bundle(oid)  # noqa: SLF001 - o dicionário da tarefa é o objeto do teste
    card = b.board_service.cards_of(b.board.id)[0]
    card.contexto_adicional = ["não altere a API pública"]
    card.correction_actions = ["corrigir o nome da rota"]
    agente = b.agent_registry.get(str(card.assignee))
    assert agente is not None
    tarefa = svc._build_task(b, card, agente, effort="medium")  # noqa: SLF001
    assert ler_envelope(tarefa["envelope"]).card is not None
    prompt = renderizar_prompt(json.loads(json.dumps(tarefa)))
    assert "não altere a API pública" in prompt
    assert "corrigir o nome da rota" in prompt
    assert card.title in prompt


def test_versoes_do_contrato_e_do_renderizador_sao_iguais() -> None:
    assert contract.SCHEMA_VERSION == render_prompt.SCHEMA_VERSION


def test_schema_version_desconhecida_e_recusada_nos_dois_lados() -> None:
    env = envelope_de_pergunta("triagem", system=_SYSTEM, request="p").model_dump()
    env["schema_version"] = "99"
    with pytest.raises(ContratoInvalido, match="schema_version '99' desconhecida"):
        ler_envelope(env)
    with pytest.raises(render_prompt.ContratoInvalido, match="'99' desconhecida"):
        renderizar_prompt({"envelope": env})
    proc = subprocess.run(
        [sys.executable, str(RAIZ / "src/aso/agents/render_prompt.py")],
        input=json.dumps({"envelope": env}),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    assert "contrato inválido" in proc.stderr


def test_pergunta_sem_system_e_recusada() -> None:
    with pytest.raises(ContratoInvalido, match="schema ausente"):
        ler_envelope({"kind": "ask", "task_type": "triagem", "request": "p"})
    with pytest.raises(render_prompt.ContratoInvalido, match="schema ausente"):
        renderizar_prompt(
            {"envelope": {"schema_version": "1", "kind": "ask", "task_type": "triagem"}}
        )


def test_execute_com_task_type_de_pergunta_e_recusado() -> None:
    with pytest.raises(ContratoInvalido, match="não é de execução"):
        ler_envelope({"kind": "execute", "task_type": "triagem"})


# ---------------------------------------------------------------- NDJSON (stream-json)
_NDJSON_CLAUDE = "\n".join(
    json.dumps(e)
    for e in [
        {"type": "system", "subtype": "init", "model": "claude"},
        {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "Analisando a demanda…"}]},
        },
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read"}]}},
        {
            "type": "result",
            "subtype": "success",
            "result": '{"objetivo": "Login social", "dominios": ["backend"]}',
            "total_cost_usd": 0.01,
        },
    ]
)


def test_resposta_final_do_stream_json_do_claude() -> None:
    texto = extrair_resposta_final(_NDJSON_CLAUDE)
    assert json.loads(texto) == {"objetivo": "Login social", "dominios": ["backend"]}


def test_resposta_final_sem_result_usa_ultima_fala_do_assistant() -> None:
    saida = "\n".join(
        json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": t}]}})
        for t in ["pensando", '{"branch": "x", "commit": "feat: x"}']
    )
    assert json.loads(extrair_resposta_final(saida)) == {"branch": "x", "commit": "feat: x"}


def test_resposta_final_do_codex_e_texto_puro() -> None:
    codex = json.dumps(
        {"type": "item.completed", "item": {"type": "agent_message", "text": '{"a": 1}'}}
    )
    assert extrair_resposta_final(codex) == '{"a": 1}'
    puro = 'Aqui está:\n{"a": 1}'
    assert extrair_resposta_final(puro) == puro
