"""ContextBuilder — o contexto que cada tarefa de agente recebe (ADR-0063).

O `OrchestratorContext` era gravado por todos e lido por ninguém: nenhum provider recebia
contexto, o prompt LLM só via a demanda global e, quando havia contexto, ele era cortado
em 6.000 caracteres do JSON — podendo quebrar no meio. Saídas de F1–F4 não chegavam a F5.

Este módulo é **puro**: recebe fontes já extraídas (dados simples, sem `aso.control`) e
devolve um `ContextoDaTarefa` priorizado e com orçamento de caracteres. Regras:

1. Ordem de prioridade estrita — card → item de spec de origem → discovery aprovado →
   ficha da demanda → ADRs aceitas relacionadas → vizinhança dos arquivos citados no card
   (índice estrutural, ADR-0077) → saídas anteriores do ledger por seção.
2. O card sempre entra (sem ele o agente trabalha cego).
3. Um item nunca é cortado no meio: o primeiro que não cabe é omitido inteiro, junto com
   todos os de menor prioridade, e todos aparecem em `omitidos` (auditável).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

ORCAMENTO_PADRAO = 12_000
# Seções do ledger que carregam saídas de fases anteriores úteis à implementação.
SECOES_DO_LEDGER = ("architecture", "contracts", "engineering")


class ItemDeContexto(BaseModel):
    chave: str
    titulo: str
    conteudo: str


class ContextoDaTarefa(BaseModel):
    itens: list[ItemDeContexto] = Field(default_factory=list)
    omitidos: list[str] = Field(default_factory=list)
    tamanho: int = 0
    orcamento: int = ORCAMENTO_PADRAO


@dataclass(frozen=True)
class AdrResumida:
    id: str
    titulo: str
    decisao: str


@dataclass
class FontesDoContexto:
    """Tudo o que pode entrar no contexto, já extraído pela camada de controle."""

    card_titulo: str
    card_descricao: str = ""
    card_criterios: list[str] = field(default_factory=list)
    card_correcoes: list[str] = field(default_factory=list)
    card_contexto_adicional: list[str] = field(default_factory=list)
    item_de_spec: dict[str, Any] | None = None
    discovery_resumo: str = ""
    ficha_da_demanda: dict[str, Any] = field(default_factory=dict)
    adrs: list[AdrResumida] = field(default_factory=list)
    # Uma linha por arquivo citado no card: símbolos, quem usa e testes (ADR-0077).
    vizinhanca_do_codigo: list[str] = field(default_factory=list)
    ledger: dict[str, Any] = field(default_factory=dict)


def orcamento_configurado() -> int:
    try:
        return max(1_000, int(os.environ.get("ASO_CONTEXTO_MAX_CHARS", ORCAMENTO_PADRAO)))
    except ValueError:
        return ORCAMENTO_PADRAO


def _json(valor: Any) -> str:
    return json.dumps(valor, ensure_ascii=False, indent=1, default=str)


def _lista(titulo: str, itens: list[str]) -> str:
    return f"{titulo}:\n" + "\n".join(f"- {x}" for x in itens) if itens else ""


def _item_do_card(fontes: FontesDoContexto) -> ItemDeContexto:
    partes = [f"Título: {fontes.card_titulo}"]
    if fontes.card_descricao:
        partes.append(f"Descrição: {fontes.card_descricao}")
    for titulo, itens in (
        ("Critérios de aceite", fontes.card_criterios),
        ("Correções obrigatórias", fontes.card_correcoes),
        ("Contexto adicional do operador", fontes.card_contexto_adicional),
    ):
        if itens:
            partes.append(_lista(titulo, itens))
    return ItemDeContexto(chave="card", titulo="Card desta tarefa", conteudo="\n".join(partes))


def _candidatos(fontes: FontesDoContexto) -> list[ItemDeContexto]:
    """Itens opcionais em ordem de prioridade (o card é tratado à parte)."""
    itens: list[ItemDeContexto] = []
    if fontes.item_de_spec:
        itens.append(
            ItemDeContexto(
                chave="spec",
                titulo="Item de especificação de origem",
                conteudo=_json(fontes.item_de_spec),
            )
        )
    if fontes.discovery_resumo:
        itens.append(
            ItemDeContexto(
                chave="discovery",
                titulo="Discovery aprovado (resumo)",
                conteudo=fontes.discovery_resumo,
            )
        )
    if fontes.ficha_da_demanda:
        itens.append(
            ItemDeContexto(
                chave="demanda", titulo="Ficha da demanda", conteudo=_json(fontes.ficha_da_demanda)
            )
        )
    for adr in fontes.adrs:
        itens.append(
            ItemDeContexto(
                chave=f"adr:{adr.id}",
                titulo=f"{adr.id} — {adr.titulo}",
                conteudo=adr.decisao,
            )
        )
    if fontes.vizinhanca_do_codigo:
        itens.append(
            ItemDeContexto(
                chave="codigo",
                titulo="Vizinhança no código dos arquivos citados no card (índice)",
                conteudo="\n".join(fontes.vizinhanca_do_codigo),
            )
        )
    for secao in SECOES_DO_LEDGER:
        valor = fontes.ledger.get(secao)
        if valor:
            itens.append(
                ItemDeContexto(
                    chave=f"ledger:{secao}",
                    titulo=f"Saídas anteriores — seção {secao}",
                    conteudo=_json(valor),
                )
            )
    return itens


def _tamanho(item: ItemDeContexto) -> int:
    return len(item.titulo) + len(item.conteudo)


def construir_contexto(
    fontes: FontesDoContexto, *, orcamento: int | None = None
) -> ContextoDaTarefa:
    limite = orcamento if orcamento is not None else orcamento_configurado()
    card = _item_do_card(fontes)
    itens = [card]
    usado = _tamanho(card)
    omitidos: list[str] = []
    for item in _candidatos(fontes):
        if omitidos or usado + _tamanho(item) > limite:
            # Prioridade estrita: depois do primeiro que não coube, nada de menor
            # prioridade entra — e nada é cortado no meio.
            omitidos.append(item.chave)
            continue
        itens.append(item)
        usado += _tamanho(item)
    return ContextoDaTarefa(itens=itens, omitidos=omitidos, tamanho=usado, orcamento=limite)


def renderizar_contexto(contexto: dict[str, Any] | ContextoDaTarefa | None) -> str:
    """Bloco de texto do contexto para prompts (LLM e wrapper CLI usam o mesmo formato)."""
    if contexto is None:
        return ""
    dados = contexto.model_dump() if isinstance(contexto, ContextoDaTarefa) else contexto
    blocos = [
        f"### {item.get('titulo', '')}\n{item.get('conteudo', '')}"
        for item in dados.get("itens", [])
        if isinstance(item, dict)
    ]
    if not blocos:
        return ""
    texto = "Contexto da tarefa (priorizado):\n\n" + "\n\n".join(blocos)
    omitidos = dados.get("omitidos") or []
    if omitidos:
        texto += "\n\n(Omitido por orçamento de contexto: " + ", ".join(map(str, omitidos)) + ")"
    return texto
