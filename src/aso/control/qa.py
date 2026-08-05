"""QA humano (§16/§17 do fluxo.md) — ADR-0025.

O `fluxo.md` §16 pede um passo em que alguém (QA, humano, produto, negócio)
verifica o que a automação não cobre: experiência do usuário, fluxos visuais,
regras complexas, comportamento em ambiente real, integrações externas,
aceitação de negócio. Nenhum código existia para isto — busca por `teste_manual`/
`QA`/`aceite de negócio` em `src/` só retornava `acceptance_criteria`, que é outra
coisa (critério do card, não passo de validação).

Puro e determinístico, no mesmo molde de `control/review.py`
(`exige_confirmacao_humana`): a regra de quando QA é exigido não depende de
agente/LLM — é regra de governança, não palpite.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from aso.control.triage import DemandBrief
from aso.kanban.models import KanbanCard
from aso.shared.ids import now_iso
from aso.shared.types import CardType

STATUS_PENDENTE = "pendente"
STATUS_PASSOU = "passou"
STATUS_FALHOU = "falhou"

# Domínios (`DemandBrief.dominios`, vocabulário de `decision_engine.py`) cuja
# experiência a automação não valida sozinha — regra visual/UX é julgamento humano.
_DOMINIOS_QUE_EXIGEM_QA = frozenset({"frontend"})
# Complexidade (`DemandBrief.complexidade`, mesma tabela de `control/selecao.py`)
# alta o bastante para que regra de negócio complexa mereça olho humano.
_COMPLEXIDADES_QUE_EXIGEM_QA = frozenset({"complexa", "estrategica"})
# Card de escopo maior (história/épico) tende a cruzar módulos — mais superfície
# para o tipo de regressão que só aparece em ambiente real.
_TIPOS_QUE_EXIGEM_QA = frozenset({CardType.EPIC, CardType.FEATURE})


class QaCheck(BaseModel):
    """Verificação manual do §16 — o que a automação não cobre."""

    cenario: str
    passos: list[str] = Field(default_factory=list)
    ambiente: str = ""
    resultado_esperado: str = ""
    resultado_obtido: str = ""
    evidencias: list[str] = Field(default_factory=list)
    # baixa | media | alta | critica — vira a `priority` do bug quando falha (§17).
    gravidade: str = "media"
    status: str = STATUS_PENDENTE
    responsavel: str = ""  # ator autenticado
    tipo_responsavel: str = "humano"  # humano | agente_qa | produto | negocio
    at: str = Field(default_factory=now_iso)


def exige_qa_manual(brief: DemandBrief, card: KanbanCard) -> bool:
    """§16: QA manual para o que a automação não alcança.

    Fora desta regra, QA continua **opcional** — o operador pode registrar uma
    verificação a qualquer momento mesmo sem a regra exigir; isto só decide o que
    o `next_step` cobra antes de liberar a implantação.
    """
    if set(brief.dominios) & _DOMINIOS_QUE_EXIGEM_QA:
        return True
    if brief.complexidade in _COMPLEXIDADES_QUE_EXIGEM_QA:
        return True
    return card.type in _TIPOS_QUE_EXIGEM_QA
