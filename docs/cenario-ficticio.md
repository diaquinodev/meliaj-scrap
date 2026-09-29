# VitrineOps — briefing fictício

**Projeto:** Assistente de Catálogo com IA  
**Organização do cenário:** Aurora Moda, empresa fictícia  
**Natureza:** exercício de engenharia e portfólio; não é um relato de contratação ou cliente real.

## Contexto

A Aurora Moda prepara uma coleção de roupas para vender em marketplaces. A equipe recebe nomes, cores e materiais em fichas de produto que nem sempre estão completas. Antes de publicar, precisa comparar ofertas, avaliar hipóteses de preço e revisar a descrição de cada peça.

No cenário fictício, o trabalho manual gera inconsistências no catálogo. Uma automação que invente material, garantia ou prazo de entrega também criaria problemas. O projeto explora como ajudar a equipe mantendo uma pessoa responsável pela revisão.

## Pessoas envolvidas no cenário

- **Analista de catálogo:** informa fatos confirmados e solicita um rascunho.
- **Responsável comercial:** simula preço e revisa as premissas de taxas e retorno.
- **Operações de tecnologia:** acompanha erros, latência e consumo, investigando falhas do serviço.

Esses papéis são parte da hipótese de produto. Não correspondem a depoimentos ou usuários entrevistados.

## Jornada demonstrável

1. A analista abre o VitrineOps com uma amostra sintética de ofertas.
2. Ajusta custo, taxas hipotéticas e retorno desejado para compreender o preço calculado.
3. Informa “Body feminino”, “Cor preta. Manga longa.” e deixa o material vazio quando não há confirmação.
4. Solicita o rascunho. O serviço valida os dados, limita a concorrência e chama o provedor configurado.
5. Recebe texto para revisão, com versão do prompt, latência e uso de tokens quando informado pelo provedor.
6. A publicação permanece fora desse fluxo. O serviço não concede ao modelo ferramentas para publicar anúncios.

No modo demo, a etapa de inferência usa um gerador determinístico e não um LLM. A API e a comunicação com o dashboard continuam sendo reais.

## Critérios de aceitação do exercício

| Necessidade proposta | Evidência disponível |
| --- | --- |
| Apresentação sem dependência de credenciais externas | Comando único de demonstração e dados sintéticos |
| Não preencher material por suposição | Campo opcional e checagem de correspondência na saída |
| Interromper chamadas a um provedor com falhas repetidas | Circuit breaker e testes de recuperação |
| Evitar acúmulo ilimitado de inferências | Limite de concorrência com resposta explícita |
| Investigar falhas sem registrar conteúdo do produto | Request ID e logs de resultado/latência |
| Verificar o serviço distribuído como container | Build e smoke test HTTP no GitHub Actions |
| Manter decisões comerciais compreensíveis | Fórmula de retorno sobre custo e premissas documentadas |

## Como avaliar resultado sem inventar métricas

Neste estágio, a evidência é técnica: testes automatizados, relatório da suíte sintética, respostas HTTP e execução do container. Não há dados para afirmar aumento de vendas, redução de horas, diminuição de erros humanos ou disponibilidade em produção.

Uma futura validação com usuários poderia medir tempo de preparação por item, quantidade de correções feitas na revisão, taxa de afirmações sem suporte e custo por rascunho aprovado. Essas são propostas de medição, não resultados já obtidos.

## Fora do escopo implementado

Treinamento de modelos, fine-tuning, RAG, integração com ERP, fila durável, aprovação persistida, publicação automática e implantação real em cluster. O manifesto Kubernetes é uma referência de homologação. A integração Gemini ainda precisa de avaliação real de qualidade.
