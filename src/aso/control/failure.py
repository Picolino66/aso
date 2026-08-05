"""Roteamento de falha (§13 do fluxo.md, Princípio central) — ADR-0019.

O `fluxo.md` fecha com a regra que faltava no runtime: nenhuma falha encerra
silenciosamente a execução — a esteira identifica o ponto de interrupção, registra a
causa, decide um novo agente/effort/executor (ou escala para humano) e retorna
**exatamente** ao ponto responsável pelo erro.

Tudo aqui é **puro e determinístico** (mesmo princípio de
`next_step.py`/`branch_naming.py`): dado o mesmo `FailureRecord` e o mesmo estado de
catálogo, a decisão é sempre a mesma. Nenhum LLM decide o roteamento — decisão de
governança é regra, não palpite. Quem tem I/O (persistir o ring de falhas, mover o
card, reexecutar) é `OrchestrationService`, o único lugar em `control/` autorizado a
importar isto **e** `agents/` (regra de módulo: `agents` só importa `shared` e
`governance` — o `AgentSupervisor` nunca vê esta política).
"""

from __future__ import annotations

import os

from pydantic import BaseModel, Field

from aso.execution.catalog import ExecutorCatalog
from aso.shared.ids import now_iso

# ------------------------------------------------------------------------- etapas

ETAPA_EXECUCAO = "execucao"
ETAPA_GATE = "gate"
ETAPA_CI = "ci"
ETAPA_REVIEW = "review"
ETAPA_QA = "qa"

# ------------------------------------------------------------------------ diagnóstico

DIAG_SEM_PERMISSAO = "sem_permissao"
DIAG_TIMEOUT = "timeout"
DIAG_TESTE_FALHOU = "teste_falhou"
DIAG_DIFF_VAZIO = "diff_vazio"
DIAG_AGENTE_INDISPONIVEL = "agente_indisponivel"
DIAG_DESCONHECIDO = "desconhecido"
# Verificação nomeada da bateria (§12, ADR-0022): falha trivial (formatação/lint)
# não merece um modelo maior — merece a própria saída do lint no prompt.
DIAG_FALHA_TRIVIAL = "falha_trivial"
# Categoria de risco (segurança/dependências): escala para humano mais cedo em vez
# de gastar tentativas automáticas numa causa que provavelmente exige julgamento.
DIAG_RISCO_ALTO = "risco_alto"
# QA manual reprovou (§16/§17, ADR-0025) — não é a mesma coisa que teste automatizado
# falhar: a política é mais paciente (o agente tenta de novo, sobe esforço) antes de
# escalar, porque nem toda reprovação de QA é regressão de código, pode ser ajuste fino.
DIAG_FALHA_DE_QA = "falha_de_qa"

# Marca do erro que o `CliAgentExecutionProvider` registra quando o agente roda sem
# permissão de escrita (worktree intacto) — fonte única de verdade: `next_step.py`
# importa esta constante em vez de duplicá-la (achado da ADR-0019).
MARCA_DIFF_VAZIO = "diff vazio"

# Palavras que aparecem na fala do agente/erro quando a causa real é permissão de
# escrita do CLI (`claude -p` sem `--permission-mode`, `codex exec` em sandbox
# read-only — ver `execution/cli_provider.py` e `execution/catalog.py`).
_PALAVRAS_SEM_PERMISSAO = (
    "permiss",
    "sandbox",
    "read-only",
    "somente leitura",
    "acceptedits",
    "dangerously-skip-permissions",
    "workspace-write",
)
_PALAVRAS_TIMEOUT = ("timeoutexpired", "tempo limite", "não terminou em")
_PALAVRAS_AGENTE_INDISPONIVEL = (
    "indisponível",
    "indisponivel",
    "executor desconhecido",
    "não configurado",
    "nao configurado",
)
_PALAVRAS_TESTE_FALHOU = (
    "assertionerror",
    "failed",
    "traceback",
    "exit=1",
    "exit=2",
    "erro:",
    "error:",
)

