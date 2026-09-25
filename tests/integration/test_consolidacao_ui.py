"""MEL-55 — consolidação da UI (ADR-0078), etapa 1: seções reais e módulo JS compartilhado.

Os testes de HTML deste projeto verificam o CONTEÚDO servido (não renderizam JS): garantem que a
página deixou de ser placeholder, que consome as rotas reais e que a sidebar/atalhos apontam para
onde a funcionalidade passou a viver.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from aso.api.app import create_app
from aso.application.orchestration_service import OrchestrationService
from aso.governance.models import Incident

ESTATICOS = Path(__file__).resolve().parents[2] / "src" / "aso" / "api" / "static"


def _client() -> TestClient:
    return TestClient(create_app(OrchestrationService()))


# ------------------------------------------------------------ módulo compartilhado


def test_modulo_compartilhado_e_servido_e_expoe_o_contrato() -> None:
    corpo = _client().get("/ui/aso-api.js").text
    assert "window.ASOApi" in corpo
    for funcao in ("token", "api", "esc", "mensagemDeErro", "acompanharJob"):
        assert funcao + ":" in corpo, funcao
    # 403/409 ganham mensagem própria: é o que o operador precisa ler (ADR-0057, governança)
    assert "403" in corpo and "409" in corpo
    assert "/v1/jobs/" in corpo  # resolve o 202 da fila (ADR-0067)


def test_paginas_novas_usam_o_modulo_em_vez_de_copiar_o_fetch() -> None:
    for pagina in ("modelos.html", "incidentes.html", "configuracoes.html"):
        corpo = (ESTATICOS / pagina).read_text(encoding="utf-8")
        assert '<script src="/ui/aso-api.js">' in corpo, pagina
        assert "ASOApi.api" in corpo, pagina
        # sem cópia local do helper
        assert not re.search(r"async function api\(", corpo), pagina
        assert "localStorage.getItem('aso_token')" not in corpo, pagina


# ------------------------------------------------------------ modelos (catálogo)


def test_modelos_nao_e_mais_placeholder_e_lista_executores() -> None:
    pagina = _client().get("/ui/modelos").text
    assert "active: 'modelos'" in pagina
    assert "FID-25" not in pagina and "ainda não foi implementada" not in pagina
    for rota in ("/v1/executors", "/v1/executors/sync"):
        assert rota in pagina, rota
    assert "/v1/executors/' + encodeURIComponent" in pagina  # remoção de perfil


def test_modelos_edita_streaming_permissao_e_candidato_por_campo() -> None:
    """ADR-0076: os campos do perfil substituem flags digitadas no comando."""
    pagina = _client().get("/ui/modelos").text
    for campo in ("cfStreaming", "cfPermissao", "cfCandidato"):
        assert campo in pagina, campo
    for valor in ("nenhuma", "edicoes", "total"):
        assert f'value="{valor}"' in pagina, valor
    assert "não digite-as no comando" in pagina
    assert "familia_cli" in pagina


def test_modelos_nao_expoe_valor_de_chave() -> None:
    pagina = _client().get("/ui/modelos").text
    assert "api_key_env" in pagina
    assert "apenas em variáveis de ambiente" in pagina


# ------------------------------------------------------------ incidentes


def test_incidentes_nao_e_mais_placeholder_e_usa_a_rota_cross_demanda() -> None:
    pagina = _client().get("/ui/incidentes").text
    assert "active: 'incidentes'" in pagina
    assert "ainda não foi implementada" not in pagina
    assert "/v1/incidents" in pagina
    assert "fStatus" in pagina and "fProjeto" in pagina
    # ações de ciclo de vida continuam na aba da demanda (uma fonte só)
    assert "aba=incidentes" in pagina


def test_rota_global_de_incidentes_lista_e_filtra() -> None:
    svc = OrchestrationService()
    client = TestClient(create_app(svc))
    primeira = svc.create_orchestration("demanda com incidente")
    segunda = svc.create_orchestration("outra demanda")
    # Incidente só nasce do rollback de implantação (§21): aqui gravamos direto o mesmo objeto
    # que `_criar_incidente` grava, para exercitar a consulta cross-demanda sem montar um deploy.
    for oid, titulo, gravidade in (
        (primeira.id, "rollback do deploy", "alta"),
        (segunda.id, "falha de saúde", "media"),
    ):
        b = svc._bundle(oid)  # noqa: SLF001
        b.incidents.append(
            Incident(orchestration_id=oid, titulo=titulo, gravidade=gravidade, motivo="teste")
        )
        svc._persist(b)  # noqa: SLF001

    todos = client.get("/v1/incidents").json()
    assert {i["orchestration_id"] for i in todos} == {primeira.id, segunda.id}
    assert [i["status"] for i in todos] == ["aberto", "aberto"]

    abertos = client.get("/v1/incidents", params={"status": "resolvido"}).json()
    assert abertos == []


# ------------------------------------------------------------ configurações


def test_configuracoes_nao_e_mais_placeholder_e_reune_os_ajustes() -> None:
    pagina = _client().get("/ui/configuracoes").text
    assert "active: 'configuracoes'" in pagina
    assert "FID-26" not in pagina and "ainda não foi implementada" not in pagina
    for destino in ("/ui/modelos", "/ui/agentes", "/ui/regras-roteamento", "/docs"):
        assert destino in pagina, destino


def test_configuracoes_administra_projetos_migrados_do_kanban_macro() -> None:
    """`macro.html` era a única página com criar/arquivar/restaurar projeto e o histórico."""
    pagina = _client().get("/ui/configuracoes").text
    assert "/v1/projects" in pagina
    assert "/restore" in pagina and "/events" in pagina
    assert "include_archived" in pagina
    assert "method: 'DELETE'" in pagina  # arquivar


# ------------------------------------------------------------ etapa 3: esteira = sala de controle


def test_esteira_e_a_sala_de_controle_dentro_da_sidebar() -> None:
    pagina = _client().get("/ui/esteira").text
    assert "active: 'esteira'" in pagina
    assert "ainda não foi implementada" not in pagina
    assert "Esteira F1 → F7" in pagina and "Próximo passo" in pagina.replace(
        "Próximo Passo", "Próximo passo"
    )
    for rota in ("/next-step", "/agents/", "/autopilot", "/quality-gates/run", "/spec/run"):
        assert rota in pagina, rota
    assert "/v1/phases" in pagina  # esteira descrita pelo runtime, não fixa no HTML
    assert "agent-log" in pagina  # painel "o que o agente está fazendo" (ADR-0015)


def test_esteira_sem_id_mostra_seletor_de_demanda() -> None:
    pagina = _client().get("/ui/esteira").text
    assert "semDemanda" in pagina and "listaDemandas" in pagina
    assert "/ui/esteira?id=" in pagina


def test_esteira_aponta_a_auditoria_para_a_aba_de_governanca() -> None:
    pagina = _client().get("/ui/esteira").text
    assert "/ui/console" not in pagina
    assert "aba Governança da demanda" in pagina


# ------------------------------------------------------------ etapa 4: rotas legadas


def test_rotas_legadas_redirecionam_preservando_a_query() -> None:
    client = _client()
    for origem, destino in (
        ("/ui/", "/ui/dashboard"),
        ("/ui/nova", "/ui/demanda-nova"),
        ("/ui/detalhe", "/ui/esteira"),
        ("/ui/console", "/ui/demanda-detalhe"),
    ):
        resposta = client.get(origem, follow_redirects=False)
        assert resposta.status_code == 307, origem
        assert resposta.headers["location"] == destino, origem
        com_query = client.get(origem + "?id=orch_x&aba=Cards", follow_redirects=False)
        assert com_query.headers["location"] == destino + "?id=orch_x&aba=Cards", origem
        # e o destino final responde 200
        assert client.get(origem, follow_redirects=True).status_code == 200, origem


def test_arquivos_das_paginas_legadas_foram_removidos() -> None:
    for arquivo in ("macro.html", "nova.html", "detalhe.html", "index.html"):
        assert not (ESTATICOS / arquivo).exists(), arquivo


def test_nenhuma_pagina_linka_para_rota_legada() -> None:
    """Link interno tem de apontar para a página final, não depender do redirecionamento."""
    proibidos = ("/ui/console", "/ui/detalhe?", "/ui/nova?", 'href="/ui/"')
    for arquivo in sorted(ESTATICOS.glob("*.html")) + sorted(ESTATICOS.glob("*.js")):
        corpo = arquivo.read_text(encoding="utf-8")
        for proibido in proibidos:
            assert proibido not in corpo, f"{arquivo.name}: {proibido}"


def test_todas_as_paginas_montam_a_sidebar() -> None:
    """Sem placeholders e sem página fora do shell: a navegação é a mesma em todas."""
    for arquivo in sorted(ESTATICOS.glob("*.html")):
        corpo = arquivo.read_text(encoding="utf-8")
        assert "ASOSidebar.mount" in corpo, arquivo.name
        assert "ainda não foi implementada" not in corpo, arquivo.name


def test_sidebar_nao_tem_placeholder() -> None:
    client = _client()
    for secao in ("esteira", "modelos", "incidentes", "configuracoes"):
        pagina = client.get(f"/ui/{secao}")
        assert pagina.status_code == 200, secao
        assert "ainda não foi implementada" not in pagina.text, secao


# ------------------------------------------------------------ etapa 2: governança na demanda


def test_demanda_detalhe_ganhou_aba_de_governanca_com_o_que_era_do_console() -> None:
    pagina = _client().get("/ui/demanda-detalhe").text
    assert "'Governança'" in pagina
    for rota in (
        "/patches",
        "/conflicts",
        "/snapshots",
        "/slo",
        "/slo-history?limit=20",
        "/worktrees",
    ):
        assert rota in pagina, rota
    # ações críticas da governança, com dry-run antes de restaurar (ADR-0061)
    assert "/restore-section/preview?section=" in pagina
    assert "/worktrees/prune" in pagina
    assert "/slo/evaluate" in pagina
    assert "/conflicts/' +" in pagina and "/resolve" in pagina
    assert "ação crítica (admin)" in pagina


def test_demanda_detalhe_mostra_tempo_e_custo_por_card() -> None:
    """`execution-timeline` (custo por card) só existia no console técnico."""
    pagina = _client().get("/ui/demanda-detalhe").text
    assert "/execution-timeline" in pagina
    assert "Tempo e custo por card" in pagina
    assert "ADR-0026" in pagina  # tempo é fallback declarado, não custo


def test_demanda_detalhe_usa_o_modulo_compartilhado() -> None:
    pagina = _client().get("/ui/demanda-detalhe").text
    assert '<script src="/ui/aso-api.js">' in pagina
    assert "ASOApi.api" in pagina
    assert "async function api(path, opts)" not in pagina


def test_polling_de_job_vive_so_no_modulo_compartilhado() -> None:
    """Duas implementações do mesmo polling divergiriam: `jobs.js` passa a delegar."""
    shim = (ESTATICOS / "jobs.js").read_text(encoding="utf-8")
    assert "ASOApi" in shim
    assert "setTimeout" not in shim  # a espera mora no módulo
    modulo = (ESTATICOS / "aso-api.js").read_text(encoding="utf-8")
    assert "acompanharJob" in modulo and "aso:job" in modulo


def test_configuracoes_mostra_estado_do_runtime() -> None:
    pagina = _client().get("/ui/configuracoes").text
    assert "/health" in pagina and "/v1/me" in pagina
    assert "regra 9" in pagina  # secrets só por variável de ambiente
