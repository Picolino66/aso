"""Fila persistida de jobs de execução com workers no processo (ADR-0067, MEL-31).

Antes, `run_card`, `run_phase`, o autopilot e a corrida de candidatos rodavam dentro da
requisição HTTP: com timeout de 1.800 s por tentativa e retries, uma requisição podia durar
horas, fechar a conexão não cancelava nada e reiniciar a API perdia o trabalho sem rastro.

Aqui fica só a infraestrutura, sem regra de negócio:

- `Job`: unidade de trabalho enfileirada (`queued → running → done | failed | cancelled`),
  persistida em `jobs` — cada job pode gerar vários `AgentRun` (ADR-0065).
- `FilaDeJobs`: `ASO_WORKERS` threads (padrão 2) consomem a fila em ordem de chegada e chamam
  o handler registrado para a operação. O handler é a mesma chamada síncrona de antes.
- Cancelamento cooperativo: o job em execução fica num `ContextVar`; o executor CLI registra
  o subprocess dele (`registrar_processo`) e o cancelamento mata o processo; laços longos
  (retries, cards da fase) consultam `verificar_cancelamento()` entre passos.
- Boot: job `running` de outra instância morreu com o processo → `failed` com o motivo;
  `queued` continua na fila.
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Protocol

from pydantic import BaseModel, Field, TypeAdapter

from aso.shared.ids import gen_id, now_iso

STATUS_NA_FILA = "queued"
STATUS_RODANDO = "running"
STATUS_CONCLUIDO = "done"
STATUS_FALHOU = "failed"
STATUS_CANCELADO = "cancelled"
STATUS_TERMINAIS = frozenset({STATUS_CONCLUIDO, STATUS_FALHOU, STATUS_CANCELADO})

MOTIVO_REINICIO = "interrompido por reinício do runtime"
_JSON = TypeAdapter(Any)


class Job(BaseModel):
    id: str = Field(default_factory=lambda: gen_id("job"))
    orchestration_id: str
    card_id: str | None = None
    operacao: str
    parametros: dict[str, Any] = Field(default_factory=dict)
    status: str = STATUS_NA_FILA
    resultado: Any = None
    erro: str = ""
    # Código HTTP equivalente ao erro, para o console mostrar o mesmo que a rota síncrona.
    erro_status: int | None = None
    ator: str = "system"
    dono: str = ""
    criado_em: str = Field(default_factory=now_iso)
    iniciado_em: str | None = None
    fim: str | None = None
    cancelamento_solicitado: bool = False


class JobRepository(Protocol):
    def salvar(self, job: Job) -> None: ...

    def obter(self, job_id: str) -> Job | None: ...

    def listar(
        self, *, orchestration_id: str | None = None, status: str | None = None
    ) -> list[Job]: ...


class InMemoryJobRepository:
    """Adapter em memória (testes e modo sem banco); guarda cópias, como um banco faria."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def salvar(self, job: Job) -> None:
        with self._lock:
            self._jobs[job.id] = job.model_copy(deep=True)

    def obter(self, job_id: str) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.model_copy(deep=True) if job is not None else None

    def listar(
        self, *, orchestration_id: str | None = None, status: str | None = None
    ) -> list[Job]:
        with self._lock:
            jobs = [
                j.model_copy(deep=True)
                for j in self._jobs.values()
                if (orchestration_id is None or j.orchestration_id == orchestration_id)
                and (status is None or j.status == status)
            ]
        return sorted(jobs, key=lambda j: j.criado_em)


class JobCancelado(BaseException):  # noqa: N818 — nome do domínio, como CancelledError
    """O operador cancelou o job em execução; o laço que consultou deve parar.

    Deriva de `BaseException` (como `asyncio.CancelledError`) de propósito: vários laços do
    fluxo usam `except Exception` para que um card inválido não derrube a fase inteira, e o
    cancelamento precisa atravessá-los — os blocos `finally` (liberação do claim) continuam
    rodando.
    """


# ---------------------------------------------------------------- cancelamento cooperativo
_JOB_ATUAL: ContextVar[str | None] = ContextVar("aso_job_atual", default=None)
_registro_lock = threading.Lock()
_processos: dict[str, set[subprocess.Popen[str]]] = {}
_cancelados: set[str] = set()


