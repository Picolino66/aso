"""Descoberta de capacidades do Codex pelo App Server local."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from aso.execution.codex_discovery import CodexDiscoveryError, discover_codex


def _fake_codex(path: Path, behavior: str = "ok") -> Path:
    script = path / "codex-fake"
    script.write_text(
        f"""#!/usr/bin/env python3
import json, sys, time
if '--version' in sys.argv:
    print('codex-cli 9.9.9')
    raise SystemExit
for line in sys.stdin:
    msg=json.loads(line)
    if msg.get('method') == 'initialize':
        print(json.dumps({{'id':msg['id'],'result':{{'userAgent':'fake'}}}}), flush=True)
    elif msg.get('method') == 'model/list':
        behavior={behavior!r}
        if behavior == 'timeout':
            time.sleep(2)
            continue
        if behavior == 'invalid':
            print(json.dumps({{'id':msg['id'],'result':{{'data':'erro'}}}}), flush=True)
            continue
        cursor=msg['params'].get('cursor')
        model='gpt-a' if not cursor else 'gpt-b'
        data=[{{'model':model,'displayName':model.upper(),'isDefault':not cursor,
          'defaultReasoningEffort':'medium','supportedReasoningEfforts':[
            {{'reasoningEffort':'low'}},{{'reasoningEffort':'medium'}}]}}]
        result={{'data':data,'nextCursor':'p2' if not cursor else None}}
        print(json.dumps({{'id':msg['id'],'result':result}}), flush=True)
""",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


def test_discover_codex_paginado(tmp_path: Path) -> None:
    capabilities = discover_codex(binary=str(_fake_codex(tmp_path)), timeout=2)
    assert capabilities.version == "codex-cli 9.9.9"
    assert [model.model for model in capabilities.models] == ["gpt-a", "gpt-b"]
    assert capabilities.models[0].is_default is True
    assert capabilities.models[0].supported_efforts == ("low", "medium")


def test_discover_codex_binario_ausente() -> None:
    with pytest.raises(CodexDiscoveryError, match="não encontrado"):
        discover_codex(binary="codex-que-nao-existe")


@pytest.mark.parametrize(("behavior", "message"), [("timeout", "tempo"), ("invalid", "data")])
def test_discover_codex_falhas_controladas(tmp_path: Path, behavior: str, message: str) -> None:
    with pytest.raises(CodexDiscoveryError, match=message):
        discover_codex(binary=str(_fake_codex(tmp_path, behavior)), timeout=0.2)
