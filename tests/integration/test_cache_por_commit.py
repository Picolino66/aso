"""MEL-57 — cache do índice/discovery por commit: reaproveitamento, invalidação e visibilidade.

O cache por `(repositório, commit)` nasceu na MEL-44 (ADR-0077). Aqui se verifica o que a MEL-57
pede: a segunda demanda no mesmo commit **não recalcula** (medido), commit novo invalida, a origem
aparece no relatório e no registro da execução, e o cache em disco não cresce sem limite.
"""

from __future__ import annotations

import json
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

from aso.application.orchestration_service import OrchestrationService
from aso.control.discovery import DiscoveryService
from aso.control.models import AgentAssignment
from aso.control.triage import DemandBrief
from aso.execution import code_index
from aso.execution.catalog import ExecutorCatalog, ExecutorProfile
from aso.execution.code_index import (
    ORIGEM_DISCO,
    ORIGEM_MEMORIA,
    ORIGEM_NOVO,
    PASTA_DO_INDICE,
    caminho_do_indice,
    indice_do_repositorio,
    indice_para_uso,
    limpar_cache_em_memoria,
    limpar_indices,
)
from aso.execution.workspace import WorkspaceAnalyzer


@pytest.fixture(autouse=True)
def _sem_cache_em_memoria() -> None:
    limpar_cache_em_memoria()


def _git(path: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=path, check=True, capture_output=True)


def _repo(raiz: Path) -> Path:
    raiz.mkdir(parents=True, exist_ok=True)
    (raiz / "src").mkdir()
    (raiz / "src" / "app.py").write_text("def principal() -> int:\n    return 1\n")
    _git(raiz, "init", "-q")
    _git(raiz, "config", "user.email", "t@t")
    _git(raiz, "config", "user.name", "t")
    _git(raiz, "add", "-A")
    _git(raiz, "commit", "-qm", "base")
    return raiz


def _commitar(raiz: Path, nome: str) -> None:
    (raiz / "src" / nome).write_text("x = 1\n")
    _git(raiz, "add", "-A")
    _git(raiz, "commit", "-qm", nome)


# ------------------------------------------------------------ reaproveitamento medido


