"""MEL-31 — fila persistida de jobs e workers no processo (ADR-0067)."""

from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from aso.db.repository import SqlAlchemyJobRepository
from aso.execution.jobs import (
    MOTIVO_REINICIO,
    STATUS_CANCELADO,
    STATUS_CONCLUIDO,
    STATUS_FALHOU,
    STATUS_NA_FILA,
    STATUS_RODANDO,
    FilaDeJobs,
    InMemoryJobRepository,
    Job,
    JobCancelado,
    desregistrar_processo,
    job_atual,
    registrar_processo,
    verificar_cancelamento,
)


def _fila(repo: Any = None, *, workers: int = 1) -> FilaDeJobs:
    return FilaDeJobs(
        repo or InMemoryJobRepository(),
        instancia_id="runtime_teste",
        workers=workers,
        classificar_erro=lambda exc: 409 if isinstance(exc, ValueError) else None,
    )


def test_worker_executa_o_handler_e_grava_resultado_json() -> None:
    fila = _fila()
    fila.registrar("somar", lambda job: {"total": sum(job.parametros["valores"])})
    fila.iniciar()
    try:
        job = fila.enfileirar("somar", "orch_1", parametros={"valores": [1, 2, 3]}, ator="ana")
        final = fila.aguardar(job.id, timeout=5)
    finally:
        fila.parar()
    assert final.status == STATUS_CONCLUIDO
    assert final.resultado == {"total": 6}
    assert final.dono == "runtime_teste" and final.ator == "ana"
    assert final.iniciado_em and final.fim


def test_excecao_vira_failed_com_status_http_e_o_worker_segue_vivo() -> None:
    fila = _fila()

    def _falha(job: Job) -> None:
        raise ValueError("estratégia aguardando aprovação humana")

    fila.registrar("falha", _falha)
    fila.registrar("ok", lambda job: "feito")
    fila.iniciar()
    try:
        ruim = fila.enfileirar("falha", "orch_1")
        bom = fila.enfileirar("ok", "orch_1")
        falhou = fila.aguardar(ruim.id, timeout=5)
        concluido = fila.aguardar(bom.id, timeout=5)
    finally:
        fila.parar()
    assert falhou.status == STATUS_FALHOU
    assert "aguardando aprovação" in falhou.erro and falhou.erro_status == 409
    assert concluido.status == STATUS_CONCLUIDO and concluido.resultado == "feito"


def test_fila_respeita_ordem_de_chegada() -> None:
    fila = _fila(workers=1)
    ordem: list[int] = []
    fila.registrar("marcar", lambda job: ordem.append(job.parametros["n"]))
    jobs = [fila.enfileirar("marcar", "orch_1", parametros={"n": n}) for n in range(5)]
    fila.iniciar()
    try:
        for job in jobs:
            fila.aguardar(job.id, timeout=5)
    finally:
        fila.parar()
    assert ordem == [0, 1, 2, 3, 4]


def test_operacao_sem_handler_e_recusada_na_entrada() -> None:
    with pytest.raises(ValueError, match="sem handler"):
        _fila().enfileirar("inexistente", "orch_1")


def test_cancelar_job_na_fila_nunca_chama_o_handler() -> None:
    fila = _fila()
    chamadas: list[str] = []
    fila.registrar("op", lambda job: chamadas.append(job.id))
    job = fila.enfileirar("op", "orch_1")
    cancelado = fila.cancelar(job.id, ator="ana")
    assert cancelado.status == STATUS_CANCELADO
    fila.iniciar()
    try:
        time.sleep(0.2)
    finally:
        fila.parar()
    assert chamadas == []
    with pytest.raises(ValueError, match="encerrado"):
        fila.cancelar(job.id)


def test_cancelar_job_rodando_interrompe_o_laco_cooperativo() -> None:
    fila = _fila()
    comecou = threading.Event()

    def _laco_longo(job: Job) -> None:
        comecou.set()
        for _ in range(500):
            verificar_cancelamento()
            time.sleep(0.01)

    fila.registrar("longo", _laco_longo)
    fila.iniciar()
    try:
        job = fila.enfileirar("longo", "orch_1")
        assert comecou.wait(5)
        assert fila.obter(job.id).status == STATUS_RODANDO  # type: ignore[union-attr]
        fila.cancelar(job.id)
        final = fila.aguardar(job.id, timeout=5)
    finally:
        fila.parar()
    assert final.status == STATUS_CANCELADO
    assert "cancelada" in final.erro


