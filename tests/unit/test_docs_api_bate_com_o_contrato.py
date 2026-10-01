"""DISCOVERED-05 — `docs/api.md` não pode citar rota que não existe (ADR-0064).

O contrato OpenAPI é gerado do código; a documentação era escrita à mão e chegou a listar 29 rotas
inexistentes (a API "ideal" do requisito, com recursos planos como `/v1/boards` e
`/v1/cards/{id}`). Quem lia procurava cancelamento e execução em rotas que nunca existiram.

Regra: toda linha `MÉTODO /v1/...` do documento tem de casar com uma operação do contrato.
Parâmetros de caminho casam por posição (`{id}` = `{orchestration_id}`); query string e trechos
abreviados com `…` são ignorados (não são rota completa).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
_ROTA = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE)\s+(/v1/[^\s;`|)\"']*|/health|/metrics)")


def _normalizar(caminho: str) -> str:
    # `?…` e a notação de opcional `[?card_id=]` não fazem parte da rota
    sem_query = caminho.split("?", 1)[0].split("[", 1)[0].rstrip(".,:")
    return re.sub(r"\{[^}]+\}", "{}", sem_query).rstrip("/") or "/"


def _operacoes_do_contrato() -> set[tuple[str, str]]:
    contrato = json.loads((RAIZ / "contracts" / "openapi.json").read_text(encoding="utf-8"))
    return {
        (metodo.upper(), _normalizar(caminho))
        for caminho, operacoes in contrato["paths"].items()
        for metodo in operacoes
    }


def _citadas(texto: str) -> list[tuple[int, str, str]]:
    citadas: list[tuple[int, str, str]] = []
    for numero, linha in enumerate(texto.split("\n"), 1):
        for m in _ROTA.finditer(linha):
            caminho = m.group(2)
            if "…" in caminho or "..." in caminho:
                continue
            citadas.append((numero, m.group(1), caminho))
    return citadas


# Documentos de referência que citam rotas da API (todos vivem ao lado do código).
_DOCUMENTOS = (
    "docs/api.md",
    "README.md",
    "docs/operations.md",
    "docs/GOVERNANCE.md",
    "docs/HOW_IT_WORKS.md",
    "docs/mapa-paginas.md",
)


def test_toda_rota_citada_em_docs_api_existe_no_contrato() -> None:
    reais = _operacoes_do_contrato()
    fantasmas = [
        f"{documento}:{numero}: {metodo} {caminho}"
        for documento in _DOCUMENTOS
        for numero, metodo, caminho in _citadas((RAIZ / documento).read_text("utf-8"))
        if (metodo, _normalizar(caminho)) not in reais
    ]
    assert fantasmas == [], "rotas citadas que não existem no contrato:\n" + "\n".join(fantasmas)


def test_a_verificacao_pega_rota_inventada() -> None:
    """Mutação: se a regex deixasse de enxergar as rotas, o teste acima passaria vazio."""
    reais = _operacoes_do_contrato()
    texto = "GET    /v1/boards\nPOST /v1/orchestrations/{id}/cards/{card}/run\n"
    citadas = _citadas(texto)
    assert len(citadas) == 2
    inexistentes = [c for c in citadas if (c[1], _normalizar(c[2])) not in reais]
    assert [c[2] for c in inexistentes] == ["/v1/boards"]
