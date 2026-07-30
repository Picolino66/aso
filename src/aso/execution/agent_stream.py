"""Interpretação da saída em NDJSON dos agentes CLI (ADR-0015).

Um agente CLI em modo não-interativo pode falar de duas formas:

- **texto puro** (`claude -p`, sem flags): uma resposta no fim, às vezes num bloco só;
- **NDJSON evento por evento** (`claude -p --output-format stream-json`, `codex exec
  --json`): uma linha por passo — o agente pensando, chamando ferramenta, recebendo
  resultado. É isso que dá a narração "ao vivo" que se vê no terminal do Claude Code.

Este módulo traduz cada linha no que a UI precisa mostrar. Ele é **puro** (string entra,
dataclass sai), então dá para testar todos os formatos sem subir subprocess nenhum.

Princípio de projeto: **nunca inventar.** O schema do `--json` do Codex varia entre
versões do CLI, e schemas de agentes mudam sem aviso. O parser reconhece o que conhece e
devolve `bruto` — com o texto original preservado — para tudo o mais. Um formato novo
degrada para "mostra como veio", nunca para linha perdida ou exceção.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from aso.shared.agent_output import KIND_BRUTO, KIND_FERRAMENTA, KIND_RESULTADO, KIND_TEXTO

# Limite por linha na tela. Um `tool_result` com arquivo inteiro, ou um diff colado no
# meio do NDJSON, encheria o painel; a linha é uma pista, não o conteúdo.
TEXTO_MAX = 600

# O raciocínio (`thinking`) sai bem mais longo que a fala e costuma vir em inglês. Cortar
# curto preserva o sinal de "está pensando" sem empurrar as ações para fora da tela.
PENSAMENTO_MAX = 140

# Envelopes do Claude Code que não são fala do agente: handshake, contagem de tokens de
# raciocínio, aviso de rate limit, deltas incrementais. Verificado contra a saída real de
# `claude -p --output-format stream-json --verbose`; sem esta lista o painel exibiria o
# JSON cru de cada um deles.
_RUIDO = frozenset(
    {
        "system",
        "rate_limit_event",
        "stream_event",
        "control_request",
        "control_response",
        "control_cancel_request",
    }
)

# Campos onde os CLIs costumam guardar "o que a ferramenta vai mexer", em ordem de
# preferência — o primeiro que existir vira o `detail` da linha.
_CAMPOS_ALVO = ("file_path", "path", "notebook_path", "command", "pattern", "url", "query")


@dataclass(frozen=True)
class Interpretada:
    """Uma linha de saída já classificada."""

    kind: str
    text: str
    detail: str = ""


def _corta(texto: str, maximo: int = TEXTO_MAX) -> str:
    limpo = " ".join(texto.split())
    return limpo if len(limpo) <= maximo else limpo[: maximo - 1] + "…"


def _alvo(entrada: Any) -> str:
    """Extrai o alvo da ferramenta (arquivo, comando, padrão) do `input` da chamada."""
    if not isinstance(entrada, dict):
        return ""
    for campo in _CAMPOS_ALVO:
        valor = entrada.get(campo)
        if isinstance(valor, str) and valor.strip():
            return _corta(valor)
    return ""


def _blocos_claude(mensagem: dict[str, Any]) -> list[Interpretada]:
    """Converte `message.content` do Claude (lista de blocos) em linhas."""
    saida: list[Interpretada] = []
    conteudo = mensagem.get("content")
    if isinstance(conteudo, str):
        if conteudo.strip():
            saida.append(Interpretada(KIND_TEXTO, _corta(conteudo)))
        return saida
    if not isinstance(conteudo, list):
        return saida
    for bloco in conteudo:
        if not isinstance(bloco, dict):
            continue
        tipo = bloco.get("type")
        if tipo == "text":
            texto = str(bloco.get("text") or "")
            if texto.strip():
                saida.append(Interpretada(KIND_TEXTO, _corta(texto)))
        elif tipo == "thinking":
            texto = str(bloco.get("thinking") or "")
            if texto.strip():
                saida.append(Interpretada(KIND_TEXTO, _corta(texto, PENSAMENTO_MAX), "pensando"))
        elif tipo == "tool_use":
            nome = str(bloco.get("name") or "ferramenta")
            saida.append(Interpretada(KIND_FERRAMENTA, nome, _alvo(bloco.get("input"))))
        elif tipo == "tool_result":
            # O `tool_use` correspondente já contou o que foi feito; repetir o retorno
            # inteiro (arquivo lido, saída de build) afogaria o painel. Só o erro importa.
            if bloco.get("is_error"):
                saida.append(Interpretada(KIND_RESULTADO, _corta(_texto_de(bloco.get("content")))))
    return saida


def _texto_de(conteudo: Any) -> str:
    """Achata o `content` de um bloco (string, ou lista de blocos com `text`)."""
    if isinstance(conteudo, str):
        return conteudo
    if isinstance(conteudo, list):
        partes = [
            str(b.get("text") or "") for b in conteudo if isinstance(b, dict) and b.get("text")
        ]
        return " ".join(partes)
    return ""


def interpretar(linha: str) -> list[Interpretada]:
    """Traduz uma linha de saída do agente. Uma linha pode virar várias (blocos).

    Devolve lista vazia para linhas em branco e para eventos puramente estruturais
    (handshake, delta incremental) que não têm o que mostrar.
    """
    crua = linha.strip()
    if not crua:
        return []
    if not (crua.startswith("{") and crua.endswith("}")):
        return [Interpretada(KIND_BRUTO, _corta(crua))]
    try:
        evento = json.loads(crua)
    except json.JSONDecodeError:
        return [Interpretada(KIND_BRUTO, _corta(crua))]
    if not isinstance(evento, dict):
        return [Interpretada(KIND_BRUTO, _corta(crua))]

    tipo = str(evento.get("type") or "")

    # --- Claude Code (`--output-format stream-json`) -------------------------
    if tipo in {"assistant", "user"} and isinstance(evento.get("message"), dict):
        return _blocos_claude(evento["message"])
    if tipo == "result":
        # `subtype` distingue sucesso de erro; `result` traz o texto final.
        texto = str(evento.get("result") or evento.get("subtype") or "concluído")
        return [Interpretada(KIND_RESULTADO, _corta(texto))]
    if tipo in _RUIDO:
        return []

    # --- Codex (`exec --json`) ----------------------------------------------
    # O envelope observado é `{"type": "item.completed", "item": {...}}`, mas o schema
    # muda entre versões: tratamos o que reconhecemos e caímos para bruto no resto.
    item = evento.get("item")
    if isinstance(item, dict):
        item_tipo = str(item.get("type") or item.get("item_type") or "")
        if "command" in item_tipo or item.get("command"):
            comando = item.get("command")
            alvo = _corta(comando if isinstance(comando, str) else json.dumps(comando))
            return [Interpretada(KIND_FERRAMENTA, "Comando", alvo)]
        fala = item.get("text") or item.get("content") or item.get("message")
        if isinstance(fala, str) and fala.strip():
            kind = KIND_RESULTADO if "complet" in item_tipo else KIND_TEXTO
            return [Interpretada(kind, _corta(fala))]

    # Formatos genéricos: alguns CLIs mandam só `{"message": "..."}`.
    for campo in ("text", "message", "content", "delta"):
        valor = evento.get(campo)
        if isinstance(valor, str) and valor.strip():
            return [Interpretada(KIND_TEXTO, _corta(valor))]

    return [Interpretada(KIND_BRUTO, _corta(crua))]


def extrair_texto(saida: str, *, limite: int = 400) -> str:
    """Reduz a saída inteira do agente à sua **fala**, para mensagens de erro.

    Com o NDJSON ligado, o `block_reason` do card mostraria JSON cru — ilegível para quem
    abre a tela querendo saber por que o card falhou. Aqui as linhas estruturais são
    descartadas e sobra o que o agente disse, priorizando o fim (o desfecho).
    """
    falas: list[str] = []
    for linha in saida.splitlines():
        for item in interpretar(linha):
            if item.detail == "pensando":
                continue  # raciocínio interno não explica a falha ao operador
            if item.kind in {KIND_TEXTO, KIND_RESULTADO, KIND_BRUTO}:
                falas.append(item.text)
            elif item.kind == KIND_FERRAMENTA:
                falas.append(f"[{item.text} {item.detail}]".strip())
    junto = " ".join(falas).strip()
    return junto[-limite:] if len(junto) > limite else junto
