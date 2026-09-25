"""MEL-54 — catálogo único de executores (ADR-0076).

Cobre: flags montadas por campo do perfil (sem editar o comando), migração sem perda dos perfis
salvos, seed do ambiente como único leitor de `ASO_CLI_COMMAND`/`ASO_LLM_*`/
`ASO_CANDIDATE_COMMANDS`, planejamento e corrida de candidatos vindos do catálogo e o bootstrap
sem provider global.
"""

from __future__ import annotations

import ast
import json
import shlex
import subprocess
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from aso.api.app import create_app
from aso.application.orchestration_service import OrchestrationService
from aso.execution.catalog import (
    ExecutorCatalog,
    ExecutorProfile,
    build_catalog_from_env,
)
from aso.execution.cli_provider import CliAgentExecutionProvider
from aso.execution.flags_de_cli import aplicar_flags, migrar_comando
from aso.execution.llm_client import FakeLlmClient
from aso.execution.repositorio_leitura import comando_somente_leitura
from aso.execution.settings_store import ExecutorSettingsStore

RAIZ = Path(__file__).resolve().parents[2]
WRAPPER = "/home/eu/Área de trabalho/aso/scripts/aso-agent-wrapper.sh"
_ENVS_DE_EXECUTOR = (
    "ASO_EXECUTORS",
    "ASO_CLI_COMMAND",
    "ASO_CANDIDATE_COMMANDS",
    "ASO_LLM_PROVIDER",
    "ASO_LLM_MODEL",
    "ASO_LLM_BASE_URL",
    "ASO_LLM_API_KEY",
    "ASO_TARGET_REPO",
)


@pytest.fixture(autouse=True)
def _ambiente_limpo(monkeypatch: pytest.MonkeyPatch) -> None:
    for nome in _ENVS_DE_EXECUTOR:
        monkeypatch.delenv(nome, raising=False)


def _repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    for args in (
        ("init", "-q"),
        ("config", "user.email", "t@t"),
        ("config", "user.name", "t"),
    ):
        subprocess.run(["git", *args], cwd=path, check=True, capture_output=True)
    (path / "README.md").write_text("base\n")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=path, check=True, capture_output=True)
    return path


# ------------------------------------------------------------------ flags por campo


def test_claude_streaming_e_permissao_viram_flags_sem_editar_o_comando() -> None:
    perfil = ExecutorProfile(
        name="claude",
        kind="cli",
        command=f"{shlex.quote(WRAPPER)} claude -p --model opus",
        streaming=True,
        permissao_escrita="edicoes",
    )
    assert "--output-format" not in perfil.command  # o comando salvo continua limpo
    comando = ExecutorCatalog([perfil]).cli_command("claude")
    assert comando[:5] == [WRAPPER, "claude", "-p", "--model", "opus"]
    assert comando.count("--output-format") == 1
    assert ["stream-json", "--verbose"] == comando[comando.index("--output-format") + 1 :][:2]
    assert comando[comando.index("--permission-mode") + 1] == "acceptEdits"


@pytest.mark.parametrize(
    ("permissao", "claude", "codex"),
    [
        ("nenhuma", ["--permission-mode", "plan"], ["--sandbox", "read-only"]),
        ("edicoes", ["--permission-mode", "acceptEdits"], ["--sandbox", "workspace-write"]),
        ("total", ["--dangerously-skip-permissions"], ["--sandbox", "danger-full-access"]),
    ],
)
def test_permissao_por_familia(permissao: str, claude: list[str], codex: list[str]) -> None:
    pronto_claude = aplicar_flags(["claude", "-p"], streaming=False, permissao_escrita=permissao)
    assert pronto_claude == ["claude", "-p", *claude]
    pronto_codex = aplicar_flags(["codex", "exec"], streaming=True, permissao_escrita=permissao)
    assert pronto_codex == ["codex", "exec", "--json", *codex]


def test_comando_fora_das_familias_conhecidas_nao_recebe_flag() -> None:
    comando = ["bash", "-c", "echo claude > x"]
    assert aplicar_flags(comando, streaming=True, permissao_escrita="total") == comando


def test_permissao_invalida_e_recusada() -> None:
    with pytest.raises(ValidationError, match="permissao_escrita"):
        ExecutorProfile(name="x", kind="cli", command="claude -p", permissao_escrita="root")


