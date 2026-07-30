"""Nomes de branch derivados do card (§26A.6, ADR-0014).

Antes, o nome da branch era `role-executor-uuid` — `BackendDevelopmentAgent-claude-
sonnet-medium-c6950ea8…` — porque o provider CLI não recebia nada do card além do
`card_id` opaco. Um nome assim não diz **o que** está sendo desenvolvido, e o operador
precisava abrir o diff para descobrir.

Aqui a branch passa a sair do título do card: `feat/calculadora-basica-a1b2c3d4`.
São funções puras (sem I/O) para servirem tanto ao caminho determinístico quanto à
validação da resposta do agente nomeador (`aso.control.naming`), que pode devolver
qualquer coisa e precisa passar pelo mesmo saneamento.
"""

from __future__ import annotations

import re
import unicodedata

from aso.shared.types import CardType

# Tamanho do slug: longo o bastante para descrever a funcionalidade, curto o bastante
# para `git branch` continuar legível numa linha de terminal.
SLUG_MAX = 40
FALLBACK_SLUG = "card"

# Prefixo estilo Conventional Commits por tipo de card — é o mesmo vocabulário que
# pedimos ao agente nas mensagens de commit, então branch e histórico combinam.
_PREFIXOS: dict[CardType, str] = {
    CardType.EPIC: "feat",
    CardType.FEATURE: "feat",
    CardType.IMPROVEMENT: "feat",
    CardType.BUG: "fix",
    CardType.INCIDENT: "fix",
    CardType.DOCUMENTATION: "docs",
    CardType.ADR_TASK: "docs",
    CardType.TEST: "test",
    CardType.TECH_DEBT: "refactor",
    CardType.TASK: "chore",
    CardType.RESEARCH: "chore",
    CardType.REVIEW: "chore",
    CardType.DEPLOY: "chore",
}
PREFIXO_PADRAO = "chore"

_NAO_ALFANUM = re.compile(r"[^a-z0-9]+")


def tem_texto_util(texto: str) -> bool:
    """Diz se sobra alguma letra/dígito ASCII depois de normalizar.

    Um título só de emoji ou pontuação não serve nem para branch nem para assunto de
    commit — quem chama precisa saber disso para escolher um texto genérico.
    """
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return bool(_NAO_ALFANUM.sub("", sem_acento.lower()))


def slugify(texto: str, *, max_len: int = SLUG_MAX) -> str:
    """Converte um texto livre em slug ASCII seguro para nome de branch git.

    Remove acentos (NFKD), descarta o que não for `[a-z0-9]` e corta no limite **sem
    partir palavra** — `"Calculadora básica com histórico"` vira `calculadora-basica`,
    não `calculadora-basica-com-hist`. Texto vazio ou só de símbolos (emoji, pontuação)
    cai em `card`, porque um nome de branch vazio quebraria o `git worktree add`.
    """
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    slug = _NAO_ALFANUM.sub("-", sem_acento.lower()).strip("-")
    if not slug:
        return FALLBACK_SLUG
    if len(slug) > max_len:
        cortado = slug[:max_len].rstrip("-")
        # Só descarta a última palavra se sobrar algo: título de palavra única e
        # gigante ("supercalifragilistico…") precisa do corte duro.
        if "-" in cortado:
            cortado = cortado.rsplit("-", 1)[0]
        slug = cortado or slug[:max_len]
    return slug.strip("-") or FALLBACK_SLUG


def prefixo_para(card_type: CardType | str | None) -> str:
    """Prefixo Conventional Commits do tipo de card (`feat`, `fix`, `docs`, …)."""
    if card_type is None:
        return PREFIXO_PADRAO
    try:
        tipo = CardType(card_type)
    except ValueError:
        return PREFIXO_PADRAO
    return _PREFIXOS.get(tipo, PREFIXO_PADRAO)


def branch_stem(card_type: CardType | str | None, title: str) -> str:
    """Raiz da branch do card, sem sufixo: `feat/calculadora-basica`.

    Fica separada de `unique_branch` de propósito: a **identidade** da branch vem do
    card (uma por card), mas a **unicidade** é um problema do worktree — `retry` e
    candidatos concorrentes (§26A.6) criam branches para o mesmo card ao mesmo tempo,
    e `git worktree add` falha se a branch já existe.
    """
    return f"{prefixo_para(card_type)}/{slugify(title)}"


def unique_branch(stem: str, suffix: str) -> str:
    """Fecha a branch com o sufixo de unicidade: `feat/calculadora-basica-a1b2c3d4`."""
    return f"{stem}-{sufixo_curto(suffix)}"


def sufixo_curto(valor: str) -> str:
    """Reduz um id a 8 caracteres seguros — o bastante para não colidir na prática."""
    limpo = _NAO_ALFANUM.sub("", valor.lower())
    return (limpo or "00000000")[:8]


def worktree_dir_name(branch: str) -> str:
    """Nome de diretório para a branch: `feat/x-a1b2` → `feat-x-a1b2`.

    O worktree vive em `.aso/worktrees/<nome>`; manter as barras criaria subdiretórios
    aninhados e um `git worktree remove` mais frágil.
    """
    return slugify(branch, max_len=80)
