#!/usr/bin/env bash
# Adaptador entre o ASO Runtime e um agente CLI (Codex, Claude Code, Aider, …).
#
# O ASO executa o comando do executor no worktree do card e entrega a TAREFA como
# JSON no stdin. A maioria dos CLIs espera um PROMPT, não esse JSON. Este wrapper lê
# o JSON, monta um prompt em pt-BR e invoca o agente passado em "$@" com o prompt
# como último argumento.
#
# Dois tipos de tarefa:
#   - execução (padrão): implementar o card no worktree, com commits pequenos;
#   - "kind": "naming": só produzir um JSON com nome de branch e assunto de commit
#     (ADR-0014) — roda numa pasta temporária, sem alterar código.
#
# Uso (campo "comando CLI" da tela ⚙ Config, com caminho ABSOLUTO):
#   /app/scripts/aso-agent-wrapper.sh codex exec
#   /app/scripts/aso-agent-wrapper.sh claude -p
#
# Requer python3 no PATH (já presente na imagem do ASO).
set -euo pipefail

export ASO_TASK="$(cat)"

prompt="$(python3 <<'PY'
import json, os
try:
    d = json.loads(os.environ.get("ASO_TASK") or "{}")
except Exception:
    d = {}
c = d.get("content") or {}

# Tarefa de nomeação: o agente só devolve JSON, não toca em arquivo nenhum.
if d.get("kind") == "naming":
    print((c.get("system") or "") + "\n\n" + (c.get("request") or ""))
    raise SystemExit

req = c.get("request") or c.get("by") or "(sem demanda)"
gate = c.get("validation_command")
titulo = c.get("card_title") or ""
descricao = c.get("card_description") or ""
criterios = c.get("acceptance_criteria") or []
correcoes = c.get("correction_actions") or []
commit = c.get("commit_subject") or ""

linhas = [
    f"Você é um agente de engenharia autônoma no ASO Runtime (fase {d.get('phase', '?')}).",
    f"Demanda do produto: {req}",
]
# Sem isto o agente trabalhava cego: recebia só a demanda global da orquestração e
# não sabia QUAL card estava implementando.
if titulo:
    linhas.append(f"Card desta execução ({c.get('card_type') or 'Task'}): {titulo}")
if descricao:
    linhas.append(f"Detalhes do card: {descricao}")
if criterios:
    linhas.append("Critérios de aceite (todos devem valer ao final):")
    linhas += [f"  - {x}" for x in criterios]
if correcoes:
    # Re-execução depois de uma revisão reprovada (§15, ADR-0017): sem isto o
    # agente repetia o mesmo erro, cego ao que a revisão pediu.
    linhas.append("Correções obrigatórias apontadas pela revisão independente:")
    linhas += [f"  - {x}" for x in correcoes]
linhas.append(f"Seção-alvo do contexto: {d.get('target_path', '')}")
linhas.append(
    "Implemente/produza o necessário NESTE diretório (worktree isolado do card), em "
    "pt-BR, com commits pequenos e foco APENAS neste card. Se for fase de código, "
    "deixe os testes verdes."
)
if commit:
    linhas.append(
        "Use Conventional Commits em pt-BR nas mensagens; o primeiro commit deve ter "
        f"como assunto: {commit}"
    )
if gate:
    linhas.append(f"Comando de aceite obrigatório e finito: {gate}")
print("\n".join(linhas))
PY
)"

exec "$@" "$prompt"
