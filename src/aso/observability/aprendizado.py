"""Aprendizado da esteira (§24 do fluxo.md) — ADR-0025.

Puro: recebe dados já coletados e produz um relatório agregado. Não importa
`control` (regra de módulo: `observability` importa só `shared`) — quem coleta
o estado e monta a entrada é `OrchestrationService.get_learning_report`, no
mesmo arranjo de `next_step.py` (função pura) + `Service.next_step` (coleta),
e de `agent_log` (ADR-0015).

Até este incremento, `metrics.py`/`slo_report` eram só observacionais: nada
agregava por executor e nada realimentava decisão. Agora há insumo de verdade
— `card.failures` com categoria (ADR-0022), `card.executor` (ADR-0017),
rodadas de revisão (ADR-0017) — o que faltava quando o §24 foi adiado nos
planos anteriores.

**Limite deliberado**: o relatório NÃO realimenta decisão automaticamente. O
§24 diz que as informações "podem ser utilizadas" para melhorar decisões
futuras — permissivo, não imperativo. Fechar o laço agora significaria um
runtime que muda de perfil de executor sozinho com base em amostra pequena e
enviesada (as falhas observadas dependem só das demandas que apareceram).
`recomendacao` é texto para o operador ler, nunca um campo que outro código
consome para decidir.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CardSnapshot:
    """O que o agregador precisa de cada card — já achatado pelo coletor, para
    este módulo não depender do tipo `KanbanCard` de `kanban/` nem de `control`."""

    id: str
    executor: str
    failures: list[dict[str, Any]] = field(default_factory=list)
    tempo_ms: float = 0.0
    # Consumo real (§1.1, ADR-0026) — `custo_usd` acumulado do card e se ele
    # informou uso em toda execução (`indisponivel` se nenhuma informou).
    custo_usd: float = 0.0
    uso_indisponivel: bool = True
    entregue: bool = False  # chegou a Done — denominador de `custo_por_entrega`
    # Agente responsável (papel/role, `card.assignee`) — distinto de `executor`
    # (modelo, `card.executor`): "falhas por agente" (Tela 29, wf §31.1, item 8)
    # é um agrupamento diferente de "falhas por modelo" (item 7).
    agente: str = ""


@dataclass(frozen=True)
class PullRequestSnapshot:
    card_id: str | None
    review_rounds: int
    review_status: str


@dataclass(frozen=True)
class DesempenhoPorExecutor:
    """Uma linha do §24: "quais modelos tiveram melhor desempenho"."""

    executor: str
    execucoes: int
    falhas: int
    retrabalho: int  # nº de reexecuções (uma por falha registrada)
    tempo_medio_ms: float
    rodadas_de_revisao_media: float
    erros_recorrentes: dict[str, int]  # categoria -> contagem
    # Custo real (§1.1/§1.3, ADR-0026) — nunca compare custo bruto entre executores
    # sem dividir por entrega: um executor caro que acerta de primeira pode sair
    # mais barato que um barato que precisa de três tentativas.
    custo_total_usd: float = 0.0
    custo_por_entrega: float = 0.0  # custo_total_usd / cards que chegaram a Done
    execucoes_sem_custo: int = 0  # quantas não informaram uso (não somadas como zero)


@dataclass(frozen=True)
class RelatorioDeAprendizado:
    orchestration_id: str
    total_cards: int
    total_falhas: int
    total_retrabalho: int
    intervencoes_humanas: int
    falhas_por_etapa: dict[str, int]
    erros_recorrentes: dict[str, int]
    desempenho_por_executor: list[DesempenhoPorExecutor]
    recomendacao: str = ""
    # Indicadores adicionais da Tela 29 (wf §31.1, ADR-0052) — os 3 abaixo são
    # `None` sem denominador (nenhuma decisão de aprovação/nenhum deploy/nenhum
    # card executado ainda), nunca 0 fabricado por omissão, mesma disciplina de
    # `custo_por_entrega` acima.
    taxa_aprovacao: float | None = None
    taxa_rollback: float | None = None
    taxa_sucesso_primeiro_ciclo: float | None = None
    tempo_medio_por_etapa_ms: dict[str, float] = field(default_factory=dict)
    # Média por DEMANDA (orquestração), não por card — `None` sem nenhuma
    # orquestração no recorte. "Falhas por agente" usa `CardSnapshot.agente`
    # (papel), distinto de `desempenho_por_executor` (agrupado por modelo).
    tempo_medio_por_demanda_ms: float | None = None
    custo_medio_por_demanda_usd: float | None = None
    numero_medio_tentativas: float | None = None
    falhas_por_agente: dict[str, int] = field(default_factory=dict)
    # "Cobertura de testes" (wf §31.1, item 14) não tem fonte real no runtime
    # hoje — nenhum número de cobertura chega ao domínio, só a categoria de
    # falha "testes" (correlação fraca, não a métrica literal). SEMPRE `None`
    # — nunca calculado, documentado aqui em vez de aproximado por um proxy
    # que mentiria sobre o que está sendo medido.
    cobertura_de_testes: float | None = None


def consolidar(
    orchestration_id: str,
    cards: list[CardSnapshot],
    pulls: list[PullRequestSnapshot],
    *,
    intervencoes_humanas: int = 0,
    aprovados: int = 0,
    decisoes_de_aprovacao: int = 0,
    rollbacks: int = 0,
    deploys: int = 0,
    sucesso_primeiro_ciclo: int = 0,
    cards_com_tentativa: int = 0,
    tempo_por_etapa_ms: dict[str, list[float]] | None = None,
    total_orchestrations: int = 1,
    soma_tentativas: int = 0,
) -> RelatorioDeAprendizado:
    """Agrega por executor: execuções, falhas, retrabalho, tempo, rodadas,
    erros recorrentes. Sem cards, devolve um relatório vazio — sem divisão
    por zero em lugar nenhum.

    Os parâmetros a partir de `aprovados` (Tela 29, wf §31.1, ADR-0052) são
    CONTAGENS BRUTAS, não taxas já calculadas — o coletor (`control`) só soma
    fatos através de várias orquestrações quando o recorte é global; a
    divisão final acontece aqui, num único lugar, mesma disciplina de
    `custo_por_entrega`.
    """
    tempo_por_etapa_ms = tempo_por_etapa_ms or {}
    tempo_medio_por_etapa = {
        etapa: round(sum(valores) / len(valores), 2)
        for etapa, valores in tempo_por_etapa_ms.items()
        if valores
    }
    taxa_aprovacao = aprovados / decisoes_de_aprovacao if decisoes_de_aprovacao else None
    taxa_rollback = rollbacks / deploys if deploys else None
    taxa_sucesso_primeiro_ciclo = (
        sucesso_primeiro_ciclo / cards_com_tentativa if cards_com_tentativa else None
    )
    numero_medio_tentativas = soma_tentativas / cards_com_tentativa if cards_com_tentativa else None
    if not cards:
        return RelatorioDeAprendizado(
            orchestration_id=orchestration_id,
            total_cards=0,
            total_falhas=0,
            total_retrabalho=0,
            intervencoes_humanas=intervencoes_humanas,
            falhas_por_etapa={},
            erros_recorrentes={},
            desempenho_por_executor=[],
            taxa_aprovacao=taxa_aprovacao,
            taxa_rollback=taxa_rollback,
            taxa_sucesso_primeiro_ciclo=taxa_sucesso_primeiro_ciclo,
            tempo_medio_por_etapa_ms=tempo_medio_por_etapa,
            numero_medio_tentativas=numero_medio_tentativas,
            tempo_medio_por_demanda_ms=0.0 if total_orchestrations else None,
            custo_medio_por_demanda_usd=0.0 if total_orchestrations else None,
        )
    por_executor: dict[str, list[CardSnapshot]] = {}
    for card in cards:
        chave = card.executor or "(sem executor)"
        por_executor.setdefault(chave, []).append(card)
    rounds_por_card = {p.card_id: p.review_rounds for p in pulls if p.card_id}

    desempenho: list[DesempenhoPorExecutor] = []
    erros_totais: dict[str, int] = {}
    falhas_por_etapa: dict[str, int] = {}
    falhas_por_agente: dict[str, int] = {}
    total_falhas = 0
    for executor, seus_cards in sorted(por_executor.items()):
        falhas = sum(len(c.failures) for c in seus_cards)
        rounds = [rounds_por_card.get(c.id, 0) for c in seus_cards]
        tempos = [c.tempo_ms for c in seus_cards if c.tempo_ms]
        erros: dict[str, int] = {}
        for card in seus_cards:
            agente = card.agente or "(sem agente)"
            for falha in card.failures:
                categoria = str(falha.get("categoria") or "desconhecida")
                etapa = str(falha.get("etapa") or "desconhecida")
                erros[categoria] = erros.get(categoria, 0) + 1
                erros_totais[categoria] = erros_totais.get(categoria, 0) + 1
                falhas_por_etapa[etapa] = falhas_por_etapa.get(etapa, 0) + 1
                falhas_por_agente[agente] = falhas_por_agente.get(agente, 0) + 1
        custo_total = round(sum(c.custo_usd for c in seus_cards), 6)
        entregas = sum(1 for c in seus_cards if c.entregue)
        desempenho.append(
            DesempenhoPorExecutor(
                executor=executor,
                execucoes=len(seus_cards),
                falhas=falhas,
                retrabalho=falhas,
                tempo_medio_ms=round(sum(tempos) / len(tempos), 2) if tempos else 0.0,
                rodadas_de_revisao_media=round(sum(rounds) / len(rounds), 2) if rounds else 0.0,
                erros_recorrentes=erros,
                custo_total_usd=custo_total,
                custo_por_entrega=round(custo_total / entregas, 6) if entregas else 0.0,
                execucoes_sem_custo=sum(1 for c in seus_cards if c.uso_indisponivel),
            )
        )
        total_falhas += falhas

    tempo_total_ms = sum(c.tempo_ms for c in cards)
    custo_total_geral = sum(c.custo_usd for c in cards)
    return RelatorioDeAprendizado(
        orchestration_id=orchestration_id,
        total_cards=len(cards),
        total_falhas=total_falhas,
        total_retrabalho=total_falhas,
        intervencoes_humanas=intervencoes_humanas,
        falhas_por_etapa=falhas_por_etapa,
        erros_recorrentes=erros_totais,
        desempenho_por_executor=desempenho,
        recomendacao=_recomendar(desempenho),
        taxa_aprovacao=taxa_aprovacao,
        taxa_rollback=taxa_rollback,
        taxa_sucesso_primeiro_ciclo=taxa_sucesso_primeiro_ciclo,
        tempo_medio_por_etapa_ms=tempo_medio_por_etapa,
        numero_medio_tentativas=numero_medio_tentativas,
        falhas_por_agente=falhas_por_agente,
        tempo_medio_por_demanda_ms=(
            round(tempo_total_ms / total_orchestrations, 2) if total_orchestrations else None
        ),
        custo_medio_por_demanda_usd=(
            round(custo_total_geral / total_orchestrations, 6) if total_orchestrations else None
        ),
    )


def _recomendar(desempenho: list[DesempenhoPorExecutor]) -> str:
    """Texto informativo para o operador — nunca uma decisão automática (§24)."""
    com_execucao = [d for d in desempenho if d.execucoes]
    if not com_execucao:
        return ""
    pior = max(com_execucao, key=lambda d: d.falhas / d.execucoes)
    if pior.falhas == 0:
        return "Nenhuma falha registrada nesta amostra — sem padrão a apontar ainda."
    return (
        f"'{pior.executor}' teve {pior.falhas} falha(s) em {pior.execucoes} execução(ões) "
        "— considere revisar o perfil/effort antes da próxima demanda semelhante. "
        "Recomendação informativa: a escolha de executor continua manual (§9)."
    )


# ------------------------------------------ recomendações estruturadas (wf §31.3, ADR-0052)

RECOMENDACAO_AUMENTAR_EFFORT = "aumentar_effort"
RECOMENDACAO_EVITAR_MODELO = "evitar_modelo"
RECOMENDACAO_CRIAR_AGENTE = "criar_agente_especializado"
RECOMENDACAO_ADICIONAR_TESTE = "adicionar_teste_automatico"
RECOMENDACAO_MODIFICAR_APROVACAO = "modificar_criterios_aprovacao"
RECOMENDACAO_ALTERAR_LIMITE_TENTATIVAS = "alterar_limite_tentativas"
RECOMENDACAO_CRIAR_TEMPLATE = "criar_template_de_card"
RECOMENDACAO_AJUSTAR_ROTEAMENTO = "ajustar_regras_de_roteamento"

_ROTULOS_RECOMENDACAO: dict[str, str] = {
    RECOMENDACAO_AUMENTAR_EFFORT: "Aumentar effort para determinada categoria",
    RECOMENDACAO_EVITAR_MODELO: "Evitar modelo em tarefa específica",
    RECOMENDACAO_CRIAR_AGENTE: "Criar novo agente especializado",
    RECOMENDACAO_ADICIONAR_TESTE: "Adicionar teste automático",
    RECOMENDACAO_MODIFICAR_APROVACAO: "Modificar critérios de aprovação",
    RECOMENDACAO_ALTERAR_LIMITE_TENTATIVAS: "Alterar limite de tentativas",
    RECOMENDACAO_CRIAR_TEMPLATE: "Criar template de card",
    RECOMENDACAO_AJUSTAR_ROTEAMENTO: "Ajustar regras de roteamento",
}

# Ordem fixa do wf §31.3.
_TODAS_RECOMENDACOES: tuple[str, ...] = (
    RECOMENDACAO_AUMENTAR_EFFORT,
    RECOMENDACAO_EVITAR_MODELO,
    RECOMENDACAO_CRIAR_AGENTE,
    RECOMENDACAO_ADICIONAR_TESTE,
    RECOMENDACAO_MODIFICAR_APROVACAO,
    RECOMENDACAO_ALTERAR_LIMITE_TENTATIVAS,
    RECOMENDACAO_CRIAR_TEMPLATE,
    RECOMENDACAO_AJUSTAR_ROTEAMENTO,
)

# 2 das 8 (wf §31.3) exigem julgamento de produto que o relatório não sustenta
# com confiança: "criar agente especializado" (quando um domínio inteiro vai
# mal, criar um agente novo é só uma entre várias respostas possíveis — o
# dado não distingue "falta agente" de "falta contexto"/"tarefa mal
# decomposta") e "criar template de card" (nenhum sinal de recorrência
# estrutural de card existe no runtime hoje). Ficam desabilitadas, mesmo
# padrão de "criar investigação separada" desabilitada no FID-21/ADR-0048.
_RECOMENDACOES_DESABILITADAS: frozenset[str] = frozenset(
    {RECOMENDACAO_CRIAR_AGENTE, RECOMENDACAO_CRIAR_TEMPLATE}
)

# Categorias de falha (`FailureRecord.categoria`, `control/validation.py`) que
# indicam lacuna de teste automatizado — "testes" é a categoria real da
# bateria (ADR-0022); "qa" é a categoria do §16/§17 (ADR-0025).
_CATEGORIAS_DE_TESTE: frozenset[str] = frozenset({"testes", "qa"})

# Limiares fixos e documentados — regra determinística, não inferência de LLM
# (mesma disciplina de `checklist_aprovacao_implantacao`/`saude_pos_deploy`,
# ADR-0050): "recorrente" = pelo menos 2 ocorrências da mesma categoria;
# "modelo a evitar" = pelo menos metade das execuções falharam; "aprovação
# desalinhada"/"retrabalho alto"/"intervenção alta" = abaixo/acima de 50%/30%.
_LIMIAR_FALHA_RECORRENTE = 2
_LIMIAR_TAXA_FALHA_MODELO = 0.5
_LIMIAR_TAXA_APROVACAO_BAIXA = 0.5
_LIMIAR_TAXA_INTERVENCAO_ALTA = 0.3
_LIMIAR_TAXA_RETRABALHO_ALTA = 0.3


def recomendacoes_estruturadas(relatorio: RelatorioDeAprendizado) -> list[dict[str, object]]:
    """8 categorias do wf §31.3, cada uma com justificativa quando disparada —
    6 com regra real e determinística sobre o relatório já consolidado, 2
    desabilitadas (ver `_RECOMENDACOES_DESABILITADAS`). Nunca decisão
    automática — só sugestão com justificativa para o operador ler (mesmo
    limite deliberado de `_recomendar`, §24)."""
    justificativas: dict[str, str] = {}

    if relatorio.erros_recorrentes:
        categoria, contagem = max(relatorio.erros_recorrentes.items(), key=lambda kv: kv[1])
        if contagem >= _LIMIAR_FALHA_RECORRENTE:
            justificativas[RECOMENDACAO_AUMENTAR_EFFORT] = (
                f"Categoria '{categoria}' concentra {contagem} falha(s) recorrente(s) "
                "— considere aumentar o effort padrão para ela."
            )
        if categoria in _CATEGORIAS_DE_TESTE:
            justificativas[RECOMENDACAO_ADICIONAR_TESTE] = (
                f"Falhas recorrentes de categoria '{categoria}' sugerem cobertura de "
                "teste automatizado insuficiente para esse cenário."
            )

    com_execucao = [d for d in relatorio.desempenho_por_executor if d.execucoes]
    if com_execucao:
        pior = max(com_execucao, key=lambda d: d.falhas / d.execucoes)
        taxa_falha = pior.falhas / pior.execucoes
        if taxa_falha >= _LIMIAR_TAXA_FALHA_MODELO:
            justificativas[RECOMENDACAO_EVITAR_MODELO] = (
                f"'{pior.executor}' falhou em {pior.falhas} de {pior.execucoes} "
                f"execução(ões) ({taxa_falha:.0%}) — considere evitá-lo para esse "
                "tipo de tarefa."
            )

    taxa_aprovacao = relatorio.taxa_aprovacao
    if taxa_aprovacao is not None and taxa_aprovacao < _LIMIAR_TAXA_APROVACAO_BAIXA:
        justificativas[RECOMENDACAO_MODIFICAR_APROVACAO] = (
            f"Taxa de aprovação de {taxa_aprovacao:.0%} — critérios podem "
            "estar desalinhados com o que a esteira consegue entregar."
        )

    if relatorio.total_cards:
        taxa_intervencao = relatorio.intervencoes_humanas / relatorio.total_cards
        if taxa_intervencao >= _LIMIAR_TAXA_INTERVENCAO_ALTA:
            justificativas[RECOMENDACAO_ALTERAR_LIMITE_TENTATIVAS] = (
                f"{relatorio.intervencoes_humanas} intervenção(ões) humana(s) em "
                f"{relatorio.total_cards} card(s) ({taxa_intervencao:.0%}) — considere "
                "revisar o limite de tentativas antes de escalar para humano."
            )
        taxa_retrabalho = relatorio.total_retrabalho / relatorio.total_cards
        if taxa_retrabalho >= _LIMIAR_TAXA_RETRABALHO_ALTA:
            justificativas[RECOMENDACAO_AJUSTAR_ROTEAMENTO] = (
                f"Taxa de retrabalho de {relatorio.total_retrabalho}/{relatorio.total_cards} "
                f"card(s) ({taxa_retrabalho:.0%}) sugere que as regras de roteamento "
                "atuais não estão casando bem effort/modelo com a complexidade real "
                "das demandas."
            )

    return [
        {
            "tipo": tipo,
            "rotulo": _ROTULOS_RECOMENDACAO[tipo],
            "disponivel": tipo not in _RECOMENDACOES_DESABILITADAS,
            "disparada": tipo in justificativas,
            "justificativa": justificativas.get(tipo, ""),
        }
        for tipo in _TODAS_RECOMENDACOES
    ]
