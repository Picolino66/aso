"""Renderiza o prompt de um agente CLI a partir da tarefa JSON (ADR-0059).

Chamado pelo `scripts/aso-agent-wrapper.sh` com a tarefa no stdin; imprime o prompt no
stdout. **Só biblioteca padrão, de propósito**: o wrapper roda com o `python3` do
ambiente do agente (fora da venv do runtime), então este arquivo não pode importar
Pydantic nem o resto do pacote. O contrato tipado vive em `contract.py`; aqui só se lê o
dicionário e se recusa versão desconhecida.

Uso: `python3 render_prompt.py < tarefa.json` (ou `python -m aso.agents.render_prompt`).
Exit 2 = contrato inválido (mensagem em pt-BR no stderr).
"""

from __future__ import annotations

import json
import sys
from typing import Any

SCHEMA_VERSION = "1"  # manter igual a `contract.SCHEMA_VERSION` (teste garante)

INSTRUCAO_SO_JSON = (
    "Responda SOMENTE com o objeto JSON pedido acima — sem texto antes ou depois, sem "
    "cercas de código. Não crie, altere nem execute arquivos: esta é uma pergunta, não "
    "uma tarefa de implementação."
)


class ContratoInvalido(ValueError):
    """Tarefa fora do contrato suportado por este renderizador."""


def _lista(valor: Any) -> list[str]:
    return [str(x) for x in valor] if isinstance(valor, list) else []


def _envelope(task: dict[str, Any]) -> dict[str, Any]:
    """Envelope v1 da tarefa; tarefas antigas (sem `envelope`) são convertidas."""
    bruto = task.get("envelope")
    if isinstance(bruto, dict):
        versao = str(bruto.get("schema_version", ""))
        if versao != SCHEMA_VERSION:
            raise ContratoInvalido(
                f"schema_version '{versao}' desconhecida (renderizador suporta "
                f"'{SCHEMA_VERSION}') — atualize o wrapper/runtime."
            )
        env = dict(bruto)
    else:
        env = _envelope_legado(task)
    # O supervisor injeta `nudge`/`effort` no topo da tarefa DEPOIS de montado o envelope
    # (retry com dica de correção): o valor mais recente vence.
    for campo in ("nudge", "effort"):
        if task.get(campo):
            env[campo] = task[campo]
    return env


def _envelope_legado(task: dict[str, Any]) -> dict[str, Any]:
    conteudo = task.get("content") or {}
    if not isinstance(conteudo, dict):
        conteudo = {}
    kind = str(task.get("kind") or "")
    # Formato antigo de pergunta (`agent_ask`): `kind` = rótulo + `content.system`. O
    # wrapper antigo só reconhecia "naming" e descartava o system das demais.
    if kind and conteudo.get("system"):
        return {
            "kind": "ask",
            "task_type": kind,
            "system": conteudo.get("system") or "",
            "request": conteudo.get("request") or "",
        }
    return {
        "kind": "execute",
        "task_type": "card" if conteudo.get("card_title") else "docs",
        "request": conteudo.get("request") or conteudo.get("by") or "",
        "card": {
            "titulo": conteudo.get("card_title") or "",
            "tipo": conteudo.get("card_type") or "Task",
            "descricao": conteudo.get("card_description") or "",
            "criterios": _lista(conteudo.get("acceptance_criteria")),
            "correcoes": _lista(conteudo.get("correction_actions")),
            "contexto_adicional": _lista(conteudo.get("contexto_adicional")),
        },
        "validation_command": conteudo.get("validation_command"),
        "commit_subject": conteudo.get("commit_subject") or "",
        "phase": task.get("phase") or "",
        "target_path": task.get("target_path") or "",
    }


def _prompt_pergunta(env: dict[str, Any]) -> str:
    partes = [str(env.get("system") or "").strip(), str(env.get("request") or "").strip()]
    esquema = env.get("output_schema")
    if isinstance(esquema, dict) and esquema:
        partes.append("Schema JSON da resposta:\n" + json.dumps(esquema, ensure_ascii=False))
    partes.append(INSTRUCAO_SO_JSON)
    return "\n\n".join(p for p in partes if p)


