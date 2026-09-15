"""Flags de streaming e permissão de escrita por família de CLI (ADR-0076, MEL-54).

Antes, ligar o NDJSON do painel ao vivo ou dar permissão de escrita a um agente CLI era
feito por scripts que editavam a string `command` dos perfis (`enable-agent-stream.sh`,
`fix-executor-permissions.sh`): substituição de texto, frágil, e o perfil não dizia o que
estava ligado. Agora o perfil tem campos estruturados — `streaming` e `permissao_escrita` —
e as flags são montadas aqui, por família de CLI, na hora de executar.

- `aplicar_flags`: comando do perfil + campos → comando pronto (idempotente);
- `migrar_comando`: comando antigo com flags digitadas → comando limpo + campos (migração
  automática dos perfis salvos em `.aso/executors.json`; também normaliza o que um operador
  digitar no formulário).

Famílias fora de Claude Code e Codex não recebem flag nenhuma: o comando fica como está.
"""

from __future__ import annotations

import os
import shlex

FAMILIA_CLAUDE = "claude"
FAMILIA_CODEX = "codex"

# Vazio = não gerenciado: o comando decide sozinho (compatível com comandos personalizados).
PERMISSOES_DE_ESCRITA = ("", "nenhuma", "edicoes", "total")

_STREAM_CLAUDE = ["--output-format", "stream-json", "--verbose"]
_STREAM_CODEX = ["--json"]

# `total` do Claude usa a mesma flag que o script aplicava; `nenhuma` = modo plano.
_PERMISSAO_CLAUDE = {
    "nenhuma": ["--permission-mode", "plan"],
    "edicoes": ["--permission-mode", "acceptEdits"],
    "total": ["--dangerously-skip-permissions"],
}
_MODO_CLAUDE_PARA_PERMISSAO = {
    "plan": "nenhuma",
    "acceptEdits": "edicoes",
    "bypassPermissions": "total",
}

_SANDBOX_CODEX = {
    "nenhuma": "read-only",
    "edicoes": "workspace-write",
    "total": "danger-full-access",
}
_SANDBOX_PARA_PERMISSAO = {valor: chave for chave, valor in _SANDBOX_CODEX.items()}


def familia_do_comando(command: list[str] | str) -> str:
    """`claude`, `codex` ou vazio — pelo nome do executável entre os tokens (wrapper incluso)."""
    tokens = shlex.split(command) if isinstance(command, str) else command
    nomes = {os.path.basename(token) for token in tokens}
    if FAMILIA_CLAUDE in nomes:
        return FAMILIA_CLAUDE
    if FAMILIA_CODEX in nomes:
        return FAMILIA_CODEX
    return ""


def _remover_opcao(
    tokens: list[str], nome: str, *, com_valor: bool
) -> tuple[list[str], str | None]:
    """Tira `nome` (e seu valor, se houver) do comando; devolve o último valor visto."""
    resultado: list[str] = []
    valor: str | None = None
    pular = False
    for i, token in enumerate(tokens):
        if pular:
            pular = False
            continue
        if com_valor and token.startswith(f"{nome}="):
            valor = token.split("=", 1)[1]
            continue
        if token == nome:
            if com_valor and i + 1 < len(tokens):
                valor = tokens[i + 1]
                pular = True
            elif not com_valor:
                valor = ""
            continue
        resultado.append(token)
    return resultado, valor


def _limpar_claude(tokens: list[str]) -> tuple[list[str], bool, str]:
    streaming = False
    permissao = ""
    sem_formato, formato = _remover_opcao(tokens, "--output-format", com_valor=True)
    if formato == "stream-json":
        tokens = [t for t in sem_formato if t != "--verbose"]
        streaming = True
    sem_skip, skip = _remover_opcao(tokens, "--dangerously-skip-permissions", com_valor=False)
    if skip is not None:
        tokens, permissao = sem_skip, "total"
    sem_modo, modo = _remover_opcao(tokens, "--permission-mode", com_valor=True)
    if modo in _MODO_CLAUDE_PARA_PERMISSAO:
        tokens = sem_modo
        permissao = permissao or _MODO_CLAUDE_PARA_PERMISSAO[modo]
    return tokens, streaming, permissao


def _limpar_codex(tokens: list[str]) -> tuple[list[str], bool, str]:
    permissao = ""
    sem_json, json_flag = _remover_opcao(tokens, "--json", com_valor=False)
    streaming = json_flag is not None
    tokens = sem_json
    sem_bypass, bypass = _remover_opcao(
        tokens, "--dangerously-bypass-approvals-and-sandbox", com_valor=False
    )
    if bypass is not None:
        tokens, permissao = sem_bypass, "total"
    sem_sandbox, sandbox = _remover_opcao(tokens, "--sandbox", com_valor=True)
    if sandbox in _SANDBOX_PARA_PERMISSAO:
        tokens = sem_sandbox
        permissao = permissao or _SANDBOX_PARA_PERMISSAO[sandbox]
    return tokens, streaming, permissao


def migrar_comando(command: str) -> tuple[str, bool, str]:
    """Separa flags gerenciadas do comando: `(comando_limpo, streaming, permissao)`.

    Só reescreve o texto quando encontra alguma flag conhecida — comandos sem elas voltam
    idênticos (inclusive aspas). Valores desconhecidos (ex.: `--permission-mode auto`)
    ficam no comando: sem equivalente no campo, removê-los mudaria o comportamento."""
    if not command.strip():
        return command, False, ""
    try:
        tokens = shlex.split(command)
    except ValueError:
        return command, False, ""
    familia = familia_do_comando(tokens)
    if familia == FAMILIA_CLAUDE:
        limpos, streaming, permissao = _limpar_claude(tokens)
    elif familia == FAMILIA_CODEX:
        limpos, streaming, permissao = _limpar_codex(tokens)
    else:
        return command, False, ""
    if limpos == tokens:
        return command, False, ""
    return shlex.join(limpos), streaming, permissao


def aplicar_flags(command: list[str], *, streaming: bool, permissao_escrita: str) -> list[str]:
    """Comando pronto com as flags dos campos do perfil (sem duplicar o que já está lá)."""
    familia = familia_do_comando(command)
    if not familia or (not streaming and not permissao_escrita):
        return list(command)
    if familia == FAMILIA_CLAUDE:
        tokens, _, _ = _limpar_claude(list(command))
        if streaming:
            tokens.extend(_STREAM_CLAUDE)
        if permissao_escrita in _PERMISSAO_CLAUDE:
            tokens.extend(_PERMISSAO_CLAUDE[permissao_escrita])
        return tokens
    tokens, _, _ = _limpar_codex(list(command))
    if streaming:
        tokens.extend(_STREAM_CODEX)
    if permissao_escrita in _SANDBOX_CODEX:
        tokens.extend(["--sandbox", _SANDBOX_CODEX[permissao_escrita]])
    return tokens
