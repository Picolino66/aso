# ADR-0046 — Documentos, especificações e revisão documental (Telas 08 e 09)

- **Status:** ACCEPTED
- **Fase:** F4 (evolução pós-O5)
- **Data:** 2026-08-08
- **Relaciona-se com:** [ADR-0021](ADR-0021-especificacao-e-revisao-documental.md)
  (`SpecDocument`, `DocReviewVerdict`/`ReviewService.revisar_documento` — a base
  quase inteira deste card já existia lá), [ADR-0033](ADR-0033-comentario-de-revisao-ancorado.md)
  (`ReviewComment`, comparado campo a campo e rejeitado como reutilizável),
  [ADR-0036](ADR-0036-sidebar-e-mapa-de-paginas.md) (seção fixa "Documentos" da
  sidebar, `documentos.html`, placeholder desde o FID-09 apontando para este
  card), [ADR-0042](ADR-0042-editor-visual-de-regras-de-roteamento.md) (mesmo
  cuidado de ordenação de rotas Starlette), [`wiframe-fluxo.md`](../../wiframe-fluxo.md)
  §10 (Tela 08) e §11 (Tela 09)

## Contexto

Numeração conferida sem divergência (§10 = Tela 08, §11 = Tela 09). O
wireframe pede 13 tipos de documento (Requisitos, Especificação funcional,
Especificação técnica, Arquitetura, Diagrama de componentes, Diagrama de
fluxo, Modelo de dados, Contrato de API, Plano de migração, Plano de testes,
Plano de implantação, Plano de rollback, Checklist de segurança), lista com
versão/autor/status/ações, editor com Markdown+render+histórico+diff+
comentários+aprovação, e um checklist de revisor com exatamente 4 desfechos.

Investigação prévia (antes de qualquer código) mapeou os 13 tipos contra o
que já existe:
- **1 tipo** (Especificação técnica) já é `SpecDocument` — entidade madura,
  com fluxo de revisão completo (`ReviewService.revisar_documento`,
  `DocReviewVerdict`, ciclo de rodadas, materialização de cards).
- **4 tipos** (Plano de testes/implantação/rollback, Checklist de segurança)
  já são CAMPOS reais dentro de `SpecDocument`
  (`estrategia_de_testes`/`estrategia_de_implantacao`/`plano_de_rollback`/
  `checklist_seguranca`) — a própria ADR-0021 já tinha decidido
  deliberadamente NÃO dar campos próprios a esses artefatos.
- **8 tipos** (Requisitos, Especificação funcional, Arquitetura, Diagrama de
  componentes, Diagrama de fluxo, Modelo de dados, Contrato de API, Plano de
  migração) **não tinham NENHUMA representação** no runtime.

Achado decisivo: `DocReviewVerdict` (ADR-0021, §6) já tem **exatamente os
quatro desfechos** do wf §11.2 (`aprovado`/`aprovado_com_observacoes`/
`reprovado`/`necessita_humano`) — o comentário original do código já cita
"não são os cinco do §14" —, e `ReviewService.revisar_documento` já é
genérico (`documento: BaseModel`, serializa via `model_dump_json` para o
prompt) — funciona com qualquer documento, não só `SpecDocument`.

Duas decisões foram confirmadas com o usuário: onde encaixar a tela
(implícito pela evidência de `documentos.html`/`mapa-paginas.md`, sem
necessidade de pergunta) e como tratar os 5 tipos já cobertos pelo spec
(pergunta explícita).

## Decisão

**(1) Entidade genérica `Documento`** (`control/documento.py`, novo módulo) —
não 8 modelos Pydantic separados. Precedente direto já usado no projeto:
`ContextPatch`/`DomainEvent` (tipo + conteúdo genérico) e o próprio
`control/documentos.py` (ring versionado genérico, já usado por
`discovery_reports`/`spec_documents`). `Documento` cobre só os **8 tipos sem
representação anterior**; vocabulário fechado `TIPOS_VALIDOS`.

**(2) Os 5 tipos já cobertos pelo `SpecDocument` continuam vivendo só lá —
nunca duplicados** (opção recomendada, aprovada). `list_documentos` compõe a
lista de §10.2 juntando os 8 rings novos (editáveis) com os 5 tipos do spec
(somente leitura, `editavel: false`, dado lido ao vivo de `SpecDocument`
corrente). Tentar `PUT`/`review`/comentar um dos 5 tipos devolve `400`
(`DocumentoError`) com mensagem explícita "servido pelo fluxo de
especificação — edite em `/spec`". Motivo: migrar a especificação para a
entidade genérica arriscaria regressão num subsistema maduro (ciclo de
rodadas, materialização de cards, quality gates que checam `status`) só
para uniformizar a UI.

