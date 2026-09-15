"""MEL-32 — regra da camada de aplicação: nenhum serviço extraído volta à façade (ADR-0066)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

APLICACAO = Path(__file__).resolve().parents[2] / "src/aso/application"


@pytest.mark.parametrize("modulo", sorted(p.name for p in APLICACAO.glob("*.py")))
def test_modulo_de_aplicacao_nao_importa_a_facade(modulo: str) -> None:
    arvore = ast.parse((APLICACAO / modulo).read_text(encoding="utf-8"))
    importados = {n.module for n in ast.walk(arvore) if isinstance(n, ast.ImportFrom)}
    assert "aso.control.orchestration_service" not in importados


@pytest.mark.parametrize("modulo", sorted(p.name for p in APLICACAO.glob("*.py")))
def test_modulo_de_aplicacao_tem_no_maximo_800_linhas(modulo: str) -> None:
    assert len((APLICACAO / modulo).read_text(encoding="utf-8").splitlines()) <= 800


def test_facade_delega_entrega_ao_delivery_service() -> None:
    from aso.application.delivery import DeliveryService
    from aso.control.orchestration_service import OrchestrationService

    svc = OrchestrationService()
    assert isinstance(svc._delivery, DeliveryService)  # noqa: SLF001
    assert svc._delivery._bundle_store is svc._bundle_store  # noqa: SLF001


API = APLICACAO.parent / "api"


def test_app_so_compoe_gateway_e_routers() -> None:
    """Passo 10: `app.py` < 300 linhas e sem rotas próprias — tudo vem de `api/routers`."""
    fonte = (API / "app.py").read_text(encoding="utf-8")
    assert len(fonte.splitlines()) < 300
    decoradores = [
        d
        for n in ast.walk(ast.parse(fonte))
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
        for d in n.decorator_list
    ]
    # Só o gateway (`middleware`) e o ciclo de vida da fila (`asynccontextmanager`) ficam aqui.
    permitidos = ("app.middleware", "asynccontextmanager")
    rotas = [ast.unparse(d) for d in decoradores if not ast.unparse(d).startswith(permitidos)]
    assert rotas == []


@pytest.mark.parametrize("modulo", sorted(p.name for p in (API / "routers").glob("*.py")))
def test_router_tem_no_maximo_800_linhas_e_expoe_criar_router(modulo: str) -> None:
    fonte = (API / "routers" / modulo).read_text(encoding="utf-8")
    assert len(fonte.splitlines()) <= 800
    if modulo != "__init__.py":
        nomes = {n.name for n in ast.parse(fonte).body if isinstance(n, ast.FunctionDef)}
        assert "criar_router" in nomes


def test_todas_as_rotas_do_contrato_vem_dos_routers() -> None:
    """Cada path do contrato OpenAPI é declarado num router por recurso (nenhum solto)."""
    from aso.api.openapi_export import gerar_openapi

    declarados: set[str] = set()
    for arquivo in (API / "routers").glob("*.py"):
        for no in ast.walk(ast.parse(arquivo.read_text(encoding="utf-8"))):
            if (
                isinstance(no, ast.Call)
                and isinstance(no.func, ast.Attribute)
                and isinstance(no.func.value, ast.Name)
                and no.func.value.id == "router"
                and no.args
                and isinstance(no.args[0], ast.Constant)
            ):
                declarados.add(str(no.args[0].value))
    contrato = set(gerar_openapi()["paths"])
    assert contrato
    assert contrato <= declarados


# Mutadores que recebem o bundle já carregado: o chamador detém o lock (revisão documentada).
_MUTADORES_SOB_LOCK_DO_CHAMADOR = {
    "delivery.py::_apply_review_verdict": "chamado por run_review dentro do lock",
    "execution.py::_reivindicar_card": "claim: o chamador DEVE deter o lock (ADR-0058)",
    "execution.py::_recuperar_execucoes_interrompidas": "roda no BundleStore.get, na hidratação",
    "settings.py::_provider_for": "recebe o bundle de run_card/run_phase/docs, já sob lock",
}


def _usa_lock(no: ast.With) -> bool:
    return any("lock_for" in ast.unparse(item.context_expr) for item in no.items)


def test_todo_mutador_persiste_sob_o_lock_do_bundle_store() -> None:
    """Critério do MEL-32: toda mutação persistida passa pelo lock por orquestração."""
    sem_lock: list[str] = []
    for arquivo in sorted(APLICACAO.glob("*.py")):
        if arquivo.name == "bundles.py":
            continue
        for classe in ast.parse(arquivo.read_text(encoding="utf-8")).body:
            if not isinstance(classe, ast.ClassDef):
                continue
            for metodo in classe.body:
                if not isinstance(metodo, ast.FunctionDef) or metodo.name == "_persist":
                    continue
                chave = f"{arquivo.name}::{metodo.name}"
                if chave in _MUTADORES_SOB_LOCK_DO_CHAMADOR:
                    continue
                protegidas: set[int] = set()
                for no in ast.walk(metodo):
                    if isinstance(no, ast.With) and _usa_lock(no):
                        protegidas.update(id(x) for x in ast.walk(no))
                for no in ast.walk(metodo):
                    if (
                        isinstance(no, ast.Call)
                        and isinstance(no.func, ast.Attribute)
                        and no.func.attr in {"_persist", "persist"}
                        and id(no) not in protegidas
                    ):
                        sem_lock.append(chave)
                        break
    assert sem_lock == []


def test_lock_so_nasce_no_bundle_store() -> None:
    """Serviços adquirem o lock via `BundleStore.lock_for`, nunca criam o próprio RLock."""
    for arquivo in APLICACAO.glob("*.py"):
        if arquivo.name != "bundles.py":
            assert "RLock()" not in arquivo.read_text(encoding="utf-8"), arquivo.name
