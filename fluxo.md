# Esteira Operacional Multiagente do ASO

O ASO funciona como uma empresa de desenvolvimento de software automatizada, na qual um agente orquestrador recebe uma demanda, transforma essa demanda em trabalho estruturado e distribui cada atividade para agentes especializados.

Cada etapa possui responsáveis, documentos, critérios de aprovação, testes, revisões e mecanismos de retorno quando algum resultado não atende ao esperado.

## 1. Entrada da demanda

A esteira começa quando uma nova demanda é registrada.

A demanda pode ser:

* Uma nova funcionalidade;
* Uma correção de erro;
* Uma refatoração;
* Uma melhoria de arquitetura;
* Uma alteração de infraestrutura;
* Uma investigação técnica;
* Uma atualização de documentação;
* Uma atividade de segurança;
* Uma melhoria de desempenho;
* Uma solicitação de produto.

O agente orquestrador recebe a demanda e realiza uma análise inicial para identificar:

* Objetivo da solicitação;
* Problema que precisa ser resolvido;
* Resultado esperado;
* Sistemas e módulos afetados;
* Dependências;
* Riscos;
* Critérios de aceite;
* Necessidade de aprovação humana;
* Nível estimado de complexidade.

Quando a demanda estiver incompleta, o orquestrador poderá solicitar informações adicionais antes de iniciar a execução.

## 2. Classificação da demanda

O orquestrador classifica a demanda por tipo, prioridade, risco e complexidade.

Exemplos de classificação:

* Tipo: funcionalidade, correção, arquitetura, infraestrutura ou documentação;
* Prioridade: baixa, média, alta ou crítica;
* Risco: baixo, moderado, alto ou crítico;
* Complexidade: simples, intermediária, complexa ou estratégica;
* Impacto: isolado, parcial ou sistêmico.

Essa classificação ajuda a determinar quais agentes, modelos e níveis de effort serão utilizados.

## 3. Discovery e análise do projeto

Antes de criar tarefas de implementação, um agente é responsável por analisar o contexto da demanda.

Esse agente poderá investigar:

* Estrutura atual do projeto;
* Código existente;
* Documentação disponível;
* Regras de negócio;
* Arquitetura;
* Banco de dados;
* APIs;
* Dependências externas;
* Infraestrutura;
* Testes existentes;
* Padrões adotados pelo projeto;
* Riscos de compatibilidade;
* Impactos em outras funcionalidades.

Ao final, o agente produz um relatório de discovery.

O documento de discovery deve apresentar:

* Situação atual;
* Problema identificado;
* Componentes afetados;
* Restrições;
* Riscos;
* Alternativas possíveis;
* Recomendação técnica;
* Pontos que precisam de decisão.

## 4. Aprovação do discovery

O relatório de discovery passa por uma aprovação.

A aprovação pode ser automática quando:

* A demanda é de baixo risco;
* O escopo está claro;
* Não há mudança relevante de arquitetura;
* Não há impacto financeiro, jurídico ou operacional;
* A solução segue padrões já aprovados.

A aprovação deve ser humana quando:

* A demanda altera arquitetura;
* Existe mais de uma solução viável com impactos diferentes;
* Há mudança significativa de custo;
* Existe risco de perda de dados;
* A alteração afeta segurança, privacidade ou permissões;
* A demanda modifica regras importantes de negócio;
* O agente apresenta baixa confiança na recomendação.

Quando o documento não for aprovado, ele retorna para o agente responsável pelo discovery com os comentários da revisão.

O agente ajusta o documento e o submete novamente.

## 5. Criação da especificação

Com o discovery aprovado, um agente de análise ou arquitetura cria a especificação da solução.

Dependendo da demanda, podem ser gerados:

* Documento de requisitos;
* Especificação funcional;
* Especificação técnica;
* Documento de arquitetura;
* Diagrama de componentes;
* Diagrama de fluxo;
* Modelo de dados;
* Contrato de API;
* Plano de migração;
* Plano de testes;
* Plano de implantação;
* Plano de rollback;
* Checklist de segurança.

A especificação deve definir claramente:

* O que será construído;
* O que não faz parte do escopo;
* Como a solução deve funcionar;
* Critérios de aceite;
* Regras de negócio;
* Componentes envolvidos;
* Alterações esperadas no código;
* Alterações esperadas no banco;
* Alterações de infraestrutura;
* Estratégia de testes;
* Estratégia de implantação.

## 6. Revisão e aprovação dos documentos

Os documentos criados são revisados antes da implementação.

Um agente revisor verifica:

