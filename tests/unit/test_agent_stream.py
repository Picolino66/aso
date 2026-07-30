"""Interpretação do NDJSON dos agentes CLI (ADR-0015).

As linhas de `_ENVELOPE_REAL` foram **capturadas de uma execução de verdade** de
`claude -p --output-format stream-json --verbose` (Claude Code, julho/2026) — não são
inventadas. É o que protege o painel ao vivo de mostrar JSON cru: `system`,
`rate_limit_event` e afins existem no fluxo real e não são fala do agente.
"""

from __future__ import annotations

import json

from aso.execution.agent_stream import (
    PENSAMENTO_MAX,
    TEXTO_MAX,
    extrair_texto,
    interpretar,
)
from aso.shared.agent_output import (
    KIND_BRUTO,
    KIND_FERRAMENTA,
    KIND_RESULTADO,
    KIND_TEXTO,
)

# Sequência real, na ordem em que saiu do CLI.
_ENVELOPE_REAL = [
    '{"type":"system","subtype":"init","session_id":"29b61a71"}',
    '{"type":"system","subtype":"thinking_tokens","tokens":128}',
    '{"type":"rate_limit_event","rate_limit_info":{"status":"allowed","resetsAt":1785375000},'
    '"uuid":"f61adfb7"}',
    '{"type":"assistant","message":{"content":[{"type":"thinking","thinking":"O usuário pediu '
    'para eu responder apenas oi."}]}}',
    '{"type":"assistant","message":{"content":[{"type":"text","text":"oi"}]}}',
    '{"type":"result","subtype":"success","result":"oi"}',
]


def _kinds(linha: str) -> list[str]:
    return [item.kind for item in interpretar(linha)]


# ------------------------------------------------------------------ envelope real


def test_envelope_real_nao_vaza_json_cru() -> None:
    """O sintoma que motivou a lista de ruído: rate_limit_event virava JSON na tela."""
    for linha in _ENVELOPE_REAL:
        for item in interpretar(linha):
            assert item.kind != KIND_BRUTO, f"vazou como bruto: {linha[:60]}"


def test_envelope_real_produz_pensamento_fala_e_resultado() -> None:
    itens = [item for linha in _ENVELOPE_REAL for item in interpretar(linha)]
    assert [i.kind for i in itens] == [KIND_TEXTO, KIND_TEXTO, KIND_RESULTADO]
    assert itens[0].detail == "pensando"
    assert itens[1].text == "oi"
    assert itens[2].text == "oi"


def test_ruido_de_controle_e_descartado() -> None:
    for tipo in ("system", "rate_limit_event", "stream_event", "control_request"):
        assert interpretar(json.dumps({"type": tipo, "x": 1})) == []


# ------------------------------------------------------------------ ferramentas


def test_tool_use_com_arquivo() -> None:
    linha = json.dumps(
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "name": "Write", "input": {"file_path": "src/app.js"}}
                ]
            },
        }
    )
    (item,) = interpretar(linha)
    assert item.kind == KIND_FERRAMENTA
    assert item.text == "Write"
    assert item.detail == "src/app.js"


def test_tool_use_com_comando() -> None:
    linha = json.dumps(
        {
            "type": "assistant",
            "message": {
                "content": [{"type": "tool_use", "name": "Bash", "input": {"command": "npm test"}}]
            },
        }
    )
    (item,) = interpretar(linha)
    assert (item.kind, item.text, item.detail) == (KIND_FERRAMENTA, "Bash", "npm test")


def test_tool_use_sem_alvo_reconhecido() -> None:
    linha = json.dumps(
        {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "name": "TodoWrite", "input": {"x": 1}}]},
        }
    )
    (item,) = interpretar(linha)
    assert item.text == "TodoWrite" and item.detail == ""


def test_tool_result_normal_e_suprimido_mas_erro_aparece() -> None:
    # O `tool_use` já contou o que foi feito; repetir o retorno inteiro afogaria o painel.
    ok = json.dumps(
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": "240 linhas"}]}}
    )
    assert interpretar(ok) == []
    falhou = json.dumps(
        {
            "type": "user",
            "message": {
                "content": [
                    {"type": "tool_result", "is_error": True, "content": "ENOENT: sem tal arquivo"}
                ]
            },
        }
    )
    (item,) = interpretar(falhou)
    assert item.kind == KIND_RESULTADO
    assert "ENOENT" in item.text


def test_tool_result_com_content_em_blocos() -> None:
    linha = json.dumps(
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "is_error": True,
                        "content": [{"type": "text", "text": "falhou aqui"}],
                    }
                ]
            },
        }
    )
    (item,) = interpretar(linha)
    assert item.text == "falhou aqui"