def _renderizar_contexto(contexto: Any) -> str:
    """Mesmo formato de `context_builder.renderizar_contexto` (teste garante a igualdade);
    duplicado aqui porque este arquivo roda só com a biblioteca padrão."""
    if not isinstance(contexto, dict):
        return ""
    blocos = [
        f"### {item.get('titulo', '')}\n{item.get('conteudo', '')}"
        for item in contexto.get("itens", [])
        if isinstance(item, dict)
    ]
    if not blocos:
        return ""
    texto = "Contexto da tarefa (priorizado):\n\n" + "\n\n".join(blocos)
    omitidos = contexto.get("omitidos") or []
    if omitidos:
        texto += "\n\n(Omitido por orçamento de contexto: " + ", ".join(map(str, omitidos)) + ")"
    return texto


def _prompt_execucao(env: dict[str, Any]) -> str:
    card_bruto = env.get("card")
    card: dict[str, Any] = card_bruto if isinstance(card_bruto, dict) else {}
    linhas = [
        f"Você é um agente de engenharia autônoma no ASO Runtime (fase {env.get('phase') or '?'}).",
        f"Demanda do produto: {env.get('request') or '(sem demanda)'}",
    ]
    # Sem o card o agente trabalhava cego: recebia só a demanda global da orquestração.
    if card.get("titulo"):
        linhas.append(f"Card desta execução ({card.get('tipo') or 'Task'}): {card['titulo']}")
    if card.get("descricao"):
        linhas.append(f"Detalhes do card: {card['descricao']}")
    criterios = _lista(card.get("criterios"))
    if criterios:
        linhas.append("Critérios de aceite (todos devem valer ao final):")
        linhas += [f"  - {x}" for x in criterios]
    correcoes = _lista(card.get("correcoes"))
    if correcoes:
        # Re-execução depois de revisão reprovada (§15, ADR-0017).
        linhas.append("Correções obrigatórias apontadas pela revisão independente:")
        linhas += [f"  - {x}" for x in correcoes]
    contexto = _lista(card.get("contexto_adicional"))
    if contexto:
        # "Adicionar contexto" do operador (Tela 15, ADR-0048).
        linhas.append("Contexto adicional do operador (siga estas instruções):")
        linhas += [f"  - {x}" for x in contexto]
    if env.get("nudge"):
        # Dica de correção do supervisor após uma tentativa falha (§15).
        linhas.append(f"Atenção — a tentativa anterior falhou: {env['nudge']}")
    bloco_contexto = _renderizar_contexto(env.get("contexto"))
    if bloco_contexto:
        # Saídas de fases anteriores, spec, discovery e ADRs (ADR-0063).
        linhas.append(bloco_contexto)
    if env.get("system"):
        linhas.append(str(env["system"]))
    if env.get("target_path"):
        linhas.append(f"Seção-alvo do contexto: {env['target_path']}")
    linhas.append(
        "Implemente/produza o necessário NESTE diretório (worktree isolado do card), em "
        "pt-BR, com commits pequenos e foco APENAS nesta tarefa. Se for fase de código, "
        "deixe os testes verdes."
    )
    if env.get("effort"):
        linhas.append(f"Nível de esforço solicitado: {env['effort']}")
    if env.get("commit_subject"):
        linhas.append(
            "Use Conventional Commits em pt-BR nas mensagens; o primeiro commit deve ter "
            f"como assunto: {env['commit_subject']}"
        )
    if env.get("validation_command"):
        linhas.append(f"Comando de aceite obrigatório e finito: {env['validation_command']}")
    return "\n".join(linhas)


def renderizar_prompt(task: dict[str, Any]) -> str:
    env = _envelope(task)
    kind = env.get("kind")
    if kind == "ask":
        if not str(env.get("system") or "").strip():
            raise ContratoInvalido(
                f"Pergunta '{env.get('task_type')}' sem system (schema ausente)."
            )
        return _prompt_pergunta(env)
    if kind == "execute":
        return _prompt_execucao(env)
    raise ContratoInvalido(f"kind '{kind}' desconhecido (esperado 'execute' ou 'ask').")


def main() -> int:
    bruto = sys.stdin.read()
    try:
        task = json.loads(bruto or "{}")
        if not isinstance(task, dict):
            raise ContratoInvalido("A tarefa JSON precisa ser um objeto.")
        print(renderizar_prompt(task))
    except (ContratoInvalido, json.JSONDecodeError) as exc:
        print(f"aso-agent-wrapper: contrato inválido — {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