* Consistência;
* Completude;
* Viabilidade;
* Segurança;
* Compatibilidade com o projeto;
* Clareza dos critérios de aceite;
* Presença de plano de testes;
* Presença de plano de rollback;
* Ausência de contradições.

A revisão documental pode resultar em:

* Aprovado;
* Aprovado com observações;
* Reprovado;
* Necessita decisão humana.

Quando o documento é reprovado, ele volta para o agente que o produziu.

O ciclo continua até que o documento seja aprovado.

## 7. Decomposição em épicos, histórias e tarefas

Após a aprovação da solução, o agente orquestrador transforma a especificação em itens de trabalho.

A estrutura pode ser:

* Projeto;
* Épico;
* História;
* Card;
* Subtarefa;
* Checklist.

Exemplo:

**Épico:** Implementar autenticação por OAuth.

**Cards:**

1. Criar configuração do provedor OAuth;
2. Implementar endpoint de login;
3. Implementar callback;
4. Criar persistência de tokens;
5. Implementar renovação de token;
6. Criar testes unitários;
7. Criar testes de integração;
8. Atualizar documentação;
9. Configurar ambiente;
10. Preparar implantação.

Cada card deve possuir:

* Título;
* Descrição;
* Objetivo;
* Contexto;
* Dependências;
* Critérios de aceite;
* Arquivos ou módulos envolvidos;
* Riscos;
* Prioridade;
* Estimativa de complexidade;
* Agente responsável;
* Modelo selecionado;
* Nível de effort;
* Status;
* Evidências esperadas.

## 8. Criação dos cards no Kanban

O orquestrador cria os cards no Kanban e posiciona cada um na etapa adequada.

Exemplo de colunas:

1. Backlog;
2. Em análise;
3. Aguardando aprovação;
4. Pronto para desenvolvimento;
5. Em desenvolvimento;
6. Em testes;
7. Em revisão;
8. Aguardando correção;
9. Pronto para implantação;
10. Em implantação;
11. Em validação;
12. Concluído;
13. Bloqueado;
14. Cancelado.

O status do card deve ser atualizado automaticamente durante a execução.

Cada movimentação precisa registrar:

* Data;
* Agente responsável;
* Motivo da alteração;
* Resultado obtido;
* Evidências;
* Próxima ação.

## 9. Seleção do agente, modelo e effort

Para cada card, o orquestrador escolhe o agente mais adequado.

Os agentes podem utilizar Codex ou Claude, com modelos como:

* Sonnet;
* Opus;
* Luna;
* Terra;
* Sol.

O orquestrador também define o nível de effort permitido para o modelo selecionado.

A escolha considera:

* Complexidade da tarefa;
* Quantidade de contexto;
* Risco de erro;
* Necessidade de raciocínio;
* Necessidade de leitura extensa de código;
* Necessidade de geração de código;
* Necessidade de revisão;
* Custo;
* Tempo;
* Confiabilidade esperada.

Exemplo de distribuição:

### Tarefas simples

Exemplos:

* Ajustes pequenos;
* Alteração de texto;
* Criação de testes básicos;
* Atualização de documentação;
* Correções locais.

Podem utilizar modelos mais rápidos, com effort baixo ou médio.

### Tarefas intermediárias

Exemplos:

* Implementação de endpoints;
* Regras de negócio;
* Integrações conhecidas;
* Refatorações controladas;
* Correção de bugs moderados.

Podem utilizar Sonnet, Luna ou Terra, com effort médio ou alto.

### Tarefas complexas

Exemplos:

* Arquitetura;
* Concorrência;
* Segurança;
* Migração de dados;
* Debugging avançado;
* Refatoração sistêmica;
* Alterações críticas de infraestrutura.

Podem utilizar Opus ou Sol, com effort alto ou máximo.

## 10. Preparação para implementação

Antes de alterar o código, o agente responsável pelo card deve:

* Ler a especificação;
* Ler os critérios de aceite;
* Analisar o código afetado;
* Identificar dependências;
* Verificar testes existentes;
* Criar ou utilizar uma branch;
* Registrar um plano de execução;
* Validar que o card está desbloqueado.

Se houver uma dependência pendente, o card é movido para “Bloqueado”.

O orquestrador identifica a dependência e cria uma tarefa adicional para resolvê-la.

## 11. Implementação

O agente inicia a implementação seguindo o card.

Durante a execução, ele deve:

* Alterar apenas o escopo necessário;
* Manter os padrões do projeto;
* Adicionar ou atualizar testes;
* Atualizar documentação quando necessário;
* Evitar mudanças não relacionadas;
* Registrar decisões técnicas;
* Registrar limitações;
* Executar validações locais.

O agente deve produzir como evidência:

