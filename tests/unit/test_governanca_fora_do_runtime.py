"""MEL-04 — `.aso/` é só estado de runtime; a governança da construção mora em `governanca/`.

`.aso/` misturava duas coisas com os mesmos nomes: o que o **runtime** grava (worktrees, catálogo de
executores, índice, PID/log) e a papelada do **processo de construção do próprio ASO** (contexto,
board, snapshots, gates, reviews) — que o runtime nunca lê. Quem abria `.aso/` concluía que
`board.json` era estado do produto. Este teste impede a mistura de voltar (ADR-0081).
"""

from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]

# O que pertencia ao processo de construção e não pode voltar para `.aso/`.
_PROCESSO = ("context", "kanban", "snapshots", "quality-gates", "reviews")
_CAMINHOS_ANTIGOS = re.compile(r"\.aso/(?:context|kanban|snapshots|quality-gates|reviews)\b")
# Documentos vivos que instruem quem trabalha no repositório (registros históricos ficam de fora:
# `requerimentos.md`, `feedback.md`, `tasks/`, `CHANGELOG.md` contam como era na época).
_VIVOS = ("CLAUDE.md", "AGENTS.md", "README.md", "scripts/reset.sh")


def test_aso_nao_tem_artefato_do_processo_de_construcao() -> None:
    aso = RAIZ / ".aso"
    if not aso.exists():
        return  # máquina limpa: o runtime cria `.aso/` sob demanda
    misturados = [nome for nome in _PROCESSO if (aso / nome).exists()]
    assert misturados == [], f"governança da construção dentro de .aso/: {misturados}"


def test_governanca_viva_mora_em_governanca() -> None:
    assert (RAIZ / "governanca" / "context" / "orchestrator-context.json").is_file()
    assert (RAIZ / "governanca" / "kanban" / "board.json").is_file()


def test_historico_congelado_mora_em_docs_historico() -> None:
    historico = RAIZ / "docs" / "historico"
    for caminho in (
        "phases/F1-discovery.md",
        "mvp/mvp-1.md",
        "specs-mvp1/README.md",
        "plano-fidelidade-fluxo.md",
        "governanca-construcao/snapshots",
        "governanca-construcao/quality-gates",
    ):
        assert (historico / caminho).exists(), caminho
    for antigo in ("specs", "docs/phases", "docs/mvp", "docs/plano-fidelidade-fluxo.md"):
        assert not (RAIZ / antigo).exists(), antigo


def test_aso_inteiro_e_ignorado_pelo_git() -> None:
    linhas = [
        linha.strip()
        for linha in (RAIZ / ".gitignore").read_text(encoding="utf-8").split("\n")
        if linha.strip() and not linha.startswith("#")
    ]
    assert ".aso/" in linhas


def test_instrucoes_vivas_apontam_para_os_caminhos_novos() -> None:
    for nome in _VIVOS:
        texto = (RAIZ / nome).read_text(encoding="utf-8")
        assert not _CAMINHOS_ANTIGOS.search(texto), f"{nome} ainda cita o caminho antigo"
    for nome in ("CLAUDE.md", "AGENTS.md"):
        texto = (RAIZ / nome).read_text(encoding="utf-8")
        assert "governanca/kanban/board.json" in texto, nome
        assert "governanca/context/orchestrator-context.json" in texto, nome


def test_docs_vivos_nao_citam_o_caminho_antigo() -> None:
    """`docs/` (fora de `docs/historico/`) e as ADRs apontam para onde os arquivos estão hoje."""
    citam: list[str] = []
    for md in sorted((RAIZ / "docs").rglob("*.md")):
        if "historico" in md.relative_to(RAIZ / "docs").parts:
            continue
        if md.name.startswith("ADR-0081"):
            continue  # a ADR da mudança precisa nomear o caminho antigo
        if _CAMINHOS_ANTIGOS.search(md.read_text(encoding="utf-8")):
            citam.append(str(md.relative_to(RAIZ)))
    assert citam == [], f"docs vivos citando o caminho antigo: {citam}"
