"""NamingService — batiza branches e commits a partir do card (ADR-0014).

O nome da branch e o assunto do commit saem do **título do card**, não de um uuid.
Há dois caminhos:

1. **Determinístico** (padrão): slug do título via `aso.execution.branch_naming`.
   Grátis, instantâneo, sempre disponível.
2. **Agente nomeador**: o executor configurado em `agent_assignments["naming"]` recebe
   o card e devolve um nome melhor — útil quando o título do card é longo ou vago.

A garantia de governança é que **nomear nunca derruba um card**: qualquer falha do
agente (timeout, JSON inválido, executor removido do catálogo, sandbox sem permissão)
cai no caminho determinístico e registra o motivo. Um card não pode falhar porque o
serviço de nomes falhou — o trabalho de engenharia é o que importa.

O prefixo (`feat/`, `fix/`, …) e o sufixo de unicidade são sempre impostos por nós:
o agente só influencia o miolo do slug. Assim ele não consegue produzir uma branch
malformada nem colidir com a de outro candidato rodando em paralelo.
"""

from __future__ import annotations

import json
import subprocess
import tempfile

from pydantic import BaseModel

from aso.control.models import AgentAssignment
from aso.execution.branch_naming import branch_stem, prefixo_para, slugify, tem_texto_util
from aso.execution.catalog import ExecutorCatalog
from aso.execution.llm_client import LlmError
from aso.execution.llm_provider import parse_llm_json
from aso.shared.types import CardType, Phase

# Assunto de commit no padrão Conventional Commits, em pt-BR e curto o bastante para
# `git log --oneline` (72 é o limite clássico da primeira linha).
ASSUNTO_MAX = 72
TIMEOUT_PADRAO = 30.0

_NAMING_SYSTEM = (
    "Você nomeia branches e commits de um runtime de engenharia autônoma.\n"
    "Responda SOMENTE com um objeto JSON válido, sem cercas de código, na forma:\n"
    '{"branch": "slug-curto-em-kebab-case", "commit": "feat: assunto em pt-BR"}\n'
    "Regras: o slug tem no máximo 4 palavras, sem acento, e descreve a FUNCIONALIDADE "
    "(não o agente, não a fase). O assunto do commit é imperativo, em português do "
    "Brasil, com no máximo 72 caracteres, e usa o mesmo prefixo Conventional Commits "
    "informado na tarefa."
)


class BranchNaming(BaseModel):
    """Nomes escolhidos para o card, com a origem (para auditoria).

    `branch_stem` é a raiz sem sufixo (`feat/calculadora-basica`): quem cria o worktree
    fecha o nome com o sufixo de unicidade, porque o mesmo card pode ter várias branches
    vivas ao mesmo tempo (retry, candidatos concorrentes).
    """

    branch_stem: str
    commit_subject: str
    source: str = "deterministico"  # deterministico | agente
    fallback_reason: str = ""


