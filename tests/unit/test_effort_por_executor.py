"""MEL-43 — esforço mapeado por tipo de executor (ADR-0073)."""

from __future__ import annotations

from typing import Any

import pytest

from aso.application.agent_task import _effort_aplicado
from aso.control.agent_ask import _effort_da_pergunta
from aso.control.models import AgentAssignment
from aso.execution import llm_client
from aso.execution.catalog import ExecutorCatalog, ExecutorProfile
from aso.execution.cli_provider import CliAgentExecutionProvider
from aso.execution.effort import aplicar_effort_no_comando, suporte_de_effort
from aso.execution.llm_client import AnthropicClient, OpenAICompatibleClient
from aso.execution.llm_provider import LlmExecutionProvider


@pytest.mark.parametrize(
    ("perfil", "suporta"),
    [
        ({"kind": "mock"}, False),
        ({"kind": "cli", "command": "/app/wrapper.sh codex exec", "managed_by": "codex"}, True),
        ({"kind": "cli", "command": "codex exec --json"}, True),
        ({"kind": "cli", "command": "/app/scripts/aso-agent-wrapper.sh claude -p"}, True),
        ({"kind": "cli", "command": "aider --yes"}, False),
        ({"kind": "llm", "provider": "openai", "model": "gpt-5.1"}, True),
        ({"kind": "llm", "provider": "openai", "model": "o4-mini"}, True),
        ({"kind": "llm", "provider": "openai", "model": "gpt-4o"}, False),
        ({"kind": "llm", "provider": "anthropic", "model": "claude-sonnet-4-5"}, True),
        ({"kind": "llm", "provider": "anthropic", "model": "claude-3-5-haiku"}, False),
        ({"kind": "llm", "provider": "deepseek", "model": "deepseek-reasoner"}, False),
    ],
)
def test_matriz_de_suporte_por_tipo_de_executor(perfil: dict[str, str], suporta: bool) -> None:
    resultado = suporte_de_effort(**perfil)
    assert resultado.suporta is suporta and resultado.como


def test_comando_do_claude_recebe_effort_e_o_do_codex_a_flag_de_raciocinio() -> None:
    catalogo = ExecutorCatalog(
        [
            ExecutorProfile(name="claude", kind="cli", command="claude -p", effort="medium"),
            ExecutorProfile(
                name="codex", kind="cli", command="codex exec", managed_by="codex", model="gpt-5"
            ),
            ExecutorProfile(name="aider", kind="cli", command="aider --yes"),
        ]
    )
    assert catalogo.cli_command("claude", effort_override="high")[-2:] == ["--effort", "high"]
    codex = catalogo.cli_command("codex", effort_override="low")
    assert codex[-2:] == ["-c", "model_reasoning_effort=low"] and "-m" in codex
    assert catalogo.cli_command("aider", effort_override="high") == ["aider", "--yes"]


def test_aplicar_effort_substitui_em_vez_de_duplicar() -> None:
    assert aplicar_effort_no_comando(["claude", "-p", "--effort", "low"], "max") == [
        "claude",
        "-p",
        "--effort",
        "max",
    ]
    duplo = aplicar_effort_no_comando(["codex", "exec", "-c", "model_reasoning_effort=low"], "high")
    assert duplo == ["codex", "exec", "-c", "model_reasoning_effort=high"]


def test_perfil_publico_diz_se_o_effort_tem_efeito() -> None:
    publico = ExecutorProfile(name="aider", kind="cli", command="aider").public()
    assert publico["suporta_effort"] is False and publico["effort_como"]


def _capturar(monkeypatch: pytest.MonkeyPatch, resposta: dict[str, Any]) -> list[dict[str, Any]]:
    corpos: list[dict[str, Any]] = []

    def _post(url: str, headers: dict[str, str], body: dict[str, Any], timeout: float) -> Any:
        corpos.append(body)
        return resposta

    monkeypatch.setattr(llm_client, "_http_post_json", _post)
    return corpos


def test_openai_envia_reasoning_effort_so_em_modelo_de_raciocinio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    corpos = _capturar(monkeypatch, {"choices": [{"message": {"content": "ok"}}]})
    base = "https://api.openai.com/v1"
    raciocinio = OpenAICompatibleClient(
        api_key="k", model="gpt-5", base_url=base, effort="high", provider="openai"
    )
    comum = OpenAICompatibleClient(
        api_key="k", model="gpt-4o", base_url=base, effort="high", provider="openai"
    )
    raciocinio.complete(system="s", user="u")
    comum.complete(system="s", user="u")
    assert corpos[0]["reasoning_effort"] == "high" and raciocinio.aplica_effort()
    assert "reasoning_effort" not in corpos[1] and not comum.aplica_effort()


def test_anthropic_pensamento_por_nivel_e_nao_junto_de_ferramenta_forcada(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    corpos = _capturar(
        monkeypatch,
        {
            "content": [
                {"type": "thinking", "thinking": "..."},
                {"type": "text", "text": "resposta"},
            ]
        },
    )
    cliente = AnthropicClient(api_key="k", model="claude-sonnet-4-5", effort="medium")
    assert cliente.complete(system="s", user="u") == "resposta"
    assert corpos[0]["thinking"] == {"type": "enabled", "budget_tokens": 8192}
    assert corpos[0]["max_tokens"] > 8192
    com_schema = _capturar(monkeypatch, {"content": [{"type": "tool_use", "input": {"x": 1}}]})
    cliente.completar(system="s", user="u", esquema={"type": "object"})
    assert "thinking" not in com_schema[0] and com_schema[0]["tool_choice"]["type"] == "tool"


def test_run_registra_se_o_effort_foi_aplicado() -> None:
    assert _effort_aplicado(CliAgentExecutionProvider(["claude", "-p"], "/tmp"), "high") is True
    assert _effort_aplicado(CliAgentExecutionProvider(["bash", "-c", "x"], "/tmp"), "high") is False
    assert _effort_aplicado(None, "") is None
    provider = LlmExecutionProvider(
        OpenAICompatibleClient(api_key="k", model="gpt-4o", effort="high", provider="openai")
    )
    assert _effort_aplicado(provider, "high") is False


def test_pergunta_na_anthropic_com_schema_nao_aplica_effort() -> None:
    catalogo = ExecutorCatalog(
        [
            ExecutorProfile(
                name="a", kind="llm", provider="anthropic", model="claude-opus-4-1", effort="high"
            )
        ]
    )
    assignment = AgentAssignment(executor="a")
    assert _effort_da_pergunta(catalogo, assignment, estruturada=True) is False
    assert _effort_da_pergunta(catalogo, assignment, estruturada=False) is True
