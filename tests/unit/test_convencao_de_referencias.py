"""MEL-06 — referências a documento sempre qualificadas.

`§13` era ambíguo: existe em `requerimentos.md` (padrões multiagente), em `fluxo.md`
(tratamento de falhas nos testes) e em `wiframe-fluxo.md` (Tela 11). A convenção é
`req §n`, `fluxo §n`, `wf §n`, `ADR-NNNN` ou `MEL-NN §n`; este teste é o que impede a
volta do `§` solto e das referências a arquivos que não existem no repositório.
"""

from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
SRC = RAIZ / "src" / "aso"

# Prefixos aceitos imediatamente antes de um `§`.
QUALIFICADO = re.compile(r"(?:req|fluxo|wf|ADR-\d{4}|MEL-\d+)\s+§")
REFERENCIA = re.compile(r"§\s?\d")
# Documentos de planejamento que foram consolidados em ADRs e não existem no repositório.
MORTAS = re.compile(r"\bplano\d")


def _arquivos() -> list[Path]:
    return sorted(SRC.rglob("*.py"))


def test_nenhuma_referencia_de_secao_sem_documento() -> None:
    soltas: list[str] = []
    for arquivo in _arquivos():
        for numero, linha in enumerate(arquivo.read_text(encoding="utf-8").split("\n"), 1):
            for m in REFERENCIA.finditer(linha):
                if QUALIFICADO.search(linha[max(0, m.start() - 12) : m.end()]):
                    continue
                soltas.append(f"{arquivo.relative_to(RAIZ)}:{numero}: {linha.strip()[:100]}")
    assert soltas == [], "referências §n sem documento (use req/fluxo/wf/ADR/MEL):\n" + "\n".join(
        soltas[:20]
    )


def test_nenhuma_referencia_a_documento_inexistente() -> None:
    """`planoN.md` nunca entrou no repositório: o que importa deles está em ADR."""
    mortas: list[str] = []
    for arquivo in _arquivos():
        for numero, linha in enumerate(arquivo.read_text(encoding="utf-8").split("\n"), 1):
            if MORTAS.search(linha):
                mortas.append(f"{arquivo.relative_to(RAIZ)}:{numero}: {linha.strip()[:100]}")
    assert mortas == [], "referências a plano*.md (aponte para a ADR):\n" + "\n".join(mortas[:20])


def test_documentos_referenciados_existem() -> None:
    for nome in ("requerimentos.md", "fluxo.md", "wiframe-fluxo.md"):
        assert (RAIZ / nome).is_file(), nome


def test_prefixo_nao_se_repete_na_mesma_referencia() -> None:
    """`fluxo §5/§6`, não `fluxo §5/fluxo §6` — a lista fica ilegível."""
    repetidos: list[str] = []
    padrao = re.compile(r"(req|fluxo|wf) §[\d.]+\s*/\s*(req|fluxo|wf) §")
    for arquivo in _arquivos():
        for numero, linha in enumerate(arquivo.read_text(encoding="utf-8").split("\n"), 1):
            if padrao.search(linha):
                repetidos.append(f"{arquivo.relative_to(RAIZ)}:{numero}")
    assert repetidos == [], "prefixo repetido:\n" + "\n".join(repetidos[:20])


def test_secao_citada_existe_no_documento() -> None:
    """Qualificar sem conferir seria trocar ambiguidade por erro: a seção tem de existir."""
    numeros: dict[str, set[str]] = {}
    for chave, nome in (
        ("req", "requerimentos.md"),
        ("fluxo", "fluxo.md"),
        ("wf", "wiframe-fluxo.md"),
    ):
        encontrados: set[str] = set()
        for linha in (RAIZ / nome).read_text(encoding="utf-8").split("\n"):
            m = re.match(r"^#+\s+(?:§\s?)?(\d+(?:\.\d+)*)", linha.strip())
            if m:
                encontrados.add(m.group(1))
                encontrados.add(m.group(1).split(".")[0])
        numeros[chave] = encontrados

    inexistentes: list[str] = []
    padrao = re.compile(r"(req|fluxo|wf) §\s?(\d+(?:\.\d+)*)")
    for arquivo in _arquivos():
        for numero, linha in enumerate(arquivo.read_text(encoding="utf-8").split("\n"), 1):
            for m in padrao.finditer(linha):
                doc, secao = m.group(1), m.group(2)
                # `§26A.6` e afins: o sufixo com letra não é numeração de título
                if secao in numeros[doc] or secao.split(".")[0] in numeros[doc]:
                    continue
                inexistentes.append(
                    f"{arquivo.relative_to(RAIZ)}:{numero}: {doc} §{secao} não existe"
                )
    assert inexistentes == [], "seções citadas que não existem:\n" + "\n".join(inexistentes[:20])
