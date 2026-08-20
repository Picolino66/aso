"""Histórico de tentativas por card (§36.4 do wiframe, ADR-0031).

`card.failures` (ADR-0019) só registra **falhas** — não há registro nenhum de
tentativas bem-sucedidas, e o contador de "quantas vezes esta card já foi
tentado" usava `len(card.failures)`, que é o tamanho do RING (travado em 5), não
o número real de tentativas. Um `max_tentativas` configurável acima de 5 nunca
disparava a escalação, porque a contagem nunca passava de 5 — bug real, não só
lacuna de funcionalidade (ver ADR-0031).

Este módulo separa as duas responsabilidades: `card.tentativa_atual` (inteiro
simples, nunca truncado, contador AUTORITATIVO de tentativas totais — sucesso ou
falha — para exibição e para o teto por agente, ADR-0053) e `card.tentativas`
(ring com histórico detalhado — sucesso e falha — para auditoria/UI, mesma
disciplina de tamanho limitado de `card.failures`/`qa_checks`). `decidir()` usa
um terceiro contador, `card.tentativa_falha_atual` (§13, ADR-0019) — zera a cada
sucesso, pois a escalação de falha olha só falhas consecutivas, não o total.

Puro e determinístico, no mesmo molde de `control/failure.py`/`control/qa.py`.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from aso.shared.ids import now_iso

RESULTADO_SUCESSO = "sucesso"
RESULTADO_FALHOU = "falhou"

_RING_PADRAO = 10


class TentativaRegistro(BaseModel):
    """Uma tentativa de execução do card — sucesso ou falha, sempre com modelo e
    esforço usados (§36.4 do wiframe: "Modelo: Luna / Effort: Médio / Resultado")."""

    numero: int
    executor: str = ""
    effort: str = ""
    resultado: str = RESULTADO_FALHOU
    diagnostico: str = ""
    at: str = Field(default_factory=now_iso)


def registrar_tentativa(
    tentativas: list[dict[str, object]], registro: TentativaRegistro, *, limite: int = _RING_PADRAO
) -> list[dict[str, object]]:
    """Acrescenta `registro` ao ring, descartando o mais antigo além de `limite` —
    mesmo padrão de `control/failure.py::registrar`."""
    novo = [*tentativas, registro.model_dump(mode="json")]
    return novo[-limite:]
