# MEL-43 — Effort como campo do contrato, mapeado por provider

| Campo | Valor |
|---|---|
| Fase do roadmap | 4 — Inteligência |
| Prioridade | P2 |
| Esforço | médio |
| Status | Backlog |
| Depende de | MEL-14 |
| Origem | [feedback.md](../feedback.md) §2 item 26, §4 (roteamento de modelo e effort) |
| Requer ADR | Sim, curta: atualiza ADR-0022 com a matriz de suporte por provider |

## Problema

- O effort é resolvido com cuidado (explícito → override do card → etapa → orquestração →
  sugestão pela ficha → perfil), mas só tem efeito real em perfis Codex gerenciados, via
  `-c model_reasoning_effort` em `ExecutorCatalog.cli_command`.
- Para Claude CLI, o effort vai no JSON e o wrapper o ignora.
- `OpenAICompatibleClient` e `AnthropicClient` não recebem effort.
- A sugestão automática (`sugerir_effort`) e a ação `aumentar_effort` do roteamento de falha
  parecem funcionar, mas não mudam nada fora do Codex.

## Mudança proposta

1. `effort` como campo tipado do `TaskEnvelope` (`low|medium|high`).
2. Interface `MapeadorDeEffort` por tipo de executor, declarando se suporta effort e como aplicá-lo:
   - Codex gerenciado: flag atual;
   - Claude CLI: confirmar na documentação oficial do CLI qual opção controla modelo/raciocínio e testar;
   - APIs de LLM: parâmetro de raciocínio do provider/modelo quando existir;
   - sem suporte: registrar `effort_aplicado = false`.
3. `ExecutorProfile.public()` expõe `suporta_effort`; o console desabilita a escolha quando não há suporte.
4. `failure.decidir` não escolhe `aumentar_effort` para executor sem suporte (vai direto para trocar executor).
5. `agent_runs` registra effort solicitado e effort aplicado.

## Critérios de aceite

- [ ] Para cada tipo de executor, teste verifica a aplicação (ou a declaração de não suporte).
- [ ] Roteamento de falha não propõe aumentar effort em executor sem suporte.
- [ ] Console indica quando o effort não tem efeito no executor escolhido.
