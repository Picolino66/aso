"""Índice estrutural do repositório por commit (ADR-0077, MEL-44).

Discovery ("componentes afetados"), especificação e revisão ("risco de regressão") decidiam sem
nenhum fato estrutural do código: o `WorkspaceAnalyzer` só via diretórios de topo. Falta um mapa
**barato e determinístico** — não RAG vetorial: os agentes CLI já leem o código (ADR-0069), o que
o runtime precisa é orientar a pergunta e **verificar** a resposta.

O que o índice guarda por arquivo: linguagem, linhas, se é teste, símbolos públicos (nome, tipo,
linha), imports internos já resolvidos para caminhos do próprio repositório e pontos de entrada
detectáveis (rotas HTTP, comandos de CLI). Python sai de `ast` (exato); TypeScript/JavaScript sai
de expressões regulares conservadoras (aproximado, e o índice diz isso em `precisao`); outras
linguagens entram só como arquivo + linguagem.

Consultas pequenas (é para isso que ele existe): `vizinhanca`, `testes_que_cobrem`, `quem_importa`.

Segurança: nada de `.env`, chaves, binários, `node_modules`, `.venv` ou caches — a lista de
diretórios é a mesma do workspace e os padrões de segredo são recusados por nome.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import time
from pathlib import Path

from pydantic import BaseModel, Field

from aso.execution.workspace import DIRETORIOS_IGNORADOS
from aso.shared.cache import TTLCache

VERSAO_DO_SCHEMA = 1
PASTA_DO_INDICE = ".aso/index"

LINGUAGEM_PYTHON = "python"
LINGUAGEM_TS = "typescript"
LINGUAGEM_JS = "javascript"

_EXTENSOES = {
    ".py": LINGUAGEM_PYTHON,
    ".pyi": LINGUAGEM_PYTHON,
    ".ts": LINGUAGEM_TS,
    ".tsx": LINGUAGEM_TS,
    ".js": LINGUAGEM_JS,
    ".jsx": LINGUAGEM_JS,
    ".mjs": LINGUAGEM_JS,
    ".cjs": LINGUAGEM_JS,
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".rb": "ruby",
    ".php": "php",
    ".cs": "csharp",
    ".kt": "kotlin",
    ".swift": "swift",
    ".sh": "shell",
    ".sql": "sql",
    ".md": "markdown",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".json": "json",
    ".toml": "toml",
    ".html": "html",
    ".css": "css",
}
# Só estas são analisadas de verdade; o resto entra como arquivo + linguagem.
_ANALISADAS = (LINGUAGEM_PYTHON, LINGUAGEM_TS, LINGUAGEM_JS)

# Arquivos que NUNCA entram no índice (§5 da MEL-44): segredo, credencial, binário.
_NOMES_DE_SEGREDO = re.compile(
    r"(^\.env($|\.)|(^|[._-])secret|(^|[._-])credential|^id_[rd]sa|\.(pem|key|p12|pfx|jks|keystore"
    r"|crt|cer|der)$|(^|[._-])senha|(^|[._-])password)",
    re.IGNORECASE,
)
_EXTENSOES_BINARIAS = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".bmp",
        ".ico",
        ".webp",
        ".svgz",
        ".pdf",
        ".zip",
        ".gz",
        ".bz2",
        ".xz",
        ".7z",
        ".tar",
        ".rar",
        ".jar",
        ".war",
        ".class",
        ".so",
        ".dylib",
        ".dll",
        ".exe",
        ".bin",
        ".o",
        ".a",
        ".pyc",
        ".pyd",
        ".wasm",
        ".woff",
        ".woff2",
        ".ttf",
        ".otf",
        ".eot",
        ".mp3",
        ".mp4",
        ".avi",
        ".mov",
        ".wav",
        ".ogg",
        ".webm",
        ".sqlite",
        ".db",
        ".pkl",
        ".parquet",
        ".npy",
        ".onnx",
        ".pt",
    }
)
_MAX_BYTES = 1_000_000  # arquivo maior que isso não é código que se lê: só conta no inventário

_TESTE_PY = re.compile(r"(^|/)(test_[^/]+|[^/]+_test)\.pyi?$")
_TESTE_JS = re.compile(r"(^|/)[^/]+\.(test|spec)\.(t|j)sx?$")
_PASTAS_DE_TESTE = ("tests/", "test/", "spec/", "__tests__/")

# TS/JS por regex (sem parser): conservador de propósito — ver `precisao` no índice.
_IMPORT_TS = re.compile(
    r"""(?:^|\n)\s*(?:import\b[^;\n]*?from\s*|import\s*|export\b[^;\n]*?from\s*)"""
    r"""['"]([^'"]+)['"]|require\(\s*['"]([^'"]+)['"]\s*\)""",
)
_SIMBOLO_TS = re.compile(
    r"""^\s*export\s+(?:default\s+)?(?:async\s+)?(class|function|const|let|var|interface|type|enum)"""
    r"""\s+([A-Za-z_$][\w$]*)""",
    re.MULTILINE,
)
_ROTA_TS = re.compile(
    r"""\b(?:app|router|server|api)\.(get|post|put|patch|delete|all)\(\s*['"`]([^'"`]+)['"`]""",
    re.IGNORECASE,
)
_METODOS_HTTP = frozenset({"get", "post", "put", "patch", "delete", "head", "options"})


class Simbolo(BaseModel):
    """Definição pública de um arquivo — o suficiente para localizar, não para reimplementar."""

    nome: str
    tipo: str  # classe | funcao | constante | tipo
    linha: int


class ArquivoIndexado(BaseModel):
    linguagem: str
    linhas: int = 0
    e_teste: bool = False
    simbolos: list[Simbolo] = Field(default_factory=list)
    # Caminhos do próprio repositório importados por este arquivo (imports externos ficam fora).
    importa: list[str] = Field(default_factory=list)
    # Rotas HTTP e comandos de CLI declarados aqui (ex.: "GET /v1/executors", "cli: aso run").
    entradas: list[str] = Field(default_factory=list)


class IndiceDoRepositorio(BaseModel):
    """Índice de um `(repositório, commit)`. Serializa para `.aso/index/<commit>.json`."""

    versao_do_schema: int = VERSAO_DO_SCHEMA
    commit: str
    sujo: bool = False  # árvore com mudanças não commitadas: índice válido, mas não reaproveitável
    gerado_em: str = ""
    duracao_ms: int = 0
    precisao: dict[str, str] = Field(default_factory=dict)
    modulos: list[str] = Field(default_factory=list)
    arquivos: dict[str, ArquivoIndexado] = Field(default_factory=dict)

    # ------------------------------------------------------------------ consultas
    def quem_importa(self, caminho: str) -> list[str]:
        """Arquivos que importam `caminho` (ou o módulo dele) — o raio da regressão."""
        alvo = caminho.strip().lstrip("./")
        return sorted(arquivo for arquivo, dados in self.arquivos.items() if alvo in dados.importa)

    def testes_que_cobrem(self, caminho: str) -> list[str]:
        """Testes que importam o arquivo, direta ou indiretamente (2 níveis).

        Diretos primeiro: quem chama corta a lista e o mais provável tem de vir na frente."""
        vizinhos = self.quem_importa(caminho)
        diretos = sorted(a for a in vizinhos if self._e_teste(a))
        indiretos = sorted(
            {
                teste
                for vizinho in vizinhos
                for teste in self.quem_importa(vizinho)
                if self._e_teste(teste)
            }
            - set(diretos)
        )
        return [*diretos, *indiretos]

    def vizinhanca(self, caminho: str) -> dict[str, list[str]]:
        """O que o arquivo usa, quem o usa e quais testes o cobrem."""
        dados = self.arquivos.get(caminho.strip().lstrip("./"))
        return {
            "importa": list(dados.importa) if dados else [],
            "importado_por": self.quem_importa(caminho),
            "testes": self.testes_que_cobrem(caminho),
        }

    def contem(self, caminho: str) -> bool:
        """`caminho` é arquivo indexado, diretório indexado ou módulo de topo?"""
        alvo = caminho.strip().strip("`'\"").removeprefix("./").rstrip("/")
        if not alvo:
            return False
        if alvo in self.arquivos or alvo in self.modulos:
            return True
        prefixo = f"{alvo}/"
        return any(arquivo.startswith(prefixo) for arquivo in self.arquivos)

    def _e_teste(self, caminho: str) -> bool:
        dados = self.arquivos.get(caminho)
        return bool(dados and dados.e_teste)

    def resumo(self) -> dict[str, object]:
        """Números para o ledger/ADR (o índice inteiro nunca entra no contexto)."""
        por_linguagem: dict[str, int] = {}
        for dados in self.arquivos.values():
            por_linguagem[dados.linguagem] = por_linguagem.get(dados.linguagem, 0) + 1
        return {
            "commit": self.commit,
            "arquivos": len(self.arquivos),
            "simbolos": sum(len(d.simbolos) for d in self.arquivos.values()),
            "testes": sum(1 for d in self.arquivos.values() if d.e_teste),
            "entradas": sum(len(d.entradas) for d in self.arquivos.values()),
            "modulos": list(self.modulos),
            "por_linguagem": por_linguagem,
            "duracao_ms": self.duracao_ms,
            "sujo": self.sujo,
        }


# ---------------------------------------------------------------------- coleta


def indexavel(relativo: str, tamanho: int) -> bool:
    """Regra única de elegibilidade (também é o que o teste de segurança exercita)."""
    partes = relativo.split("/")
    if any(parte in DIRETORIOS_IGNORADOS for parte in partes[:-1]):
        return False
    nome = partes[-1]
    if _NOMES_DE_SEGREDO.search(nome):
        return False
    if Path(nome).suffix.lower() in _EXTENSOES_BINARIAS:
        return False
    return tamanho <= _MAX_BYTES


def _linguagem(relativo: str) -> str:
    return _EXTENSOES.get(Path(relativo).suffix.lower(), "")


def _e_teste(relativo: str) -> bool:
    if _TESTE_PY.search(relativo) or _TESTE_JS.search(relativo):
        return True
    return any(pasta in f"/{relativo}" for pasta in (f"/{p}" for p in _PASTAS_DE_TESTE))


def _modulo_python(relativo: str) -> str:
    sem_ext = re.sub(r"\.pyi?$", "", relativo)
    if sem_ext.endswith("/__init__"):
        sem_ext = sem_ext[: -len("/__init__")]
    return sem_ext.replace("/", ".")


def _indice_de_modulos_python(caminhos: list[str]) -> dict[str, str]:
    """`aso.execution.catalog` → `src/aso/execution/catalog.py`, inclusive com raiz `src/`."""
    mapa: dict[str, str] = {}
    for relativo in caminhos:
        if _linguagem(relativo) != LINGUAGEM_PYTHON:
            continue
        pontilhado = _modulo_python(relativo)
        mapa.setdefault(pontilhado, relativo)
        partes = pontilhado.split(".")
        # Raízes de projeto comuns (`src.x` → `x`): o import do código não as inclui.
        for raiz in ("src", "lib", "app"):
            if partes and partes[0] == raiz:
                mapa.setdefault(".".join(partes[1:]), relativo)
    return mapa


def _simbolos_e_entradas_python(arvore: ast.Module) -> tuple[list[Simbolo], list[str]]:
    simbolos: list[Simbolo] = []
    entradas: list[str] = []

    def rota_do_decorador(no: ast.expr) -> str | None:
        if not isinstance(no, ast.Call) or not isinstance(no.func, ast.Attribute):
            return None
        metodo = no.func.attr.lower()
        if metodo not in _METODOS_HTTP or not no.args:
            return None
        primeiro = no.args[0]
        if isinstance(primeiro, ast.Constant) and isinstance(primeiro.value, str):
            return f"{metodo.upper()} {primeiro.value}"
        return None

    def visitar(corpo: list[ast.stmt], prefixo: str = "") -> None:
        for no in corpo:
            if isinstance(no, ast.ClassDef):
                if not no.name.startswith("_"):
                    simbolos.append(Simbolo(nome=prefixo + no.name, tipo="classe", linha=no.lineno))
                visitar(no.body, prefixo=f"{no.name}.")
            elif isinstance(no, ast.FunctionDef | ast.AsyncFunctionDef):
                if not no.name.startswith("_"):
                    simbolos.append(Simbolo(nome=prefixo + no.name, tipo="funcao", linha=no.lineno))
                for decorador in no.decorator_list:
                    rota = rota_do_decorador(decorador)
                    if rota:
                        entradas.append(rota)
            elif isinstance(no, ast.Assign) and not prefixo:
                for alvo in no.targets:
                    if isinstance(alvo, ast.Name) and alvo.id.isupper() and alvo.id[0] != "_":
                        simbolos.append(Simbolo(nome=alvo.id, tipo="constante", linha=no.lineno))
            elif isinstance(no, ast.If | ast.Try | ast.With):
                # Rotas declaradas dentro de fábricas (`def criar_router()`) e blocos de guarda.
                visitar(no.body, prefixo=prefixo)
        return None

    visitar(arvore.body)
    # Rotas em funções aninhadas (padrão `criar_router`): varredura completa da árvore.
    for no in ast.walk(arvore):
        if isinstance(no, ast.FunctionDef | ast.AsyncFunctionDef):
            for decorador in no.decorator_list:
                rota = rota_do_decorador(decorador)
                if rota and rota not in entradas:
                    entradas.append(rota)
    return simbolos, sorted(set(entradas))


def _imports_python(arvore: ast.Module, relativo: str, modulos: dict[str, str]) -> list[str]:
    alvos: set[str] = set()

    def registrar(nome: str) -> None:
        arquivo = modulos.get(nome)
        if arquivo and arquivo != relativo:
            alvos.add(arquivo)

    pacote = _modulo_python(relativo).rsplit(".", 1)[0]
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            for alias in no.names:
                registrar(alias.name)
        elif isinstance(no, ast.ImportFrom):
            base = no.module or ""
            if no.level:  # import relativo: resolve contra o pacote do próprio arquivo
                partes = pacote.split(".")
                raiz = ".".join(partes[: len(partes) - no.level + 1])
                base = f"{raiz}.{base}" if base else raiz
            registrar(base)
            for alias in no.names:
                registrar(f"{base}.{alias.name}" if base else alias.name)
    return sorted(alvos)


def _resolver_import_ts(origem: str, especificador: str, existentes: set[str]) -> str | None:
    """Só imports relativos: pacote de `node_modules` não é arquivo do repositório."""
    if not especificador.startswith("."):
        return None
    base = (Path(origem).parent / especificador).as_posix()
    base = Path(base).as_posix()
    partes: list[str] = []
    for parte in base.split("/"):
        if parte == "..":
            if partes:
                partes.pop()
        elif parte not in ("", "."):
            partes.append(parte)
    alvo = "/".join(partes)
    candidatos = [alvo, *(f"{alvo}{ext}" for ext in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"))]
    candidatos += [f"{alvo}/index{ext}" for ext in (".ts", ".tsx", ".js", ".jsx")]
    for candidato in candidatos:
        if candidato in existentes and candidato != origem:
            return candidato
    return None


def _analisar_ts(
    texto: str, relativo: str, existentes: set[str]
) -> tuple[list[Simbolo], list[str], list[str]]:
    simbolos = [
        Simbolo(
            nome=m.group(2),
            tipo={"class": "classe", "interface": "tipo", "type": "tipo", "enum": "tipo"}.get(
                m.group(1), "funcao" if m.group(1) == "function" else "constante"
            ),
            linha=texto.count("\n", 0, m.start()) + 1,
        )
        for m in _SIMBOLO_TS.finditer(texto)
    ]
    importa: set[str] = set()
    for m in _IMPORT_TS.finditer(texto):
        especificador = m.group(1) or m.group(2) or ""
        alvo = _resolver_import_ts(relativo, especificador, existentes)
        if alvo:
            importa.add(alvo)
    entradas = sorted({f"{m.group(1).upper()} {m.group(2)}" for m in _ROTA_TS.finditer(texto)})
    return simbolos, sorted(importa), entradas


def _ler(caminho: Path) -> str | None:
    try:
        return caminho.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def construir_indice(
    raiz: str | Path, *, commit: str = "", sujo: bool = False
) -> IndiceDoRepositorio:
    """Percorre o repositório e devolve o índice — função de leitura, não grava nada."""
    inicio = time.monotonic()
    base = Path(raiz)
    elegiveis: list[tuple[str, Path]] = []
    for arquivo in _arquivos(base):
        relativo = arquivo.relative_to(base).as_posix()
        try:
            tamanho = arquivo.stat().st_size
        except OSError:
            continue
        if indexavel(relativo, tamanho):
            elegiveis.append((relativo, arquivo))
    caminhos = [relativo for relativo, _ in elegiveis]
    existentes = set(caminhos)
    modulos_py = _indice_de_modulos_python(caminhos)

    arquivos: dict[str, ArquivoIndexado] = {}
    for relativo, caminho in elegiveis:
        linguagem = _linguagem(relativo)
        dados = ArquivoIndexado(linguagem=linguagem or "outro", e_teste=_e_teste(relativo))
        if linguagem in _ANALISADAS:
            texto = _ler(caminho)
            if texto is not None:
                dados.linhas = texto.count("\n") + 1 if texto else 0
                if linguagem == LINGUAGEM_PYTHON:
                    try:
                        arvore = ast.parse(texto)
                    except SyntaxError:
                        arvore = None
                    if arvore is not None:
                        dados.simbolos, dados.entradas = _simbolos_e_entradas_python(arvore)
                        dados.importa = _imports_python(arvore, relativo, modulos_py)
                else:
                    dados.simbolos, dados.importa, dados.entradas = _analisar_ts(
                        texto, relativo, existentes
                    )
        arquivos[relativo] = dados

    modulos = sorted(
        {
            relativo.split("/")[0]
            for relativo in caminhos
            if "/" in relativo and not relativo.startswith(".")
        }
    )
    return IndiceDoRepositorio(
        commit=commit,
        sujo=sujo,
        gerado_em=_agora(),
        duracao_ms=int((time.monotonic() - inicio) * 1000),
        precisao={
            LINGUAGEM_PYTHON: "ast (exato)",
            LINGUAGEM_TS: "regex (aproximado)",
            LINGUAGEM_JS: "regex (aproximado)",
        },
        modulos=modulos,
        arquivos=arquivos,
    )


def _arquivos(base: Path) -> list[Path]:
    """Enumeração determinística, sem seguir links e podando diretórios ignorados."""
    encontrados: list[Path] = []

    def caminhar(diretorio: Path) -> None:
        try:
            entradas = sorted(diretorio.iterdir(), key=lambda e: e.name)
        except (OSError, PermissionError):
            return
        for entrada in entradas:
            try:
                if entrada.is_symlink():
                    continue
                if entrada.is_dir():
                    if entrada.name in DIRETORIOS_IGNORADOS:
                        continue
                    caminhar(entrada)
                elif entrada.is_file():
                    encontrados.append(entrada)
            except OSError:
                continue

    caminhar(base)
    return encontrados


def _agora() -> str:
    from aso.shared.ids import now_iso

    return now_iso()


# ---------------------------------------------------------------------- cache por commit


def _git(base: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=str(base), capture_output=True, text=True, check=False
    )
    return proc.stdout.strip() if proc.returncode == 0 else ""


def estado_do_commit(raiz: str | Path) -> tuple[str, bool]:
    """`(sha, sujo)` do repositório; `("", True)` quando não há git ou commit.

    O que o próprio runtime escreve em `.aso/` (worktrees dos cards, este índice) não conta como
    sujeira: senão gravar o índice tornaria a árvore suja e o commit seguinte nunca reaproveitaria
    nada — o repositório-alvo pode não ter `.aso/` no `.gitignore`."""
    base = Path(raiz)
    sha = _git(base, "rev-parse", "HEAD")
    if not sha:
        return "", True
    mudancas = [
        linha
        for linha in _git(base, "status", "--porcelain").splitlines()
        if linha.strip() and not linha[3:].strip().strip('"').startswith(".aso/")
    ]
    return sha, bool(mudancas)


def caminho_do_indice(raiz: str | Path, commit: str) -> Path:
    return Path(raiz) / PASTA_DO_INDICE / f"{commit or 'sem-commit'}.json"


def indice_do_repositorio(
    raiz: str | Path, *, forcar: bool = False
) -> tuple[IndiceDoRepositorio, bool]:
    """Índice do commit atual, reaproveitando o arquivo quando ele serve.

    Devolve `(índice, reaproveitado)`. Árvore suja (`sujo=True`) nunca é reaproveitada nem
    gravada: o índice descreveria um estado que não corresponde a commit nenhum."""
    base = Path(raiz)
    commit, sujo = estado_do_commit(base)
    destino = caminho_do_indice(base, commit)
    if not (forcar or sujo) and destino.is_file():
        try:
            salvo = IndiceDoRepositorio.model_validate_json(destino.read_text(encoding="utf-8"))
            if salvo.versao_do_schema == VERSAO_DO_SCHEMA and salvo.commit == commit:
                return salvo, True
        except (OSError, ValueError):
            pass  # índice corrompido ou de outro schema: recalcula e sobrescreve
    indice = construir_indice(base, commit=commit, sujo=sujo)
    if not sujo and commit:
        try:
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text(
                json.dumps(indice.model_dump(mode="json"), ensure_ascii=False), encoding="utf-8"
            )
        except OSError:
            pass  # repositório somente leitura: o índice ainda serve nesta execução
    return indice, False


# Reaproveitamento no processo: árvore suja não tem arquivo em `.aso/index`, e reconstruir a
# cada card custaria ~1 s por orquestração. TTL curto para o índice não descrever um passado
# distante enquanto o agente edita o worktree.
_TTL_DO_INDICE_S = 60.0
_EM_MEMORIA = TTLCache(ttl_seconds=_TTL_DO_INDICE_S)


def indice_para_uso(raiz: str | Path) -> IndiceDoRepositorio | None:
    """Índice pronto para orientar/verificar uma pergunta; `None` se a pasta não serve.

    Erra para o lado de não atrapalhar: pasta inexistente, sem permissão ou sem arquivo algum
    devolve `None` e quem chama segue sem os fatos estruturais."""
    base = Path(raiz)
    if not base.is_dir():
        return None
    commit, sujo = estado_do_commit(base)
    chave = f"{base.resolve()}|{commit}|{int(sujo)}"
    guardado = _EM_MEMORIA.get(chave)
    if isinstance(guardado, IndiceDoRepositorio):
        return guardado
    try:
        indice, _ = indice_do_repositorio(base)
    except OSError:
        return None
    if not indice.arquivos:
        return None
    _EM_MEMORIA.set(chave, indice)
    return indice


def limpar_cache_em_memoria() -> None:
    """Usado por testes que mexem no repositório entre duas leituras."""
    _EM_MEMORIA.clear()


def arquivos_do_diff(diff: str) -> list[str]:
    """Caminhos tocados por um diff unificado (`diff --git a/x b/y`), sem duplicar."""
    encontrados: list[str] = []
    for linha in diff.splitlines():
        if not linha.startswith("diff --git "):
            continue
        partes = linha.split(" b/", 1)
        if len(partes) != 2:
            continue
        caminho = partes[1].strip()
        if caminho and caminho not in encontrados:
            encontrados.append(caminho)
    return encontrados