# Categoria da verificação (§12, ADR-0022) -> diagnóstico direto. Com a bateria
# nomeada, a causa deixa de ser adivinhada por palavra-chave e vira fato: o gate
# sabe que falhou "mypy" (categoria "tipos"), não que "a saída continha 'error'".
_CATEGORIA_DIAGNOSTICO: dict[str, str] = {
    "formatacao": DIAG_FALHA_TRIVIAL,
    "lint": DIAG_FALHA_TRIVIAL,
    "compilacao": DIAG_TESTE_FALHOU,
    "tipos": DIAG_TESTE_FALHOU,
    "testes": DIAG_TESTE_FALHOU,
    "integracao": DIAG_TESTE_FALHOU,
    "contrato": DIAG_TESTE_FALHOU,
    "e2e": DIAG_TESTE_FALHOU,
    "estatica": DIAG_TESTE_FALHOU,
    "migrations": DIAG_TESTE_FALHOU,
    "cobertura": DIAG_TESTE_FALHOU,
    "desempenho": DIAG_TESTE_FALHOU,
    "seguranca": DIAG_RISCO_ALTO,
    "dependencias": DIAG_RISCO_ALTO,
    # QA manual (§16/§17, ADR-0025) não vem da bateria nomeada (ADR-0022), mas
    # reaproveita o mesmo atalho por categoria em vez de uma heurística por palavra.
    "qa": DIAG_FALHA_DE_QA,
}


class FailureRecord(BaseModel):
    """O que o §13 manda registrar quando algo falha — um item do ring `card.failures`."""

    etapa: str = ETAPA_EXECUCAO
    tentativa: int = 1
    comando: str = ""
    mensagem: str = ""
    saida: str = ""  # cauda ampliada de stdout+stderr (ou o texto disponível)
    arquivos: list[str] = Field(default_factory=list)
    executor: str = ""
    effort: str = ""
    # Nome/categoria da verificação da bateria que falhou (§12, ADR-0022) — vazio
    # quando a falha não veio do gate nomeado (ex.: falha de execução do agente).
    check: str = ""
    categoria: str = ""
    at: str = Field(default_factory=now_iso)


def registrar(
    falhas: list[dict[str, object]], record: FailureRecord, *, limite: int = 5
) -> list[dict[str, object]]:
    """Acrescenta `record` ao ring, descartando o mais antigo além de `limite`."""
    novo = [*falhas, record.model_dump(mode="json")]
    return novo[-limite:]


def diagnosticar(record: FailureRecord) -> str:
    """Classifica a falha, preferindo o fato à heurística (§4.3, ADR-0022).

    Com `categoria` preenchida (a falha veio de uma verificação nomeada da
    bateria, §12), o diagnóstico é direto — fato, não palpite. Só cai na
    heurística por palavras-chave (§4.3 do plano4 — frágil e fora de escopo trocar
    por regex por linguagem) quando não há categoria, o que preserva o
    comportamento de toda orquestração que nunca configurou a bateria nomeada.
    """
    if record.categoria:
        diagnostico_direto = _CATEGORIA_DIAGNOSTICO.get(record.categoria)
        if diagnostico_direto is not None:
            return diagnostico_direto
    texto = f"{record.mensagem} {record.saida}".lower()
    if any(p in texto for p in _PALAVRAS_TIMEOUT):
        return DIAG_TIMEOUT
    if MARCA_DIFF_VAZIO in texto:
        if any(p in texto for p in _PALAVRAS_SEM_PERMISSAO):
            return DIAG_SEM_PERMISSAO
        return DIAG_DIFF_VAZIO
    if any(p in texto for p in _PALAVRAS_AGENTE_INDISPONIVEL):
        return DIAG_AGENTE_INDISPONIVEL
    if any(p in texto for p in _PALAVRAS_TESTE_FALHOU):
        return DIAG_TESTE_FALHOU
    return DIAG_DESCONHECIDO


# --------------------------------------------------------------------------- decisão

ACAO_MESMO_AGENTE = "mesmo_agente"
ACAO_AUMENTAR_EFFORT = "aumentar_effort"
ACAO_TROCAR_EXECUTOR = "trocar_executor"
ACAO_ESCALAR_HUMANO = "escalar_humano"
ACAO_BLOQUEAR = "bloquear"

# Sobe um degrau de esforço por padrão (perfis Codex gerenciados podem ter uma lista
# própria em `supported_efforts` — ver `execution/catalog.py`).
_EFFORTS = ("low", "medium", "high")

