"""CandidateRunner — executa múltiplos agentes CLI em paralelo por card (§26A.6).

Cada agente CLI (ex.: Claude Code, Codex) gera um candidato em worktree/branch
isolado; os diffs são coletados e comparados antes de escolher qual vira PR/merge.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from aso.agents.executor import ExecutionProvider
from aso.agents.models import AgentSpec

_DIFF_FILE = re.compile(r"^\+\+\+ b/(.+)$", re.MULTILINE)
# Limite de caracteres do diff devolvido ao cliente (evita payloads gigantes no console/API).
_DIFF_CAP = 20_000


@dataclass
class Candidate:
    executor_id: str
    branch: str
    diff_lines: int
    files: list[str] = field(default_factory=list)
    diff: str = ""
    error: str | None = None


class CandidateRunner:
    def run(
        self, agent: AgentSpec, task: dict[str, Any], providers: list[ExecutionProvider]
    ) -> list[Candidate]:
        def _one(provider: ExecutionProvider) -> Candidate:
            try:
                out = provider.execute(agent, dict(task))
                diff = str(out.artifacts.get("diff", ""))
                capped = diff[:_DIFF_CAP] + ("\n… (diff truncado)" if len(diff) > _DIFF_CAP else "")
                return Candidate(
                    executor_id=out.executor_id,
                    branch=str(out.artifacts.get("branch", "")),
                    diff_lines=len(diff.splitlines()),
                    files=_DIFF_FILE.findall(diff),
                    diff=capped,
                )
            except Exception as exc:  # noqa: BLE001 — candidato falho não derruba os demais
                return Candidate(
                    executor_id=getattr(provider, "id", "?"),
                    branch="",
                    diff_lines=0,
                    error=str(exc),
                )

        if len(providers) > 1:
            with ThreadPoolExecutor(max_workers=min(4, len(providers))) as pool:
                return list(pool.map(_one, providers))
        return [_one(p) for p in providers]

    @staticmethod
    def compare(candidates: list[Candidate]) -> dict[str, Any]:
        """Compara candidatos e recomenda um (heurística: menor diff válido)."""
        valid = [c for c in candidates if c.error is None and c.branch]
        recommended = min(valid, key=lambda c: c.diff_lines).branch if valid else None
        return {
            "candidates": [
                {
                    "executor": c.executor_id,
                    "branch": c.branch,
                    "diff_lines": c.diff_lines,
                    "files": c.files,
                    "diff": c.diff,
                    "error": c.error,
                }
                for c in candidates
            ],
            "recommended_branch": recommended,
        }
