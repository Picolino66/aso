"""Autenticação por API key + RBAC (req §34).

Tokens são configurados via `ASO_API_KEYS` (JSON: {token: {actor, role}}).
Sem tokens, o **modo dev** (principal `dev`/`admin` anônimo) só é aceito quando pedido
explicitamente com `ASO_DEV_MODE=1` (ADR-0057): admin anônimo por omissão de variável
transformava qualquer cliente da rede em administrador capaz de rodar comandos no host.

Papéis (hierárquicos): viewer < operator < admin.
- viewer: leitura (GET)
- operator: escrita (criar orquestração, rodar, patches, feedback, cards...)
- admin: ações críticas (aprovar/rejeitar aprovação, rollback, avançar fase, comandos no host)
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
            # Fail-closed (regra 4/9, ADR-0057): sem tokens e sem pedido explícito de
            # modo dev, a API não sobe — melhor falhar no boot que servir admin anônimo.
            if os.environ.get("ASO_DEV_MODE") != "1":
                raise RuntimeError(
                    "ASO_API_KEYS não configurada. Defina ASO_API_KEYS (JSON "
                    '{"token": {"actor": "...", "role": "admin|operator|viewer"}}) ou, só '
                    "para desenvolvimento local, ASO_DEV_MODE=1 (todo cliente vira admin)."
                )
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
    if (method == "DELETE" and path.startswith("/v1/projects/")) or path.endswith("/restore"):
        return "admin"
    if path.endswith(
        (
            "/approve",
            "/reject",
            "/rollback",
            "/restaurar-ledger",
            "/merge",
            "/race",
            "/restore-section",
            "/recover-execution",
            "/discovery/decide",
            "/spec/approve",
            "/budget",
            "/worktrees/prune",
            # Avanço de fase (regra inviolável 3/4): muda o estágio da esteira inteira.
            "/advance-phase",
        )
    ):
        return "admin"
    if method == "GET":
        return "viewer"
    # Comandos no host (ADR-0057): configurar a bateria de validação/deploy ou disparar
    # a implantação roda `subprocess` na máquina do runtime — mesmo nível de /executors.
    # `validation_command` enviado no corpo (criação/execution-settings) é checado no
    # handler, porque `required_role` não lê o corpo.
    if path.endswith(("/validation-checks", "/deploy/config", "/deploy/pipeline", "/deploy/run")):
        return "admin"
    # Configuração de executores (criar/editar/remover perfis) é ação administrativa.
    if method != "GET" and "/executors" in path:
        return "admin"
    # Regras de roteamento (req §33, ADR-0028): escrita muda a política de decisão de
    # toda orquestração futura — mesmo nível crítico de /executors.
    if method != "GET" and "/routing-rules" in path:
        return "admin"
    # Catálogo de agentes (Tela 30, wf §32, ADR-0053): escrita muda a política de
    # PERMISSÃO REAL do ContextBus (deny-by-default) — nível crítico máximo.
    if method != "GET" and "/agent-definitions" in path:
        return "admin"
    return "operator"