**(3) Persistência como duas colunas JSONB novas em `orchestrations`**
(`documentos: dict[str, list[dict]]`, um ring por tipo; `documento_comentarios:
list[dict]`, lista plana) — não tabelas novas. Mesmo padrão de
`discovery_reports`/`spec_documents` (ring) e de `validation_checks`/
`deploy_health_checks` (lista plana), generalizado. `ReviewComment` (ADR-0033)
usa tabela própria porque acompanha um ciclo de revisão de CÓDIGO mais
volumoso; aqui o volume esperado por demanda é pequeno, e o padrão JSONB já
provado nos dois precedentes citados é suficiente — decisão consciente,
documentada aqui para não ser confundida com a escolha da ADR-0033.
Persistência 100% genérica via `OrchestrationRow(**orchestration.model_dump())`
— nenhuma mudança de repositório foi necessária além da migration
(`9c89dc38ffcc`), validada em SQLite (suíte de testes) **e** Postgres real
(Docker: criação, leitura, `PUT`, comentário, todos com round-trip real).

**(4) Checklist do revisor reaproveita `revisar_documento`/`DocReviewVerdict`
sem alteração** — os quatro desfechos já batem. Fluxo deliberadamente **mais
simples** que o da especificação: sem contagem de rodadas (`ASO_MAX_RODADAS_DOC`)
nem exigência de revisor diferente do autor — os 8 tipos novos são artefatos
de apoio à decisão, não o gate central de qualidade que a spec já é.
Executor de revisão reaproveita a MESMA atribuição de agente da
especificação (`SPEC_KEY`/`agent_assignments["especificacao"]`) — não cria
uma chave nova de atribuição, já que ambos são artefatos de pré-implementação
revisados pelo mesmo papel.

**(5) Comparação de versões via `difflib.unified_diff`** (stdlib, zero
dependência nova) — `GET .../documentos/{tipo}/diff?de=&para=`, comparando
duas versões existentes no ring pelo número de versão.

**(6) Os 8 campos de comentário do wf §10.3/§11.3 (Autor, Tipo, Severidade,
Trecho relacionado, Descrição, Ação solicitada, Status, Resposta do autor)
viram `DocumentComment`, novo modelo — não uma reutilização de
`ReviewComment`.** Comparação campo a campo (ADR-0033) mostrou só 3 de 8
batendo diretamente; `ReviewComment` ancora em arquivo+linha de diff de
código, não em trecho de texto Markdown; não tem `autor` nem "resposta do
autor". Vocabulário de `tipo`/`severidade` do comentário reaproveita o mesmo
de `review.py` (`correcao|teste|seguranca|clareza|escopo|documentacao|
performance`; `baixa|media|alta|critica`) por consistência, sem duplicar
semântica nova.

**(7) Nova página `/ui/documentos?id=`** — substitui o placeholder
`documentos.html` (uma das 16 seções fixas da sidebar, reservada desde o
FID-09/ADR-0036, nunca satélite de `demanda-detalhe.html`). Sem `id`, mostra
um seletor simples de demanda (lista as orquestrações existentes) em vez de
redirecionar — diferente do padrão dos satélites (`demanda-estrutura.html`
etc.), porque esta é uma seção de PRIMEIRO NÍVEL da sidebar, alcançável a
qualquer momento sem contexto de demanda prévio.

**(8) Editor Markdown com "subconjunto simples" de renderização** —
conversor próprio em JavaScript (cabeçalhos `#`/`##`/`###`, **negrito**,
*itálico*, `código`, listas `- item`, links `[texto](url)`, parágrafos), não
um parser CommonMark completo nem uma biblioteca externa nova — mantém o
precedente "zero dependência externa" das ADR-0034/0035/0036/0041 (a
exceção continua sendo só `mermaid.js` no Dashboard, ADR-0037).

## Consequências

**Positivas**
- Reaproveitamento real e grande: `DocReviewVerdict`/`revisar_documento`
  (motor de revisão inteiro), `control/documentos.py` (versionamento),
  vocabulário de `review.py` (categoria/severidade), `SPEC_KEY` (atribuição
  de agente) — nenhum desses precisou de nenhuma mudança.
- Migration testada em Postgres real (não só SQLite), evitando o pitfall
  documentado no CLAUDE.md de FKs/JSONB que só aparecem no Postgres.
- Zero risco ao subsistema de especificação (ADR-0021) — intocado.

**Negativas / riscos aceitos**
- Fluxo de revisão dos 8 tipos novos é mais simples que o da spec (sem
  rodadas, sem exigência de revisor diferente do autor) — um documento pode,
  em teoria, ser "revisado" pelo mesmo agente que o escreveu, diferente do
  code review (§14) e da revisão documental da spec (§6). Aceito
  conscientemente pelo escopo menor desses artefatos.
- Markdown renderizado é um subconjunto simples — tabelas, blocos de código
  cercados (```), imagens e Markdown aninhado complexo não são suportados.
  Documentado explicitamente, não escondido.
- `/ui/documentos` sem `id` mostra até 30 demandas recentes sem paginação —
  aceitável no volume dev-scale do projeto, mesmo raciocínio já aceito em
  `header_summary`/`search` (ADR-0035).
