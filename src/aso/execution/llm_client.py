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
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from aso.execution.effort import parametros_anthropic, parametros_openai
from aso.shared.agent_usage import ORIGEM_TOKENS, UsoDoAgente


class LlmError(RuntimeError):
    """Falha ao chamar o provedor de LLM."""


@dataclass(frozen=True)
class RespostaLlm:
    """Texto da resposta + consumo informado pelo provedor (ADR-0070)."""

    texto: str
    uso: UsoDoAgente = field(default_factory=UsoDoAgente)


def _int(valor: object) -> int:
    return valor if isinstance(valor, int) else 0


def uso_openai(payload: Any, modelo: str) -> UsoDoAgente:
    """`usage.{prompt_tokens, completion_tokens, prompt_tokens_details.cached_tokens}`.

    `prompt_tokens` inclui os tokens em cache: separamos para o preço de cache valer só neles."""
    usage = payload.get("usage") if isinstance(payload, dict) else None
    if not isinstance(usage, dict):
        return UsoDoAgente(modelo=modelo)
    detalhes = usage.get("prompt_tokens_details")
    cache = _int(detalhes.get("cached_tokens")) if isinstance(detalhes, dict) else 0
    return UsoDoAgente(
        tokens_entrada=max(0, _int(usage.get("prompt_tokens")) - cache),
        tokens_saida=_int(usage.get("completion_tokens")),
        tokens_cache_leitura=cache,
        modelo=str(payload.get("model") or modelo),
        origem=ORIGEM_TOKENS,
    )


def uso_anthropic(payload: Any, modelo: str) -> UsoDoAgente:
    """`usage.{input_tokens, output_tokens, cache_read_input_tokens,
    cache_creation_input_tokens}` — na Anthropic o cache não entra em `input_tokens`."""
    usage = payload.get("usage") if isinstance(payload, dict) else None
    if not isinstance(usage, dict):
        return UsoDoAgente(modelo=modelo)
    return UsoDoAgente(
        tokens_entrada=_int(usage.get("input_tokens")),
        tokens_saida=_int(usage.get("output_tokens")),
        tokens_cache_leitura=_int(usage.get("cache_read_input_tokens")),
        tokens_cache_escrita=_int(usage.get("cache_creation_input_tokens")),
        modelo=str(payload.get("model") or modelo),
        origem=ORIGEM_TOKENS,
    )


def saida_estruturada_ativa() -> bool:
    """`ASO_LLM_SAIDA_ESTRUTURADA=0` desliga o modo nativo (servidor compatível que o recusa)."""
    return os.environ.get("ASO_LLM_SAIDA_ESTRUTURADA", "1") != "0"


