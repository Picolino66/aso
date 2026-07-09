"""Scaffold determinístico de documentação docs-first (padrão ai-docs-self-healing).

Cria a estrutura mínima de docs IA-first numa pasta de trabalho, **sem** precisar de
agente/LLM — usado para pastas vazias (nada a analisar) e como base garantida da
navegação docs-first:

    docs/
      index.md                     ← ponto de entrada; a IA lê isto ANTES do código
      modules/
        <módulo>/
          index.md                 ← índice do módulo
          <módulo>.md              ← feature inicial no template de 8 seções

Quando não há módulos detectados (pasta vazia), cria só `docs/index.md` e
`docs/modules/.gitkeep`. Retorna a lista de arquivos criados (não sobrescreve os
que já existem — a atualização de conteúdo real é tarefa do agente).

Tudo em pt-BR (regra de governança).
"""

from __future__ import annotations

from pathlib import Path

# Template obrigatório de feature (8 seções) — espelha a skill ai-docs-self-healing.
_FEATURE_SECTIONS = (
    "## Descrição",
    "## Localização no código",
    "## Entrada",
    "## Saída",
    "## Dependências",
    "## Regras de negócio",
    "## Fluxo resumido",
    "## Possíveis erros",
)


def _index_md(project_name: str, modules: list[str]) -> str:
    linhas = [
        f"# {project_name} — Documentação (docs-first)",
        "",
        "> Fonte de verdade para IA. **Leia este `index.md` antes de tocar no código.**",
        "> Documentação em português do Brasil (pt-BR).",
        "",
        "## Como navegar",
        "",
        "1. Leia este índice.",
        "2. Identifique o módulo e a feature.",
        "3. Abra `modules/<módulo>/index.md` e o `.md` da feature.",
        "4. Só vá ao código se a documentação não bastar.",
        "5. Após qualquer mudança de código, **atualize a documentação** correspondente.",
        "",
        "## Módulos",
        "",
    ]
    if modules:
        linhas += [f"- [{m}](modules/{m}/index.md)" for m in modules]
    else:
        linhas.append("_Nenhum módulo ainda. Adicione um em `modules/<módulo>/index.md`._")
    linhas.append("")
    return "\n".join(linhas)


def _module_index_md(module: str) -> str:
    return "\n".join(
        [
            f"# Módulo `{module}`",
            "",
            "> Índice do módulo. Liste aqui cada feature com um link para o `.md` dela.",
            "",
            "## Features",
            "",
            f"- [{module}]({module}.md)",
            "",
        ]
    )


def _feature_md(feature: str) -> str:
    linhas = [f"# {feature}", ""]
    for sec in _FEATURE_SECTIONS:
        linhas += [sec, "", "_A preencher._", ""]
    return "\n".join(linhas)


def write_scaffold(path: str | Path, modules: list[str] | None = None) -> list[str]:
    """Escreve a estrutura docs-first mínima em `path`. Não sobrescreve existentes.

    Retorna os caminhos relativos criados (para rastreabilidade/commit).
    """
    root = Path(path)
    project_name = root.name or "Projeto"
    mods = [m for m in (modules or [])]
    created: list[str] = []

    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    modules_dir = docs / "modules"
    modules_dir.mkdir(parents=True, exist_ok=True)

    index = docs / "index.md"
    if not index.exists():
        index.write_text(_index_md(project_name, mods), encoding="utf-8")
        created.append("docs/index.md")

    if not mods:
        gitkeep = modules_dir / ".gitkeep"
        if not gitkeep.exists():
            gitkeep.write_text("", encoding="utf-8")
            created.append("docs/modules/.gitkeep")
        return created

    for m in mods:
        mdir = modules_dir / m
        mdir.mkdir(parents=True, exist_ok=True)
        midx = mdir / "index.md"
        if not midx.exists():
            midx.write_text(_module_index_md(m), encoding="utf-8")
            created.append(f"docs/modules/{m}/index.md")
        feat = mdir / f"{m}.md"
        if not feat.exists():
            feat.write_text(_feature_md(m), encoding="utf-8")
            created.append(f"docs/modules/{m}/{m}.md")
    return created
