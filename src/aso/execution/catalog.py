"""ExecutorCatalog — catálogo de executores selecionáveis por etapa.

Permite escolher, por fase/execução, QUAL agente rodar (Claude CLI, Codex,
DeepSeek, ou outro configurado), com MODELO e ESFORÇO (low/medium/high). Os
perfis vêm do ambiente (`ASO_EXECUTORS`, JSON) com defaults sensatos. As chaves
(secrets) nunca aparecem nas listagens — só o metadado para a UI.

Formato de `ASO_EXECUTORS` (JSON):
[
  {"name": "claude", "kind": "cli", "command": "claude -p", "model": "sonnet", "effort": "high"},
  {"name": "codex", "kind": "cli", "command": "codex exec"},
  {"name": "deepseek", "kind": "llm", "provider": "deepseek", "model": "deepseek-chat"}
]
"""

from __future__ import annotations

import json
import os
import shlex

from pydantic import BaseModel

from aso.agents.executor import ExecutionProvider, LocalMockExecutionProvider
from aso.execution.cli_provider import CliAgentExecutionProvider
from aso.execution.llm_client import AnthropicClient, LlmClient, OpenAICompatibleClient
from aso.execution.llm_provider import LlmExecutionProvider

_EFFORTS = ("low", "medium", "high")


class ExecutorProfile(BaseModel):
    """Perfil de um executor selecionável (metadado; NUNCA guarda a chave)."""

    name: str
    kind: str = "mock"  # mock | llm | cli
    provider: str = ""  # para llm: deepseek | openai | anthropic
    model: str = ""
    effort: str = "medium"  # low | medium | high
    command: str = ""  # para cli
    base_url: str = ""
    api_key_env: str = ""  # nome da env var que guarda a chave (secret fica no ambiente)
    is_default: bool = False

    def _key_env_name(self) -> str:
        return self.api_key_env or f"ASO_{self.name.upper()}_API_KEY"

    def public(self) -> dict[str, object]:
        """Representação para a UI/API — inclui status da chave, nunca o segredo."""
        key_env = self._key_env_name()
        has_key = bool(os.environ.get(key_env) or os.environ.get("ASO_LLM_API_KEY"))
        return {
            "name": self.name,
            "kind": self.kind,
            "provider": self.provider,
            "model": self.model,
            "effort": self.effort,
            "efforts": list(_EFFORTS),
            "command": self.command,
            "base_url": self.base_url,
            "api_key_env": key_env,
            "has_key": has_key if self.kind == "llm" else True,
            "is_default": self.is_default,
        }


class ExecutorCatalog:
    """Registra perfis de executor e constrói o provider concreto sob demanda."""

    def __init__(self, profiles: list[ExecutorProfile] | None = None) -> None:
        self._profiles: dict[str, ExecutorProfile] = {}
        for p in profiles or []:
            self._profiles[p.name] = p
        if "mock" not in self._profiles:
            self._profiles["mock"] = ExecutorProfile(name="mock", kind="mock")

    # -------------------------------------------------------------- consulta
    def entries(self) -> list[dict[str, object]]:
        return [p.public() for p in self._profiles.values()]

    def profiles(self) -> list[ExecutorProfile]:
        return list(self._profiles.values())

    def get(self, name: str) -> ExecutorProfile | None:
        return self._profiles.get(name)

    # -------------------------------------------------------------- edição
    def upsert(self, profile: ExecutorProfile) -> None:
        """Cria/atualiza um perfil. Se marcado default, desmarca os demais."""
        if profile.is_default:
            for p in self._profiles.values():
                p.is_default = False
        self._profiles[profile.name] = profile

    def remove(self, name: str) -> None:
        if name == "mock":
            raise ValueError("O executor 'mock' não pode ser removido.")
        self._profiles.pop(name, None)

    def default_name(self) -> str:
        for p in self._profiles.values():
            if p.is_default:
                return p.name
        return next(iter(self._profiles))

    # -------------------------------------------------------------- construção
    def build(self, name: str) -> ExecutionProvider:
        """Constrói o provider do perfil (lê secrets do ambiente). Levanta se faltar."""
        profile = self._profiles.get(name)
        if profile is None:
            raise KeyError(f"Executor desconhecido: {name}")
        if profile.kind == "mock":
            return LocalMockExecutionProvider()
        if profile.kind == "cli":
            repo = os.environ.get("ASO_TARGET_REPO")
            if not (profile.command and repo):
                raise ValueError(f"Executor CLI '{name}' exige command + ASO_TARGET_REPO.")
            return CliAgentExecutionProvider(
                shlex.split(profile.command), repo, executor_id=profile.name
            )
        if profile.kind == "llm":
            key = os.environ.get(profile._key_env_name()) or os.environ.get("ASO_LLM_API_KEY")
            if not (key and profile.model):
                raise ValueError(f"Executor LLM '{name}' exige API key + model.")
            client: LlmClient
            if profile.provider == "anthropic":
                base = profile.base_url or "https://api.anthropic.com"
                client = AnthropicClient(
                    api_key=key, model=profile.model, base_url=base, client_id=name
                )
            else:
                default_base = (
                    "https://api.deepseek.com"
                    if profile.provider == "deepseek"
                    else "https://api.openai.com/v1"
                )
                client = OpenAICompatibleClient(
                    api_key=key,
                    model=profile.model,
                    base_url=profile.base_url or default_base,
                    client_id=name,
                )
            return LlmExecutionProvider(client, executor_id=f"llm:{name}")
        raise ValueError(f"Tipo de executor inválido: {profile.kind}")


def build_catalog_from_env() -> ExecutorCatalog:
    """Monta o catálogo a partir de `ASO_EXECUTORS` (+ defaults do ambiente)."""
    profiles: list[ExecutorProfile] = []
    raw = os.environ.get("ASO_EXECUTORS")
    if raw:
        try:
            for item in json.loads(raw):
                profiles.append(ExecutorProfile.model_validate(item))
        except (json.JSONDecodeError, ValueError):
            profiles = []
    # Defaults derivados do ambiente, se nenhum perfil explícito cobrir.
    names = {p.name for p in profiles}
    if os.environ.get("ASO_LLM_PROVIDER") and "llm" not in names:
        profiles.append(
            ExecutorProfile(
                name="llm",
                kind="llm",
                provider=os.environ.get("ASO_LLM_PROVIDER", ""),
                model=os.environ.get("ASO_LLM_MODEL", ""),
            )
        )
    if os.environ.get("ASO_CLI_COMMAND") and "cli" not in names:
        profiles.append(
            ExecutorProfile(name="cli", kind="cli", command=os.environ.get("ASO_CLI_COMMAND", ""))
        )
    # Marca um default (o primeiro não-mock, se houver).
    if profiles and not any(p.is_default for p in profiles):
        profiles[0].is_default = True
    return ExecutorCatalog(profiles)
