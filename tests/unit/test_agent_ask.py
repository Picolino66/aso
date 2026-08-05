"""`perguntar_ao_agente` — dispatch comum aos serviços de agente (§4.1 do plano4.md).

Cobre o transporte extraído: ramo LLM e ramo CLI devem produzir o mesmo dict a partir
da mesma resposta, e cada uma das exceções de `ERROS_DE_AGENTE` precisa continuar
propagando — é o chamador (cada serviço) quem decide o fallback.
"""

from __future__ import annotations

import shlex

import pytest

from aso.control.agent_ask import ERROS_DE_AGENTE, perguntar_ao_agente
from aso.control.models import AgentAssignment
from aso.execution.catalog import ExecutorCatalog, ExecutorProfile


def _cli_catalog(saida: str, *, exit_code: int = 0) -> ExecutorCatalog:
    script = f'cat > /dev/null; printf %s "$1"; exit {exit_code}'
    comando = shlex.join(["bash", "-c", script, "_", saida])
    return ExecutorCatalog([ExecutorProfile(name="agente", kind="cli", command=comando)])


def test_ramo_cli_produz_o_dict_saneado() -> None:
    catalogo = _cli_catalog('{"campo": "valor"}')
    resultado = perguntar_ao_agente(
        catalogo,
        AgentAssignment(executor="agente"),
        system="system prompt",
        pedido="pedido",
        kind="teste",
        timeout=5.0,
    )
    assert resultado == {"campo": "valor"}


def test_ramo_llm_produz_o_mesmo_dict_a_partir_da_mesma_resposta() -> None:
    class _FakeLlmClient:
        def complete(self, *, system: str, user: str) -> str:
            assert system == "system prompt"
            assert user == "pedido"
            return '{"campo": "valor"}'

    class _FakeCatalog:
        def get(self, name: str) -> ExecutorProfile:
            return ExecutorProfile(name=name, kind="llm", command="")

        def llm_client(self, name: str, *, effort_override: str | None = None) -> _FakeLlmClient:
            return _FakeLlmClient()

    resultado = perguntar_ao_agente(
        _FakeCatalog(),  # type: ignore[arg-type]
        AgentAssignment(executor="agente-llm"),
        system="system prompt",
        pedido="pedido",
        kind="teste",
        timeout=5.0,
    )
    assert resultado == {"campo": "valor"}


def test_executor_fora_do_catalogo_leva_a_keyerror() -> None:
    with pytest.raises(KeyError):
        perguntar_ao_agente(
            ExecutorCatalog([]),
            AgentAssignment(executor="fantasma"),
            system="s",
            pedido="p",
            kind="teste",
            timeout=5.0,
        )


def test_executor_de_tipo_nao_textual_leva_a_valueerror() -> None:
    catalogo = ExecutorCatalog([ExecutorProfile(name="mudo", kind="mock", command="")])
    with pytest.raises(ValueError, match="não sabe produzir texto"):
        perguntar_ao_agente(
            catalogo,
            AgentAssignment(executor="mudo"),
            system="s",
            pedido="p",
            kind="teste",
            timeout=5.0,
        )


def test_exit_nao_zero_leva_a_valueerror() -> None:
    catalogo = _cli_catalog("boom", exit_code=1)
    with pytest.raises(ValueError, match="exit=1"):
        perguntar_ao_agente(
            catalogo,
            AgentAssignment(executor="agente"),
            system="s",
            pedido="p",
            kind="teste",
            timeout=5.0,
        )


def test_json_invalido_leva_a_erro_de_agente() -> None:
    catalogo = _cli_catalog("isto não é JSON")
    with pytest.raises(ERROS_DE_AGENTE):
        perguntar_ao_agente(
            catalogo,
            AgentAssignment(executor="agente"),
            system="s",
            pedido="p",
            kind="teste",
            timeout=5.0,
        )


def test_timeout_leva_a_subprocess_error() -> None:
    comando = shlex.join(["sleep", "5"])
    catalogo = ExecutorCatalog([ExecutorProfile(name="lento", kind="cli", command=comando)])
    with pytest.raises(ERROS_DE_AGENTE):
        perguntar_ao_agente(
            catalogo,
            AgentAssignment(executor="lento"),
            system="s",
            pedido="p",
            kind="teste",
            timeout=0.1,
        )
