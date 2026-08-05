# ADR-0024 — Corrida de candidatos: causa raiz do candidato fantasma

- **Status:** ACCEPTED
- **Fase:** F5 (correção de bug pré-existente, não regressão)
- **Data:** 2026-07-31
- **Relaciona-se com:** [`execution/candidates.py`](../../src/aso/execution/candidates.py),
  [`execution/cli_provider.py`](../../src/aso/execution/cli_provider.py),
  [ADR-0019](ADR-0019-roteamento-de-falha.md) (diagnóstico `diff_vazio`),
  [`plano6.md`](../../plano6.md) §0

## Contexto

A avaliação do Incremento E (`plano6.md` §0) reportou uma falha intermitente:
`tests/integration/test_candidates.py::test_race_candidates_and_merge_recommended`
falhava em ~2 de 5 execuções da suíte completa, sempre com a mesma assinatura —
um candidato de uma corrida de dois voltava **sem arquivo nenhum**, apesar de o
comando (`bash -c "printf 'a\nb\nc\n' > sol_codex.py"`) ser determinístico e
não poder falhar sozinho. O mesmo teste passava 10/10 quando rodado isolado.

A hipótese inicial, registrada no plano antes de investigar, era contenção de
lockfile do git entre worktrees do mesmo repositório base — `collect_diff`
(`execution/worktree.py`) já documenta esse risco e serializa operações de
metadados com `_GIT_META_LOCK`. O plano exigia explicitamente **não presumir
a causa**: reproduzir com um teste de estresse antes de mexer em qualquer
código, e só então diagnosticar com evidência.

## Como foi reproduzido

`tests/integration/test_race_stress.py` roda uma corrida de 3 candidatos, `N`
vezes em sequência (`ASO_RACE_STRESS_N`, default 20), falhando se **qualquer**
candidato voltar com `error`. Na primeira execução, sem nenhuma mudança de
código, o teste reprovou já na rodada 0:

```
AssertionError: 3/60 candidatos falharam: [
  {'rodada': 0, 'executor': 'a', ...,
   'error': 'Falha ao enviar a tarefa ao executor CLI: [Errno 32] Broken pipe'},
  {'rodada': 6, 'executor': 'b', ..., 'error': '... Broken pipe'},
  {'rodada': 10, 'executor': 'a', ..., 'error': '... Broken pipe'},
]
```

Isso já era a evidência: `BrokenPipeError`, não um erro de git.

## Causa raiz

Em `execution/cli_provider.py::_rodar`, a versão anterior escrevia a tarefa no
stdin do processo **depois** de já ter iniciado as threads leitoras de
stdout/stderr:

```python
proc = subprocess.Popen(self.command, stdin=subprocess.PIPE, ...)
# ... threads leitoras iniciadas ...
if proc.stdin is not None:
    proc.stdin.write(json.dumps(task, ensure_ascii=False))
    proc.stdin.close()
```

Os comandos de teste usados na corrida (`bash -c "echo a > sol.py"`) **nunca
leem stdin** — não precisam da tarefa para rodar. Um comando `bash -c` desse
tamanho termina e fecha o próprio stdin em microssegundos. Se o processo pai
não chegar a `proc.stdin.write(...)` antes de o filho morrer, a escrita
recebe `EPIPE`/`BrokenPipeError` do kernel — o mesmo mecanismo por trás de
`yes | head`. O código antigo tratava **qualquer** `OSError` nesse ponto como
falha do executor CLI e abortava, sem sequer chamar `proc.wait()` para
verificar se o processo, na real, tinha terminado com sucesso.

Sob carga (suíte com 730+ testes, contenção de CPU real), a janela entre
`Popen()` retornar e a thread do candidato chegar a `stdin.write()` fica mais
larga — daí a falha aparecer só sob repetição/carga, nunca isolada. **Não é**
contenção de lockfile do git: todas as operações de metadados
(`create`/`collect_diff`/`commit`/`merge`/`remove`) já estavam sob
`_GIT_META_LOCK` desde antes, e a suspeita inicial do plano se mostrou
incorreta — a instrumentação (o próprio teste de estresse, que já expõe
`Candidate.error`) revelou a causa real antes de qualquer código de
diagnóstico adicional ser necessário.

