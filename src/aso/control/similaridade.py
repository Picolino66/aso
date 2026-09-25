"""Demandas parecidas por BM25 — texto, sem embeddings (ADR-0079, MEL-45).

O relatório de aprendizado (ADR-0052) agrega por faixas de complexidade e risco; o painel de
recomendação (ADR-0044) decide por regra ou heurística. Nenhum dos dois responde a pergunta que o
operador faz antes de aprovar uma estratégia: **demandas parecidas com esta falharam onde, com
qual executor e a que custo?**

Este módulo é a parte pura: recebe as demandas já lidas do repositório (texto + desfecho) e
devolve as mais parecidas com a consulta, ranqueadas por **BM25** (Okapi, k1/b clássicos).

Por que BM25 em processo e não `tsvector`/FTS5 (o que a task propunha):

- **uma implementação, dois bancos** — `tsvector` (Postgres) e FTS5 (SQLite) exigiriam schema e
  migração diferentes por banco, e o teste rodaria contra um mecanismo diferente do de produção,
  que é justamente o risco que o ASO evita validando no Postgres;
- **determinismo e teste** — a fórmula é uma função pura: a mesma entrada dá a mesma ordem, e o
  teste afirma a ordem, não "veio algo";
- **escala honesta** — o ranqueamento roda sobre uma janela limitada de demandas recentes
  (`LIMITE_DE_CANDIDATAS`), lendo só as colunas de texto. Quando essa janela apertar, trocar o
  coletor por um índice do banco não muda quem chama: a interface é `ranquear(...)`.

Nada de embeddings: a task pede busca textual primeiro, e recomendação precisa de **evidência
citável** ("estas 3 demandas"), não de vizinhança semântica sem fonte.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field

# Okapi BM25 clássico: k1 controla a saturação do termo repetido, b a normalização por tamanho.
K1 = 1.5
B = 0.75
LIMITE_DE_CANDIDATAS = 500
# Mínimo de demandas com desfecho para o painel afirmar algo (abaixo disso ele diz que não sabe).
MINIMO_DE_HISTORICO = 2

# Palavras sem valor discriminante em pt-BR + jargão que aparece em toda demanda do runtime.
_PARADAS = frozenset(
    """a ao aos as à às com como da das de do dos e em entre era essa esse esta este eu for
    foi isso já la lhe mais mas me mesmo meu minha muito na nao não nas nem no nos nossa nosso
    num numa o os ou para pela pelas pelo pelos por qual quando que quem se sem ser seu sua são
    só tambem também te tem ter teu tua um uma voce você vocês as os the of and to in for on
    demanda tarefa card sistema projeto fazer novo nova""".split()
)
_MINIMO_DE_LETRAS = 3


def normalizar(texto: str) -> str:
    """Minúsculas sem acento: "Validação" e "validacao" são o mesmo termo para a busca."""
    decomposto = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in decomposto if unicodedata.category(c) != "Mn")


def tokenizar(texto: str) -> list[str]:
    """Palavras úteis do texto, já normalizadas (sem paradas nem fragmentos curtos)."""
    return [
        palavra
        for palavra in re.findall(r"[a-z0-9_]+", normalizar(texto))
        if len(palavra) >= _MINIMO_DE_LETRAS and palavra not in _PARADAS
    ]


@dataclass(frozen=True)
class DemandaIndexada:
    """Uma demanda candidata: o texto que descreve o pedido + o que aconteceu com ela.

    `desfecho` é opcional de propósito — uma demanda recém-criada é parecida, mas não ensina
    nada; quem monta a recomendação decide se a usa como evidência."""

    orchestration_id: str
    titulo: str
    texto: str
    criada_em: str = ""
    status: str = ""
    desfecho: dict[str, object] = field(default_factory=dict)

    @property
    def termos(self) -> list[str]:
        return tokenizar(self.texto)


@dataclass(frozen=True)
class Similar:
    """Uma demanda parecida, com a pontuação que a colocou ali."""

    orchestration_id: str
    titulo: str
    score: float
    termos_em_comum: list[str]
    criada_em: str = ""
    status: str = ""
    desfecho: dict[str, object] = field(default_factory=dict)


def ranquear(
    consulta: str, candidatas: list[DemandaIndexada], *, limite: int = 5, minimo: float = 0.1
) -> list[Similar]:
    """As `limite` demandas mais parecidas com `consulta`, por BM25.

    Empate é resolvido pela demanda mais recente (`criada_em`), para a lista não oscilar entre
    chamadas. Pontuação abaixo de `minimo` não entra: "nada parecido" é uma resposta melhor que
    uma lista de coincidências de uma palavra."""
    termos_da_consulta = tokenizar(consulta)
    if not termos_da_consulta or not candidatas:
        return []

    documentos = [c.termos for c in candidatas]
    total = len(documentos)
    tamanho_medio = sum(len(d) for d in documentos) / total if total else 0.0
    if not tamanho_medio:
        return []

    frequencia_de_documento: dict[str, int] = {}
    for documento in documentos:
        for termo in set(documento):
            frequencia_de_documento[termo] = frequencia_de_documento.get(termo, 0) + 1

    resultados: list[Similar] = []
    for candidata, documento in zip(candidatas, documentos, strict=True):
        if not documento:
            continue
        contagem: dict[str, int] = {}
        for termo in documento:
            contagem[termo] = contagem.get(termo, 0) + 1
        score = 0.0
        comuns: list[str] = []
        for termo in dict.fromkeys(termos_da_consulta):
            ocorrencias = contagem.get(termo, 0)
            if not ocorrencias:
                continue
            comuns.append(termo)
            df = frequencia_de_documento.get(termo, 0)
            # IDF do BM25 (com o +0.5/+0.5 que evita peso negativo em termo quase universal).
            idf = math.log(1 + (total - df + 0.5) / (df + 0.5))
            norma = K1 * (1 - B + B * len(documento) / tamanho_medio)
            score += idf * (ocorrencias * (K1 + 1)) / (ocorrencias + norma)
        if score < minimo:
            continue
        resultados.append(
            Similar(
                orchestration_id=candidata.orchestration_id,
                titulo=candidata.titulo,
                score=round(score, 4),
                termos_em_comum=comuns,
                criada_em=candidata.criada_em,
                status=candidata.status,
                desfecho=dict(candidata.desfecho),
            )
        )
    resultados.sort(key=lambda s: (-s.score, s.criada_em and _inverso(s.criada_em)))
    return resultados[:limite]


def _inverso(texto: str) -> str:
    """Chave de ordenação decrescente para string (mais recente primeiro) sem parsear data."""
    return "".join(chr(0x10FFFF - ord(c)) if ord(c) < 0x10FFFF else c for c in texto)


def texto_da_demanda(user_request: str, ficha: dict[str, object]) -> str:
    """O texto que descreve uma demanda: o pedido + os campos de conteúdo da ficha.

    Só campos que descrevem O QUE se pede (objetivo, problema, resultado, módulos, critérios,
    riscos). `tipo`, `risco`, `complexidade` e `dominios` ficam fora: são rótulos de vocabulário
    fechado — entrariam em toda demanda e empurrariam o BM25 a ranquear por rótulo, não por
    assunto (medido no Docker: `dominios` colocava "backend" entre os termos em comum de
    demandas que não tinham nada a ver)."""
    partes = [user_request or ""]
    for chave in (
        "objetivo",
        "problema",
        "resultado_esperado",
        "modulos_afetados",
        "sistemas_afetados",
        "criterios_de_aceite",
        "riscos",
    ):
        valor = ficha.get(chave)
        if isinstance(valor, str):
            partes.append(valor)
        elif isinstance(valor, list):
            partes.extend(str(item) for item in valor)
    return " ".join(parte for parte in partes if parte)
