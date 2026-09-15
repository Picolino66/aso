"""Definições declarativas dos quality gates por fase (ADR-0060).

Antes, `run_quality_gate` montava os critérios inline a cada chamada e o critério de
saída era `store.version > 0 or not has_work`: **global** (um patch em F5 aprovava F2) e
**vacuamente verdadeiro** em fase sem cards. Não havia um lugar que dissesse "o que F3
exige".

Aqui cada critério é declarado uma vez — nome, fases, descrição, se bloqueia — e gerado a
partir de um retrato de dados (`EstadoDoGate`) montado pela camada de controle. O módulo
não importa `aso.control`: a regra de dependência aponta para dentro, então tudo que
depende de I/O (rodar a bateria, checar drift de docs) chega aqui como função pronta.

Fase em que nenhum critério **bloqueante** se aplica não é "aprovada": o gate devolve
`SKIPPED` (sem snapshot, sem aprovação humana de fase vazia).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from aso.governance.quality_gate_engine import Criterion
from aso.shared.types import ColumnKey, Phase

Verificacao = Callable[[], tuple[bool, str]]

# Colunas que tiram o card do escopo do gate: trabalho descartado não é pendência.
_FORA_DO_ESCOPO = frozenset({ColumnKey.CANCELLED, ColumnKey.ARCHIVED})


@dataclass(frozen=True)
class CardNoGate:
    id: str
    titulo: str
    status: ColumnKey
    tem_branch: bool


@dataclass(frozen=True)
class VerificacaoDaBateria:
    nome: str
    executar: Verificacao
    bloqueante: bool = True


@dataclass
class EstadoDoGate:
    """Retrato do que o gate de uma fase precisa saber — só dados e funções prontas."""

    fase: Phase
    cards: list[CardNoGate] = field(default_factory=list)  # só os cards DESTA fase
    fases_com_patch_aplicado: frozenset[Phase] = frozenset()
    discovery_status: str | None = None  # None = discovery nunca rodou
    discovery_aprovado: bool = False
    deploy: tuple[bool, str] | None = None  # None = nunca houve implantação
    validacao_configurada: bool = False
    bateria: list[VerificacaoDaBateria] = field(default_factory=list)
    docs_sync: Verificacao | None = None

    @property
    def cards_no_escopo(self) -> list[CardNoGate]:
        return [c for c in self.cards if c.status not in _FORA_DO_ESCOPO]


@dataclass(frozen=True)
class DefinicaoDeCriterio:
    nome: str
    fases: frozenset[Phase]
    descricao: str
    bloqueante: bool
    gerar: Callable[[EstadoDoGate], list[Criterion]]


_TODAS = frozenset(Phase)
_CODIGO = frozenset({Phase.F5, Phase.F6})


def _constante(resultado: tuple[bool, str]) -> Callable[[dict[str, Any]], tuple[bool, str]]:
    def predicado(_contexto: dict[str, Any]) -> tuple[bool, str]:
        return resultado

    return predicado


def _adiado(verificacao: Verificacao) -> Callable[[dict[str, Any]], tuple[bool, str]]:
    """Adia a execução (comando externo) para dentro do engine, que mede a duração."""

    def predicado(_contexto: dict[str, Any]) -> tuple[bool, str]:
        return verificacao()

    return predicado


def _entregue(card: CardNoGate) -> bool:
    # Done = mesclado. Testing sem branch = fase sem entrega por PR (ex.: execução mock
    # ou documento) — não há merge a esperar.
    return card.status == ColumnKey.DONE or (
        card.status == ColumnKey.TESTING and not card.tem_branch
    )


def _cards_entregues(estado: EstadoDoGate) -> list[Criterion]:
    cards = estado.cards_no_escopo
    if not cards:
        return []
    pendentes = [c for c in cards if not _entregue(c)]
    if pendentes:
        lista = ", ".join(f"{c.titulo} [{c.id}] ({c.status.value})" for c in pendentes)
        resultado = (False, f"cards pendentes na fase {estado.fase.value}: {lista}")
    else:
        resultado = (True, f"{len(cards)} card(s) da fase {estado.fase.value} entregue(s)")
    return [Criterion("cards_da_fase_entregues", _constante(resultado))]


def _output_da_fase(estado: EstadoDoGate) -> list[Criterion]:
    if not estado.cards_no_escopo:
        return []
    ok = estado.fase in estado.fases_com_patch_aplicado
    evidencia = (
        f"patch aplicado na fase {estado.fase.value}"
        if ok
        else f"nenhum patch aplicado na fase {estado.fase.value} "
        "(patches de outras fases não contam)"
    )
    return [Criterion("output_da_fase_aplicado", _constante((ok, evidencia)))]


def _discovery(estado: EstadoDoGate) -> list[Criterion]:
    if estado.discovery_status is None:
        return []
    resultado = (estado.discovery_aprovado, f"discovery {estado.discovery_status or 'sem status'}")
    return [Criterion("discovery_aprovado", _constante(resultado))]


def _deploy(estado: EstadoDoGate) -> list[Criterion]:
    if estado.deploy is None:
        return []
    ok, status = estado.deploy
    return [Criterion("deploy_aprovado", _constante((ok, f"implantação {status or 'sem status'}")))]


def _bateria(estado: EstadoDoGate) -> list[Criterion]:
    return [Criterion(v.nome, _adiado(v.executar), blocking=v.bloqueante) for v in estado.bateria]


def _merge_governado(estado: EstadoDoGate) -> list[Criterion]:
    cards = estado.cards_no_escopo
    if not estado.validacao_configurada or not cards:
        return []
    ok = all(c.status == ColumnKey.DONE for c in cards)
    evidencia = "todos os cards foram mesclados" if ok else "há cards sem merge governado"
    return [Criterion("cards_entregues", _constante((ok, evidencia)))]


def _docs(estado: EstadoDoGate) -> list[Criterion]:
    if estado.docs_sync is None:
        return []
    return [Criterion("docs_in_sync", _adiado(estado.docs_sync), blocking=False)]


DEFINICOES: tuple[DefinicaoDeCriterio, ...] = (
    DefinicaoDeCriterio(
        "cards_da_fase_entregues",
        _TODAS,
        "Todo card da fase (fora Cancelled/Archived) está Done, ou Testing sem branch.",
        True,
        _cards_entregues,
    ),
    DefinicaoDeCriterio(
        "output_da_fase_aplicado",
        _TODAS,
        "Ao menos um ContextPatch aplicado com a fase igual à do gate (quando há cards).",
        True,
        _output_da_fase,
    ),
    DefinicaoDeCriterio(
        "discovery_aprovado",
        frozenset({Phase.F1}),
        "Último relatório de discovery aprovado (só se o discovery foi rodado).",
        True,
        _discovery,
    ),
    DefinicaoDeCriterio(
        "deploy_aprovado",
        frozenset({Phase.F6}),
        "Implantação aceita / pipeline completo (só se houve implantação).",
        True,
        _deploy,
    ),
    DefinicaoDeCriterio(
        "bateria de validações (1 critério por verificação)",
        _CODIGO,
        "Cada verificação configurada roda na pasta de trabalho (bloqueia conforme a verificação).",
        True,
        _bateria,
    ),
    DefinicaoDeCriterio(
        "cards_entregues",
        _CODIGO,
        "Com validação configurada e cards na fase: todos mesclados (Done).",
        True,
        _merge_governado,
    ),
    DefinicaoDeCriterio(
        "docs_in_sync",
        _CODIGO,
        "Documentação docs-first sem drift em relação ao código (aviso, não bloqueia).",
        False,
        _docs,
    ),
)


def criterios_da_fase(estado: EstadoDoGate) -> list[Criterion]:
    """Critérios aplicáveis ao gate da fase do `estado`, na ordem das definições."""
    criterios: list[Criterion] = []
    for definicao in DEFINICOES:
        if estado.fase in definicao.fases:
            criterios.extend(definicao.gerar(estado))
    return criterios


def tabela_markdown() -> str:
    """Tabela dos gates por fase, gerada das definições (fonte de `docs/quality-gates.md`)."""
    linhas = [
        "| Critério | Fases | Bloqueia | Regra |",
        "|---|---|---|---|",
    ]
    for d in DEFINICOES:
        fases = "todas" if d.fases == _TODAS else ", ".join(sorted(f.value for f in d.fases))
        linhas.append(
            f"| `{d.nome}` | {fases} | {'sim' if d.bloqueante else 'não'} | {d.descricao} |"
        )
    linhas.append(
        "| _(nenhum critério bloqueante aplicável)_ | todas | — | Gate `SKIPPED`: sem "
        "snapshot e sem aprovação humana de fase vazia. |"
    )
    return "\n".join(linhas)
