"""Configuração global dos testes (vale para unit e integration).

`aso.api.app` cria a aplicação no import (`app = create_app(...)`), e sem tokens a API
só sobe com modo dev explícito (ADR-0057). Os testes que exercitam RBAC injetam o
próprio `AuthService`; os demais rodam em modo dev. As raízes de workspace ficam
abertas (`/`) porque os testes usam `tmp_path` fora do `$HOME` — os testes da regra de
raízes sobrescrevem a variável com `monkeypatch`.
"""

from __future__ import annotations

import os

os.environ.setdefault("ASO_DEV_MODE", "1")
os.environ.setdefault("ASO_WORKSPACE_ROOTS", os.sep)
