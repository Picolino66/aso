"""Documento — os 8 tipos sem nenhuma representação hoje (Tela 08, wf §10, ADR-0046).

Cinco dos 13 tipos do wireframe (Especificação técnica, Plano de testes, Plano de
implantação, Plano de rollback, Checklist de segurança) já são dado real dentro de
`SpecDocument` (ADR-0021) — não duplicados aqui; a lista de documentos os mostra em
modo leitura, linkados ao fluxo de especificação já maduro e revisado (escolha
confirmada com o usuário, sobre a alternativa de migrar tudo para este módulo).

Este módulo cobre só os 8 tipos que não tinham NENHUMA representação: Requisitos,
Especificação funcional, Arquitetura, Diagrama de componentes, Diagrama de fluxo,
Modelo de dados, Contrato de API, Plano de migração.

Reaproveita o mesmo vocabulário de status de `control/spec.py` e o mesmo motor de
revisão documental (`ReviewService.revisar_documento`/`DocReviewVerdict`, ADR-0021)
— os quatro desfechos do §6 já batem EXATAMENTE com os quatro do wf §11.2. Também
reaproveita o versionamento em ring genérico de `control/documentos.py`
(`proxima_versao`/`acrescentar_versao`/`versao_atual`), só que com um ring por tipo
em vez de um ring único — mesmo raciocínio de `discovery_reports`/`spec_documents`,
generalizado para N tipos.
"""

from __future__ import annotations

import difflib

from pydantic import BaseModel, Field

from aso.control.spec import STATUS_RASCUNHO
from aso.shared.ids import gen_id, now_iso

TIPO_REQUISITOS = "requisitos"
TIPO_ESPECIFICACAO_FUNCIONAL = "especificacao_funcional"
TIPO_ARQUITETURA = "arquitetura"
TIPO_DIAGRAMA_COMPONENTES = "diagrama_componentes"
TIPO_DIAGRAMA_FLUXO = "diagrama_fluxo"
TIPO_MODELO_DE_DADOS = "modelo_de_dados"
TIPO_CONTRATO_DE_API = "contrato_de_api"
TIPO_PLANO_DE_MIGRACAO = "plano_de_migracao"

TIPOS_VALIDOS = frozenset(
    {
        TIPO_REQUISITOS,
        TIPO_ESPECIFICACAO_FUNCIONAL,
        TIPO_ARQUITETURA,
        TIPO_DIAGRAMA_COMPONENTES,
        TIPO_DIAGRAMA_FLUXO,
        TIPO_MODELO_DE_DADOS,
        TIPO_CONTRATO_DE_API,
        TIPO_PLANO_DE_MIGRACAO,
    }
)

# Rótulo humano (wf §10.1, coluna "Documento" de §10.2) — usado na lista e no
# título do editor; a chave é o valor persistido, o rótulo é só para exibição.
ROTULOS: dict[str, str] = {
    TIPO_REQUISITOS: "Requisitos",
    TIPO_ESPECIFICACAO_FUNCIONAL: "Especificação funcional",
    TIPO_ARQUITETURA: "Arquitetura",
    TIPO_DIAGRAMA_COMPONENTES: "Diagrama de componentes",
    TIPO_DIAGRAMA_FLUXO: "Diagrama de fluxo",
    TIPO_MODELO_DE_DADOS: "Modelo de dados",
    TIPO_CONTRATO_DE_API: "Contrato de API",
    TIPO_PLANO_DE_MIGRACAO: "Plano de migração",
}

# Os 5 tipos do wf §10.1 já cobertos por `SpecDocument` — mostrados em modo leitura
# na lista de documentos, nunca escritos por este módulo.
TIPOS_DA_ESPECIFICACAO: dict[str, str] = {
    "especificacao_tecnica": "Especificação técnica",
    "plano_de_testes": "Plano de testes",
    "plano_de_implantacao": "Plano de implantação",
    "plano_de_rollback": "Plano de rollback",
    "checklist_de_seguranca": "Checklist de segurança",
}


class DocumentoError(ValueError):
    """Tipo/vocabulário de documento ou comentário inválido — vira 400 na API,
    distinto de um `ValueError` de conflito de estado (vira 409)."""


TIPOS_COMENTARIO_VALIDOS = frozenset(
    {"correcao", "teste", "seguranca", "clareza", "escopo", "documentacao", "performance"}
)
SEVERIDADES_COMENTARIO_VALIDAS = frozenset({"baixa", "media", "alta", "critica"})
STATUS_COMENTARIO_VALIDOS = frozenset({"pendente", "resolvido"})


class Documento(BaseModel):
    """Uma versão de um documento (wf §10) — ring versionado, mesmo padrão de
    `DiscoveryReport`/`SpecDocument` (`control/documentos.py`), um ring por `tipo`."""

    tipo: str = ""
    autor: str = ""
    status: str = STATUS_RASCUNHO
    conteudo_markdown: str = ""
    versao: int = 1
    # Referências a código/cards/outros documentos (wf §10.3) — texto livre (não há
    # validação de existência: um caminho de arquivo ou id de card que ainda não
    # existe no momento da escrita não é erro, o documento pode antecipar trabalho).
    referencias_codigo: list[str] = Field(default_factory=list)
    referencias_cards: list[str] = Field(default_factory=list)
    referencias_documentos: list[str] = Field(default_factory=list)
    revisao_resumo: str = ""
    revisao_pontos_verificados: list[str] = Field(default_factory=list)
    revisor: str = ""
    at: str = Field(default_factory=now_iso)


class DocumentComment(BaseModel):
    """Comentário ancorado num documento (wf §10.3, §11.3, ADR-0046) — os 8 campos
    literais do wireframe: autor, tipo, severidade, trecho relacionado, descrição,
    ação solicitada, status, resposta do autor."""

    id: str = Field(default_factory=lambda: gen_id("doccomment"))
    orchestration_id: str = ""
    documento_tipo: str = ""
    documento_versao: int = 0
    autor: str = ""
    tipo: str = "correcao"
    severidade: str = "media"
    trecho_relacionado: str = ""
    descricao: str = ""
    acao_solicitada: str = ""
    status: str = "pendente"
    resposta_do_autor: str = ""
    created_at: str = Field(default_factory=now_iso)
    resolved_at: str | None = None


def diff_versoes(anterior: str, atual: str) -> list[str]:
    """Diff de linhas entre duas versões (wf §10.3, "Comparação de versões") —
    `difflib.unified_diff` da stdlib, sem dependência nova, sem inventar formato."""
    return list(
        difflib.unified_diff(
            anterior.splitlines(),
            atual.splitlines(),
            fromfile="versão anterior",
            tofile="versão atual",
            lineterm="",
        )
    )
