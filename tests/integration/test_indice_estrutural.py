"""MEL-44 — índice estrutural do workspace por commit (ADR-0077).

Cobre: o que entra e o que NUNCA entra no índice (segredo, cache, binário), símbolos/imports/
pontos de entrada por linguagem, as três consultas, o reaproveitamento por commit, e os três usos
— contexto do card, validação do discovery e impacto na revisão.
"""

from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path
from typing import Any

import pytest

from aso.agents.context_builder import construir_contexto
from aso.application.orchestration_service import OrchestrationService
from aso.control.discovery import (
    STATUS_APROVADO,
    DiscoveryReport,
    DiscoveryService,
    _sanear,
    mapa_do_repositorio,
)
from aso.control.models import AgentAssignment
from aso.control.review import ReviewService
from aso.control.triage import DemandBrief
from aso.execution.catalog import ExecutorCatalog, ExecutorProfile
from aso.execution.code_index import (
    VERSAO_DO_SCHEMA,
    arquivos_do_diff,
    caminho_do_indice,
    construir_indice,
    indexavel,
    indice_do_repositorio,
    indice_para_uso,
    limpar_cache_em_memoria,
)
from aso.execution.impacto import impacto_de, vizinhanca_para_contexto
from aso.execution.workspace import WorkspaceAnalyzer, WorkspaceService

RAIZ_DO_ASO = Path(__file__).resolve().parents[2]


def _git(path: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=path, check=True, capture_output=True)


@pytest.fixture(autouse=True)
def _sem_cache() -> None:
    limpar_cache_em_memoria()


