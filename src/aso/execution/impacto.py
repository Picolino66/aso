"""Impacto estrutural de um conjunto de arquivos, tirado do índice (ADR-0077, MEL-44).

O índice (`code_index.py`) é grande; o que entra num prompt é **pequeno e verificável**: quem
importa os arquivos alterados (raio da regressão) e quais testes os cobrem. Este módulo faz essa
redução e devolve o texto pronto — a revisão (§14) e o contexto do card (ADR-0063) usam o mesmo.

Nada aqui lê disco: recebe o índice já carregado, para o cálculo ser testável e determinístico.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from aso.execution.code_index import IndiceDoRepositorio

LIMITE_DE_ITENS = 15


@dataclass(frozen=True)
class ImpactoEstrutural:
    """Vizinhança dos arquivos alterados: dependentes, testes e o que eles usam."""

    arquivos: list[str] = field(default_factory=list)
    dependentes: list[str] = field(default_factory=list)
    testes: list[str] = field(default_factory=list)
    desconhecidos: list[str] = field(default_factory=list)
    commit: str = ""

    def vazio(self) -> bool:
        return not (self.dependentes or self.testes)

    def como_texto(self) -> str:
        """Bloco para o pedido ao agente — fatos, com a origem declarada."""
        linhas = [
            "Impacto estrutural pelo índice do repositório "
            f"(commit {self.commit[:8] or 'sem commit'}; ADR-0077 — fatos, não opinião):"
        ]
        if self.dependentes:
            linhas.append(
                f"- Arquivos que importam os alterados ({len(self.dependentes)}): "
                + ", ".join(self.dependentes[:LIMITE_DE_ITENS])
            )
        else:
            linhas.append("- Nenhum arquivo do repositório importa os alterados.")
        if self.testes:
            linhas.append(
                f"- Testes relacionados ({len(self.testes)}): "
                + ", ".join(self.testes[:LIMITE_DE_ITENS])
            )
        else:
            linhas.append("- Nenhum teste indexado cobre os arquivos alterados.")
        if self.desconhecidos:
            linhas.append(
                "- Fora do índice (novos, ignorados ou não indexáveis): "
                + ", ".join(self.desconhecidos[:LIMITE_DE_ITENS])
            )
        return "\n".join(linhas)


def impacto_de(indice: IndiceDoRepositorio, arquivos: list[str]) -> ImpactoEstrutural:
    """Une a vizinhança de cada arquivo, sem repetir e sem incluir os próprios alterados."""
    alvos = [a.strip().removeprefix("./") for a in arquivos if a.strip()]
    conhecidos = [a for a in alvos if a in indice.arquivos]
    desconhecidos = [a for a in alvos if a not in indice.arquivos]
    dependentes: list[str] = []
    testes: list[str] = []
    for alvo in conhecidos:
        vizinhanca = indice.vizinhanca(alvo)
        for arquivo in vizinhanca["importado_por"]:
            if arquivo not in alvos and arquivo not in dependentes:
                dependentes.append(arquivo)
        for teste in vizinhanca["testes"]:
            if teste not in alvos and teste not in testes:
                testes.append(teste)
    # Teste também é dependente; listar duas vezes só gasta contexto.
    dependentes = [a for a in dependentes if a not in testes]
    return ImpactoEstrutural(
        arquivos=conhecidos,
        dependentes=dependentes,
        testes=testes,
        desconhecidos=desconhecidos,
        commit=indice.commit,
    )


def vizinhanca_para_contexto(
    indice: IndiceDoRepositorio, arquivos: list[str], *, limite: int = LIMITE_DE_ITENS
) -> list[str]:
    """Linhas curtas por arquivo citado no card: símbolos, dependentes e testes (ADR-0063)."""
    linhas: list[str] = []
    for alvo in arquivos:
        chave = alvo.strip().removeprefix("./")
        dados = indice.arquivos.get(chave)
        if dados is None:
            continue
        vizinhanca = indice.vizinhanca(chave)
        partes = [f"{chave} ({dados.linguagem}, {dados.linhas} linhas)"]
        if dados.simbolos:
            partes.append(
                "define: " + ", ".join(f"{s.nome}:{s.linha}" for s in dados.simbolos[:limite])
            )
        if dados.entradas:
            partes.append("entradas: " + ", ".join(dados.entradas[:limite]))
        if vizinhanca["importa"]:
            partes.append("usa: " + ", ".join(vizinhanca["importa"][:limite]))
        if vizinhanca["importado_por"]:
            partes.append("usado por: " + ", ".join(vizinhanca["importado_por"][:limite]))
        if vizinhanca["testes"]:
            partes.append("testes: " + ", ".join(vizinhanca["testes"][:limite]))
        linhas.append(" | ".join(partes))
    return linhas
