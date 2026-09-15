"""MEL-33 — gravação incremental, versão otimista e reidratação fiel (ADR-0068)."""

from __future__ import annotations

import os
import re
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text

from aso.api.app import create_app
from aso.application.orchestration_service import OrchestrationService
from aso.control.models import DecisionInput
from aso.db.repository import SqlAlchemyOrchestrationRepository
from aso.governance.models import SloEvaluation
from aso.persistence.memory import InMemoryOrchestrationRepository
from aso.persistence.ports import ConcurrentModificationError


def _url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'aso.db'}"


@pytest.fixture(params=["sqlite", "postgres"])
def url(request: pytest.FixtureRequest, tmp_path: Path) -> str:
    """SQLite sempre; Postgres quando `ASO_TEST_POSTGRES_URL` aponta para um banco de teste
    (ordem de FK e ordem física das linhas só aparecem de verdade no Postgres)."""
    if request.param == "sqlite":
        return _url(tmp_path)
    pg = os.environ.get("ASO_TEST_POSTGRES_URL")
    if not pg:
        pytest.skip("ASO_TEST_POSTGRES_URL não definida")
    return pg


def _servico(url: str) -> OrchestrationService:
    return OrchestrationService(repository=SqlAlchemyOrchestrationRepository(url))


@contextmanager
def _contando(repo: SqlAlchemyOrchestrationRepository) -> Iterator[Counter[str]]:
    """Conta comandos SQL por verbo+tabela enquanto o bloco roda."""
    contagem: Counter[str] = Counter()

    def _antes(_conn: Any, _cursor: Any, sql: str, *_args: Any) -> None:
        m = re.match(r"\s*(INSERT INTO|DELETE FROM|UPDATE)\s+(\w+)", sql, re.IGNORECASE)
        if m:
            contagem[f"{m.group(1).split()[0].upper()} {m.group(2)}"] += 1

    event.listen(repo.engine, "before_cursor_execute", _antes)
    try:
        yield contagem
    finally:
        event.remove(repo.engine, "before_cursor_execute", _antes)


def _verbo(contagem: Counter[str], verbo: str) -> int:
    return sum(n for chave, n in contagem.items() if chave.startswith(verbo))


def _orquestracao_com_historico(svc: OrchestrationService) -> str:
    oid = svc.create_orchestration(
        "arquitetura e backend",
        decision_input=DecisionInput(user_request="x", domains=["architecture", "backend"]),
    ).id
    svc.start_autopilot(oid)  # cards, patches, gate, snapshot, aprovação, eventos
    return oid


def test_nova_gravacao_insere_so_o_que_mudou_e_nao_apaga_nada(url: str) -> None:
    svc = _servico(url)
    oid = _orquestracao_com_historico(svc)
    repo = svc._bundle_store.repository  # noqa: SLF001
    assert isinstance(repo, SqlAlchemyOrchestrationRepository)
    eventos_antes = len(svc.timeline(oid))
    assert eventos_antes > 10

    with _contando(repo) as contagem:
        svc.request_approval(oid, "conferir manualmente")  # 1 aprovação + 1 evento

    assert _verbo(contagem, "DELETE") == 0
    assert contagem["INSERT human_approvals"] == 1
    assert contagem["INSERT events"] == 1
    assert _verbo(contagem, "INSERT") == 2
    # só a orquestração (versão) muda de linha existente
    assert contagem["UPDATE orchestrations"] == 1


def test_releitura_em_outra_instancia_nao_regrava_nada(url: str) -> None:
    """As impressões montadas no `load` batem com as da gravação: salvar sem mudança = só a
    versão. Uma divergência de normalização aqui faria toda gravação reescrever o agregado."""
    oid = _orquestracao_com_historico(_servico(url))

    outro = _servico(url)
    bundle = outro._bundle(oid)  # noqa: SLF001
    repo = outro._bundle_store.repository  # noqa: SLF001
    assert isinstance(repo, SqlAlchemyOrchestrationRepository)
    with _contando(repo) as contagem:
        outro._persist(bundle)  # noqa: SLF001
    assert dict(contagem) == {"UPDATE orchestrations": 1}


def test_reidratacao_identica_ao_estado_em_memoria(url: str) -> None:
    svc = _servico(url)
    oid = _orquestracao_com_historico(svc)
    svc.add_feedback(oid, "melhorar mensagens de erro")
    card = svc.get_cards(oid)[0]
    svc.block_card(oid, card.id, "aguardando insumo")
    svc.unblock_card(oid, card.id)
    em_memoria = svc._to_state(svc._bundle(oid))  # noqa: SLF001

    lido = SqlAlchemyOrchestrationRepository(url).load(oid)
    assert lido is not None
    assert lido.versao == em_memoria.versao
    assert lido.model_dump(mode="json") == em_memoria.model_dump(mode="json")


def test_remocao_de_itens_do_agregado_apaga_as_linhas_na_ordem_de_fk(url: str) -> None:
    svc = OrchestrationService(repository=SqlAlchemyOrchestrationRepository(url), max_slo_samples=2)
    oid = svc.create_orchestration("backend").id
    for i in range(4):
        svc.record_slo_evaluation(oid, SloEvaluation(orchestration_id=oid, fail_rate=float(i)))
    repo = svc._bundle_store.repository  # noqa: SLF001
    assert isinstance(repo, SqlAlchemyOrchestrationRepository)
    with repo.engine.connect() as conn:
        total = conn.execute(
            text("select count(*) from slo_evaluations where orchestration_id = :o"), {"o": oid}
        ).scalar()
    assert total == 2
    lido = SqlAlchemyOrchestrationRepository(url).load(oid)
    assert lido is not None and [s.fail_rate for s in lido.slo_evaluations] == [2.0, 3.0]