def test_pergunta_somente_leitura_anula_permissao_total() -> None:
    """Governança (ADR-0069): um perfil com escrita total não pode escrever numa pergunta."""
    catalogo = ExecutorCatalog(
        [
            ExecutorProfile(name="c", kind="cli", command="claude -p", permissao_escrita="total"),
            ExecutorProfile(name="x", kind="cli", command="codex exec", permissao_escrita="total"),
        ]
    )
    leitura_claude = comando_somente_leitura(catalogo.cli_command("c"))
    assert "--dangerously-skip-permissions" not in leitura_claude
    assert leitura_claude[leitura_claude.index("--permission-mode") + 1] == "plan"
    leitura_codex = comando_somente_leitura(catalogo.cli_command("x"))
    assert leitura_codex[leitura_codex.index("--sandbox") + 1] == "read-only"
    assert "danger-full-access" not in leitura_codex


# ------------------------------------------------------------------ migração


def test_migracao_do_que_os_scripts_escreviam_e_idempotente() -> None:
    antigo = (
        f'"{WRAPPER}" claude -p --dangerously-skip-permissions --model opus '
        "--output-format stream-json --verbose"
    )
    limpo, streaming, permissao = migrar_comando(antigo)
    assert shlex.split(limpo) == [WRAPPER, "claude", "-p", "--model", "opus"]
    assert (streaming, permissao) == (True, "total")
    assert migrar_comando(limpo) == (limpo, False, "")

    codex = (
        f"{shlex.quote(WRAPPER)} codex exec --ignore-user-config --sandbox workspace-write --json"
    )
    limpo, streaming, permissao = migrar_comando(codex)
    assert shlex.split(limpo) == [WRAPPER, "codex", "exec", "--ignore-user-config"]
    assert (streaming, permissao) == (True, "edicoes")


def test_migracao_nao_toca_comando_sem_flag_nem_valor_desconhecido() -> None:
    com_aspas = f'"{WRAPPER}" claude -p'
    assert migrar_comando(com_aspas) == (com_aspas, False, "")  # texto idêntico, aspas incluídas
    auto = "claude -p --permission-mode auto"
    assert migrar_comando(auto) == (auto, False, "")  # sem campo equivalente: fica no comando


def test_store_migra_arquivo_antigo_sem_perda_e_so_uma_vez(tmp_path: Path) -> None:
    arquivo = tmp_path / "executors.json"
    antigos: list[dict[str, Any]] = [
        {
            "name": "claude-opus",
            "kind": "cli",
            "model": "opus",
            "effort": "high",
            "command": f'"{WRAPPER}" claude -p --dangerously-skip-permissions '
            "--output-format stream-json --verbose",
            "is_default": True,
        },
        {
            "name": "codex-default",
            "kind": "cli",
            "command": "/w /usr/bin/codex exec --ignore-user-config --sandbox workspace-write",
            "managed_by": "codex",
            "supported_efforts": ["low", "medium"],
            "runtime_version": "codex-cli 9.9",
        },
        {"name": "custom", "kind": "cli", "command": "meu-agente --rapido"},
        {"name": "deepseek", "kind": "llm", "provider": "deepseek", "model": "deepseek-chat"},
    ]
    arquivo.write_text(json.dumps(antigos), encoding="utf-8")
    catalogo_antes = {p["name"]: shlex.split(p["command"]) for p in antigos if p["kind"] == "cli"}

    perfis = {p.name: p for p in ExecutorSettingsStore(str(arquivo)).load()}

    assert perfis["claude-opus"].streaming is True
    assert perfis["claude-opus"].permissao_escrita == "total"
    assert perfis["claude-opus"].is_default and perfis["claude-opus"].effort == "high"
    assert perfis["codex-default"].permissao_escrita == "edicoes"
    assert perfis["codex-default"].managed_by == "codex"
    assert perfis["codex-default"].supported_efforts == ["low", "medium"]
    assert perfis["codex-default"].runtime_version == "codex-cli 9.9"
    assert perfis["custom"].command == "meu-agente --rapido"
    # sem chave própria, o LLM antigo aponta para a reserva global que saiu do runtime
    assert perfis["deepseek"].api_key_env == "ASO_LLM_API_KEY"
    # o comando pronto tem exatamente os mesmos tokens de antes (fora o esforço gerenciado)
    catalogo = ExecutorCatalog(list(perfis.values()))
    for nome, tokens in catalogo_antes.items():
        pronto = catalogo.cli_command(nome, effort_override=None)
        sem_effort = [t for t in pronto if t not in ("--effort", "high", "-c")]
        sem_effort = [t for t in sem_effort if not t.startswith("model_reasoning_effort=")]
        assert sorted(sem_effort) == sorted(tokens), nome

    # regravado já migrado, com cópia do original; a segunda leitura não regrava
    assert json.loads((tmp_path / "executors.json.antes-adr-0076").read_text()) == antigos
    gravado = arquivo.read_text(encoding="utf-8")
    assert "--dangerously-skip-permissions" not in gravado
    ExecutorSettingsStore(str(arquivo)).load()
    assert arquivo.read_text(encoding="utf-8") == gravado


