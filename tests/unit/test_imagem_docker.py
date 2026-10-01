"""DISCOVERED-02 — a imagem leva o que o runtime referencia em tempo de execução.

Os perfis Codex gerenciados (`managed_codex_profiles`) e o README apontam para
`/app/scripts/aso-agent-wrapper.sh`. Se o Dockerfile não copiar o wrapper (ou o `.dockerignore`
excluí-lo), perfil CLI via wrapper falha só dentro do container — erro que o teste local não pega.
"""

from __future__ import annotations

from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]


def test_dockerfile_copia_o_wrapper_dos_agentes_e_o_torna_executavel() -> None:
    dockerfile = (RAIZ / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY scripts/aso-agent-wrapper.sh ./scripts/aso-agent-wrapper.sh" in dockerfile
    assert "chmod +x ./scripts/aso-agent-wrapper.sh" in dockerfile
    assert (RAIZ / "scripts" / "aso-agent-wrapper.sh").is_file()


def test_dockerignore_nao_exclui_o_wrapper() -> None:
    ignorados = (RAIZ / ".dockerignore").read_text(encoding="utf-8").split("\n")
    for linha in (bruta.strip() for bruta in ignorados):
        assert linha not in ("scripts", "scripts/", "scripts/*", "*.sh"), linha


def test_wrapper_padrao_dos_perfis_gerenciados_aponta_para_o_caminho_da_imagem() -> None:
    """O padrão (`<raiz>/scripts/aso-agent-wrapper.sh`) é o caminho que a imagem cria em /app."""
    import inspect

    from aso.execution import catalog

    fonte = inspect.getsource(catalog.managed_codex_profiles)
    assert "scripts/aso-agent-wrapper.sh" in fonte
