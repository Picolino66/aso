"""MEL-14 — o wrapper real (`scripts/aso-agent-wrapper.sh`) com um agente CLI fake.

O fake só responde o JSON certo quando o prompt traz o `system` do serviço e NÃO manda
implementar — exatamente o que o wrapper antigo quebrava para triagem/discovery/spec/
revisão. Roda nos dois formatos de saída: texto puro e NDJSON `stream-json`.
"""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from aso.control.models import AgentAssignment
from aso.control.naming import NamingService
from aso.control.review import ReviewService
from aso.control.triage import TriageService
from aso.execution.catalog import ExecutorCatalog, ExecutorProfile

RAIZ = Path(__file__).resolve().parents[2]
WRAPPER = RAIZ / "scripts/aso-agent-wrapper.sh"

_FAKE = r"""
import json, sys
prompt = sys.argv[-1]
modo_stream = sys.argv[1] == "stream"
open(sys.argv[2], "w").write(prompt)
resposta = None
if "Implemente" not in prompt:
    if "Você faz a triagem" in prompt:
        resposta = {"tipo": "funcionalidade", "objetivo": "Login social via agente",
                    "dominios": ["backend"], "risco": "medium", "complexidade": "media"}
    elif "Você nomeia branches" in prompt:
        resposta = {"branch": "login-social", "commit": "feat: adicionar login social"}
    elif "Você revisa código" in prompt:
        resposta = {"veredito": "aprovado", "resumo": "diff correto", "acoes": [],
                    "comentarios": [], "pontos_verificados": ["correção"]}
texto = json.dumps(resposta, ensure_ascii=False) if resposta else "Implementei tudo!"
if modo_stream:
    print(json.dumps({"type": "system", "subtype": "init"}))
    print(json.dumps({"type": "assistant",
                      "message": {"content": [{"type": "text", "text": "ok"}]}}))
    print(json.dumps({"type": "result", "subtype": "success", "result": texto}))
else:
    print(texto)
"""


def _catalogo(tmp_path: Path, modo: str) -> tuple[ExecutorCatalog, Path]:
    fake = tmp_path / "fake_agent.py"
    fake.write_text(_FAKE)
    registro = tmp_path / "prompt.txt"
    comando = shlex.join([str(WRAPPER), sys.executable, str(fake), modo, str(registro)])
    perfil = ExecutorProfile(name="cli-fake", kind="cli", command=comando)
    return ExecutorCatalog([perfil]), registro


_MODOS = ["texto", "stream"]


@pytest.mark.parametrize("modo", _MODOS)
def test_triagem_via_wrapper_usa_o_agente(tmp_path: Path, modo: str) -> None:
    catalogo, registro = _catalogo(tmp_path, modo)
    ficha = TriageService(catalogo, timeout=30).analisar(
        AgentAssignment(executor="cli-fake"), user_request="Adicionar login social"
    )
    assert ficha.fallback_reason == ""
    assert ficha.origem == "cli-fake"  # não "heuristica"
    assert ficha.objetivo == "Login social via agente"
    assert "Você faz a triagem" in registro.read_text()


@pytest.mark.parametrize("modo", _MODOS)
def test_naming_via_wrapper_usa_o_agente(tmp_path: Path, modo: str) -> None:
    catalogo, _registro = _catalogo(tmp_path, modo)
    nomes = NamingService(catalogo, timeout=30).suggest(
        AgentAssignment(executor="cli-fake"), card_type="Feature", title="Login social"
    )
    assert nomes.source == "agente", nomes.fallback_reason
    assert "login-social" in nomes.branch_stem


@pytest.mark.parametrize("modo", _MODOS)
def test_revisao_via_wrapper_usa_o_agente(tmp_path: Path, modo: str) -> None:
    catalogo, registro = _catalogo(tmp_path, modo)
    veredito = ReviewService(catalogo, timeout=30).revisar(
        AgentAssignment(executor="cli-fake"),
        diff="+def soma(a, b):\n+    return a + b\n",
        card_title="Somar",
    )
    assert veredito.veredito == "aprovado", veredito.fallback_reason
    assert "Você revisa código" in registro.read_text()


def test_execucao_via_wrapper_recebe_prompt_de_implementacao(tmp_path: Path) -> None:
    from aso.control.orchestration_service import OrchestrationService

    svc = OrchestrationService()
    oid = svc.create_orchestration("Criar calculadora").id
    b = svc._bundle(oid)  # noqa: SLF001 - usa a tarefa real montada pelo runtime
    card = b.board_service.cards_of(b.board.id)[0]
    card.contexto_adicional = ["use apenas stdlib"]
    agente = b.agent_registry.get(str(card.assignee))
    assert agente is not None
    tarefa = svc._build_task(b, card, agente)  # noqa: SLF001
    tarefa["nudge"] = "tentativa 1 falhou: testes vermelhos"

    fake = tmp_path / "fake_agent.py"
    fake.write_text(_FAKE)
    registro = tmp_path / "prompt.txt"
    proc = subprocess.run(
        [str(WRAPPER), sys.executable, str(fake), "texto", str(registro)],
        input=json.dumps(tarefa, ensure_ascii=False),
        capture_output=True,
        text=True,
        cwd=tmp_path,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    prompt = registro.read_text()
    assert "Implemente" in prompt
    assert card.title in prompt
    assert "use apenas stdlib" in prompt
    assert "tentativa 1 falhou: testes vermelhos" in prompt


def test_wrapper_recusa_envelope_de_versao_desconhecida(tmp_path: Path) -> None:
    fake = tmp_path / "fake_agent.py"
    fake.write_text(_FAKE)
    tarefa = {"envelope": {"schema_version": "2", "kind": "ask", "task_type": "triagem"}}
    proc = subprocess.run(
        [str(WRAPPER), sys.executable, str(fake), "texto", str(tmp_path / "p.txt")],
        input=json.dumps(tarefa),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    assert "schema_version '2' desconhecida" in proc.stderr
    assert not (tmp_path / "p.txt").exists()  # o agente nem foi chamado