def test_cancelar_mata_o_subprocess_registrado_pelo_executor() -> None:
    fila = _fila()
    registrado = threading.Event()
    codigos: list[int] = []

    def _agente_cli(job: Job) -> None:
        proc = subprocess.Popen(["sleep", "30"], text=True)
        registrar_processo(proc)
        registrado.set()
        try:
            codigos.append(proc.wait(timeout=20))
        finally:
            desregistrar_processo(proc)

    fila.registrar("cli", _agente_cli)
    fila.iniciar()
    inicio = time.monotonic()
    try:
        job = fila.enfileirar("cli", "orch_1")
        assert registrado.wait(5)
        fila.cancelar(job.id)
        final = fila.aguardar(job.id, timeout=10)
    finally:
        fila.parar()
    assert final.status == STATUS_CANCELADO
    assert codigos and codigos[0] != 0  # morto pelo sinal, não terminou sozinho
    assert time.monotonic() - inicio < 10


def test_boot_marca_running_orfao_como_failed_e_executa_o_que_estava_na_fila() -> None:
    repo = InMemoryJobRepository()
    orfao = Job(orchestration_id="orch_1", operacao="op", status=STATUS_RODANDO, dono="morto")
    na_fila = Job(orchestration_id="orch_1", operacao="op")
    repo.salvar(orfao)
    repo.salvar(na_fila)
    fila = _fila(repo)
    fila.registrar("op", lambda job: "ok")
    fila.iniciar()
    try:
        executado = fila.aguardar(na_fila.id, timeout=5)
    finally:
        fila.parar()
    recuperado = repo.obter(orfao.id)
    assert recuperado is not None
    assert recuperado.status == STATUS_FALHOU and recuperado.erro == MOTIVO_REINICIO
    assert executado.status == STATUS_CONCLUIDO


def test_boot_nao_toca_running_da_propria_instancia() -> None:
    repo = InMemoryJobRepository()
    proprio = Job(orchestration_id="o", operacao="op", status=STATUS_RODANDO, dono="runtime_teste")
    repo.salvar(proprio)
    assert _fila(repo).recuperar_no_boot() == []
    assert repo.obter(proprio.id).status == STATUS_RODANDO  # type: ignore[union-attr]


def test_contexto_do_job_so_existe_dentro_do_worker() -> None:
    fila = _fila()
    vistos: list[str | None] = []
    fila.registrar("ver", lambda job: vistos.append(job_atual()))
    fila.iniciar()
    try:
        job = fila.enfileirar("ver", "orch_1")
        fila.aguardar(job.id, timeout=5)
    finally:
        fila.parar()
    assert vistos == [job.id]
    assert job_atual() is None
    verificar_cancelamento()  # fora de job: nunca cancela


def test_job_cancelado_atravessa_except_exception() -> None:
    """Laços do fluxo usam `except Exception` por card; o cancelamento não pode ser engolido."""
    assert not issubclass(JobCancelado, Exception)
    with pytest.raises(JobCancelado):
        try:
            raise JobCancelado("cancelado")
        except Exception:  # noqa: BLE001
            pytest.fail("JobCancelado não pode ser capturado como Exception")


def test_repositorio_sql_persiste_e_filtra(tmp_path: Path) -> None:
    repo = SqlAlchemyJobRepository(f"sqlite:///{tmp_path / 'jobs.db'}")
    a = Job(orchestration_id="o1", operacao="run_card", card_id="c1", parametros={"x": 1})
    b = Job(orchestration_id="o2", operacao="run_phase")
    repo.salvar(a)
    repo.salvar(b)
    a.status = STATUS_CONCLUIDO
    a.resultado = [{"status": "applied"}]
    repo.salvar(a)
    lido = repo.obter(a.id)
    assert lido is not None and lido.resultado == [{"status": "applied"}]
    assert lido.parametros == {"x": 1} and lido.card_id == "c1"
    assert [j.id for j in repo.listar(orchestration_id="o1")] == [a.id]
    assert [j.id for j in repo.listar(status=STATUS_NA_FILA)] == [b.id]
    assert repo.obter("job_inexistente") is None