* Arquivos alterados;
* Resumo da implementação;
* Decisões tomadas;
* Testes adicionados;
* Testes executados;
* Resultados;
* Riscos conhecidos.

## 12. Validações automáticas

Quando a implementação termina, a esteira executa automaticamente os quality gates.

Exemplos:

* Formatação;
* Lint;
* Compilação;
* Type checking;
* Testes unitários;
* Testes de integração;
* Testes de contrato;
* Testes end-to-end;
* Análise estática;
* Verificação de dependências;
* Scan de vulnerabilidades;
* Validação de migrations;
* Validação de documentação;
* Verificação de cobertura;
* Testes de desempenho, quando aplicável.

Caso todas as validações passem, o card avança para revisão.

Caso alguma validação falhe, o card retorna para “Aguardando correção”.

## 13. Tratamento de falhas nos testes

Quando um teste falha, a esteira registra:

* Comando executado;
* Teste que falhou;
* Mensagem de erro;
* Stack trace;
* Arquivos relacionados;
* Ambiente;
* Tentativas anteriores;
* Alteração que possivelmente causou a falha.

O orquestrador decide se:

* O mesmo agente deve corrigir;
* Outro agente deve investigar;
* Um modelo mais avançado deve ser utilizado;
* O effort deve ser aumentado;
* O problema deve ser escalado para revisão humana.

O card retorna para a etapa de implementação.

Após a correção, todos os testes relevantes são executados novamente.

Não apenas o teste que falhou.

## 14. Revisão de código

Depois que os testes passam, um agente diferente realiza o code review.

O revisor avalia:

* Correção da implementação;
* Aderência aos requisitos;
* Qualidade do código;
* Clareza;
* Manutenibilidade;
* Segurança;
* Tratamento de erros;
* Performance;
* Uso correto de padrões;
* Cobertura de testes;
* Risco de regressão;
* Mudanças fora de escopo.

O agente que implementou o código não deve ser o único responsável pela aprovação.

O review pode resultar em:

* Aprovado;
* Aprovado com sugestões;
* Alterações obrigatórias;
* Reprovado;
* Necessita revisão humana.

## 15. Código reprovado no review

Quando o código não passa no review, o card volta para “Aguardando correção”.

Os comentários do revisor são transformados em ações objetivas.

Exemplo:

* Corrigir tratamento de exceção;
* Remover duplicação;
* Adicionar teste para cenário de erro;
* Ajustar nome de método;
* Reduzir acoplamento;
* Corrigir falha de segurança;
* Atualizar documentação.

O agente responsável aplica as correções e devolve o card para:

1. Testes automáticos;
2. Nova revisão de código.

Esse ciclo continua até a aprovação.

## 16. Testes manuais

Quando necessário, o card passa por testes manuais.

Os testes podem ser realizados por:

* Um agente de QA;
* Um usuário humano;
* Um responsável de produto;
* Um especialista de negócio.

Os testes manuais verificam aspectos que podem não ser cobertos completamente por automação, como:

* Experiência do usuário;
* Fluxos visuais;
* Regras complexas;
* Compatibilidade com dispositivos;
* Comportamento em ambiente real;
* Validação de integrações externas;
* Aceitação de negócio.

O responsável registra:

* Cenário testado;
* Passos executados;
* Resultado esperado;
* Resultado obtido;
* Evidências;
* Erros encontrados.

## 17. Falha em teste manual

Quando o teste manual falha, é criado um bug ou subtarefa vinculada ao card original.

O item deve informar:

* Como reproduzir;
* Ambiente;
* Evidências;
* Resultado atual;
* Resultado esperado;
* Gravidade;
* Impacto.

O orquestrador atribui o bug a um agente.

Após a correção, o fluxo volta para:

* Implementação;
* Testes automáticos;
* Code review;
* Teste manual.

A etapa exata de retorno depende do tipo de falha.

## 18. Aprovação para implantação

Com código, testes e revisão aprovados, o card fica pronto para implantação.

Antes do deploy, a esteira verifica:

* Pull request aprovado;
* Testes aprovados;
* Migrations validadas;
* Variáveis de ambiente configuradas;
* Documentação atualizada;
* Plano de rollback disponível;
* Dependências implantadas;
* Janela de implantação;
* Aprovação humana, quando necessária.

Mudanças de baixo risco podem ser liberadas automaticamente.

Mudanças críticas exigem aprovação humana.

## 19. Implantação

A implantação pode ocorrer em etapas:

1. Ambiente de desenvolvimento;
2. Ambiente de testes;
3. Homologação;
4. Staging;
5. Produção.

Durante o deploy, a esteira registra:

