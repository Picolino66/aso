"""CliAgentExecutionProvider — executa um agente CLI real em worktree isolado (§26.3).

Cria um worktree/branch por card, roda o comando do agente CLI (ex.: `claude`, `codex`)
com o prompt via stdin, coleta o diff e retorna uma `AgentOutput` com um ContextPatch
descrevendo a alteração (branch + resumo do diff) — que o ContextBus valida/aplica.

A saída é lida **linha a linha, enquanto o agente trabalha** (ADR-0015): antes usávamos
`subprocess.run(capture_output=True)`, que só entrega os pipes depois que o processo
morre — o operador ficava minutos diante de uma tela parada sem saber se o agente estava
produzindo, travado pedindo permissão, ou morto. Cada linha vai para o `OutputSink`
(porta em `aso.shared.agent_output`) e alimenta o painel ao vivo da tela de detalhe.

O comando é injetável; nos testes usamos um comando fake que edita arquivos, exercitando
worktree + diff de verdade sem depender de um agente CLI instalado.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from dataclasses import asdict
from typing import IO, Any

from aso.agents.executor import AgentExecutionError
from aso.agents.models import AgentOutput, AgentSpec
from aso.execution.agent_stream import extrair_texto, extrair_uso, interpretar
from aso.execution.branch_naming import unique_branch
from aso.execution.worktree import WorktreeManager
from aso.governance.models import ContextPatch
from aso.shared.agent_output import STREAM_STDERR, STREAM_STDOUT, OutputBus, OutputSink
from aso.shared.agent_usage import UsoDoAgente
from aso.shared.ids import gen_id
from aso.shared.types import PatchType, Phase

# Rede de segurança, não limite apertado: um agente pode legitimamente levar dezenas de
# minutos. O que este teto impede é o caso patológico — CLI parado esperando permissão
# interativa ou TTY — que antes prendia uma thread do servidor e um worktree para sempre.
TIMEOUT_PADRAO = float(os.environ.get("ASO_AGENT_TIMEOUT", "1800"))


class CliAgentExecutionProvider:
    """ExecutionProvider que roda um agente CLI em worktree isolado."""

    def __init__(
        self,
        command: list[str],
        base_repo: str,
        *,
        worktree: WorktreeManager | None = None,
        executor_id: str = "cli_agent",
        log_bus: OutputBus | None = None,
        timeout: float | None = None,
    ) -> None:
        # `executor_id` distingue candidatos concorrentes no mesmo repo (§26A.6).
        self.id = executor_id
        self.command = command
        self.worktree = worktree or WorktreeManager(base_repo)
        # Sem bus, a execução funciona igual — só não há painel ao vivo (testes, CLI).
        self.log_bus = log_bus
        self.timeout = TIMEOUT_PADRAO if timeout is None else timeout

    def execute(self, agent: AgentSpec, task: dict[str, Any]) -> AgentOutput:
        # A branch é batizada pelo card (`feat/calculadora-basica`, ADR-0014) e fechada
        # aqui com um sufixo único: candidatos concorrentes (§26A.6) e retries executam
        # a MESMA task e colidiriam em `git worktree add` com um nome fixo.
        # Sem raiz — execução direta do provider, testes, chamadas legadas — mantém o
        # nome antigo, que já carregava executor_id + uuid pelo mesmo motivo.
        stem = str(task.get("branch_stem") or "")
        escolhida = unique_branch(stem, gen_id()) if stem else ""
        name = escolhida or f"{agent.role}-{self.id}-{gen_id()}"
        path, branch = self.worktree.create(name, branch=escolhida or None)
        sink = self._abrir_sink(agent, task, branch)
        try:
            saida = self._rodar(task, str(path), sink)
            if saida.returncode != 0:
                detail = _failure_detail(saida.stderr or saida.stdout)
                raise AgentExecutionError(
                    f"Executor CLI terminou com exit={saida.returncode}: {detail or 'sem saída'}"
                )
            diff = self.worktree.collect_diff(path)
            if not diff.strip():
                raise AgentExecutionError(_empty_diff_detail(saida.stdout, saida.stderr))
            # Só entra em ação se o agente NÃO commitou (árvore suja); quando ele
            # commitou, o histórico já é dele — governamos via prompt, não reescrevendo.
            padrao = f"aso: {agent.role} ({task.get('card_id', '-')})"
            self.worktree.commit(path, str(task.get("commit_subject") or padrao))
        except Exception as exc:
            if sink is not None:
                sink.close(ok=False, detail=str(exc)[:200])
            raise
        else:
            if sink is not None:
                sink.close(ok=True, detail=f"{len(diff.splitlines())} linhas de diff")
        finally:
            self.worktree.remove(path)

        section = agent.context_sections[0] if agent.context_sections else "engineering"
        diff_lines = len(diff.splitlines())
        patch = ContextPatch(
            orchestration_id=str(task["orchestration_id"]),
            card_id=task.get("card_id"),
            agent=agent.role,
            phase=Phase(task.get("phase", Phase.F5)),
            patch_type=PatchType.UPDATE,
            target_path=f"{section}.cli_{agent.role}",
            content={"branch": branch, "diff_lines": diff_lines, "exit_code": saida.returncode},
            evidence=[f"worktree={name}", f"branch={branch}", f"exit={saida.returncode}"],
        )
        return AgentOutput(
            agent_role=agent.role,
            executor_id=self.id,
            summary=f"[cli] {agent.role} rodou em {branch} (diff: {diff_lines} linhas)",
            patches=[patch],
            # A cauda, não o início: o desfecho do agente é o que interessa depois.
            artifacts={
                "branch": branch,
                "diff": diff,
                "stdout": saida.stdout[-4000:],
                "uso": asdict(saida.uso),
            },
        )

    def _abrir_sink(self, agent: AgentSpec, task: dict[str, Any], branch: str) -> OutputSink | None:
        if self.log_bus is None:
            return None
        return self.log_bus.open(
            str(task["orchestration_id"]),
            card_id=task.get("card_id"),
            agent=agent.role,
            executor=self.id,
            branch=branch,
        )

    def _rodar(self, task: dict[str, Any], cwd: str, sink: OutputSink | None) -> _Saida:
        """Roda o agente lendo os pipes **enquanto** ele trabalha.

        Uma thread por pipe em vez de `selectors`: mantém `stdout` e `stderr` separados
        (o motivo de falha prefere o stderr) e elimina o risco de deadlock quando um dos
        pipes enche enquanto lemos o outro.
        """
        # Muitos CLIs bufferizam em bloco ao detectar que não há TTY; isto ajuda no que
        # for Python. Para os demais, quem resolve é a flag de streaming do próprio
        # agente (`--output-format stream-json`, `--json`) — ver docs/operations.md.
        env = {**os.environ, "PYTHONUNBUFFERED": "1"}
        proc = subprocess.Popen(
            self.command,
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
        )
        out: list[str] = []
        err: list[str] = []
        bombas = [
            threading.Thread(
                target=self._bombear, args=(proc.stdout, out, STREAM_STDOUT, sink), daemon=True
            ),
            threading.Thread(
                target=self._bombear, args=(proc.stderr, err, STREAM_STDERR, sink), daemon=True
            ),
        ]
        for bomba in bombas:
            bomba.start()
        self._enviar_tarefa(proc, task)
        try:
            proc.wait(timeout=self.timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            for bomba in bombas:
                bomba.join(timeout=2.0)
            if sink is not None:
                sink.marco(f"tempo limite de {self.timeout:.0f}s estourado — processo encerrado")
            raise AgentExecutionError(
                f"Executor CLI não terminou em {self.timeout:.0f}s e foi encerrado. "
                f"Última saída: {extrair_texto(''.join(out) or ''.join(err)) or 'nenhuma'}"
            ) from None
        for bomba in bombas:
            bomba.join(timeout=5.0)
        uso = _extrair_uso_da_saida(out)
        return _Saida(returncode=proc.returncode, stdout="".join(out), stderr="".join(err), uso=uso)

    @staticmethod
    def _enviar_tarefa(proc: subprocess.Popen[str], task: dict[str, Any]) -> None:
        """Escreve a tarefa no stdin do processo — sem presumir que ele vai lê-la.

        Causa raiz da corrida de candidatos intermitente (plano6 §0, ADR-0024): um
        comando rápido e determinístico que não lê stdin (ou já terminou) fecha o
        pipe antes desta escrita, e `proc.stdin.write` levanta `BrokenPipeError`.
        O código antigo tratava isso como falha do executor e abortava — mas o
        processo pode ter rodado e terminado com sucesso sem nunca precisar da
        tarefa via stdin. O próprio `subprocess.communicate()` da stdlib ignora o
        mesmo erro pelo mesmo motivo; aqui deixamos `proc.wait()` decidir pelo
        código de saída real, não pelo sucesso da escrita.
        """
        if proc.stdin is None:
            return
        try:
            proc.stdin.write(json.dumps(task, ensure_ascii=False))
        except BrokenPipeError:
            pass
        try:
            proc.stdin.close()
        except BrokenPipeError:
            pass

    @staticmethod
    def _bombear(
        pipe: IO[str] | None, destino: list[str], stream: str, sink: OutputSink | None
    ) -> None:
        """Lê o pipe linha a linha até o EOF, acumulando e publicando ao vivo."""
        if pipe is None:
            return
        try:
            for linha in pipe:
                destino.append(linha)
                if sink is None:
                    continue
                for item in interpretar(linha):
                    sink.write(stream, item.text, kind=item.kind, detail=item.detail)
        except (OSError, ValueError):  # pipe fechado no kill: a saída já foi capturada
            return
        finally:
            pipe.close()


class _Saida:
    """Resultado de uma execução — o mesmo trio que o `subprocess.run` devolvia, mais
    o consumo relatado pelo agente (§26A.11, ADR-0026)."""

    __slots__ = ("returncode", "stdout", "stderr", "uso")

    def __init__(
        self, *, returncode: int, stdout: str, stderr: str, uso: UsoDoAgente | None = None
    ) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.uso = uso or UsoDoAgente()


def _extrair_uso_da_saida(linhas: list[str]) -> UsoDoAgente:
    """Última linha com uso reconhecido vence — o envelope `result` do Claude Code
    é a última linha do stream, mas não custa varrer tudo em vez de presumir posição."""
    uso = UsoDoAgente()
    for linha in linhas:
        encontrado = extrair_uso(linha)
        if encontrado is not None:
            uso = encontrado
    return uso


def _empty_diff_detail(stdout: str, stderr: str) -> str:
    """Motivo do diff vazio **com a última fala do agente** — é ela que revela a causa.

    O caso mais comum não é o agente "não saber fazer": é ele rodar **sem permissão de
    escrita** (`claude -p` sem `--permission-mode`, `codex exec` em sandbox read-only).
    Aí o CLI responde em texto ("aguardo sua permissão"), sai com código 0 e o worktree
    fica intacto. Descartar essa saída deixava o operador sem pista nenhuma.
    """
    base = "Executor CLI não produziu alterações no worktree (diff vazio)."
    # `extrair_texto` destila a FALA do agente: com o streaming em NDJSON ligado, a saída
    # crua é uma parede de JSON e o motivo no card ficaria ilegível.
    fala = extrair_texto(stdout or stderr or "")
    if not fala:
        return f"{base} O agente não deixou saída — confira o comando do executor."
    return f"{base} Última saída do agente: {fala}"


def _failure_detail(output: str) -> str:
    """Extrai a mensagem estruturada sem devolver prompt/JSON bruto ao console."""
    messages: list[str] = []
    for line in output.splitlines():
        candidate = line.strip()
        if candidate.startswith("ERROR:"):
            candidate = candidate.removeprefix("ERROR:").strip()
        if not candidate.startswith("{"):
            continue
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        error = payload.get("error") if isinstance(payload, dict) else None
        message = error.get("message") if isinstance(error, dict) else None
        if isinstance(message, str) and message not in messages:
            messages.append(message)
    if messages:
        return " ".join(messages)[:600]
    # Sem erro estruturado: devolve a fala destilada, não o NDJSON cru.
    return extrair_texto(output, limite=600) or output.strip()[-600:]
