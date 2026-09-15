"""MEL-42 — structured outputs com JSON Schema gerado dos modelos (ADR-0072).

Snapshots em `tests/snapshots/schemas/`: mudar um modelo de resposta muda o contrato com os
agentes, então o teste falha até o snapshot ser regerado de propósito
(`ASO_ATUALIZAR_SNAPSHOTS=1 pytest tests/unit/test_respostas_estruturadas.py`).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from aso.control import agent_ask
from aso.control.discovery import _DISCOVERY_COM_REPOSITORIO, _DISCOVERY_SYSTEM, RespostaDiscovery
from aso.control.models import AgentAssignment
from aso.control.naming import _NAMING_SYSTEM, NamingService, RespostaNomeacao
from aso.control.planning import _PLANNING_SYSTEM, PlanningService, ProjectPlan
from aso.control.respostas_estruturadas import RespostaInvalida, esquema_de, validar
from aso.control.review import (
    _DOC_REVIEW_SYSTEM,
    RespostaRevisao,
    RespostaRevisaoDocumental,
    system_de_revisao,
)
from aso.control.spec import _SPEC_SYSTEM, RespostaEspecificacao
from aso.control.triage import _TRIAGE_SYSTEM, RespostaTriagem, TriageService
from aso.execution import llm_client
from aso.execution.catalog import ExecutorCatalog, ExecutorProfile
from aso.execution.llm_client import AnthropicClient, FakeLlmClient, OpenAICompatibleClient
from aso.shared.types import CardType

SNAPSHOTS = Path(__file__).resolve().parents[1] / "snapshots" / "schemas"
MODELOS: dict[str, type[BaseModel]] = {
    "nomeacao": RespostaNomeacao,
    "triagem": RespostaTriagem,
    "discovery": RespostaDiscovery,
    "especificacao": RespostaEspecificacao,
    "revisao": RespostaRevisao,
    "revisao_documental": RespostaRevisaoDocumental,
    "planejamento": ProjectPlan,
}


@pytest.mark.parametrize(
    "prompt",
    [
        _NAMING_SYSTEM,
        _TRIAGE_SYSTEM,
        _DISCOVERY_SYSTEM,
        _DISCOVERY_COM_REPOSITORIO,
        _SPEC_SYSTEM,
        _DOC_REVIEW_SYSTEM,
        system_de_revisao(com_repositorio=False),
        system_de_revisao(com_repositorio=True),
        _PLANNING_SYSTEM,
    ],
)
def test_nenhum_prompt_de_sistema_traz_formato_json_escrito_a_mao(prompt: str) -> None:
    assert "na forma" not in prompt
    assert not re.search(r"\{\s*\"", prompt), "formato JSON escrito à mão no prompt"
    assert not re.search(r"\w+\|\w+\|\w+", prompt), "vocabulário listado à mão (vai no schema)"


@pytest.mark.parametrize("nome", sorted(MODELOS))
def test_schema_enviado_corresponde_ao_snapshot_do_modelo(nome: str) -> None:
    arquivo = SNAPSHOTS / f"{nome}.json"
    atual = json.dumps(esquema_de(MODELOS[nome]), ensure_ascii=False, indent=2, sort_keys=True)
    if os.environ.get("ASO_ATUALIZAR_SNAPSHOTS") == "1":
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        arquivo.write_text(atual + "\n", encoding="utf-8")
    assert arquivo.read_text(encoding="utf-8") == atual + "\n"


def _catalogo_cli(tmp_path: Path, resposta: str) -> tuple[ExecutorCatalog, Path]:
    captura = tmp_path / "tarefa.json"
    script = f'cat > "{captura}"; printf %s "$1"'
    import shlex

    comando = shlex.join(["bash", "-c", script, "_", resposta])
    return ExecutorCatalog([ExecutorProfile(name="agente", kind="cli", command=comando)]), captura


def test_envelope_da_pergunta_leva_o_schema_do_modelo(tmp_path: Path) -> None:
    catalog, captura = _catalogo_cli(tmp_path, json.dumps({"tipo": "correcao", "objetivo": "x"}))
    TriageService(catalog).analisar(AgentAssignment(executor="agente"), user_request="corrigir x")
    tarefa = json.loads(captura.read_text(encoding="utf-8"))
    assert tarefa["envelope"]["output_schema"] == esquema_de(RespostaTriagem)
    # o prompt do envelope não repete o schema (o renderizador acrescenta a partir dele)
    assert "JSON Schema" not in tarefa["envelope"]["system"]
    # wrappers antigos, sem envelope, recebem o formato no system
    assert "JSON Schema" in tarefa["content"]["system"]


def test_resposta_invalida_aponta_o_campo_e_tem_uma_unica_correcao(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cliente = FakeLlmClient(default=json.dumps({"resumo": "sem veredito"}))
    monkeypatch.setattr(ExecutorCatalog, "llm_client", lambda self, name, **kw: cliente)
    catalog = ExecutorCatalog([ExecutorProfile(name="llm", kind="llm", model="m")])
    with pytest.raises(RespostaInvalida) as erro:
        agent_ask.perguntar_ao_agente(
            catalog,
            AgentAssignment(executor="llm"),
            system="revise",
            pedido="diff",
            kind="revisao",
            timeout=5,
            modelo_resposta=RespostaRevisao,
        )
    assert any(c.startswith("veredito") for c in erro.value.campos)
    assert len(cliente.calls) == 2  # original + uma correção, nunca mais
    assert "veredito" in cliente.calls[1][1] and "não seguiu o schema" in cliente.calls[1][1]
    assert cliente.esquemas == [esquema_de(RespostaRevisao)] * 2


def test_correcao_bem_sucedida_devolve_a_resposta_valida(monkeypatch: pytest.MonkeyPatch) -> None:
    respostas = iter([json.dumps({"resumo": "faltou"}), json.dumps({"veredito": "aprovado"})])
    cliente = FakeLlmClient(lambda s, u: next(respostas))
    monkeypatch.setattr(ExecutorCatalog, "llm_client", lambda self, name, **kw: cliente)
    catalog = ExecutorCatalog([ExecutorProfile(name="llm", kind="llm", model="m")])
    resposta = agent_ask.perguntar_ao_agente(
        catalog,
        AgentAssignment(executor="llm"),
        system="revise",
        pedido="diff",
        kind="revisao",
        timeout=5,
        modelo_resposta=RespostaRevisao,
    )
    assert resposta["veredito"] == "aprovado" and len(cliente.calls) == 2


def test_fallback_deterministico_continua_quando_o_agente_erra_o_formato(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cliente = FakeLlmClient(default=json.dumps({"branch": 42}))
    monkeypatch.setattr(ExecutorCatalog, "llm_client", lambda self, name, **kw: cliente)
    catalog = ExecutorCatalog([ExecutorProfile(name="llm", kind="llm", model="m")])
    nomes = NamingService(catalog).suggest(
        AgentAssignment(executor="llm"), card_type=CardType.TASK, title="Calcular frete"
    )
    assert nomes.source == "deterministico" and "schema" in nomes.fallback_reason
    assert len(cliente.calls) == 2


def test_validar_devolve_o_bruto_quando_valido() -> None:
    bruto: dict[str, object] = {"veredito": "aprovado", "extra": 1}
    assert validar(RespostaRevisao, bruto) is bruto


def test_planejamento_corrige_uma_vez_e_valida(monkeypatch: pytest.MonkeyPatch) -> None:
    respostas = iter(
        [json.dumps({"backlog": "não é lista"}), json.dumps({"backlog": [{"title": "Item"}]})]
    )
    cliente = FakeLlmClient(lambda s, u: next(respostas))
    plano = PlanningService(cliente).plan("loja")
    assert [b.title for b in plano.backlog] == ["Item"]
    assert len(cliente.calls) == 2 and cliente.esquemas[0] == esquema_de(ProjectPlan)
    assert "JSON Schema" in cliente.calls[0][0]


def _capturar(monkeypatch: pytest.MonkeyPatch, resposta: dict[str, Any]) -> list[dict[str, Any]]:
    corpos: list[dict[str, Any]] = []

    def _post(url: str, headers: dict[str, str], body: dict[str, Any], timeout: float) -> Any:
        corpos.append(body)
        return resposta

    monkeypatch.setattr(llm_client, "_http_post_json", _post)
    return corpos


def test_openai_pede_json_schema_e_deepseek_json_object(monkeypatch: pytest.MonkeyPatch) -> None:
    corpos = _capturar(monkeypatch, {"choices": [{"message": {"content": "{}"}}]})
    esquema = esquema_de(RespostaNomeacao)
    openai = OpenAICompatibleClient(
        api_key="k", model="gpt", base_url="https://api.openai.com/v1", client_id="openai"
    )
    openai.completar(system="s", user="u", esquema=esquema)
    OpenAICompatibleClient(api_key="k", model="ds", client_id="deepseek").completar(
        system="s", user="u", esquema=esquema
    )
    assert corpos[0]["response_format"]["json_schema"]["schema"] == esquema
    assert corpos[1]["response_format"] == {"type": "json_object"}
    monkeypatch.setenv("ASO_LLM_SAIDA_ESTRUTURADA", "0")
    OpenAICompatibleClient(api_key="k", model="gpt").completar(
        system="s", user="u", esquema=esquema
    )
    assert "response_format" not in corpos[2]


def test_anthropic_forca_ferramenta_com_o_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    corpos = _capturar(
        monkeypatch,
        {"content": [{"type": "tool_use", "name": "responder", "input": {"veredito": "aprovado"}}]},
    )
    esquema = esquema_de(RespostaRevisao)
    resposta = AnthropicClient(api_key="k", model="claude").completar(
        system="s", user="u", esquema=esquema
    )
    assert corpos[0]["tools"][0]["input_schema"] == esquema
    assert corpos[0]["tool_choice"] == {"type": "tool", "name": "responder"}
    assert json.loads(resposta.texto) == {"veredito": "aprovado"}