class NamingService:
    """Sugere nome de branch e assunto de commit para um card."""

    def __init__(
        self, catalog: ExecutorCatalog | None = None, *, timeout: float = TIMEOUT_PADRAO
    ) -> None:
        self._catalog = catalog
        self._timeout = timeout

    def suggest(
        self,
        assignment: AgentAssignment | None,
        *,
        card_type: CardType | str | None,
        title: str,
        description: str = "",
        acceptance_criteria: list[str] | None = None,
        phase: Phase | str | None = None,
    ) -> BranchNaming:
        """Nomes do card. Sem agente configurado (ou com falha), usa o determinístico."""
        base = _deterministico(card_type, title)
        if assignment is None or self._catalog is None:
            return base
        try:
            bruto = self._perguntar(
                assignment, card_type, title, description, acceptance_criteria or [], phase
            )
        except (LlmError, ValueError, KeyError, OSError, subprocess.SubprocessError) as exc:
            return base.model_copy(update={"fallback_reason": f"{type(exc).__name__}: {exc}"[:200]})
        return _sanear(bruto, card_type, title) or base.model_copy(
            update={"fallback_reason": "resposta do agente sem branch/commit utilizáveis"}
        )

    def _perguntar(
        self,
        assignment: AgentAssignment,
        card_type: CardType | str | None,
        title: str,
        description: str,
        acceptance_criteria: list[str],
        phase: Phase | str | None,
    ) -> dict[str, object]:
        assert self._catalog is not None  # noqa: S101 - garantido pelo chamador
        profile = self._catalog.get(assignment.executor)
        if profile is None:
            raise KeyError(f"Executor '{assignment.executor}' não está no catálogo.")
        pedido = _pedido(card_type, title, description, acceptance_criteria, phase)
        if profile.kind == "llm":
            client = self._catalog.llm_client(
                assignment.executor, effort_override=assignment.effort
            )
            return parse_llm_json(client.complete(system=_NAMING_SYSTEM, user=pedido))
        if profile.kind == "cli":
            command = self._catalog.cli_command(
                assignment.executor, effort_override=assignment.effort
            )
            return parse_llm_json(self._rodar_cli(command, pedido))
        raise ValueError(f"Executor '{assignment.executor}' não sabe produzir texto.")

    def _rodar_cli(self, command: list[str], pedido: str) -> str:
        """Roda o agente CLI só para obter texto — em pasta temporária, sem worktree.

        Nomear não altera código, então nada de `git worktree add`: o agente roda num
        diretório vazio e descartável, e só o stdout interessa.
        """
        tarefa = json.dumps(
            {"kind": "naming", "content": {"request": pedido, "system": _NAMING_SYSTEM}},
            ensure_ascii=False,
        )
        with tempfile.TemporaryDirectory(prefix="aso-naming-") as tmp:
            proc = subprocess.run(
                command,
                cwd=tmp,
                input=tarefa,
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )
        if proc.returncode != 0:
            raise ValueError(f"exit={proc.returncode}: {(proc.stderr or proc.stdout)[-200:]}")
        return proc.stdout


def _pedido(
    card_type: CardType | str | None,
    title: str,
    description: str,
    acceptance_criteria: list[str],
    phase: Phase | str | None,
) -> str:
    linhas = [
        f"Prefixo obrigatório: {prefixo_para(card_type)}",
        f"Fase da esteira: {phase or '-'}",
        f"Título do card: {title}",
    ]
    if description:
        linhas.append(f"Descrição: {description[:500]}")
    if acceptance_criteria:
        criterios = "; ".join(acceptance_criteria[:5])
        linhas.append(f"Critérios de aceite: {criterios[:500]}")
    linhas.append("Produza o JSON com branch e commit.")
    return "\n".join(linhas)


def _deterministico(card_type: CardType | str | None, title: str) -> BranchNaming:
    return BranchNaming(
        branch_stem=branch_stem(card_type, title),
        commit_subject=_assunto(card_type, title),
        source="deterministico",
    )


def _assunto(card_type: CardType | str | None, texto: str) -> str:
    """Monta `feat: título do card`, truncado no limite da primeira linha do commit."""
    prefixo = prefixo_para(card_type)
    # Título só de emoji/pontuação daria um `fix: 🚀` inútil no `git log`.
    corpo = " ".join(texto.split()).strip() if tem_texto_util(texto) else "atualiza o card"
    assunto = f"{prefixo}: {corpo}"
    if len(assunto) <= ASSUNTO_MAX:
        return assunto
    return assunto[: ASSUNTO_MAX - 1].rstrip() + "…"


def _sanear(
    bruto: dict[str, object], card_type: CardType | str | None, title: str
) -> BranchNaming | None:
    """Aceita a sugestão do agente **depois** de impor o prefixo e sanear o slug.

    O agente pode devolver `"Feature/Calculadora Básica!!"`; só o miolo do slug é dele.
    """
    slug_bruto = str(bruto.get("branch") or "").strip()
    slug = slugify(slug_bruto.rsplit("/", 1)[-1]) if slug_bruto else ""
    if not slug or slug == "card":
        return None
    commit = str(bruto.get("commit") or "").strip().splitlines()
    assunto = _assunto(card_type, commit[0]) if commit and commit[0] else _assunto(card_type, title)
    # O agente costuma já vir com o prefixo; evita `feat: feat: ...`.
    prefixo = prefixo_para(card_type)
    if commit and commit[0].lower().startswith(f"{prefixo}:"):
        assunto = commit[0].strip()[:ASSUNTO_MAX]
    return BranchNaming(branch_stem=f"{prefixo}/{slug}", commit_subject=assunto, source="agente")