# Rede de segurança: nunca deixe o roteamento escalar sozinho para sempre.
_MAX_ESCALONAMENTOS_PADRAO = int(os.environ.get("ASO_MAX_ESCALONAMENTOS", "3"))

# Tabela de política (§4.1 da ADR-0019): diagnóstico -> passos, na ordem em que se
# aplicam a cada nova falha (1ª, 2ª, 3ª...). `sem_permissao` nunca re-tenta — é a
# única causa fora do alcance do agente.
_TABELA: dict[str, tuple[str, ...]] = {
    DIAG_SEM_PERMISSAO: (ACAO_BLOQUEAR,),
    DIAG_TIMEOUT: (ACAO_AUMENTAR_EFFORT, ACAO_TROCAR_EXECUTOR, ACAO_ESCALAR_HUMANO),
    DIAG_TESTE_FALHOU: (
        ACAO_MESMO_AGENTE,
        ACAO_AUMENTAR_EFFORT,
        ACAO_TROCAR_EXECUTOR,
        ACAO_ESCALAR_HUMANO,
    ),
    DIAG_DIFF_VAZIO: (ACAO_MESMO_AGENTE, ACAO_TROCAR_EXECUTOR, ACAO_ESCALAR_HUMANO),
    DIAG_AGENTE_INDISPONIVEL: (ACAO_TROCAR_EXECUTOR, ACAO_ESCALAR_HUMANO),
    DIAG_DESCONHECIDO: (ACAO_MESMO_AGENTE, ACAO_ESCALAR_HUMANO),
    # Falha trivial (formatação/lint, §4.3 do plano5.md): nunca sobe effort — o
    # mesmo agente com a saída do lint no prompt resolve; escala só se insistir.
    DIAG_FALHA_TRIVIAL: (ACAO_MESMO_AGENTE, ACAO_MESMO_AGENTE, ACAO_ESCALAR_HUMANO),
    # Categoria de risco (segurança/dependências): escala já na primeira falha —
    # não gasta tentativa automática numa causa que pede julgamento humano.
    DIAG_RISCO_ALTO: (ACAO_ESCALAR_HUMANO,),
    # QA reprovado (§17, plano6 §3.2): mais paciente que um teste automatizado —
    # o mesmo agente corrige, sobe esforço, só então escala.
    DIAG_FALHA_DE_QA: (ACAO_MESMO_AGENTE, ACAO_AUMENTAR_EFFORT, ACAO_ESCALAR_HUMANO),
}

_MOTIVOS: dict[str, str] = {
    ACAO_MESMO_AGENTE: "repete o mesmo agente com o erro no nudge",
    ACAO_AUMENTAR_EFFORT: "sobe o nível de esforço do mesmo executor",
    ACAO_TROCAR_EXECUTOR: "troca para outro executor disponível",
    ACAO_ESCALAR_HUMANO: "esgotou as tentativas automáticas — decisão humana necessária",
    ACAO_BLOQUEAR: "causa fora do alcance do agente — ajuste o perfil do executor",
}

_NUDGES: dict[str, str] = {
    DIAG_TESTE_FALHOU: (
        "A tentativa anterior falhou nos testes/validação — leia a saída e corrija "
        "especificamente o que quebrou, sem tocar no resto."
    ),
    DIAG_FALHA_TRIVIAL: (
        "A verificação de formatação/lint reprovou — aplique exatamente o que a "
        "saída pede, sem mudar lógica."
    ),
    DIAG_RISCO_ALTO: (
        "A verificação de segurança/dependências reprovou — decisão humana antes de tentar de novo."
    ),
    DIAG_FALHA_DE_QA: (
        "A verificação manual de QA reprovou — leia o cenário, os passos e o resultado "
        "obtido vs. esperado, e corrija especificamente o que foi observado."
    ),
    DIAG_DIFF_VAZIO: (
        "A tentativa anterior não alterou nenhum arquivo — escreva o código necessário "
        "e garanta que as mudanças fiquem no worktree."
    ),
    DIAG_AGENTE_INDISPONIVEL: (
        "O executor anterior estava indisponível — esta tentativa usa outro perfil."
    ),
    DIAG_TIMEOUT: "A tentativa anterior estourou o tempo limite — tente uma abordagem mais direta.",
    DIAG_DESCONHECIDO: (
        "A tentativa anterior falhou por um motivo não identificado — revise a tarefa."
    ),
}