def job_atual() -> str | None:
    return _JOB_ATUAL.get()


@contextmanager
def executando_job(job_id: str) -> Iterator[None]:
    token = _JOB_ATUAL.set(job_id)
    try:
        yield
    finally:
        _JOB_ATUAL.reset(token)
        with _registro_lock:
            _processos.pop(job_id, None)
            _cancelados.discard(job_id)


def registrar_processo(proc: subprocess.Popen[str]) -> None:
    """Chamado pelo executor CLI logo após abrir o subprocess do agente."""
    job_id = _JOB_ATUAL.get()
    if job_id is None:
        return
    with _registro_lock:
        _processos.setdefault(job_id, set()).add(proc)
        ja_cancelado = job_id in _cancelados
    if ja_cancelado:  # cancelado entre a verificação e o Popen: não deixa o agente rodar
        _encerrar(proc)


def desregistrar_processo(proc: subprocess.Popen[str]) -> None:
    job_id = _JOB_ATUAL.get()
    if job_id is None:
        return
    with _registro_lock:
        _processos.get(job_id, set()).discard(proc)


def cancelamento_pedido() -> bool:
    job_id = _JOB_ATUAL.get()
    if job_id is None:
        return False
    with _registro_lock:
        return job_id in _cancelados


def verificar_cancelamento() -> None:
    if cancelamento_pedido():
        raise JobCancelado("Execução cancelada pelo operador.")