* Versão;
* Commit;
* Branch;
* Ambiente;
* Horário;
* Responsável;
* Logs;
* Resultado;
* Tempo de execução.

Se a implantação falhar, o card retorna para a etapa responsável pela falha.

Exemplos:

* Falha de build: volta para implementação;
* Falha de configuração: volta para infraestrutura;
* Falha de migration: volta para banco de dados;
* Falha de teste pós-deploy: volta para correção;
* Falha crítica em produção: executa rollback.

## 20. Validação pós-implantação

Depois do deploy, são executadas validações de saúde.

Exemplos:

* Health check;
* Smoke tests;
* Testes de rota;
* Testes de autenticação;
* Verificação de logs;
* Verificação de métricas;
* Verificação de banco;
* Validação de filas;
* Validação de integrações;
* Monitoramento de erros.

Se tudo estiver correto, o card avança para conclusão.

Caso seja identificado um problema, o orquestrador classifica a gravidade e inicia a correção.

## 21. Rollback

Quando uma implantação causa erro grave, a esteira pode executar rollback.

O rollback pode envolver:

* Retorno da aplicação para a versão anterior;
* Reversão de configuração;
* Desativação por feature flag;
* Restauração de banco;
* Suspensão de filas;
* Desativação temporária de integração.

Depois do rollback, é aberta uma tarefa de análise de causa raiz.

A demanda só volta para produção após nova implementação, testes e aprovação.

## 22. Aceite final

Após a validação técnica, ocorre o aceite final.

O aceite pode ser:

* Automático, quando todos os critérios mensuráveis foram atendidos;
* Humano, quando é necessário validar comportamento, resultado de negócio ou experiência.

O aceite confirma que:

* Os critérios foram atendidos;
* Os testes passaram;
* O comportamento está correto;
* A documentação foi atualizada;
* A implantação foi concluída;
* Não existem pendências bloqueadoras.

## 23. Encerramento do card

Quando aprovado, o card é movido para “Concluído”.

O encerramento deve conter:

* Resumo do que foi entregue;
* Agentes utilizados;
* Modelos utilizados;
* Effort utilizado;
* Commits;
* Pull requests;
* Documentos produzidos;
* Testes executados;
* Evidências;
* Data de implantação;
* Decisões técnicas;
* Riscos residuais;
* Pendências futuras.

## 24. Aprendizado da esteira

Ao final de cada demanda, o orquestrador analisa o desempenho da execução.

Ele avalia:

* Quantidade de retrabalho;
* Falhas por etapa;
* Modelos que tiveram melhor desempenho;
* Effort necessário;
* Tempo gasto;
* Qualidade das entregas;
* Taxa de aprovação;
* Quantidade de intervenções humanas;
* Tipos de erro recorrentes.

Essas informações podem ser utilizadas para melhorar futuras decisões.

Exemplos:

* Aumentar o effort para tarefas de determinada categoria;
* Evitar um modelo em tarefas específicas;
* Criar novos templates de cards;
* Adicionar novos testes automáticos;
* Alterar critérios de aprovação;
* Criar novos agentes especializados;
* Ajustar regras de roteamento.

# Fluxo resumido

**Demanda recebida**

↓

**Classificação e análise inicial**

↓

**Discovery técnico**

↓

**Aprovação do discovery**

↓

**Criação da especificação e documentos**

↓

**Revisão e aprovação dos documentos**

↓

**Criação do épico e dos cards no Kanban**

↓

**Definição do agente, modelo e effort de cada card**

↓

**Implementação**

↓

**Testes automáticos**

* Falhou: retorna para implementação;
* Passou: segue para code review.

↓

**Code review**

* Reprovado: retorna para implementação e testes;
* Aprovado: segue para testes manuais ou implantação.

↓

**Testes manuais**

* Falhou: cria correção e retorna à implementação;
* Passou: segue para aprovação de implantação.

↓

**Implantação**

* Falhou: retorna à etapa responsável;
* Passou: segue para validação pós-deploy.

↓

**Validação pós-implantação**

* Falhou: correção ou rollback;
* Passou: segue para aceite.

↓

**Aceite final**

↓

**Conclusão do card e da demanda**

# Princípio central

Nenhuma falha encerra silenciosamente a execução.

Quando uma etapa falha, a esteira identifica o ponto de interrupção, registra a causa, define um novo agente ou mantém o agente atual, ajusta o modelo ou o nível de effort quando necessário e retorna para a etapa correta.

Dessa forma, o fluxo não precisa reiniciar completamente.

Ele retorna exatamente ao ponto responsável pelo erro e repete as validações necessárias até que a demanda seja aprovada ou formalmente bloqueada.