## Decisão

`_enviar_tarefa` (novo método privado de `CliAgentExecutionProvider`) escreve
a tarefa e ignora `BrokenPipeError` tanto na escrita quanto no fechamento do
pipe — o mesmo padrão que `subprocess.communicate()` da stdlib já usa para o
motivo idêntico (`Popen._communicate`, CPython). O código não presume mais que
uma escrita falha em stdin significa que o executor falhou: quem decide
sucesso/falha volta a ser `proc.wait()` e o `returncode` real, exatamente como
já acontecia para qualquer outro caminho de erro. Um comando real (`claude
-p`, `codex exec`) que de fato precisa da tarefa via stdin continua recebendo
normalmente — só passou a não travar em falso quando o processo não precisa
dela.

```python
@staticmethod
def _enviar_tarefa(proc: subprocess.Popen[str], task: dict[str, Any]) -> None:
    if proc.stdin is None:
        return
    try:
        proc.stdin.write(json.dumps(task, ensure_ascii=False))
    except BrokenPipeError:
        pass
    try:
        proc.stdin.close()
    except BrokenPipeError:
        pass
```

### Parar de engolir falhas (independente da causa raiz)

O plano exigia esta parte **mesmo que a causa raiz não fosse encontrada** —
uma corrida que perde candidato nunca pode parecer uma comparação completa:

- `CandidateRunner.compare` devolve `falhas: list[dict]` além de `candidates`
  — a mesma informação já estava por candidato, mas nenhum consumidor a
  isolava.
- `OrchestrationService.race_card` registra um evento `CandidateFailed` por
  candidato perdido (executor, branch, erro), rastreável mesmo depois que o
  ring de corridas (`_prune_races`) descartar a entrada.
- `next_step.py` ganha `_race_blocker` → bloqueio `corrida_degradada`
  (severidade `acao_do_operador`) quando a corrida mais recente de um card
  ainda aberto (não `Done`) perdeu candidato — corrida degradada num card já
  mesclado é histórico, não bloqueio.
- UI (`index.html`): tanto a corrida ao vivo quanto o histórico mostram
  "N de M candidatos concluíram" em destaque quando há falha, em vez de só
  listar os vencedores.

## Consequências

**Positivas**
- Bug real corrigido, não só mascarado: o mesmo `BrokenPipeError` podia
  atingir um executor CLI real de produção que saísse rápido (erro de
  configuração, flag inválida) antes de ler stdin — não era exclusivo dos
  comandos de teste.
- `DIAG_DIFF_VAZIO`/roteamento de falha (ADR-0019) deixam de ser acionados por
  um artefato do runtime: antes, um `BrokenPipeError` classificado como falha
  do executor podia disparar retry e troca de executor por um motivo que não
  tinha nada a ver com o agente.
- Suíte completa rodada 5× seguidas após a correção: 781 passed em todas,
  incluindo o teste de estresse (`ASO_RACE_STRESS_N=20`, 60 execuções de
  candidato por rodada da suíte).
- `tests/integration/test_race_stress.py` fica na suíte permanentemente —
  qualquer regressão futura no envio de tarefa ao executor CLI reprova aqui
  antes de virar um "teste flaky" reportado por acaso.

**Negativas / riscos aceitos**
- O teste de estresse adiciona ~1-2s à suíte (20 rodadas × 3 candidatos por
  execução) — aceito: é o único teste desta ADR que prova a correção sob
  repetição, não é cortável.
- `corrida_degradada` só olha a corrida mais recente por card em `next_step`;
  uma corrida antiga degradada num card ainda aberto que foi seguida por uma
  corrida bem-sucedida não aparece mais (comportamento desejado — a corrida
  mais recente é a que importa) mas não há um "histórico de degradações"
  agregado na tela, só no event log.