def _encerrar(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is None:
        proc.kill()


def _sinalizar_cancelamento(job_id: str) -> None:
    with _registro_lock:
        _cancelados.add(job_id)
        processos = list(_processos.get(job_id, ()))
    for proc in processos:
        _encerrar(proc)


# ------------------------------------------------------------------------------ fila
Handler = Callable[[Job], Any]
ClassificadorDeErro = Callable[[Exception], int | None]


def workers_configurados() -> int:
    try:
        return max(1, int(os.environ.get("ASO_WORKERS", "2")))
    except ValueError:
        return 2


class FilaDeJobs:
    """Fila FIFO persistida consumida por threads do próprio processo."""

    def __init__(
        self,
        repository: JobRepository,
        *,
        instancia_id: str,
        workers: int | None = None,
        classificar_erro: ClassificadorDeErro | None = None,
        mascarar: Callable[[str], str] = lambda texto: texto,
        ao_terminar: Callable[[Job], None] | None = None,
    ) -> None:
        self._repo = repository
        self._instancia_id = instancia_id
        self._n_workers = workers if workers is not None else workers_configurados()
        self._handlers: dict[str, Handler] = {}
        self._classificar_erro = classificar_erro or (lambda _exc: None)
        self._mascarar = mascarar
        # Notificação de término (ex.: SSE do console); falha nela nunca afeta o job.
        self._ao_terminar = ao_terminar
        self._cond = threading.Condition()
        self._threads: list[threading.Thread] = []
        self._parar = False

    def registrar(self, operacao: str, handler: Handler) -> None:
        self._handlers[operacao] = handler

    @property
    def operacoes(self) -> frozenset[str]:
        return frozenset(self._handlers)

    # ------------------------------------------------------------ ciclo de vida
    def iniciar(self) -> None:
        """Recupera jobs órfãos e sobe os workers (idempotente e seguro entre threads)."""
        with self._cond:
            if self._threads:
                return
            self.recuperar_no_boot()
            self._parar = False
            for i in range(self._n_workers):
                thread = threading.Thread(target=self._laco, name=f"aso-worker-{i}", daemon=True)
                thread.start()
                self._threads.append(thread)

    def parar(self, timeout: float = 5.0) -> None:
        with self._cond:
            self._parar = True
            self._cond.notify_all()
            threads, self._threads = self._threads, []
        for thread in threads:
            thread.join(timeout=timeout)

    def recuperar_no_boot(self) -> list[str]:
        """`running` de outra instância não tem mais worker vivo: vira `failed` (ADR-0067)."""
        interrompidos: list[str] = []
        for job in self._repo.listar(status=STATUS_RODANDO):
            if job.dono == self._instancia_id:
                continue
            job.status = STATUS_FALHOU
            job.erro = MOTIVO_REINICIO
            job.fim = now_iso()
            self._repo.salvar(job)
            interrompidos.append(job.id)
        return interrompidos

    # ------------------------------------------------------------ operações
    def enfileirar(
        self,
        operacao: str,
        orchestration_id: str,
        *,
        parametros: dict[str, Any] | None = None,
        card_id: str | None = None,
        ator: str = "system",
    ) -> Job:
        if operacao not in self._handlers:
            raise ValueError(f"Operação sem handler na fila: {operacao}")
        job = Job(
            orchestration_id=orchestration_id,
            card_id=card_id,
            operacao=operacao,
            parametros=dict(parametros or {}),
            ator=ator,
        )
        with self._cond:
            self._repo.salvar(job)
            self._cond.notify()
        return job

    def obter(self, job_id: str) -> Job | None:
        return self._repo.obter(job_id)

    def listar(
        self, *, orchestration_id: str | None = None, status: str | None = None
    ) -> list[Job]:
        return self._repo.listar(orchestration_id=orchestration_id, status=status)

    def cancelar(self, job_id: str, *, ator: str = "system") -> Job:
        with self._cond:
            job = self._repo.obter(job_id)
            if job is None:
                raise KeyError(f"Job inexistente: {job_id}")
            if job.status in STATUS_TERMINAIS:
                raise ValueError(f"Job já encerrado ({job.status}).")
            if job.status == STATUS_NA_FILA:
                job.status = STATUS_CANCELADO
                job.fim = now_iso()
                job.erro = f"cancelado por {ator} antes de iniciar"
            else:
                job.cancelamento_solicitado = True
            self._repo.salvar(job)
        if job.status == STATUS_RODANDO:
            _sinalizar_cancelamento(job_id)
        return job

    def aguardar(self, job_id: str, timeout: float = 30.0) -> Job:
        """Espera o job terminar (testes, CLI e smoke)."""
        limite = time.monotonic() + timeout
        while True:
            job = self._repo.obter(job_id)
            if job is None:
                raise KeyError(f"Job inexistente: {job_id}")
            if job.status in STATUS_TERMINAIS:
                return job
            if time.monotonic() >= limite:
                raise TimeoutError(f"Job {job_id} ainda em {job.status}")
            time.sleep(0.02)

    # ------------------------------------------------------------ worker
    def _reivindicar_proximo(self) -> Job | None:
        """Pega o job mais antigo da fila e o marca `running` (sob a condição da fila)."""
        for job in self._repo.listar(status=STATUS_NA_FILA):
            job.status = STATUS_RODANDO
            job.dono = self._instancia_id
            job.iniciado_em = now_iso()
            self._repo.salvar(job)
            return job
        return None

    def _laco(self) -> None:
        while True:
            with self._cond:
                job = None
                while not self._parar:
                    job = self._reivindicar_proximo()
                    if job is not None:
                        break
                    self._cond.wait(timeout=1.0)
                if self._parar:
                    return
            assert job is not None  # noqa: S101 - o laço acima só sai com job ou parada
            self._executar(job)

    def _executar(self, job: Job) -> None:
        handler = self._handlers[job.operacao]
        resultado: Any = None
        erro: BaseException | None = None
        with executando_job(job.id):
            try:
                resultado = handler(job)
            except (Exception, JobCancelado) as exc:  # noqa: BLE001 — registrada; o worker segue
                erro = exc
        with self._cond:
            atual = self._repo.obter(job.id) or job
            atual.fim = now_iso()
            if atual.cancelamento_solicitado:
                atual.status = STATUS_CANCELADO
                atual.erro = self._mascarar(str(erro)) if erro is not None else "cancelado"
            elif erro is not None:
                atual.status = STATUS_FALHOU
                atual.erro = self._mascarar(str(erro)) or type(erro).__name__
                atual.erro_status = (
                    self._classificar_erro(erro) if isinstance(erro, Exception) else None
                )
            else:
                atual.status = STATUS_CONCLUIDO
                atual.resultado = _JSON.dump_python(resultado, mode="json")
            self._repo.salvar(atual)
        self._notificar(atual)

    def _notificar(self, job: Job) -> None:
        if self._ao_terminar is None:
            return
        try:
            self._ao_terminar(job)
        except Exception:  # noqa: BLE001, S110 — notificação é best-effort
            pass
