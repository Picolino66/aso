"""Clientes LLM (o "cérebro" do runtime) — M1 do autopilot.

Porta `LlmClient` injetável com adapters para APIs compatíveis com OpenAI
(DeepSeek, OpenAI) e Anthropic. Usa apenas a stdlib (`urllib`) para não exigir
dependência extra e permitir testes offline com o `FakeLlmClient`.

Secrets (chaves) SEMPRE por variável de ambiente — nunca no repositório.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable


class LlmError(RuntimeError):
    """Falha ao chamar o provedor de LLM."""


@runtime_checkable
class LlmClient(Protocol):
    """Porta mínima de um provedor de LLM: recebe system+user, devolve texto."""

    id: str

    def complete(self, *, system: str, user: str) -> str: ...


def _http_post_json(url: str, headers: dict[str, str], body: dict[str, Any], timeout: float) -> Any:
    """POST JSON via stdlib; levanta LlmError em falha de rede/HTTP."""
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:  # pragma: no cover - rede
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise LlmError(f"HTTP {exc.code} do provedor LLM: {detail}") from None
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:  # pragma: no cover - rede
        raise LlmError(f"Falha ao chamar o provedor LLM: {exc}") from None


class OpenAICompatibleClient:
    """Adapter para APIs compatíveis com OpenAI (DeepSeek, OpenAI, locais)."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://api.deepseek.com",
        timeout: float = 60.0,
        client_id: str = "openai_compat",
    ) -> None:
        self.id = client_id
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def complete(self, *, system: str, user: str) -> str:
        payload = _http_post_json(
            f"{self._base_url}/chat/completions",
            {
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            {
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.2,
                "stream": False,
            },
            self._timeout,
        )
        try:
            return str(payload["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:  # pragma: no cover - resposta inesperada
            raise LlmError(f"Resposta inesperada do provedor: {payload}") from exc


class AnthropicClient:
    """Adapter para a API de mensagens da Anthropic (Claude)."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://api.anthropic.com",
        timeout: float = 60.0,
        client_id: str = "anthropic",
    ) -> None:
        self.id = client_id
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def complete(self, *, system: str, user: str) -> str:
        payload = _http_post_json(
            f"{self._base_url}/v1/messages",
            {
                "x-api-key": self._api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            {
                "model": self._model,
                "max_tokens": 4096,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
            self._timeout,
        )
        try:
            return str(payload["content"][0]["text"])
        except (KeyError, IndexError, TypeError) as exc:  # pragma: no cover - resposta inesperada
            raise LlmError(f"Resposta inesperada do provedor: {payload}") from exc


class FakeLlmClient:
    """Cliente determinístico para testes/offline: devolve uma resposta canônica.

    `responder` recebe (system, user) e devolve o texto — permite simular JSON
    estruturado sem rede. Sem `responder`, devolve `default`.
    """

    def __init__(
        self,
        responder: Callable[[str, str], str] | None = None,
        *,
        default: str = "{}",
        client_id: str = "fake_llm",
    ) -> None:
        self.id = client_id
        self._responder = responder
        self._default = default
        self.calls: list[tuple[str, str]] = []

    def complete(self, *, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self._responder(system, user) if self._responder else self._default


def build_llm_client_from_env(prefix: str = "ASO_LLM") -> LlmClient | None:
    """Constrói um LlmClient a partir do ambiente, ou None se não configurado.

    Variáveis (com o prefixo dado, default `ASO_LLM`):
    - `{prefix}_PROVIDER` = openai | deepseek | anthropic
    - `{prefix}_API_KEY`, `{prefix}_MODEL`, `{prefix}_BASE_URL` (opcional)
    """
    provider = os.environ.get(f"{prefix}_PROVIDER", "").strip().lower()
    api_key = os.environ.get(f"{prefix}_API_KEY", "").strip()
    model = os.environ.get(f"{prefix}_MODEL", "").strip()
    base_url = os.environ.get(f"{prefix}_BASE_URL", "").strip()
    if not (provider and api_key and model):
        return None
    if provider == "anthropic":
        if base_url:
            return AnthropicClient(api_key=api_key, model=model, base_url=base_url)
        return AnthropicClient(api_key=api_key, model=model)
    # openai/deepseek/local — todos OpenAI-compatible.
    default_base = (
        "https://api.deepseek.com" if provider == "deepseek" else "https://api.openai.com/v1"
    )
    return OpenAICompatibleClient(
        api_key=api_key, model=model, base_url=base_url or default_base, client_id=provider
    )
