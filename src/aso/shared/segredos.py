"""Redação de segredos na saída de agente (ADR-0080, MEL-58) — regra 9 de governança.

A regra 9 diz que segredo só existe em variável de ambiente, nunca no repositório. Nada disso
impede, porém, que a **saída do agente** carregue o valor de um segredo para dentro do estado
governado: um `echo $ASO_LLM_API_KEY` no log, uma mensagem de erro do CLI com `Authorization:
Bearer …`, um `api_key=` num stack trace. Esse texto vai para evento, card, log ao vivo e
`agent_runs` — todos persistidos e servidos pela API.

Este módulo é a redação, e vive em `shared` porque é aplicada nos **pontos de entrada** do estado
governado, em camadas diferentes: `EventLog.append` (shared), `FailureRecord` e o motivo de
bloqueio do card (kanban/control), `AgentLogBus` e `AgentRun` (observability).

Duas fontes de verdade sobre o que é segredo:

1. **valores do ambiente** cujo nome parece sensível (`*KEY*`, `*TOKEN*`, `*SECRET*`, `*PASSWORD*`,
   `*SENHA*`) — o mais eficaz, porque compara o valor exato que o processo conhece;
2. **padrões conhecidos** de credencial (`sk-…`, `ghp_…`, `AKIA…`, `Bearer …`, `api_key=…`), que
   pegam segredo de terceiro que o runtime nunca viu.

A redação é irreversível de propósito: o runtime não guarda o original em lugar nenhum.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

MASCARA = "[SEGREDO REMOVIDO]"

_PADROES = (
    re.compile(r"sk-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{12,}"),
    re.compile(r"(?i)(api[_-]?key|token|secret|password|senha)\s*[=:]\s*[^\s\"',]{8,}"),
)
_NOME_SENSIVEL = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|SENHA", re.IGNORECASE)
# Valor curto não é segredo utilizável e mascará-lo estragaria texto comum ("token: 1").
_MINIMO_DO_VALOR = 8


def valores_sensiveis_do_ambiente() -> list[str]:
    """Valores de variáveis com nome sensível, dos maiores para os menores.

    A ordem importa: mascarar primeiro o valor mais longo evita que o prefixo de um segredo
    sobreviva quando dois valores se sobrepõem."""
    return sorted(
        {
            valor
            for nome, valor in os.environ.items()
            if _NOME_SENSIVEL.search(nome) and valor and len(valor) >= _MINIMO_DO_VALOR
        },
        key=len,
        reverse=True,
    )


def mascarar_segredos(texto: str) -> str:
    """Troca por `[SEGREDO REMOVIDO]` valores de ambiente sensíveis e padrões de credencial."""
    if not texto:
        return texto
    for valor in valores_sensiveis_do_ambiente():
        texto = texto.replace(valor, MASCARA)
    for padrao in _PADROES:
        texto = padrao.sub(MASCARA, texto)
    return texto


def mascarar_valor(valor: Any) -> Any:
    """Redação recursiva preservando a forma: texto é mascarado, estrutura é percorrida.

    Usado onde o conteúdo é arbitrário (payload de evento, envelope): número, booleano e `None`
    passam intactos — o segredo sempre chega como texto."""
    if isinstance(valor, str):
        return mascarar_segredos(valor)
    if isinstance(valor, dict):
        return {chave: mascarar_valor(item) for chave, item in valor.items()}
    if isinstance(valor, list):
        return [mascarar_valor(item) for item in valor]
    if isinstance(valor, tuple):
        return tuple(mascarar_valor(item) for item in valor)
    return valor


def mascarar_json(valor: dict[str, Any]) -> dict[str, Any]:
    """Mesma redação para um dicionário já serializável (compatibilidade com a ADR-0065)."""
    if not valor:
        return valor
    resultado = json.loads(mascarar_segredos(json.dumps(valor, ensure_ascii=False, default=str)))
    return resultado if isinstance(resultado, dict) else {}
