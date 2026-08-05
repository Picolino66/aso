"""Versionamento de documentos em ring — discovery e spec (§4.2 do plano4.md, ADR-0021).

`DiscoveryReport` (ADR-0020) era sobrescrito a cada `/discovery/run`: reexecutar
depois de uma reprovação apagava o relatório anterior, e o comentário da reprovação
só sobrevivia porque entrava no prompt da próxima tentativa — não como histórico
consultável. O §6 do fluxo.md exige um ciclo de reprovação e reenvio até a aprovação;
sem histórico não há como responder "esta spec já foi reprovada duas vezes, pelos
mesmos motivos?" — a pergunta que detecta um agente girando em falso.

Mesmo raciocínio das ADR-0014/0016/0017/0019: sem tabela nova, um ring de até
`LIMITE_RING` versões guardado como lista de dict na orquestração — a linha inteira
é reescrita a cada `save`, então o histórico fica pequeno de propósito.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

LIMITE_RING = 5


def proxima_versao(ring: list[dict[str, Any]]) -> int:
    """Versão monotônica do próximo documento — não reinicia quando o ring descarta
    o item mais antigo (a versão vem do último item, não do tamanho da lista)."""
    if not ring:
        return 1
    return int(ring[-1].get("versao") or len(ring)) + 1


def acrescentar_versao(
    ring: list[dict[str, Any]], documento: BaseModel, *, limite: int = LIMITE_RING
) -> list[dict[str, Any]]:
    """Acrescenta uma nova versão ao ring, descartando a mais antiga além de `limite`."""
    novo = [*ring, documento.model_dump(mode="json")]
    return novo[-limite:]


def versao_atual[T: BaseModel](ring: list[dict[str, Any]], modelo: type[T]) -> T:
    """Última versão do ring — vazio (documento nunca produzido) devolve o default."""
    if not ring:
        return modelo()
    return modelo.model_validate(ring[-1])
