# VitrineOps — roteiro do case para a entrevista na EVEO

Apresente como projeto de portfólio aplicado à **Aurora Moda, empresa fictícia**. A história de negócio é simulada; as decisões de implementação e os testes são demonstráveis.

## Demonstração de 8–10 minutos

Antes de começar, execute `python -m scripts.demo --check`. Para apresentar, use `python -m scripts.demo --open`: API e dashboard iniciam juntos, com dados sintéticos e token temporário. Não depende de uma conta Gemini. Ctrl+C encerra ambos.

1. **Problema (1 min):** a Aurora Moda, empresa fictícia, precisa preparar uma nova coleção para marketplaces. Explique como fichas incompletas e revisão manual motivam o case, deixando claro que é uma hipótese de negócio.
2. **Antes/depois (2 min):** o protótipo misturava UI, scraping e IA. Preços perdiam centavos e erros eram silenciados. Mostre parser separado, teste de card incompleto e simulação de preço.
3. **Fluxo de IA (2 min):** abra a aba **Rascunho com IA** no dashboard e clique em gerar. Mostre modo demo, contrato, prompt versionado e revisão humana. Declare que demo não chama um modelo.
4. **Confiabilidade (2 min):** rode os testes de timeout e circuit breaker. Explique por que 503 é preferível a acumular trabalho sem limite e por que retries de inferência não são automáticos.
5. **LLMOps (2 min):** abra o relatório de avaliação e /metrics. Diferencie schema válido, qualidade semântica, latência, consumo e custo estimado.
6. **Limites (1 min):** explique o que ainda falta para produção: eval real/humana, testes de carga, observabilidade integrada, gestão de segredos e rollout validado.

## Como relacionar à vaga sem exagerar

### Abertura sugerida

> Desenvolvi o VitrineOps como um case de portfólio para uma empresa fictícia de moda. O objetivo foi tratar a geração de anúncios como um serviço de engenharia: com dados de entrada limitados, contrato de saída, revisão humana, tratamento de falhas e observabilidade. Na demonstração uso dados sintéticos; o foco é explicar as decisões e comprovar o comportamento com testes, incluindo comunicação HTTP real e o container no CI.

| Responsabilidade | Evidência neste case | Limite a declarar |
| --- | --- | --- |
| Integrações de IA via API | FastAPI, adapter Gemini e schema Pydantic | Adapter configurado/testado com mocks; resultados reais exigem homologação |
| LLMOps e avaliação | Prompt versionado, suíte JSON e gate de CI | Cinco casos sintéticos; não é benchmark de qualidade |
| SRE | Timeout, concorrência, circuit breaker, probes e runbook | Sem histórico real de on-call ou SLO atingido |
| Observabilidade | Prometheus, request ID, tokens e estimativa de custo | Sem painel/collector implantado nem drift monitorado |
| Docker/Kubernetes | Dockerfile não root, smoke test HTTP do container no CI e manifesto de referência | O cluster ainda precisa ser validado no ambiente de destino |
| Governança | Auth, dados ausentes explícitos, revisão humana, sem publicação no fluxo | Sem RBAC por usuário ou trilha persistente de aprovação |
| Pipelines/orquestração | Fluxo síncrono definido e avaliação reproduzível | Não usa Airflow/Prefect nem processamento durável |
| ML/RAG/fine-tuning/cloud | Discussão de critérios e próximos passos | Não implementados; não use este case como evidência dessas experiências |

## Perguntas que vale praticar

**Por que não LangChain ou um agente com várias ferramentas?**  
O fluxo atual tem uma chamada com saída estruturada. Um adapter pequeno permite testar falhas e trocar o provedor sem introduzir uma abstração que o problema ainda não exige. Agentes com ferramentas fazem sentido quando houver decisões e ações com autorização, idempotência e auditoria.

**Por que não fine-tuning?**  
Primeiro, construir um conjunto de avaliação e identificar erros sistemáticos. Só considerar treinamento se prompt, dados de entrada e recuperação de contexto não resolverem o problema de forma suficiente e econômica.

**Quando usar RAG?**  
Para recuperar dados verificáveis, como catálogo interno e políticas versionadas. O case hoje recebe poucos fatos diretamente. RAG adicionaria ingestão, controle de acesso, atualização e avaliação de recuperação.

**O circuit breaker garante disponibilidade?**  
Não. Ele limita insistência num provedor que falha. Disponibilidade depende também de rede, capacidade, dependências e operação. Um fallback deve preservar qualidade e indicar a origem; por isso não existe troca silenciosa de Gemini para demo.

**Como distinguir margem de retorno sobre custo?**  
Com custo 8, taxa fixa 4 e taxa de 20%, preço-alvo 18 gera resultado 2,40. Isso representa 30% do custo, mas 13,33% da receita. São denominadores diferentes.

**O que fazer com prompt injection?**  
Tratar entrada como dados, limitar saída e poderes, testar ataques e manter revisão. O prompt sozinho não é fronteira de segurança. Este serviço não tem ferramentas de publicação; a checagem de material cobre um caso específico, não toda a semântica.

**Como medir drift?**  
Separar mudança de input (tipos de produto, tamanhos, campos ausentes) de mudança de qualidade (amostras rotuladas por humanos). Definir uma janela de referência, amostragem e alertas antes de escolher a métrica. Isso está planejado, não implementado.

**Qual seria seu primeiro passo em produção?**  
Homologar com tráfego representativo, medir latência/qualidade/custo, definir capacidade e configurar secrets/telemetria. Fazer rollout pequeno com rollback por digest e prompt versionado.

## Honestidade sobre experiência

O case demonstra decisões e código que você deve conseguir explicar. Não substitui os três anos de experiência pedidos nem prova operação real em produção. Se usou assistência de IA para refatoração, explique como revisou as mudanças, executou os testes e compreendeu os limites.