def test_varios_blocos_numa_linha_viram_varias_linhas() -> None:
    linha = json.dumps(
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": "vou editar"},
                    {"type": "tool_use", "name": "Edit", "input": {"file_path": "a.py"}},
                ]
            },
        }
    )
    assert _kinds(linha) == [KIND_TEXTO, KIND_FERRAMENTA]


def test_content_como_string() -> None:
    linha = json.dumps({"type": "assistant", "message": {"content": "resposta direta"}})
    (item,) = interpretar(linha)
    assert (item.kind, item.text) == (KIND_TEXTO, "resposta direta")


# ------------------------------------------------------------------ truncamento


def test_pensamento_e_cortado_mais_curto_que_a_fala() -> None:
    longo = "raciocínio " * 200
    pensando = json.dumps(
        {"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": longo}]}}
    )
    falando = json.dumps(
        {"type": "assistant", "message": {"content": [{"type": "text", "text": longo}]}}
    )
    (p,) = interpretar(pensando)
    (f,) = interpretar(falando)
    assert len(p.text) <= PENSAMENTO_MAX
    assert PENSAMENTO_MAX < len(f.text) <= TEXTO_MAX


def test_texto_gigante_nao_estoura_o_limite() -> None:
    (item,) = interpretar(json.dumps({"type": "result", "result": "x" * 5000}))
    assert len(item.text) <= TEXTO_MAX


# ------------------------------------------------------------------ formatos alheios


def test_linha_nao_json_vira_bruto_preservando_o_texto() -> None:
    (item,) = interpretar("Warning: no stdin data received in 3s")
    assert item.kind == KIND_BRUTO
    assert "no stdin data" in item.text


def test_json_de_formato_desconhecido_vira_bruto() -> None:
    # Um CLI novo, ou uma versão que mudou o schema: mostra como veio, não perde a linha.
    (item,) = interpretar('{"algo":"que nao conhecemos","n":1}')
    assert item.kind == KIND_BRUTO


def test_json_malformado_vira_bruto() -> None:
    (item,) = interpretar('{"type":"assistant","message":{')
    assert item.kind == KIND_BRUTO


def test_linha_vazia_e_ignorada() -> None:
    assert interpretar("") == []
    assert interpretar("   \n") == []


def test_lista_json_no_lugar_de_objeto_vira_bruto() -> None:
    (item,) = interpretar("[1, 2, 3]")
    assert item.kind == KIND_BRUTO


def test_formato_generico_com_campo_message() -> None:
    (item,) = interpretar('{"message":"algo aconteceu"}')
    assert (item.kind, item.text) == (KIND_TEXTO, "algo aconteceu")


def test_envelope_do_codex_com_comando() -> None:
    linha = json.dumps({"type": "item.completed", "item": {"type": "command", "command": "ls -la"}})
    (item,) = interpretar(linha)
    assert (item.kind, item.text, item.detail) == (KIND_FERRAMENTA, "Comando", "ls -la")


def test_envelope_do_codex_com_texto_completo() -> None:
    linha = json.dumps(
        {"type": "item.completed", "item": {"type": "agent_message.completed", "text": "pronto"}}
    )
    (item,) = interpretar(linha)
    assert (item.kind, item.text) == (KIND_RESULTADO, "pronto")


# ------------------------------------------------------------------ extrair_texto


def test_extrair_texto_destila_a_fala_ignorando_o_raciocinio() -> None:
    """O motivo no card precisa ser legível: nem JSON cru, nem monólogo interno."""
    destilado = extrair_texto("\n".join(_ENVELOPE_REAL))
    assert "rate_limit" not in destilado
    assert "O usuário pediu" not in destilado  # o pensamento não explica a falha
    assert destilado == "oi oi"


def test_extrair_texto_inclui_ferramentas_usadas() -> None:
    linhas = [
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "tool_use", "name": "Bash", "input": {"command": "pytest"}}
                    ]
                },
            }
        ),
        json.dumps({"type": "result", "result": "tudo verde"}),
    ]
    destilado = extrair_texto("\n".join(linhas))
    assert "[Bash pytest]" in destilado
    assert "tudo verde" in destilado


def test_extrair_texto_de_saida_em_texto_puro() -> None:
    # Sem as flags de streaming, a saída é texto comum — precisa continuar funcionando.
    assert extrair_texto("Aguardo sua permissão para criar o arquivo.") == (
        "Aguardo sua permissão para criar o arquivo."
    )


def test_extrair_texto_respeita_o_limite_pegando_a_cauda() -> None:
    saida = "\n".join(f"linha {i}" for i in range(500))
    destilado = extrair_texto(saida, limite=80)
    assert len(destilado) <= 80
    assert "499" in destilado  # o desfecho, não o começo


def test_extrair_texto_de_saida_vazia() -> None:
    assert extrair_texto("") == ""
