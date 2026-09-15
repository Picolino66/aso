"""MEL-19 — ContextBuilder: prioridade, orçamento e omissão inteira (ADR-0063)."""

from __future__ import annotations

from typing import Any

from aso.agents import render_prompt
from aso.agents.context_builder import (
    AdrResumida,
    FontesDoContexto,
    construir_contexto,
    renderizar_contexto,
)
from aso.agents.executor import AgentSpec
from aso.execution.llm_provider import LlmExecutionProvider


def _fontes(**extra: Any) -> FontesDoContexto:
    base: dict[str, Any] = {
        "card_titulo": "Calcular frete",
        "card_descricao": "Tabela por CEP",
        "card_criterios": ["CEP inválido retorna 422"],
        "card_correcoes": ["faltou teste de CEP vazio"],
        "card_contexto_adicional": ["não mude a API pública"],
        "item_de_spec": {"titulo": "Calcular frete", "fase": "F5"},
        "discovery_resumo": "Problema: frete manual",
        "ficha_da_demanda": {"objetivo": "Automatizar frete"},
        "adrs": [AdrResumida(id="ADR-0002", titulo="Postgres", decisao="Usar Postgres")],
        "ledger": {"architecture": {"pattern": "modular-monolith"}},
    }
    base.update(extra)
    return FontesDoContexto(**base)


def test_ordem_de_prioridade_dos_itens() -> None:
    contexto = construir_contexto(_fontes(), orcamento=100_000)
    assert [i.chave for i in contexto.itens] == [
        "card",
        "spec",
        "discovery",
        "demanda",
        "adr:ADR-0002",
        "ledger:architecture",
    ]
    assert contexto.omitidos == []
    card = contexto.itens[0].conteudo
    for trecho in ("Calcular frete", "CEP inválido", "CEP vazio", "API pública"):
        assert trecho in card


def test_acima_do_orcamento_omite_itens_inteiros_de_menor_prioridade() -> None:
    enorme = "x" * 5_000
    contexto = construir_contexto(_fontes(discovery_resumo=enorme), orcamento=1_500)
    chaves = [i.chave for i in contexto.itens]
    assert chaves == ["card", "spec"]
    # Discovery não coube → ele e todos os de menor prioridade ficam de fora, inteiros.
    assert contexto.omitidos == ["discovery", "demanda", "adr:ADR-0002", "ledger:architecture"]
    assert all(enorme not in i.conteudo for i in contexto.itens)
    assert contexto.tamanho <= 1_500


def test_nenhum_item_e_cortado_no_meio() -> None:
    ledger = {"architecture": {"k": "v" * 900}}
    contexto = construir_contexto(_fontes(ledger=ledger), orcamento=100_000)
    item = next(i for i in contexto.itens if i.chave == "ledger:architecture")
    assert "v" * 900 in item.conteudo


def test_card_sempre_entra_mesmo_com_orcamento_minimo() -> None:
    contexto = construir_contexto(_fontes(), orcamento=10)
    assert [i.chave for i in contexto.itens] == ["card"]
    assert "spec" in contexto.omitidos


def test_renderizador_do_wrapper_e_do_llm_produzem_o_mesmo_texto() -> None:
    contexto = construir_contexto(_fontes(discovery_resumo="y" * 3_000), orcamento=2_000)
    dump = contexto.model_dump()
    assert renderizar_contexto(contexto) == render_prompt._renderizar_contexto(dump)  # noqa: SLF001
    assert "Omitido por orçamento" in renderizar_contexto(dump)


class _LlmEspiao:
    id = "espiao"

    def __init__(self) -> None:
        self.user = ""

    def complete(self, *, system: str, user: str) -> str:
        self.user = user
        return '{"summary": "ok", "content": {"feito": true}}'


def test_prompt_llm_contem_titulo_criterios_correcoes_e_contexto() -> None:
    contexto = construir_contexto(_fontes(), orcamento=100_000)
    tarefa = {
        "orchestration_id": "orch_x",
        "card_id": "card_x",
        "phase": "F5",
        "target_path": "engineering.card_x",
        "content": {"request": "frete"},
        "envelope": {"contexto": contexto.model_dump()},
    }
    espiao = _LlmEspiao()
    LlmExecutionProvider(espiao).execute(  # type: ignore[arg-type]
        AgentSpec(role="BackendDevelopmentAgent"), tarefa
    )
    for trecho in (
        "Calcular frete",
        "CEP inválido retorna 422",
        "faltou teste de CEP vazio",
        "modular-monolith",
        "ADR-0002",
    ):
        assert trecho in espiao.user
