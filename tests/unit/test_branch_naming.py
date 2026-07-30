"""Nomes de branch derivados do card (ADR-0014).

O antigo `role-executor-uuid` nunca falhava porque não dependia de texto humano. Estes
testes cobrem o que muda com isso: título com acento, emoji, vazio, gigante — tudo tem
que virar um nome de branch que o git aceite.
"""

from __future__ import annotations

from aso.execution.branch_naming import (
    FALLBACK_SLUG,
    SLUG_MAX,
    branch_stem,
    prefixo_para,
    slugify,
    sufixo_curto,
    unique_branch,
    worktree_dir_name,
)
from aso.shared.ids import gen_id
from aso.shared.types import CardType


def test_slug_remove_acento_e_pontuacao() -> None:
    assert slugify("Calculadora básica (com histórico!)") == "calculadora-basica-com-historico"


def test_slug_de_texto_sem_letras_cai_no_fallback() -> None:
    # Título só de emoji/pontuação existiria como nome de branch inválido.
    assert slugify("🚀🚀🚀") == FALLBACK_SLUG
    assert slugify("   ") == FALLBACK_SLUG
    assert slugify("") == FALLBACK_SLUG


def test_slug_corta_sem_partir_palavra() -> None:
    slug = slugify("Implementar a exportação de relatórios financeiros em PDF e CSV")
    assert len(slug) <= SLUG_MAX
    assert not slug.endswith("-")
    # o corte cai numa fronteira de palavra, não no meio de "relatorios"
    assert slug.split("-")[-1] in {"a", "exportacao", "de", "relatorios", "implementar"}


def test_slug_de_palavra_unica_gigante_usa_corte_duro() -> None:
    # Sem fronteira de palavra para respeitar, o corte duro é o único caminho.
    slug = slugify("a" * 120)
    assert slug == "a" * SLUG_MAX


def test_prefixo_por_tipo_de_card() -> None:
    assert prefixo_para(CardType.FEATURE) == "feat"
    assert prefixo_para(CardType.BUG) == "fix"
    assert prefixo_para(CardType.DOCUMENTATION) == "docs"
    assert prefixo_para(CardType.TEST) == "test"
    assert prefixo_para(CardType.TECH_DEBT) == "refactor"
    assert prefixo_para(CardType.TASK) == "chore"


def test_prefixo_tolera_tipo_desconhecido_ou_ausente() -> None:
    assert prefixo_para(None) == "chore"
    assert prefixo_para("InventadoPeloAgente") == "chore"
    assert prefixo_para("Feature") == "feat"  # string crua do JSON


def test_stem_junta_prefixo_e_slug() -> None:
    assert branch_stem(CardType.FEATURE, "Calculadora básica") == "feat/calculadora-basica"


def test_unique_branch_fecha_com_sufixo_curto() -> None:
    branch = unique_branch("feat/calculadora-basica", "c6950ea8ee3e4eb8a75a083e00001043")
    assert branch == "feat/calculadora-basica-c6950ea8"


def test_sufixo_curto_sanea_e_tem_tamanho_fixo() -> None:
    assert sufixo_curto("AB-12_cd/ef!ghij") == "ab12cdef"
    assert sufixo_curto("") == "00000000"


def test_branches_do_mesmo_card_nao_colidem() -> None:
    # Candidatos concorrentes e retries executam a MESMA task: a unicidade tem que
    # vir do sufixo, senão o segundo `git worktree add` falha.
    stem = branch_stem(CardType.FEATURE, "Calculadora")
    nomes = {unique_branch(stem, gen_id()) for _ in range(200)}
    assert len(nomes) == 200


def test_diretorio_do_worktree_achata_as_barras() -> None:
    # `.aso/worktrees/feat/x-a1b2` criaria subdiretório e um remove mais frágil.
    assert worktree_dir_name("feat/calculadora-basica-a1b2c3d4") == (
        "feat-calculadora-basica-a1b2c3d4"
    )
