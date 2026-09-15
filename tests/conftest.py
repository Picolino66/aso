"""Configuração global dos testes (vale para unit e integration).

`aso.api.app` cria a aplicação no import (`app = create_app(...)`), e sem tokens a API
só sobe com modo dev explícito (ADR-0057). Os testes que exercitam RBAC injetam o
próprio `AuthService`; os demais rodam em modo dev. As raízes de workspace ficam
abertas (`/`) porque os testes usam `tmp_path` fora do `$HOME` — os testes da regra de
raízes sobrescrevem a variável com `monkeypatch`.

O catálogo de executores salvo aponta para um arquivo temporário: a leitura migra e regrava
perfis antigos (ADR-0076), e um teste que sobe `build_service` na raiz do repositório não pode
tocar o `.aso/executors.json` do operador.
"""

from __future__ import annotations

import os
import tempfile

os.environ.setdefault("ASO_DEV_MODE", "1")
os.environ.setdefault("ASO_WORKSPACE_ROOTS", os.sep)
os.environ.setdefault(
    "ASO_EXECUTORS_FILE", os.path.join(tempfile.mkdtemp(prefix="aso-executores-"), "executors.json")
)