def test_duas_instancias_no_mesmo_banco_a_segunda_gravacao_recebe_conflito(
    url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ASO_BUNDLE_VERIFICACAO_S", "-1")  # sem sonda: força a leitura velha
    api = _servico(url)
    cli = _servico(url)
    oid = api.create_orchestration("backend").id
    cli.get(oid)  # a CLI leu a versão 1

    api.request_approval(oid, "decisão da API")  # versão 2 gravada pela API
    with pytest.raises(ConcurrentModificationError):
        cli.request_approval(oid, "decisão da CLI com leitura velha")

    # Nada da API foi perdido; a CLI recarrega e grava por cima da versão nova.
    assert oid not in cli._bundles  # noqa: SLF001
    cli.request_approval(oid, "decisão da CLI depois de recarregar")
    acoes = [a.action for a in _servico(url).list_approvals(oid)]
    assert "decisão da API" in acoes
    assert "decisão da CLI depois de recarregar" in acoes
    assert "decisão da CLI com leitura velha" not in acoes


def test_api_responde_409_no_conflito_de_versao(url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASO_BUNDLE_VERIFICACAO_S", "-1")
    svc = _servico(url)
    oid = svc.create_orchestration("backend").id
    svc.get(oid)
    _servico(url).request_approval(oid, "outro processo gravou")
    client = TestClient(create_app(svc))
    resp = client.post(f"/v1/orchestrations/{oid}/cancel")
    assert resp.status_code == 409
    assert "alterada por outra gravação" in resp.json()["detail"]
    # a segunda tentativa já lê a versão nova e passa
    assert client.post(f"/v1/orchestrations/{oid}/cancel").status_code == 200


def test_repositorio_em_memoria_tambem_recusa_versao_velha() -> None:
    repo = InMemoryOrchestrationRepository()
    svc = OrchestrationService(repository=repo)
    oid = svc.create_orchestration("backend").id
    estado = repo.load(oid)
    assert estado is not None and estado.versao == 1
    svc.request_approval(oid, "grava versão 2")
    with pytest.raises(ConcurrentModificationError):
        repo.save(estado)
    assert repo.versao_atual(oid) == 2


def test_sonda_de_versao_recarrega_o_que_outro_processo_gravou(
    url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ASO_BUNDLE_VERIFICACAO_S", "0")
    api = _servico(url)
    cli = _servico(url)
    oid = api.create_orchestration("backend").id
    cli.get(oid)
    api.request_approval(oid, "gravada pela API")
    # a CLI enxerga a gravação nova e grava sem conflito
    assert "gravada pela API" in [a.action for a in cli.list_approvals(oid)]
    cli.request_approval(oid, "gravada pela CLI")
    assert len(_servico(url).list_approvals(oid)) == 2


def test_cache_de_bundles_respeita_o_limite(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASO_BUNDLE_CACHE_MAX", "2")
    svc = OrchestrationService()
    ids = [svc.create_orchestration(f"demanda {i}").id for i in range(5)]
    assert len(svc._bundles) == 2  # noqa: SLF001
    assert list(svc._bundles) == ids[-2:]  # noqa: SLF001
    # a descartada volta do repositório, com o que foi gravado
    assert svc.get(ids[0]).user_request == "demanda 0"
    assert len(svc._bundles) == 2  # noqa: SLF001


def test_cache_nao_descarta_bundle_com_lock_em_uso_por_outra_thread() -> None:
    import threading

    svc = OrchestrationService()
    store = svc._bundle_store  # noqa: SLF001
    primeiro = svc.create_orchestration("em uso").id
    store.cache.maximo = 1
    segurando = threading.Event()
    liberar = threading.Event()

    def _usar() -> None:
        with store.lock_for(primeiro):
            segurando.set()
            liberar.wait(5)

    thread = threading.Thread(target=_usar)
    thread.start()
    try:
        assert segurando.wait(5)
        outra = svc.create_orchestration("outra").id
        assert primeiro in store.cache  # em uso: não saiu, mesmo acima do limite
        assert outra in store.cache  # recém-criada também fica
    finally:
        liberar.set()
        thread.join()


def test_boot_de_producao_nao_chama_create_all(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O schema é das migrations: o bootstrap não cria tabelas por fora do Alembic."""
    from alembic import command
    from alembic.config import Config

    from aso.bootstrap import build_job_repository, build_service
    from aso.db.models import Base

    raiz = Path(__file__).resolve().parents[2]
    url = _url(tmp_path)
    monkeypatch.setenv("ASO_DATABASE_URL", url)
    monkeypatch.chdir(raiz)
    command.upgrade(Config(str(raiz / "alembic.ini")), "head")

    def _proibido(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("create_all chamado no boot de produção")

    monkeypatch.setattr(Base.metadata, "create_all", _proibido)
    svc = build_service()
    build_job_repository()
    oid = svc.create_orchestration("boot migrado").id
    assert SqlAlchemyOrchestrationRepository(url, create_schema=False).versao_atual(oid) == 1