class DecisaoDeFalha(BaseModel):
    """O que fazer a seguir — traduzida em `card.block_reason`/evento/nudge."""

    acao: str
    motivo: str
    executor: str | None = None  # preenchido em trocar_executor
    effort: str | None = None  # preenchido em aumentar_effort
    nudge: str = ""
    proxima_etapa: str = ETAPA_EXECUCAO


def proximo_effort(atual: str, suportados: list[str]) -> str | None:
    """Sobe um degrau em `_EFFORTS` respeitando `supported_efforts` do perfil.

    Devolve `None` quando já está no topo — a política cai para o próximo degrau da
    tabela (troca de executor).
    """
    ordem = [e for e in _EFFORTS if e in suportados] or list(suportados)
    if not ordem:
        return None
    if atual not in ordem:
        return ordem[0]
    idx = ordem.index(atual)
    return ordem[idx + 1] if idx + 1 < len(ordem) else None


def proximo_executor(atual: str, catalogo: ExecutorCatalog) -> str | None:
    """Outro perfil **disponível** e de mesmo `kind`, diferente do atual.

    Respeita `profile.available` — o catálogo já recusa executor indisponível antes de
    criar worktree, e trocar para um perfil quebrado seria um passo para trás.
    """
    atual_profile = catalogo.get(atual) if atual else None
    kind = atual_profile.kind if atual_profile is not None else None
    for profile in catalogo.profiles():
        if profile.name == atual or not profile.available:
            continue
        if kind is not None and profile.kind != kind:
            continue
        return profile.name
    return None


def decidir(
    diagnostico: str,
    tentativa: int,
    *,
    executor_atual: str = "",
    effort_atual: str = "",
    catalogo: ExecutorCatalog | None = None,
    max_escalonamentos: int | None = None,
) -> DecisaoDeFalha:
    """Decide o próximo passo a partir do diagnóstico e de quantas vezes já falhou.

    `tentativa` é `len(card.failures)` **depois** de registrar a falha atual — o
    contador persiste no card, então o limite sobrevive a um restart da API.
    """
    limite = max_escalonamentos if max_escalonamentos is not None else _MAX_ESCALONAMENTOS_PADRAO
    if tentativa > limite:
        return DecisaoDeFalha(
            acao=ACAO_ESCALAR_HUMANO,
            motivo=f"limite de {limite} tentativa(s) automática(s) esgotado",
        )
    passos = _TABELA.get(diagnostico, (ACAO_ESCALAR_HUMANO,))
    idx = min(tentativa - 1, len(passos) - 1)
    nudge = _NUDGES.get(diagnostico, "")
    while idx < len(passos):
        acao = passos[idx]
        if acao == ACAO_AUMENTAR_EFFORT:
            perfil = catalogo.get(executor_atual) if catalogo else None
            suportados = list(perfil.supported_efforts or _EFFORTS) if perfil else list(_EFFORTS)
            novo_effort = proximo_effort(effort_atual, suportados)
            if novo_effort is None:
                idx += 1
                continue
            return DecisaoDeFalha(acao=acao, motivo=_MOTIVOS[acao], effort=novo_effort, nudge=nudge)
        if acao == ACAO_TROCAR_EXECUTOR:
            if catalogo is None:
                idx += 1
                continue
            novo_executor = proximo_executor(executor_atual, catalogo)
            if novo_executor is None:
                idx += 1
                continue
            return DecisaoDeFalha(
                acao=acao, motivo=_MOTIVOS[acao], executor=novo_executor, nudge=nudge
            )
        # mesmo_agente / bloquear / escalar_humano não dependem de recursos externos.
        acao_nudge = nudge if acao == ACAO_MESMO_AGENTE else ""
        return DecisaoDeFalha(acao=acao, motivo=_MOTIVOS[acao], nudge=acao_nudge)
    return DecisaoDeFalha(
        acao=ACAO_ESCALAR_HUMANO, motivo="nenhuma alternativa disponível na política"
    )
