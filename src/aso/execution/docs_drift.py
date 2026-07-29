"""Detecção determinística de *drift* entre código e documentação docs-first.

A skill `ai-docs-self-healing` exige que `/docs` seja a fonte de verdade e fique
**em sincronia com o código**: toda mudança de código atualiza a doc da feature,
índices sem links quebrados, sem docs órfãs. Este módulo calcula, **só com
leitura** (sem git, sem agente), um sinal objetivo de drift para:

- alimentar um critério **não-bloqueante** do quality gate em F5/F6 (avisa, não
  reprova); e
- guiar o *self-heal* (o que criar/atualizar).

Sinais de drift detectados:

- `undocumented_modules` — diretórios de código sem `docs/modules/<módulo>/`;
- `orphan_module_docs` — `docs/modules/<módulo>/` cujo diretório de código sumiu;
- `broken_links` — links markdown internos apontando para arquivos inexistentes;
- `unfilled_features` — docs de feature ainda com o placeholder `_A preencher._`.

Tudo em pt-BR (regra de governança).
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel

from aso.execution.workspace import WorkspaceAnalyzer, WorkspaceService

# Link markdown: captura o alvo entre parênteses.
_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
# Placeholder deixado pelo scaffold determinístico (docs ainda não preenchidas).
_PLACEHOLDER = "_A preencher._"
# Módulo neutro criado pelo scaffold quando não há módulos de código detectados;
# não é "órfão" — é um ponto de partida legítimo.
_NEUTRAL_MODULE = "projeto"


class DocsDriftReport(BaseModel):
    """Retrato determinístico do drift entre docs e código."""

    path: str
    has_docs: bool
    has_drift: bool
    undocumented_modules: list[str]
    orphan_module_docs: list[str]
    broken_links: list[str]
    unfilled_features: list[str]


def _internal_link_target(raw: str) -> str | None:
    """Extrai o alvo de um link markdown se for **relativo interno**, senão None.

    Ignora âncoras (`#...`), URLs externas (`http://`, `mailto:`) e títulos opcionais
    (`(arquivo.md "título")`).
    """
    alvo = raw.strip()
    if not alvo or alvo.startswith("#"):
        return None
    alvo = alvo.split()[0]  # descarta ' "título"'
    alvo = alvo.split("#", 1)[0]  # descarta âncora
    if not alvo:
        return None
    if "://" in alvo or alvo.startswith("mailto:"):
        return None
    return alvo


def check_drift(path: str | Path, service: WorkspaceService | None = None) -> DocsDriftReport:
    """Calcula o drift entre `docs/` e o código na pasta `path` (só leitura)."""
    svc = service or WorkspaceService()
    root = path if isinstance(path, Path) else svc.validate(str(path))
    docs = root / "docs"
    docs_index = docs / "index.md"
    docs_modules = docs / "modules"
    has_docs = docs_index.is_file() and docs_modules.is_dir()
    if not has_docs:
        # Sem docs-first ainda: quem trata a criação é o analyze_folder, não o drift.
        return DocsDriftReport(
            path=str(root),
            has_docs=False,
            has_drift=False,
            undocumented_modules=[],
            orphan_module_docs=[],
            broken_links=[],
            unfilled_features=[],
        )

    code_modules = set(WorkspaceAnalyzer(svc).analyze(root).detected_modules)
    documented = {d.name for d in docs_modules.iterdir() if d.is_dir()}
    undocumented = sorted(code_modules - documented)
    orphan = sorted(documented - code_modules - {_NEUTRAL_MODULE})

    broken: list[str] = []
    unfilled: list[str] = []
    for md in sorted(docs.rglob("*.md")):
        rel = md.relative_to(root).as_posix()
        try:
            text = md.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        if _PLACEHOLDER in text:
            unfilled.append(rel)
        for match in _LINK_RE.finditer(text):
            alvo = _internal_link_target(match.group(1))
            if alvo is None:
                continue
            if not (md.parent / alvo).exists():
                broken.append(f"{rel} → {alvo}")

    has_drift = bool(undocumented or orphan or broken or unfilled)
    return DocsDriftReport(
        path=str(root),
        has_docs=True,
        has_drift=has_drift,
        undocumented_modules=undocumented,
        orphan_module_docs=orphan,
        broken_links=broken,
        unfilled_features=unfilled,
    )