def test_llm_antigo_com_chave_propria_mantem_o_nome_padrao(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ASO_DEEPSEEK_API_KEY", "segredo")
    arquivo = tmp_path / "executors.json"
    arquivo.write_text(json.dumps([{"name": "deepseek", "kind": "llm", "model": "m"}]))
    (perfil,) = ExecutorSettingsStore(str(arquivo)).load()
    assert perfil.api_key_env == ""
    assert perfil.public()["api_key_env"] == "ASO_DEEPSEEK_API_KEY"
    assert "segredo" not in arquivo.read_text()


def test_sync_do_codex_preserva_escolhas_do_operador() -> None:
    from aso.execution.catalog import managed_codex_profiles
    from aso.execution.codex_discovery import CodexCapabilities, CodexModel

    caps = CodexCapabilities(
        binary="/usr/bin/codex",
        version="codex-cli 1",
        models=(
            CodexModel(
                model="gpt-x",
                display_name="GPT X",
                is_default=True,
                default_effort="medium",
                supported_efforts=("low", "medium"),
            ),
        ),
    )
    catalogo = ExecutorCatalog(managed_codex_profiles(caps, wrapper="/w"))
    perfil = catalogo.get("codex-default")
    assert perfil is not None
    catalogo.upsert(
        perfil.model_copy(
            update={"streaming": True, "candidato": True, "permissao_escrita": "total"}
        )
    )
    catalogo.replace_managed_codex(managed_codex_profiles(caps, wrapper="/w"))
    depois = catalogo.get("codex-default")
    assert depois is not None
    assert (depois.streaming, depois.candidato, depois.permissao_escrita) == (True, True, "total")


def test_api_de_executores_expoe_e_grava_os_campos() -> None:
    client = TestClient(create_app(OrchestrationService(catalog=ExecutorCatalog())))
    corpo = {
        "name": "claude",
        "kind": "cli",
        "command": "claude -p --output-format stream-json --verbose",
        "permissao_escrita": "edicoes",
        "candidato": True,
    }
    entradas = client.post("/v1/executors", json=corpo).json()
    claude = next(e for e in entradas if e["name"] == "claude")
    # flag digitada no formulário vira campo (uma única representação)
    assert claude["command"] == "claude -p"
    assert claude["streaming"] is True
    assert claude["permissao_escrita"] == "edicoes"
    assert claude["candidato"] is True
    assert claude["familia_cli"] == "claude"


# ------------------------------------------------------------------ seed e varredura


def test_seed_do_ambiente_gera_perfis_do_catalogo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASO_CLI_COMMAND", "claude -p")
    monkeypatch.setenv("ASO_LLM_PROVIDER", "DeepSeek")
    monkeypatch.setenv("ASO_LLM_MODEL", "deepseek-chat")
    monkeypatch.setenv(
        "ASO_CANDIDATE_COMMANDS",
        json.dumps(["codex exec", {"id": "claude-b", "command": "claude -p --model haiku"}]),
    )
    catalogo = build_catalog_from_env()
    cli, llm = catalogo.get("cli"), catalogo.get("llm")
    assert cli is not None and cli.is_default  # código vai para o CLI, como o provider antigo
    assert llm is not None and llm.provider == "deepseek"
    assert llm.api_key_env == "ASO_LLM_API_KEY"
    candidatos = {p.name for p in catalogo.profiles() if p.candidato}
    assert candidatos == {"cli_1", "claude-b"}


_LEITURAS_LEGADAS = ("ASO_CLI_COMMAND", "ASO_CANDIDATE_COMMANDS", "ASO_LLM_")
# Flags de comportamento do cliente LLM, não fontes de executor.
_PERMITIDAS_FORA_DO_SEED = {"ASO_LLM_SAIDA_ESTRUTURADA"}
_FUNCOES_DO_SEED = {"build_catalog_from_env", "_candidatos_do_ambiente"}


def _leituras_fora_do_seed(raiz: Path) -> list[str]:
    achados: list[str] = []
    for arquivo in sorted(raiz.rglob("*.py")):
        arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
        pais: dict[ast.AST, ast.AST] = {}
        for no in ast.walk(arvore):
            for filho in ast.iter_child_nodes(no):
                pais[filho] = no
        for no in ast.walk(arvore):
            if not (isinstance(no, ast.Constant) and isinstance(no.value, str)):
                continue
            valor = no.value
            if not valor.startswith(_LEITURAS_LEGADAS) or valor in _PERMITIDAS_FORA_DO_SEED:
                continue
            if isinstance(pais.get(no), ast.Expr):
                continue  # docstring
            atual: ast.AST | None = no
            funcao = ""
            while atual is not None:
                if isinstance(atual, ast.FunctionDef):
                    funcao = atual.name
                atual = pais.get(atual)
            relativo = arquivo.relative_to(raiz).as_posix()
            no_seed = relativo == "execution/catalog.py" and funcao in _FUNCOES_DO_SEED
            constante_da_chave = relativo == "execution/catalog.py" and valor == "ASO_LLM_API_KEY"
            if not (no_seed or constante_da_chave):
                achados.append(f"{relativo}:{no.lineno} {valor}")
    return achados


def test_nenhuma_leitura_de_executor_por_ambiente_fora_do_seed() -> None:
    assert _leituras_fora_do_seed(RAIZ / "src" / "aso") == []


def test_varredura_pega_leitura_nova_fora_do_seed(tmp_path: Path) -> None:
    (tmp_path / "execution").mkdir()
    (tmp_path / "execution" / "catalog.py").write_text(
        "import os\ndef build_catalog_from_env():\n    return os.environ.get('ASO_CLI_COMMAND')\n"
    )
    (tmp_path / "bootstrap.py").write_text(
        "import os\ndef build_service():\n    return os.environ.get('ASO_LLM_MODEL')\n"
    )
    assert _leituras_fora_do_seed(tmp_path) == ["bootstrap.py:3 ASO_LLM_MODEL"]


# ------------------------------------------------------------------ planejamento


def _catalogo_com_llm(monkeypatch: pytest.MonkeyPatch) -> tuple[ExecutorCatalog, list[Any]]:
    catalogo = ExecutorCatalog(
        [
            ExecutorProfile(name="cli", kind="cli", command="claude -p", is_default=True),
            ExecutorProfile(name="barato", kind="llm", model="m", api_key_env="CHAVE_BARATA"),
            ExecutorProfile(name="forte", kind="llm", model="m", api_key_env="CHAVE_FORTE"),
        ]
    )
    chamadas: list[Any] = []
    plano = {
        "product": {"name": "P", "domain": "d", "mvp_hypothesis": "h"},
        "adrs": [],
        "backlog": [{"title": "t", "phase": "F5", "domain": "backend"}],
    }

    def _cliente(self: ExecutorCatalog, nome: str, *, effort_override: str | None = None) -> Any:
        self.validate(nome, effort_override)
        chamadas.append((nome, effort_override))
        return FakeLlmClient(lambda _s, _u: json.dumps(plano), client_id=nome)

    monkeypatch.setattr(ExecutorCatalog, "llm_client", _cliente)
    return catalogo, chamadas


def test_planejamento_sem_llm_com_chave_no_catalogo_responde_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalogo, chamadas = _catalogo_com_llm(monkeypatch)
    client = TestClient(create_app(OrchestrationService(catalog=catalogo)))
    oid = client.post("/v1/orchestrations", json={"user_request": "x"}).json()["id"]
    resp = client.post(f"/v1/orchestrations/{oid}/plan", json={"idea": "algo"})
    assert resp.status_code == 409
    assert "catálogo" in resp.json()["detail"]
    assert chamadas == []


def test_planejamento_usa_llm_padrao_e_depois_o_da_etapa(monkeypatch: pytest.MonkeyPatch) -> None:
    catalogo, chamadas = _catalogo_com_llm(monkeypatch)
    monkeypatch.setenv("CHAVE_FORTE", "k")
    monkeypatch.setenv("CHAVE_BARATA", "k")
    client = TestClient(create_app(OrchestrationService(catalog=catalogo)))
    oid = client.post("/v1/orchestrations", json={"user_request": "x"}).json()["id"]

    assert client.post(f"/v1/orchestrations/{oid}/plan", json={"idea": "a"}).status_code == 201
    assert chamadas[-1] == ("barato", None)  # primeiro LLM com chave (nenhum é default)

    atribuicao = client.put(
        f"/v1/orchestrations/{oid}/agents/planejamento",
        json={"executor": "forte", "effort": "high"},
    )
    assert atribuicao.status_code == 200
    assert client.post(f"/v1/orchestrations/{oid}/plan", json={"idea": "b"}).status_code == 201
    assert chamadas[-1] == ("forte", "high")


def test_etapa_de_planejamento_recusa_executor_que_nao_e_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalogo, _ = _catalogo_com_llm(monkeypatch)
    client = TestClient(create_app(OrchestrationService(catalog=catalogo)))
    oid = client.post("/v1/orchestrations", json={"user_request": "x"}).json()["id"]
    resp = client.put(f"/v1/orchestrations/{oid}/agents/planejamento", json={"executor": "cli"})
    assert resp.status_code in (400, 409)
    assert "LLM" in resp.json()["detail"]


def test_pipeline_completo_planeja_na_criacao_com_o_llm_do_catalogo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalogo, chamadas = _catalogo_com_llm(monkeypatch)
    monkeypatch.setenv("CHAVE_FORTE", "k")
    client = TestClient(create_app(OrchestrationService(catalog=catalogo)))
    resp = client.post(
        "/v1/orchestrations", json={"user_request": "x", "execution_mode": "full-pipeline"}
    )
    assert resp.status_code == 201
    assert chamadas and chamadas[0][0] == "forte"


# ------------------------------------------------------------------ corrida


def _svc_corrida(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> OrchestrationService:
    monkeypatch.setenv("ASO_TARGET_REPO", str(_repo(tmp_path / "proj")))
    return OrchestrationService(
        catalog=ExecutorCatalog(
            [
                ExecutorProfile(name="a", kind="cli", command="bash -c 'echo a > a.py'"),
                ExecutorProfile(
                    name="b", kind="cli", command="bash -c 'echo b > b.py'", candidato=True
                ),
                ExecutorProfile(name="llm", kind="llm", model="m"),
            ]
        )
    )


def test_corrida_com_executores_escolhidos_na_requisicao(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    svc = _svc_corrida(tmp_path, monkeypatch)
    client = TestClient(create_app(svc))
    orch = svc.create_orchestration("backend")
    card = svc.get_cards(orch.id)[0]
    url = f"/v1/orchestrations/{orch.id}/cards/{card.id}/race"

    sem_lista = client.post(url).json()  # só os marcados `candidato`
    assert [c["executor"] for c in sem_lista["candidates"]] == ["b"]
    escolhidos = client.post(url, json={"executores": ["a", "b"]}).json()
    assert {c["executor"] for c in escolhidos["candidates"]} == {"a", "b"}


@pytest.mark.parametrize(
    ("executores", "trecho"), [(["llm"], "não é um agente CLI"), (["fantasma"], "desconhecido")]
)
def test_corrida_recusa_candidato_invalido(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, executores: list[str], trecho: str
) -> None:
    svc = _svc_corrida(tmp_path, monkeypatch)
    client = TestClient(create_app(svc))
    orch = svc.create_orchestration("backend")
    card = svc.get_cards(orch.id)[0]
    resp = client.post(
        f"/v1/orchestrations/{orch.id}/cards/{card.id}/race", json={"executores": executores}
    )
    assert resp.status_code == 409
    assert trecho in resp.json()["detail"]
    assert svc.list_candidate_runs(orch.id) == []


# ------------------------------------------------------------------ bootstrap


def test_bootstrap_sem_provider_global_usa_o_catalogo_semeado(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from aso.bootstrap import build_service

    monkeypatch.delenv("ASO_DATABASE_URL", raising=False)
    monkeypatch.setenv("ASO_EXECUTORS_FILE", str(tmp_path / "nenhum.json"))
    monkeypatch.setenv("ASO_TARGET_REPO", str(_repo(tmp_path / "proj")))
    monkeypatch.setenv("ASO_CLI_COMMAND", "bash -c true")
    svc = build_service()
    assert svc._provider is None  # noqa: SLF001 - não há mais provider global
    oid = svc.create_orchestration("backend").id
    provider = svc._provider_for(svc._bundle(oid), None)  # noqa: SLF001
    assert isinstance(provider, CliAgentExecutionProvider)
    assert provider.id == "cli"


def test_bootstrap_sem_pasta_e_sem_repo_alvo_cai_no_mock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from aso.bootstrap import build_service

    monkeypatch.delenv("ASO_DATABASE_URL", raising=False)
    monkeypatch.setenv("ASO_EXECUTORS_FILE", str(tmp_path / "nenhum.json"))
    monkeypatch.setenv("ASO_CLI_COMMAND", "claude -p")  # sem ASO_TARGET_REPO nem pasta
    svc = build_service()
    oid = svc.create_orchestration("backend").id
    assert svc._provider_for(svc._bundle(oid), None) is None  # noqa: SLF001