def test_segunda_leitura_no_mesmo_commit_nao_reconstroi(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Critério 1: a segunda demanda no mesmo commit reaproveita — medido por contagem."""
    raiz = _repo(tmp_path / "proj")
    construcoes: list[str] = []
    original = code_index.construir_indice

    def contando(*args: Any, **kwargs: Any) -> Any:
        construcoes.append(str(args[0]))
        return original(*args, **kwargs)

    monkeypatch.setattr(code_index, "construir_indice", contando)

    inicio = time.monotonic()
    primeiro = indice_para_uso(raiz)
    custo_do_primeiro = time.monotonic() - inicio
    assert primeiro is not None and primeiro.origem == ORIGEM_NOVO
    assert len(construcoes) == 1

    # mesma chamada no mesmo processo: memória
    segundo = indice_para_uso(raiz)
    assert segundo is not None and segundo.origem == ORIGEM_MEMORIA
    assert len(construcoes) == 1

    # outra demanda, processo "novo" (sem o cache em memória): disco
    limpar_cache_em_memoria()
    inicio = time.monotonic()
    terceiro = indice_para_uso(raiz)
    custo_do_terceiro = time.monotonic() - inicio
    assert terceiro is not None and terceiro.origem == ORIGEM_DISCO
    assert len(construcoes) == 1  # nada foi reconstruído
    assert terceiro.arquivos.keys() == primeiro.arquivos.keys()
    # a medição é o ponto do critério: reaproveitar não pode custar mais que construir
    assert custo_do_terceiro <= custo_do_primeiro + 0.5


def test_commit_novo_invalida_o_cache(tmp_path: Path) -> None:
    raiz = _repo(tmp_path / "proj")
    primeiro, reaproveitado = indice_do_repositorio(raiz)
    assert reaproveitado is False
    assert caminho_do_indice(raiz, primeiro.commit).is_file()

    limpar_cache_em_memoria()
    _commitar(raiz, "novo.py")
    segundo, reaproveitado = indice_do_repositorio(raiz)

    assert reaproveitado is False
    assert segundo.commit != primeiro.commit
    assert segundo.origem == ORIGEM_NOVO
    assert "src/novo.py" in segundo.arquivos
    # e o commit anterior continua servindo se alguém voltar para ele
    assert caminho_do_indice(raiz, primeiro.commit).is_file()


def test_arvore_suja_nao_reaproveita_nem_grava(tmp_path: Path) -> None:
    raiz = _repo(tmp_path / "proj")
    indice_do_repositorio(raiz)
    limpar_cache_em_memoria()
    (raiz / "src" / "rascunho.py").write_text("y = 2\n")

    indice, reaproveitado = indice_do_repositorio(raiz)

    assert indice.sujo is True and reaproveitado is False
    assert indice.origem == ORIGEM_NOVO


# ------------------------------------------------------------ limpeza configurável


def test_cache_em_disco_respeita_o_limite_de_quantidade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raiz = _repo(tmp_path / "proj")
    monkeypatch.setenv("ASO_INDICE_MAX_ARQUIVOS", "2")
    commits: list[str] = []
    for nome in ("a.py", "b.py", "c.py"):
        limpar_cache_em_memoria()
        indice, _ = indice_do_repositorio(raiz)
        commits.append(indice.commit)
        _commitar(raiz, nome)
    limpar_cache_em_memoria()
    ultimo, _ = indice_do_repositorio(raiz)

    guardados = sorted(p.stem for p in (raiz / PASTA_DO_INDICE).glob("*.json"))
    assert len(guardados) == 2, guardados
    assert ultimo.commit in guardados  # o atual nunca é apagado
    assert commits[0] not in guardados  # o mais antigo saiu


def test_limpeza_por_idade_e_preservacao_do_atual(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raiz = _repo(tmp_path / "proj")
    pasta = raiz / PASTA_DO_INDICE
    pasta.mkdir(parents=True, exist_ok=True)
    antigo = pasta / "commitvelho.json"
    antigo.write_text("{}", encoding="utf-8")
    import os

    velho = time.time() - 40 * 86_400
    os.utime(antigo, (velho, velho))
    atual = pasta / "commitatual.json"
    atual.write_text("{}", encoding="utf-8")
    os.utime(atual, (velho, velho))  # também velho, mas é o que a chamada acabou de gravar

    monkeypatch.setenv("ASO_INDICE_MAX_IDADE_DIAS", "30")
    removidos = limpar_indices(raiz, manter="commitatual")

    assert removidos == ["commitvelho"]
    assert atual.is_file() and not antigo.exists()


def test_limpeza_em_pasta_sem_indice_nao_falha(tmp_path: Path) -> None:
    assert limpar_indices(tmp_path / "inexistente") == []


# ------------------------------------------------------------ visibilidade


def _catalogo(resposta: dict[str, Any]) -> ExecutorCatalog:
    script = 'cat > /dev/null; printf %s "$1"; exit 0'
    comando = shlex.join(["bash", "-c", script, "_", json.dumps(resposta, ensure_ascii=False)])
    return ExecutorCatalog([ExecutorProfile(name="agente", kind="cli", command=comando)])


def test_relatorio_de_discovery_declara_a_origem_do_mapa(tmp_path: Path) -> None:
    raiz = _repo(tmp_path / "proj")
    indice = indice_para_uso(raiz)
    assert indice is not None and indice.origem == ORIGEM_NOVO
    servico = DiscoveryService(
        catalog=_catalogo(
            {
                "situacao_atual": "há um app",
                "problema": "sem validação",
                "componentes_afetados": ["src/app.py"],
                "confianca": "media",
            }
        )
    )

    relatorio = servico.investigar(
        AgentAssignment(executor="agente"),
        user_request="validar entrada",
        demand_brief=DemandBrief(objetivo="validar"),
        workspace_report=WorkspaceAnalyzer().analyze(raiz),
        indice=indice,
    )

    assert relatorio.indice_commit == indice.commit
    assert relatorio.indice_origem == ORIGEM_NOVO
    assert any("Mapa estrutural do commit" in linha for linha in relatorio.log)
    assert any(ORIGEM_NOVO in linha for linha in relatorio.log)


def test_run_discovery_registra_a_origem_no_evento_e_no_agent_run(tmp_path: Path) -> None:
    raiz = _repo(tmp_path / "proj")
    svc = OrchestrationService(
        catalog=_catalogo(
            {"situacao_atual": "ok", "problema": "p", "componentes_afetados": ["src/app.py"]}
        )
    )
    primeira = svc.create_orchestration("validar entrada", target_path=str(raiz))
    svc.set_agent_assignment(primeira.id, "discovery", executor="agente")
    svc.run_discovery(primeira.id)

    # segunda demanda, MESMO commit: a parte estrutural é reaproveitada
    limpar_cache_em_memoria()
    segunda = svc.create_orchestration("validar saída", target_path=str(raiz))
    svc.set_agent_assignment(segunda.id, "discovery", executor="agente")
    svc.run_discovery(segunda.id)

    primeiro_evento = [e for e in svc.timeline(primeira.id) if e.type == "DiscoveryRun"][-1]
    segundo_evento = [e for e in svc.timeline(segunda.id) if e.type == "DiscoveryRun"][-1]
    assert primeiro_evento.payload["indice_origem"] == ORIGEM_NOVO
    assert segundo_evento.payload["indice_origem"] in (ORIGEM_DISCO, ORIGEM_MEMORIA)
    assert primeiro_evento.payload["indice_commit"] == segundo_evento.payload["indice_commit"]

    # e a auditoria (ADR-0065) guarda o mesmo no envelope da pergunta
    runs = [r for r in svc.list_agent_runs(segunda.id) if r.task_type == "discovery"]
    assert runs and runs[-1].envelope["indice_origem"] in (ORIGEM_DISCO, ORIGEM_MEMORIA)
    assert runs[-1].envelope["indice_commit"] == segundo_evento.payload["indice_commit"]

    relatorio = svc.get_discovery_report(segunda.id)
    assert relatorio.indice_origem in (ORIGEM_DISCO, ORIGEM_MEMORIA)


def test_painel_de_discovery_mostra_a_origem_do_mapa() -> None:
    from fastapi.testclient import TestClient

    from aso.api.app import create_app

    pagina = TestClient(create_app(OrchestrationService())).get("/ui/demanda-detalhe").text
    assert "Mapa estrutural" in pagina
    assert "reaproveitado do cache" in pagina
    assert "indice_origem" in pagina
