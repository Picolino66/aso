"""ExecutorCatalog — catálogo de executores selecionáveis por etapa.

Permite escolher, por fase/execução, QUAL agente rodar (Claude CLI, Codex,
DeepSeek, ou outro configurado), com MODELO e ESFORÇO (low/medium/high). Os
perfis vêm do ambiente (`ASO_EXECUTORS`, JSON) com defaults sensatos. As chaves
(secrets) nunca aparecem nas listagens — só o metadado para a UI.

Fonte única de executores em tempo de execução (ADR-0076, MEL-54): variáveis de ambiente
(`ASO_EXECUTORS`, `ASO_LLM_*`, `ASO_CLI_COMMAND`, `ASO_CANDIDATE_COMMANDS`) só **semeiam** o
catálogo enquanto não há catálogo salvo (`build_catalog_from_env`); depois, vale o que está em
`.aso/executors.json`. Nenhum outro módulo lê essas variáveis.

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
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

from aso.agents.executor import ExecutionProvider, LocalMockExecutionProvider
from aso.execution.cli_provider import CliAgentExecutionProvider
from aso.execution.effort import SuporteDeEffort, aplicar_effort_no_comando, suporte_de_effort
from aso.execution.flags_de_cli import (
    PERMISSOES_DE_ESCRITA,
    aplicar_flags,
    familia_do_comando,
    migrar_comando,
)
from aso.execution.llm_client import AnthropicClient, LlmClient, OpenAICompatibleClient
from aso.execution.llm_provider import LlmExecutionProvider
from aso.shared.agent_output import OutputBus

_EFFORTS = ("low", "medium", "high")
# Seeds Codex estáticos antigos: mantidos para marcar perfis legados como indisponíveis
# (MEL-53, ADR-0075) — revisar para remoção a partir de 2027-03-15.
_LEGACY_CODEX_NAMES = {
    f"codex-{model}-{effort}"
    for model in ("gpt-5-codex", "gpt-5", "o4-mini")
    for effort in _EFFORTS
}


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
    managed_by: str = ""  # vazio = perfil administrativo; "codex" = sincronizado
    supported_efforts: list[str] = Field(default_factory=list)
    available: bool = True
    availability_reason: str = ""
    runtime_version: str = ""
    # Campos estruturados no lugar de flags digitadas no comando (ADR-0076): o catálogo monta
    # as flags por família de CLI em `cli_command`.
    streaming: bool = False  # NDJSON evento por evento para o painel ao vivo (ADR-0015)
    permissao_escrita: str = ""  # "" (não gerenciada) | nenhuma | edicoes | total
    candidato: bool = False  # participa da corrida de candidatos sem lista explícita (req §26A.6)

    @model_validator(mode="after")
    def _normalizar_flags(self) -> ExecutorProfile:
        """Flags de streaming/permissão digitadas no comando viram campos (migração idempotente).

        Roda em toda validação — perfil salvo antigo, formulário ou `ASO_EXECUTORS` —, então
        há uma única representação: o comando sem essas flags e os campos ligados."""
        if self.permissao_escrita not in PERMISSOES_DE_ESCRITA:
            raise ValueError(
                f"permissao_escrita inválida: '{self.permissao_escrita}' "
                "(use nenhuma, edicoes ou total)."
            )
        if self.kind == "cli" and self.command:
            limpo, streaming, permissao = migrar_comando(self.command)
            if limpo != self.command:
                self.command = limpo
                self.streaming = self.streaming or streaming
                self.permissao_escrita = self.permissao_escrita or permissao
        return self

    def suporte_de_effort(self) -> SuporteDeEffort:
        """Se o esforço escolhido tem efeito neste executor, e como (ADR-0073)."""
        return suporte_de_effort(
            kind=self.kind,
            provider=self.provider,
            model=self.model,
            command=self.command,
            managed_by=self.managed_by,
        )

    def _key_env_name(self) -> str:
        return self.api_key_env or f"ASO_{self.name.upper()}_API_KEY"

    def public(self) -> dict[str, object]:
        """Representação para a UI/API — inclui status da chave, nunca o segredo."""
        key_env = self._key_env_name()
        has_key = bool(os.environ.get(key_env))
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
            "managed_by": self.managed_by,
            "supported_efforts": self.supported_efforts or list(_EFFORTS),
            # ADR-0073: o console avisa quando o esforço não muda nada neste executor.
            "suporta_effort": self.suporte_de_effort().suporta,
            "effort_como": self.suporte_de_effort().como,
            "available": self.available,
            "availability_reason": self.availability_reason,
            "runtime_version": self.runtime_version,
            "streaming": self.streaming,
            "permissao_escrita": self.permissao_escrita,
            "candidato": self.candidato,
            # Família reconhecida = os campos acima têm efeito; vazio = comando livre.
            "familia_cli": familia_do_comando(self.command) if self.kind == "cli" else "",
        }


class ExecutorCatalog:
    """Registra perfis de executor e constrói o provider concreto sob demanda."""

    def __init__(self, profiles: list[ExecutorProfile] | None = None) -> None:
        self._profiles: dict[str, ExecutorProfile] = {}
        for p in profiles or []:
            if p.name in _LEGACY_CODEX_NAMES and not p.managed_by:
                p.managed_by = "codex"
                p.available = False
                p.availability_reason = (
                    "perfil legado com modelo estático; sincronize o catálogo Codex"
                )
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

    def replace_managed_codex(self, profiles: list[ExecutorProfile]) -> None:
        """Substitui somente perfis Codex gerenciados e os seeds legados conhecidos.

        A escolha do operador sobre streaming, permissão e candidatura sobrevive à
        sincronização: só modelo, esforços e versão vêm da descoberta."""
        anteriores: dict[str, ExecutorProfile] = {}
        for name, profile in list(self._profiles.items()):
            if profile.managed_by == "codex" or name in _LEGACY_CODEX_NAMES:
                anteriores[name] = profile
                self._profiles.pop(name, None)
        for profile in profiles:
            antigo = anteriores.get(profile.name)
            if antigo is not None:
                profile.streaming = antigo.streaming
                profile.candidato = antigo.candidato
                profile.permissao_escrita = antigo.permissao_escrita or profile.permissao_escrita
            self.upsert(profile)

    def validate(self, name: str, effort: str | None = None) -> ExecutorProfile:
        """Falha antes do worktree quando perfil/modelo/esforço não é utilizável."""
        profile = self._profiles.get(name)
        if profile is None:
            raise ValueError(f"Executor desconhecido: {name}")
        if not profile.available:
            reason = profile.availability_reason or "indisponível no runtime atual"
            raise ValueError(f"Executor '{name}' indisponível: {reason}")
        selected_effort = effort or profile.effort
        supported = profile.supported_efforts or list(_EFFORTS)
        if profile.managed_by == "codex" and selected_effort not in supported:
            raise ValueError(
                f"Esforço '{selected_effort}' não é aceito por {name}; use: {', '.join(supported)}."
            )
        return profile

    def llm_padrao(self) -> str | None:
        """Executor LLM usado quando nenhum foi atribuído (planejamento, ADR-0076).

        Entre os LLMs disponíveis com chave no ambiente, o default vem primeiro; sem nenhum
        com chave, não há LLM padrão (planejar exige chave de verdade)."""
        llms = sorted(
            (p for p in self._profiles.values() if p.kind == "llm" and p.available),
            key=lambda p: not p.is_default,
        )
        com_chave = next((p for p in llms if os.environ.get(p._key_env_name())), None)
        return com_chave.name if com_chave is not None else None

    def default_sem_pasta(self) -> str | None:
        """Padrão utilizável por orquestração sem pasta: CLI só com `ASO_TARGET_REPO`."""
        perfil = self._profiles.get(self.default_name())
        if perfil is None or perfil.kind == "mock" or not perfil.available:
            return None
        if perfil.kind == "cli" and not os.environ.get("ASO_TARGET_REPO"):
            return None
        return perfil.name

    def default_name(self) -> str:
        for p in self._profiles.values():
            if p.is_default:
                return p.name
        return next(iter(self._profiles))

    # -------------------------------------------------------------- construção
    def build(
        self,
        name: str,
        *,
        repo_override: str | None = None,
        effort_override: str | None = None,
        log_bus: OutputBus | None = None,
    ) -> ExecutionProvider:
        """Constrói o provider do perfil (lê secrets do ambiente). Levanta se faltar.

        `repo_override` é a pasta da orquestração (workspace); quando informado,
        substitui o `ASO_TARGET_REPO` global para os executores CLI. `log_bus` liga o
        painel ao vivo (ADR-0015); sem ele a execução funciona igual, só sem streaming.
        """
        try:
            profile = self.validate(name, effort_override)
        except ValueError as exc:
            if name not in self._profiles:
                raise KeyError(str(exc)) from exc
            raise
        if profile.kind == "mock":
            return LocalMockExecutionProvider()
        if profile.kind == "cli":
            repo = repo_override or os.environ.get("ASO_TARGET_REPO")
            if not repo:
                raise ValueError(
                    f"Executor CLI '{name}' exige command + pasta da orquestração "
                    "(ou ASO_TARGET_REPO)."
                )
            command = self.cli_command(name, effort_override=effort_override)
            return CliAgentExecutionProvider(
                command, repo, executor_id=profile.name, log_bus=log_bus, modelo=profile.model
            )
        if profile.kind == "llm":
            return LlmExecutionProvider(
                self.llm_client(name, effort_override=effort_override), executor_id=f"llm:{name}"
            )
        raise ValueError(f"Tipo de executor inválido: {profile.kind}")

    def cli_command(self, name: str, *, effort_override: str | None = None) -> list[str]:
        """Comando CLI pronto do perfil, já com modelo/esforço quando gerenciado.

        Exposto separadamente do `build` porque nem todo uso de um agente CLI cria
        worktree: o nomeador (ADR-0014) só quer uma resposta em texto.
        """
        profile = self.validate(name, effort_override)
        if profile.kind != "cli" or not profile.command:
            raise ValueError(f"Executor '{name}' não é um agente CLI com comando definido.")
        command = aplicar_flags(
            shlex.split(profile.command),
            streaming=profile.streaming,
            permissao_escrita=profile.permissao_escrita,
        )
        if profile.managed_by == "codex" and profile.model:
            command.extend(["-m", profile.model])
        # Esforço aplicado pela opção do próprio CLI (Codex, Claude Code); outros ficam iguais.
        return aplicar_effort_no_comando(
            command, effort_override or profile.effort, managed_by=profile.managed_by
        )

    def llm_client(self, name: str, *, effort_override: str | None = None) -> LlmClient:
        """Cliente LLM do perfil (lê a chave do ambiente). Levanta se faltar."""
        profile = self.validate(name, effort_override)
        if profile.kind != "llm":
            raise ValueError(f"Executor '{name}' não é do tipo llm.")
        key = os.environ.get(profile._key_env_name())
        if not (key and profile.model):
            raise ValueError(f"Executor LLM '{name}' exige API key + model.")
        if profile.provider == "anthropic":
            base = profile.base_url or "https://api.anthropic.com"
            return AnthropicClient(
                api_key=key,
                model=profile.model,
                base_url=base,
                client_id=name,
                effort=effort_override or profile.effort,
            )
        default_base = (
            "https://api.deepseek.com"
            if profile.provider == "deepseek"
            else "https://api.openai.com/v1"
        )
        return OpenAICompatibleClient(
            api_key=key,
            model=profile.model,
            base_url=profile.base_url or default_base,
            client_id=name,
            effort=effort_override or profile.effort,
            provider=profile.provider,
        )


def build_catalog_from_env() -> ExecutorCatalog:
    """Semeia o catálogo a partir do ambiente — só usado enquanto não há catálogo salvo.

    Único ponto do runtime que lê `ASO_EXECUTORS`, `ASO_LLM_*`, `ASO_CLI_COMMAND` e
    `ASO_CANDIDATE_COMMANDS` (ADR-0076). Perfis explícitos de `ASO_EXECUTORS` vencem os
    derivados das outras variáveis quando o nome coincide."""
    profiles: list[ExecutorProfile] = []
    raw = os.environ.get("ASO_EXECUTORS")
    if raw:
        try:
            for item in json.loads(raw):
                profiles.append(ExecutorProfile.model_validate(item))
        except (json.JSONDecodeError, ValueError):
            profiles = []
    names = {p.name for p in profiles}
    # CLI antes do LLM: sem `is_default` explícito, o primeiro vira padrão — como o provider
    # global antigo, código vai para o CLI; o LLM segue como planejador (`llm_padrao`).
    if os.environ.get("ASO_CLI_COMMAND") and "cli" not in names:
        profiles.append(
            ExecutorProfile(name="cli", kind="cli", command=os.environ.get("ASO_CLI_COMMAND", ""))
        )
    provider = os.environ.get("ASO_LLM_PROVIDER", "").strip().lower()
    if provider and "llm" not in names:
        profiles.append(
            ExecutorProfile(
                name="llm",
                kind="llm",
                provider=provider,
                model=os.environ.get("ASO_LLM_MODEL", "").strip(),
                base_url=os.environ.get("ASO_LLM_BASE_URL", "").strip(),
                # A chave continua no ambiente; o perfil só guarda o NOME da variável.
                api_key_env=_ENV_CHAVE_LLM_LEGADA,
            )
        )
    profiles.extend(_candidatos_do_ambiente({p.name for p in profiles}))
    # Marca um default (o primeiro não-mock, se houver).
    if profiles and not any(p.is_default for p in profiles):
        profiles[0].is_default = True
    return ExecutorCatalog(profiles)


_ENV_CHAVE_LLM_LEGADA = "ASO_LLM_API_KEY"


def _candidatos_do_ambiente(existentes: set[str]) -> list[ExecutorProfile]:
    """`ASO_CANDIDATE_COMMANDS` vira perfis CLI marcados `candidato` (antes: lista paralela).

    Cada item é o comando (id `cli_N`) ou `{"id": ..., "command": ...}`."""
    raw = os.environ.get("ASO_CANDIDATE_COMMANDS")
    if not raw:
        return []
    try:
        spec = json.loads(raw)
    except json.JSONDecodeError:
        return []
    perfis: list[ExecutorProfile] = []
    for i, item in enumerate(spec if isinstance(spec, list) else []):
        if isinstance(item, str):
            nome, comando = f"cli_{i + 1}", item
        elif isinstance(item, dict) and item.get("command"):
            nome, comando = str(item.get("id") or f"cli_{i + 1}"), str(item["command"])
        else:
            continue
        existente = next((p for p in perfis if p.name == nome), None)
        if nome in existentes or existente is not None:
            continue
        perfis.append(ExecutorProfile(name=nome, kind="cli", command=comando, candidato=True))
    return perfis


def migrar_perfis_salvos(profiles: list[ExecutorProfile]) -> list[ExecutorProfile]:
    """Ajustes de perfis gravados antes da ADR-0076 que dependem do ambiente.

    As flags do comando já foram convertidas na validação do perfil; aqui só sobra a chave:
    perfil LLM sem `api_key_env` usava a variável global `ASO_LLM_API_KEY` como reserva, e a
    reserva saiu do runtime. Para não perder o acesso, o perfil passa a apontar para ela —
    a menos que a variável própria (`ASO_<NOME>_API_KEY`) exista."""
    for perfil in profiles:
        if perfil.kind == "llm" and not perfil.api_key_env:
            propria = perfil._key_env_name()
            if not os.environ.get(propria):
                perfil.api_key_env = _ENV_CHAVE_LLM_LEGADA
    return profiles


def managed_codex_profiles(
    capabilities: object, *, wrapper: str | None = None
) -> list[ExecutorProfile]:
    """Converte a descoberta numa coleção persistível de perfis seguros."""
    from aso.execution.codex_discovery import CodexCapabilities

    if not isinstance(capabilities, CodexCapabilities):
        raise TypeError("Capacidades Codex inválidas.")
    if wrapper is None:
        root = Path(__file__).resolve().parents[3]
        wrapper = os.environ.get("ASO_AGENT_WRAPPER", str(root / "scripts/aso-agent-wrapper.sh"))
    # A configuração pessoal pode fixar um modelo novo demais para o binário no PATH.
    # A autenticação continua no CODEX_HOME, mas modelo/esforço vêm do catálogo descoberto.
    # Permissão `edicoes` (= `--sandbox workspace-write`, ADR-0076) é obrigatória: com
    # `--ignore-user-config` o sandbox do config.toml pessoal é descartado e o Codex cairia em
    # read-only — responderia em texto, sairia com 0 e deixaria o worktree intacto (diff vazio).
    # Escrita fica contida no worktree isolado do card, a fronteira de governança (regra 5 ·
    # ADR-0009).
    base_command = shlex.join([wrapper, capabilities.binary, "exec", "--ignore-user-config"])
    default_model = next((m for m in capabilities.models if m.is_default), capabilities.models[0])
    profiles = [
        ExecutorProfile(
            name="codex-default",
            kind="cli",
            command=base_command,
            effort=default_model.default_effort,
            supported_efforts=list(default_model.supported_efforts),
            is_default=True,
            managed_by="codex",
            permissao_escrita="edicoes",
            runtime_version=capabilities.version,
        )
    ]
    profiles.extend(
        ExecutorProfile(
            name=f"codex-{model.model}",
            kind="cli",
            model=model.model,
            command=base_command,
            effort=model.default_effort,
            supported_efforts=list(model.supported_efforts),
            managed_by="codex",
            permissao_escrita="edicoes",
            runtime_version=capabilities.version,
        )
        for model in capabilities.models
    )
    return profiles
