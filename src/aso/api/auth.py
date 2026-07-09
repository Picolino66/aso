"""Autenticação por API key + RBAC (§34).

Tokens são configurados via `ASO_API_KEYS` (JSON: {token: {actor, role}}).
Sem tokens configurados, roda em **modo dev** (principal `dev`/`admin`) para não
travar desenvolvimento/UI; em produção defina `ASO_API_KEYS` para exigir token.

Papéis (hierárquicos): viewer < operator < admin.
- viewer: leitura (GET)
- operator: escrita (criar orquestração, rodar, patches, feedback, cards...)
- admin: ações críticas (aprovar/rejeitar aprovação, rollback)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

ROLE_RANK = {"viewer": 0, "operator": 1, "admin": 2}


@dataclass(frozen=True)
class Principal:
    actor: str
    role: str

    def can(self, min_role: str) -> bool:
        return ROLE_RANK.get(self.role, -1) >= ROLE_RANK[min_role]


class AuthService:
    """Resolve um token de `Authorization: Bearer <token>` em um Principal."""

    def __init__(self, tokens: dict[str, Principal], *, dev_mode: bool) -> None:
        self._tokens = tokens
        self.dev_mode = dev_mode

    @classmethod
    def from_env(cls) -> AuthService:
        raw = os.environ.get("ASO_API_KEYS")
        if not raw:
            return cls({}, dev_mode=True)
        data = json.loads(raw)
        tokens = {
            token: Principal(actor=info["actor"], role=info["role"]) for token, info in data.items()
        }
        return cls(tokens, dev_mode=False)

    def authenticate(self, authorization: str | None) -> Principal | None:
        """Retorna o Principal, ou None se o token for inválido/ausente (produção)."""
        if self.dev_mode:
            return Principal(actor="dev", role="admin")
        if not authorization:
            return None
        token = authorization.removeprefix("Bearer ").strip()
        return self._tokens.get(token)


def required_role(method: str, path: str) -> str:
    """Papel mínimo exigido para (método, caminho)."""
    if path.endswith(
        (
            "/approve",
            "/reject",
            "/rollback",
            "/merge",
            "/race",
            "/restore-section",
            "/recover-execution",
        )
    ):
        return "admin"
    if method == "GET":
        return "viewer"
    # Configuração de executores (criar/editar/remover perfis) é ação administrativa.
    if method != "GET" and "/executors" in path:
        return "admin"
    return "operator"
