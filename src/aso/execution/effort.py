"""Esforço (effort) mapeado por tipo de executor (ADR-0073, atualiza ADR-0022).

A resolução do esforço é cuidadosa (explícito → card → etapa → orquestração → sugestão da ficha
→ perfil), mas só tinha efeito real no Codex gerenciado. A sugestão automática e a ação
`aumentar_effort` do roteamento de falha pareciam funcionar em qualquer executor sem mudar nada.

Este módulo declara, por perfil, **se** o esforço tem efeito e **como** é aplicado:

- Codex (`codex exec`): `-c model_reasoning_effort=<nível>`;
- Claude Code (`claude`): `--effort <nível>` (confirmado no `claude --help` 2.1.215);
- API OpenAI, modelos de raciocínio (`o1`/`o3`/`o4`/`gpt-5…`): `reasoning_effort`;
- API Anthropic, modelos com pensamento estendido: `thinking.budget_tokens` por nível;
- mock, DeepSeek e CLIs sem mapeamento conhecido: sem suporte — registrado, nunca fingido.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

EFFORTS_PADRAO = ("low", "medium", "high")
ORCAMENTO_DE_PENSAMENTO = {"minimal": 1024, "low": 2048, "medium": 8192, "high": 24576}
_RACIOCINIO_OPENAI = re.compile(r"^(o\d|gpt-5)", re.IGNORECASE)
_PENSAMENTO_ANTHROPIC = re.compile(
    r"claude-(3-7|(opus|sonnet|haiku|fable)-[4-9]|[a-z]+-[5-9])", re.IGNORECASE
)


@dataclass(frozen=True)
class SuporteDeEffort:
    suporta: bool
    como: str


def _nomes(comando: str | list[str]) -> list[str]:
    tokens = comando.split() if isinstance(comando, str) else comando
    return [os.path.basename(t) for t in tokens]


def suporte_de_effort(
    *, kind: str, provider: str = "", model: str = "", command: str = "", managed_by: str = ""
) -> SuporteDeEffort:
    if kind == "cli":
        nomes = _nomes(command)
        if managed_by == "codex" or ("codex" in nomes and "exec" in nomes):
            return SuporteDeEffort(True, "Codex: -c model_reasoning_effort")
        if "claude" in nomes:
            return SuporteDeEffort(True, "Claude Code: --effort")
        return SuporteDeEffort(False, "CLI sem mapeamento de esforço conhecido")
    if kind == "llm":
        if provider == "openai" and _RACIOCINIO_OPENAI.match(model or ""):
            return SuporteDeEffort(True, "OpenAI: reasoning_effort")
        if provider == "anthropic" and _PENSAMENTO_ANTHROPIC.search(model or ""):
            return SuporteDeEffort(True, "Anthropic: thinking.budget_tokens")
        return SuporteDeEffort(False, f"API {provider or 'LLM'} sem parâmetro de esforço no modelo")
    return SuporteDeEffort(False, "executor simulado")


def aplicar_effort_no_comando(
    comando: list[str], effort: str, *, managed_by: str = ""
) -> list[str]:
    """Acrescenta (ou substitui) a opção de esforço do CLI; CLI sem suporte volta igual."""
    if not effort:
        return list(comando)
    nomes = _nomes(comando)
    if managed_by == "codex" or ("codex" in nomes and "exec" in nomes):
        limpo: list[str] = []
        pular = False
        for i, token in enumerate(comando):
            if pular:
                pular = False
                continue
            proximo = comando[i + 1] if i + 1 < len(comando) else ""
            if token == "-c" and proximo.startswith("model_reasoning_effort="):
                pular = True
                continue
            limpo.append(token)
        return [*limpo, "-c", f"model_reasoning_effort={effort}"]
    if "claude" in nomes:
        resultado = list(comando)
        if "--effort" in resultado and resultado.index("--effort") + 1 < len(resultado):
            resultado[resultado.index("--effort") + 1] = effort
            return resultado
        return [*resultado, "--effort", effort]
    return list(comando)


def parametros_openai(model: str, effort: str) -> dict[str, Any]:
    if effort and _RACIOCINIO_OPENAI.match(model or ""):
        return {"reasoning_effort": effort}
    return {}


def parametros_anthropic(model: str, effort: str, max_tokens: int) -> dict[str, Any]:
    orcamento = ORCAMENTO_DE_PENSAMENTO.get(effort)
    if not orcamento or not _PENSAMENTO_ANTHROPIC.search(model or ""):
        return {}
    return {
        "thinking": {"type": "enabled", "budget_tokens": orcamento},
        # A API exige max_tokens acima do orçamento de pensamento.
        "max_tokens": max(max_tokens, orcamento + 4096),
    }
