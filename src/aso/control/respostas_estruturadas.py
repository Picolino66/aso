"""Respostas estruturadas das funções de agente: JSON Schema gerado do modelo (ADR-0072, MEL-42).

Antes, cada prompt de sistema trazia o formato JSON escrito à mão ("na forma: {...}") e a lista
de valores aceitos em texto — podia divergir do modelo que lia a resposta, e o parsing frouxo
era compensado por `_sanear` extensos. Agora o formato vem do **modelo Pydantic de resposta**:

- `instrucao_de_formato` gera o trecho do prompt a partir de `model_json_schema()`;
- o `TaskEnvelope` leva o mesmo schema em `output_schema` (agentes CLI);
- os adapters de API usam saída estruturada nativa quando existe;
- `validar` aponta o campo exato que falhou, e `pedido_de_correcao` monta a única nova tentativa.

Vocabulários fechados aparecem como `enum` no schema (guiam o agente), mas a regra de negócio —
o que fazer com um valor fora do vocabulário — continua no `_sanear` de cada serviço.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field, JsonValue, ValidationError

TENTATIVAS_DE_CORRECAO = 1


class RespostaInvalida(ValueError):
    """A resposta do agente não segue o schema; `campos` diz exatamente onde."""

    def __init__(self, campos: list[str]) -> None:
        self.campos = campos
        super().__init__("resposta fora do schema: " + "; ".join(campos))


def vocabulario(valores: frozenset[str] | set[str] | list[str], descricao: str = "") -> Any:
    """Campo texto cujo schema declara os valores aceitos (`enum`), sem validar no parse."""
    return Field(
        default="",
        description=descricao or None,
        json_schema_extra={"enum": list[JsonValue](sorted(valores))},
    )


def lista_de_vocabulario(valores: frozenset[str] | set[str], descricao: str = "") -> Any:
    return Field(
        default_factory=list,
        description=descricao or None,
        json_schema_extra={"items": {"type": "string", "enum": list[JsonValue](sorted(valores))}},
    )


def esquema_de(modelo: type[BaseModel]) -> dict[str, Any]:
    return modelo.model_json_schema()


def instrucao_de_formato(modelo: type[BaseModel]) -> str:
    return (
        "Responda SOMENTE com um objeto JSON válido, sem cercas de código, que siga este "
        "JSON Schema (campos, tipos e valores aceitos):\n"
        + json.dumps(esquema_de(modelo), ensure_ascii=False)
    )


def validar(modelo: type[BaseModel], bruto: dict[str, object]) -> dict[str, object]:
    """Valida contra o modelo; devolve o dicionário original (o `_sanear` segue igual)."""
    try:
        modelo.model_validate(bruto)
    except ValidationError as exc:
        campos = [
            f"{'.'.join(str(p) for p in erro['loc']) or '(raiz)'}: {erro['msg']}"
            for erro in exc.errors()
        ]
        raise RespostaInvalida(campos[:10]) from None
    return bruto


def pedido_de_correcao(pedido: str, erro: RespostaInvalida) -> str:
    return (
        f"{pedido}\n\nSua resposta anterior não seguiu o schema pedido — "
        f"{'; '.join(erro.campos)}. Responda de novo, somente com o JSON corrigido."
    )