def completar(
    client: LlmClient, *, system: str, user: str, esquema: dict[str, Any] | None = None
) -> RespostaLlm:
    """Resposta com uso quando o cliente sabe informar; senão, só o texto (uso indisponível).

    `esquema` pede saída estruturada nativa ao provedor que a suporta (ADR-0072)."""
    metodo = getattr(client, "completar", None)
    if callable(metodo):
        resposta = (
            metodo(system=system, user=user, esquema=esquema)
            if esquema is not None
            else metodo(system=system, user=user)
        )
        if isinstance(resposta, RespostaLlm):
            return resposta
    return RespostaLlm(texto=client.complete(system=system, user=user))


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
        effort: str = "",
        provider: str = "",
    ) -> None:
        self.id = client_id
        self._effort = effort
        self._provider = provider
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def aplica_effort(self) -> bool:
        """Esforço só vale no provedor OpenAI e em modelos de raciocínio (ADR-0073)."""
        return (
            bool(self._effort)
            and self._provider in ("openai", "")
            and bool(parametros_openai(self._model, self._effort))
            and "deepseek" not in self._base_url
        )

    def complete(self, *, system: str, user: str) -> str:
        return self.completar(system=system, user=user).texto

    def completar(
        self, *, system: str, user: str, esquema: dict[str, Any] | None = None
    ) -> RespostaLlm:
        corpo: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
            "stream": False,
        }
        if self.aplica_effort():
            corpo.update(parametros_openai(self._model, self._effort))
        if esquema is not None and saida_estruturada_ativa():
            # DeepSeek só aceita `json_object`; OpenAI aceita o schema (modo não estrito, que
            # não exige `additionalProperties: false` em todo objeto).
            corpo["response_format"] = (
                {"type": "json_object"}
                if self.id == "deepseek" or "deepseek" in self._base_url
                else {"type": "json_schema", "json_schema": {"name": "resposta", "schema": esquema}}
            )
        payload = _http_post_json(
            f"{self._base_url}/chat/completions",
            {
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            corpo,
            self._timeout,
        )
        try:
            texto = str(payload["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:  # pragma: no cover - resposta inesperada
            raise LlmError(f"Resposta inesperada do provedor: {payload}") from exc
        return RespostaLlm(texto=texto, uso=uso_openai(payload, self._model))


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
        effort: str = "",
    ) -> None:
        self.id = client_id
        self._effort = effort
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def aplica_effort(self) -> bool:
        return bool(parametros_anthropic(self._model, self._effort, 4096))

    def complete(self, *, system: str, user: str) -> str:
        return self.completar(system=system, user=user).texto

    def completar(
        self, *, system: str, user: str, esquema: dict[str, Any] | None = None
    ) -> RespostaLlm:
        corpo: dict[str, Any] = {
            "model": self._model,
            "max_tokens": 4096,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        estruturada = esquema is not None and saida_estruturada_ativa()
        if not estruturada:
            # A API não aceita pensamento estendido com ferramenta forçada: saída estruturada vence.
            corpo.update(parametros_anthropic(self._model, self._effort, corpo["max_tokens"]))
        if estruturada:
            # Saída estruturada na Anthropic = uso forçado de uma ferramenta com o schema.
            corpo["tools"] = [
                {
                    "name": "responder",
                    "description": "Entrega a resposta no formato pedido.",
                    "input_schema": esquema,
                }
            ]
            corpo["tool_choice"] = {"type": "tool", "name": "responder"}
        payload = _http_post_json(
            f"{self._base_url}/v1/messages",
            {
                "x-api-key": self._api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            corpo,
            self._timeout,
        )
        try:
            if estruturada:
                bloco = next(b for b in payload["content"] if b.get("type") == "tool_use")
                texto = json.dumps(bloco["input"], ensure_ascii=False)
                return RespostaLlm(texto=texto, uso=uso_anthropic(payload, self._model))
            # Com pensamento estendido, o primeiro bloco é `thinking`: o texto é o bloco `text`.
            texto = str(
                next(b for b in payload["content"] if b.get("type", "text") == "text")["text"]
            )
        except (KeyError, IndexError, TypeError, StopIteration) as exc:  # pragma: no cover
            raise LlmError(f"Resposta inesperada do provedor: {payload}") from exc
        return RespostaLlm(texto=texto, uso=uso_anthropic(payload, self._model))


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
        uso: UsoDoAgente | None = None,
    ) -> None:
        self.id = client_id
        self._responder = responder
        self._default = default
        self._uso = uso
        self.calls: list[tuple[str, str]] = []
        self.esquemas: list[dict[str, Any] | None] = []

    def complete(self, *, system: str, user: str) -> str:
        return self.completar(system=system, user=user).texto

    def completar(
        self, *, system: str, user: str, esquema: dict[str, Any] | None = None
    ) -> RespostaLlm:
        """Com `uso`, simula o `usage` de um provedor real (testes do ADR-0070)."""
        self.calls.append((system, user))
        self.esquemas.append(esquema)
        texto = self._responder(system, user) if self._responder else self._default
        return RespostaLlm(texto=texto, uso=self._uso or UsoDoAgente())


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