def _projeto(tmp_path: Path, *, com_git: bool = True) -> Path:
    """Repositório de exemplo com Python, TypeScript, testes, segredo e binário."""
    raiz = tmp_path / "proj"
    (raiz / "src" / "core").mkdir(parents=True)
    (raiz / "tests").mkdir()
    (raiz / "web").mkdir()
    (raiz / "node_modules" / "lib").mkdir(parents=True)
    (raiz / ".venv").mkdir()

    (raiz / "src" / "__init__.py").write_text("")
    (raiz / "src" / "core" / "__init__.py").write_text("")
    (raiz / "src" / "core" / "dominio.py").write_text(
        "LIMITE = 10\n"
        "_INTERNO = 1\n"
        "\n\nclass Pedido:\n"
        "    def total(self) -> int:\n        return 0\n"
        "\n\ndef calcular(x: int) -> int:\n    return x\n"
        "\n\ndef _ajudante() -> None:\n    return None\n"
    )
    (raiz / "src" / "core" / "api.py").write_text(
        "from fastapi import APIRouter\n\n"
        "from src.core.dominio import calcular\n\n"
        "router = APIRouter()\n\n\n"
        "def criar_router() -> APIRouter:\n"
        "    @router.get('/v1/pedidos')\n"
        "    def listar() -> list[int]:\n"
        "        return [calcular(1)]\n\n"
        "    return router\n"
    )
    (raiz / "src" / "core" / "relatorio.py").write_text(
        "from src.core import dominio\n\n\ndef somar() -> int:\n    return dominio.LIMITE\n"
    )
    (raiz / "tests" / "test_dominio.py").write_text(
        "from src.core.dominio import calcular\n\n\ndef test_calcular() -> None:\n"
        "    assert calcular(1) == 1\n"
    )
    (raiz / "tests" / "test_api.py").write_text(
        "from src.core.api import criar_router\n\n\ndef test_router() -> None:\n"
        "    assert criar_router() is not None\n"
    )
    (raiz / "web" / "servico.ts").write_text(
        "import { util } from './util';\n\n"
        "export class Cliente {\n  fetchAll() { return util(); }\n}\n"
        "export const rota = '/x';\n"
        "app.get('/api/pedidos', (req, res) => res.json([]));\n"
    )
    (raiz / "web" / "util.ts").write_text("export function util() { return 1; }\n")
    (raiz / "web" / "servico.spec.ts").write_text(
        "import { Cliente } from './servico';\n\nit('funciona', () => new Cliente());\n"
    )
    # Nada disto pode aparecer no índice.
    (raiz / ".env").write_text("ASO_LLM_API_KEY=segredo-de-verdade\n")
    (raiz / "chave.pem").write_text("-----BEGIN PRIVATE KEY-----\n")
    (raiz / "src" / "credentials.json").write_text('{"token": "segredo"}\n')
    (raiz / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    (raiz / "node_modules" / "lib" / "index.js").write_text("module.exports = 1;\n")
    (raiz / ".venv" / "pyvenv.cfg").write_text("home = /usr\n")
    if com_git:
        _git(raiz, "init", "-q")
        _git(raiz, "config", "user.email", "t@t")
        _git(raiz, "config", "user.name", "t")
        _git(raiz, "add", "-A")
        _git(raiz, "commit", "-qm", "base")
    return raiz


# ------------------------------------------------------------------ o que entra


def test_indice_ve_simbolos_imports_testes_e_entradas(tmp_path: Path) -> None:
    indice = construir_indice(_projeto(tmp_path), commit="abc")
    dominio = indice.arquivos["src/core/dominio.py"]
    assert [(s.nome, s.tipo) for s in dominio.simbolos] == [
        ("LIMITE", "constante"),
        ("Pedido", "classe"),
        ("Pedido.total", "funcao"),
        ("calcular", "funcao"),
    ]  # privados (_INTERNO, _ajudante) ficam fora
    assert dominio.linhas > 5 and not dominio.e_teste

    api = indice.arquivos["src/core/api.py"]
    assert api.importa == ["src/core/dominio.py"]  # resolvido para caminho, com raiz `src`
    assert api.entradas == ["GET /v1/pedidos"]  # rota declarada dentro da fábrica

    assert indice.arquivos["tests/test_dominio.py"].e_teste
    servico = indice.arquivos["web/servico.ts"]
    assert {s.nome for s in servico.simbolos} == {"Cliente", "rota"}
    assert servico.importa == ["web/util.ts"]
    assert servico.entradas == ["GET /api/pedidos"]
    assert indice.arquivos["web/servico.spec.ts"].e_teste
    assert indice.precisao["typescript"].startswith("regex")


def test_relatorio_por_import_de_pacote_tambem_conta(tmp_path: Path) -> None:
    indice = construir_indice(_projeto(tmp_path), commit="abc")
    # `from src.core import dominio` → arquivo do pacote e o módulo importado
    assert "src/core/dominio.py" in indice.arquivos["src/core/relatorio.py"].importa


def test_segredos_caches_e_binarios_nunca_entram_no_indice(tmp_path: Path) -> None:
    """Governança da MEL-44 §5: índice é derivado e legível — não pode vazar segredo."""
    raiz = _projeto(tmp_path)
    indice = construir_indice(raiz, commit="abc")
    serializado = json.dumps(indice.model_dump(mode="json"), ensure_ascii=False)

    for proibido in (
        ".env",
        "chave.pem",
        "src/credentials.json",
        "logo.png",
        "node_modules/lib/index.js",
        ".venv/pyvenv.cfg",
    ):
        assert proibido not in indice.arquivos, proibido
        assert not indice.contem(proibido), proibido
    assert "segredo-de-verdade" not in serializado
    assert "node_modules" not in indice.modulos and ".venv" not in indice.modulos


@pytest.mark.parametrize(
    ("caminho", "esperado"),
    [
        ("src/app.py", True),
        ("docs/index.md", True),
        (".env", False),
        (".env.local", False),
        ("config/secrets.yml", False),
        ("app/password.txt", False),
        ("deploy/id_rsa", False),
        ("certs/api.key", False),
        ("node_modules/x/y.js", False),
        (".venv/lib/x.py", False),
        ("build/out.js", False),
        ("img/foto.jpeg", False),
    ],
)
def test_regra_de_elegibilidade(caminho: str, esperado: bool) -> None:
    assert indexavel(caminho, 10) is esperado


def test_arquivo_gigante_fica_fora(tmp_path: Path) -> None:
    assert indexavel("src/gerado.py", 5_000_000) is False


# ------------------------------------------------------------------ consultas


def test_consultas_de_vizinhanca_testes_e_dependentes(tmp_path: Path) -> None:
    indice = construir_indice(_projeto(tmp_path), commit="abc")
    assert indice.quem_importa("src/core/dominio.py") == [
        "src/core/api.py",
        "src/core/relatorio.py",
        "tests/test_dominio.py",
    ]
    # direto (importa o arquivo) e indireto (importa quem importa) — direto primeiro
    assert indice.testes_que_cobrem("src/core/dominio.py") == [
        "tests/test_dominio.py",
        "tests/test_api.py",
    ]
    vizinhanca = indice.vizinhanca("src/core/api.py")
    assert vizinhanca["importa"] == ["src/core/dominio.py"]
    assert vizinhanca["testes"] == ["tests/test_api.py"]
    assert indice.quem_importa("src/nao/existe.py") == []


def test_impacto_de_um_diff_separa_dependentes_testes_e_desconhecidos(tmp_path: Path) -> None:
    indice = construir_indice(_projeto(tmp_path), commit="abc")
    diff = (
        "diff --git a/src/core/dominio.py b/src/core/dominio.py\n"
        "--- a/src/core/dominio.py\n+++ b/src/core/dominio.py\n@@ -1 +1 @@\n-LIMITE = 10\n"
        "+LIMITE = 11\n"
        "diff --git a/novo/arquivo.py b/novo/arquivo.py\n@@ -0,0 +1 @@\n+x = 1\n"
    )
    assert arquivos_do_diff(diff) == ["src/core/dominio.py", "novo/arquivo.py"]
    impacto = impacto_de(indice, arquivos_do_diff(diff))
    assert impacto.dependentes == ["src/core/api.py", "src/core/relatorio.py"]
    assert impacto.testes == ["tests/test_dominio.py", "tests/test_api.py"]
    assert impacto.desconhecidos == ["novo/arquivo.py"]
    texto = impacto.como_texto()
    assert "Arquivos que importam os alterados (2)" in texto
    assert "tests/test_dominio.py" in texto and "novo/arquivo.py" in texto
    assert not impacto.vazio()


def test_impacto_sem_dependentes_e_declarado(tmp_path: Path) -> None:
    indice = construir_indice(_projeto(tmp_path), commit="abc")
    impacto = impacto_de(indice, ["web/servico.spec.ts"])
    assert impacto.vazio()
    assert "Nenhum arquivo do repositório importa os alterados." in impacto.como_texto()


def test_vizinhanca_para_contexto_resume_uma_linha_por_arquivo(tmp_path: Path) -> None:
    indice = construir_indice(_projeto(tmp_path), commit="abc")
    linhas = vizinhanca_para_contexto(indice, ["src/core/api.py", "nao/existe.py"])
    assert len(linhas) == 1
    assert "src/core/api.py (python" in linhas[0]
    assert "define: criar_router:" in linhas[0]
    assert "entradas: GET /v1/pedidos" in linhas[0]
    assert "usa: src/core/dominio.py" in linhas[0]
    assert "testes: tests/test_api.py" in linhas[0]


# ------------------------------------------------------------------ cache por commit


def test_mesmo_commit_reaproveita_o_indice_e_commit_novo_recalcula(tmp_path: Path) -> None:
    raiz = _projeto(tmp_path)
    indice, reaproveitado = indice_do_repositorio(raiz)
    assert reaproveitado is False
    assert indice.commit and indice.sujo is False
    arquivo = caminho_do_indice(raiz, indice.commit)
    assert arquivo.is_file()
    assert json.loads(arquivo.read_text())["versao_do_schema"] == VERSAO_DO_SCHEMA

    de_novo, reaproveitado = indice_do_repositorio(raiz)
    assert reaproveitado is True and de_novo.gerado_em == indice.gerado_em

    (raiz / "src" / "core" / "novo.py").write_text("def novo() -> int:\n    return 1\n")
    _git(raiz, "add", "-A")
    _git(raiz, "commit", "-qm", "novo arquivo")
    terceiro, reaproveitado = indice_do_repositorio(raiz)
    assert reaproveitado is False
    assert terceiro.commit != indice.commit
    assert "src/core/novo.py" in terceiro.arquivos
    assert caminho_do_indice(raiz, terceiro.commit).is_file()


def test_arvore_suja_nao_grava_nem_reaproveita(tmp_path: Path) -> None:
    raiz = _projeto(tmp_path)
    (raiz / "src" / "core" / "rascunho.py").write_text("x = 1\n")
    indice, reaproveitado = indice_do_repositorio(raiz)
    assert indice.sujo is True and reaproveitado is False
    assert "src/core/rascunho.py" in indice.arquivos  # o índice descreve o disco
    assert not caminho_do_indice(raiz, indice.commit).exists()  # mas não vira cache do commit


def test_indice_corrompido_e_refeito(tmp_path: Path) -> None:
    raiz = _projeto(tmp_path)
    indice, _ = indice_do_repositorio(raiz)
    caminho_do_indice(raiz, indice.commit).write_text("{lixo", encoding="utf-8")
    refeito, reaproveitado = indice_do_repositorio(raiz)
    assert reaproveitado is False and refeito.arquivos


def test_indice_para_uso_ignora_pasta_que_nao_serve(tmp_path: Path) -> None:
    assert indice_para_uso(tmp_path / "inexistente") is None
    vazia = tmp_path / "vazia"
    vazia.mkdir()
    assert indice_para_uso(vazia) is None
    sem_git = _projeto(tmp_path, com_git=False)
    indice = indice_para_uso(sem_git)
    assert indice is not None and indice.commit == "" and indice.sujo is True


def test_indice_do_proprio_aso_em_tempo_aceitavel() -> None:
    """Critério de aceite 1: o repositório do ASO inteiro, medido (ADR-0077)."""
    indice = construir_indice(RAIZ_DO_ASO, commit="medicao")
    resumo = indice.resumo()
    assert int(resumo["arquivos"]) > 400  # type: ignore[call-overload]
    assert int(resumo["simbolos"]) > 1000  # type: ignore[call-overload]
    assert indice.duracao_ms < 15_000, resumo
    # o índice conhece a estrutura real deste repositório
    assert "src/aso/execution/code_index.py" in indice.arquivos
    assert "aso" not in indice.modulos and "src" in indice.modulos
    assert "src/aso/execution/catalog.py" in indice.quem_importa(
        "src/aso/execution/flags_de_cli.py"
    )
    entradas = indice.arquivos["src/aso/api/routers/catalogos.py"].entradas
    assert "GET /v1/executors" in entradas
    # nenhum arquivo ignorado/segredo do próprio repo entrou
    assert not [a for a in indice.arquivos if a.startswith((".venv/", ".git/", ".aso/index/"))]


def test_gitignore_do_alvo_recebe_a_pasta_do_indice(tmp_path: Path) -> None:
    raiz = tmp_path / "alvo"
    raiz.mkdir()
    (raiz / ".gitignore").write_text("*.log\n", encoding="utf-8")
    WorkspaceService().ensure_git(raiz)
    conteudo = (raiz / ".gitignore").read_text(encoding="utf-8")
    assert ".aso/index/" in conteudo and ".aso/worktrees/" in conteudo and "*.log" in conteudo


# ------------------------------------------------------------------ usos


def _catalogo(resposta: dict[str, Any]) -> ExecutorCatalog:
    """Catálogo com um executor CLI que só cospe o JSON dado (mesmo padrão dos outros testes)."""
    script = 'cat > /dev/null; printf %s "$1"; exit 0'
    comando = shlex.join(["bash", "-c", script, "_", json.dumps(resposta, ensure_ascii=False)])
    return ExecutorCatalog([ExecutorProfile(name="agente", kind="cli", command=comando)])


def test_discovery_descarta_componente_que_nao_existe_no_indice(tmp_path: Path) -> None:
    raiz = _projeto(tmp_path)
    indice = construir_indice(raiz, commit="abc")
    bruto: dict[str, Any] = {
        "situacao_atual": "ok",
        "problema": "p",
        "componentes_afetados": ["src/core/dominio.py", "src/core", ".env", "src/inventado.py"],
        "evidencias": [
            {"arquivo": "src/core/api.py", "trecho": "router"},
            {"arquivo": ".env", "trecho": "ASO_LLM_API_KEY=..."},
        ],
        "confianca": "alta",
    }
    relatorio = _sanear(bruto, indice=indice)
    assert relatorio is not None
    assert relatorio.componentes_afetados == ["src/core/dominio.py", "src/core"]
    assert relatorio.componentes_descartados == [".env", "src/inventado.py"]
    assert [e.arquivo for e in relatorio.evidencias] == ["src/core/api.py"]


def test_pedido_do_discovery_leva_o_mapa_do_repositorio(tmp_path: Path) -> None:
    raiz = _projeto(tmp_path)
    indice = construir_indice(raiz, commit="abcdef1234")
    mapa = mapa_do_repositorio(indice)
    assert "commit abcdef12" in mapa
    assert "Módulos de topo: src, tests, web" in mapa
    assert "GET /v1/pedidos" in mapa
    assert len(mapa) < 2_000  # cabe no pedido sem empurrar o resto para fora


def test_evento_de_discovery_registra_o_commit_do_indice_e_os_descartes(tmp_path: Path) -> None:
    """Rastreabilidade: qual commit orientou e validou este discovery (ADR-0077)."""
    raiz = _projeto(tmp_path)
    catalogo = _catalogo(
        {
            "situacao_atual": "ok",
            "problema": "p",
            "componentes_afetados": ["src/core/api.py", "fantasma.py"],
            "confianca": "media",
        }
    )
    svc = OrchestrationService(catalog=catalogo)
    orch = svc.create_orchestration("investigar", target_path=str(raiz))
    svc.set_agent_assignment(orch.id, "discovery", executor="agente")
    svc.run_discovery(orch.id)
    evento = [e for e in svc.timeline(orch.id) if e.type == "DiscoveryRun"][-1]
    commit = evento.payload["indice_commit"]
    assert commit and len(commit) == 40
    assert evento.payload["componentes_descartados"] == ["fantasma.py"]
    relatorio = svc.get_discovery_report(orch.id)
    assert relatorio.componentes_afetados == ["src/core/api.py"]


def test_discovery_com_agente_valida_a_resposta_contra_o_indice(tmp_path: Path) -> None:
    raiz = _projeto(tmp_path)
    indice = construir_indice(raiz, commit="abc")
    catalogo = _catalogo(
        {
            "situacao_atual": "há um módulo core",
            "problema": "sem validação",
            "componentes_afetados": ["src/core/dominio.py", "modulo/fantasma.py"],
            "recomendacao_tecnica": "validar na borda",
            "confianca": "media",
        }
    )
    servico = DiscoveryService(catalog=catalogo)
    relatorio = servico.investigar(
        AgentAssignment(executor="agente"),
        user_request="validar pedidos",
        demand_brief=DemandBrief(objetivo="validar"),
        workspace_report=WorkspaceAnalyzer().analyze(raiz),
        indice=indice,
    )
    assert relatorio.origem == "agente"
    assert relatorio.componentes_afetados == ["src/core/dominio.py"]
    assert relatorio.componentes_descartados == ["modulo/fantasma.py"]


def test_revisao_recebe_dependentes_e_testes_no_pedido(tmp_path: Path) -> None:
    raiz = _projeto(tmp_path)
    indice = construir_indice(raiz, commit="abc")
    diff = "diff --git a/src/core/dominio.py b/src/core/dominio.py\n@@ -1 +1 @@\n-a\n+b\n"
    impacto = impacto_de(indice, arquivos_do_diff(diff))
    catalogo = _catalogo({"veredito": "aprovado", "resumo": "ok", "pontos_verificados": ["a"]})
    servico = ReviewService(catalog=catalogo)
    executor = catalogo.get("agente")
    assert executor is not None
    pedidos: list[str] = []
    original = servico._perguntar  # noqa: SLF001

    def espiao(*args: Any, **kwargs: Any) -> dict[str, Any]:
        pedidos.append(str(kwargs.get("impacto")))
        return original(*args, **kwargs)

    servico._perguntar = espiao  # type: ignore[method-assign]  # noqa: SLF001
    verdito = servico.revisar(
        AgentAssignment(executor="agente"),
        diff=diff,
        card_title="mudar limite",
        impacto=impacto,
    )
    assert verdito.veredito == "aprovado"
    assert "src/core/api.py" in pedidos[0] and "tests/test_dominio.py" in pedidos[0]


def _com_discovery(svc: OrchestrationService, oid: str, componentes: list[str]) -> None:
    """Discovery aprovado é a fonte real de arquivos citados (o runtime não preenche
    `linked_files` sozinho): os `componentes_afetados` já passaram pela validação do índice."""
    b = svc._bundle(oid)  # noqa: SLF001
    b.orchestration.discovery_reports = [
        DiscoveryReport(
            status=STATUS_APROVADO, versao=1, componentes_afetados=componentes
        ).model_dump(mode="json")
    ]
    svc._persist(b)  # noqa: SLF001


def test_contexto_do_card_inclui_a_vizinhanca_dos_arquivos_citados(tmp_path: Path) -> None:
    raiz = _projeto(tmp_path)
    svc = OrchestrationService()
    orch = svc.create_orchestration("mudar o domínio", target_path=str(raiz))
    _com_discovery(svc, orch.id, ["src/core/dominio.py", "src/core", "inventado.py"])
    card = svc.get_cards(orch.id)[0]
    fontes = svc._agent_task._fontes_do_contexto(svc._bundle(orch.id), card)  # noqa: SLF001
    assert len(fontes.vizinhanca_do_codigo) == 1  # diretório e inexistente não geram linha
    linha = fontes.vizinhanca_do_codigo[0]
    assert "src/core/dominio.py" in linha
    assert "usado por: src/core/api.py" in linha
    assert "testes: tests/test_dominio.py" in linha
    # e o contexto montado leva o item (prioridade abaixo das ADRs, ADR-0063)
    contexto = construir_contexto(fontes)
    assert [i.chave for i in contexto.itens if i.chave == "codigo"] == ["codigo"]


def test_card_sem_arquivo_citado_nao_paga_indice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Custo só onde há ganho: sem arquivo citado o índice nem é construído."""
    raiz = _projeto(tmp_path)
    chamadas: list[str] = []
    import aso.application.agent_task as agent_task

    monkeypatch.setattr(
        agent_task, "indice_para_uso", lambda alvo: chamadas.append(str(alvo)) or None
    )
    svc = OrchestrationService()
    orch = svc.create_orchestration("sem arquivos", target_path=str(raiz))
    card = svc.get_cards(orch.id)[0]
    fontes = svc._agent_task._fontes_do_contexto(svc._bundle(orch.id), card)  # noqa: SLF001
    assert fontes.vizinhanca_do_codigo == [] and chamadas == []
