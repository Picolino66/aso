#!/usr/bin/env bash
# Liga a saída em NDJSON dos executores CLI, para o painel "o que o agente está fazendo".
#
# POR QUE: `claude -p` em modo não-interativo imprime só a RESPOSTA FINAL. Fazer streaming
# do lado do ASO não cria narração — o CLI precisa emitir evento por evento. Com
# `--output-format stream-json --verbose` o Claude manda uma linha JSON por passo (texto,
# chamada de ferramenta, resultado), que é o que a tela de detalhe interpreta e mostra
# ferramenta por ferramenta, como no terminal do Claude Code. Para o Codex, o equivalente
# é `--json`.
#
# Sem estas flags nada quebra: a tela cai no modo bruto (mostra as linhas como vierem).
#
# Uso: ./scripts/enable-agent-stream.sh [http://localhost:8000]
#      ./scripts/enable-agent-stream.sh --off   (remove as flags)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

MODO="on"
BASE="http://localhost:8000"
for arg in "$@"; do
  case "$arg" in
    --off) MODO="off";;
    http*) BASE="$arg";;
    *) echo "Argumento desconhecido: $arg" >&2; exit 2;;
  esac
done

ARQUIVO="${ASO_EXECUTORS_FILE:-.aso/executors.json}"
AUTH=()
[ -n "${ASO_ADMIN_TOKEN:-}" ] && AUTH=(-H "Authorization: Bearer ${ASO_ADMIN_TOKEN}")

# A API é a fonte de verdade quando está no ar (ela reescreve o arquivo ao salvar);
# com a API parada, editamos o arquivo direto — é o mesmo formato.
if curl -fsS "${AUTH[@]}" "$BASE/v1/executors" -o /dev/null 2>/dev/null; then
  VIA="api"
  perfis="$(curl -fsS "${AUTH[@]}" "$BASE/v1/executors")"
else
  VIA="arquivo"
  [ -f "$ARQUIVO" ] || { echo "Sem API no ar e sem $ARQUIVO — nada a fazer." >&2; exit 1; }
  perfis="$(cat "$ARQUIVO")"
fi
echo "Modo: $MODO · via: $VIA"

alterados="$(MODO="$MODO" python3 - "$perfis" <<'PY'
import json, os, sys

modo = os.environ["MODO"]
# Flag por família de CLI: o que cada um precisa para falar NDJSON.
FLAGS = {
    "claude": ["--output-format", "stream-json", "--verbose"],
    "codex": ["--json"],
}

def familia(perfil):
    comando = perfil.get("command") or ""
    if "claude" in comando:
        return "claude"
    if "codex" in comando:
        return "codex"
    return ""

saida = []
for perfil in json.loads(sys.argv[1]):
    if perfil.get("kind") != "cli":
        continue
    fam = familia(perfil)
    if not fam:
        continue
    comando = perfil.get("command") or ""
    flags = FLAGS[fam]
    tem = all(f in comando for f in flags)
    if modo == "on":
        if tem:
            continue
        # No fim do comando: o wrapper acrescenta o prompt depois, e flags antes do
        # prompt é o que ambos os CLIs esperam.
        novo = comando + " " + " ".join(flags)
    else:
        if not tem:
            continue
        novo = comando
        for f in flags:
            novo = novo.replace(" " + f, "")
    saida.append({
        "name": perfil["name"], "kind": perfil["kind"],
        "provider": perfil.get("provider") or "", "model": perfil.get("model") or "",
        "effort": perfil.get("effort") or "medium", "command": novo.strip(),
        "base_url": perfil.get("base_url") or "", "api_key_env": perfil.get("api_key_env") or "",
        "is_default": bool(perfil.get("is_default")),
    })
print(json.dumps(saida, ensure_ascii=False))
PY
)"

quantos="$(printf '%s' "$alterados" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')"
if [ "$quantos" = "0" ]; then
  echo "Nenhum perfil a alterar (já estão como você pediu)."
  exit 0
fi

if [ "$VIA" = "api" ]; then
  printf '%s' "$alterados" | python3 -c 'import json,sys; [print(json.dumps(p, ensure_ascii=False)) for p in json.load(sys.stdin)]' \
  | while IFS= read -r corpo; do
      nome="$(printf '%s' "$corpo" | python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])')"
      curl -fsS "${AUTH[@]}" -X POST "$BASE/v1/executors" \
        -H 'content-type: application/json' -d "$corpo" > /dev/null
      echo "  ajustado: $nome"
    done
else
  # Mescla no arquivo preservando os campos que a API não expõe (managed_by etc.).
  ALTERADOS="$alterados" python3 - "$ARQUIVO" <<'PY'
import json, os, pathlib, sys

caminho = pathlib.Path(sys.argv[1])
perfis = json.loads(caminho.read_text(encoding="utf-8"))
novos = {p["name"]: p["command"] for p in json.loads(os.environ["ALTERADOS"])}
for perfil in perfis:
    if perfil["name"] in novos:
        perfil["command"] = novos[perfil["name"]]
        print(f"  ajustado: {perfil['name']}")
caminho.write_text(json.dumps(perfis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
fi

echo
echo "$quantos perfil(is) ajustado(s). Reinicie a API para valer: ./scripts/manager.sh reiniciar"
