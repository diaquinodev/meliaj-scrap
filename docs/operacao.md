# VitrineOps — operação e confiabilidade

## Escopo

Serviço síncrono de rascunhos do case fictício Aurora Moda, uma chamada de provedor por solicitação aceita.
Não publica anúncios nem persiste dados. Sem fila durável, SLA contratado ou implantação comprovada.

## SLOs propostos para homologação

Metas iniciais a revisar após medir tráfego real, em janela de 30 dias:

| Indicador | Meta proposta | Medição |
| --- | --- | --- |
| Disponibilidade da geração | >= 99% | success / todas as tentativas autenticadas e com input válido que chegam ao serviço |
| Latência | >= 95% em até 10 s | histograma llm_request_duration_seconds |
| Contrato válido | >= 99% das respostas retornadas pelo provedor | rejeições invalid_output / respostas recebidas |
| Qualidade semântica | Meta a definir com amostragem humana | A suíte de contrato não mede esse SLI |

Tentativas busy/circuit_open/timeout/provider_error contam contra disponibilidade.
401/422 não entram no denominador do serviço. Falhas de rede/Ingress antes da aplicação e pods ausentes não aparecem nesses contadores: acrescente métricas do gateway e probe externa para SLO ponta a ponta.
Latência inclui rejeições rápidas; analise também disponibilidade para não interpretar um serviço que rejeita tudo rapidamente como saudável.
`/health/ready` verifica configuração/startup, não chama o provedor e não promete disponibilidade externa.

A meta de 99% admite até 1% de tentativas elegíveis com falha. Isso é um orçamento por requisições, não uma promessa de minutos de indisponibilidade.
As regras em monitoring/alerts.yml usam janela curta para diagnóstico; não são alertas completos de burn rate em múltiplas janelas.

## Coleta

- Faça scrape autenticado de `/metrics` em cada pod. Use Bearer token via Secret/arquivo, sem colocar a credencial no YAML versionado.
- Agregue métricas entre réplicas; não faça scrape apenas do Service com balanceamento, que pode alternar entre contadores diferentes.
- Não use request IDs ou nomes de produtos como labels.
- Configure logging INFO para o logger `intelligence`; logs não devem incluir entrada ou saída do modelo.
- Tokens faltantes e custos desconhecidos precisam aparecer no painel. Não são custo zero.
- No exemplo, cada pod executa um worker. Contadores, limite e circuit breaker são locais ao processo.

## Resposta a incidente

1. Registrar início, versão da imagem, versão de prompt e request IDs.
2. Verificar taxa de erro, p95, in-flight, consumo de tokens e estado do provedor.
3. Classificar:
   - 401: autenticação do cliente; verificar configuração sem copiar credenciais para logs;
   - 422: contrato de entrada;
   - 502: saída inválida; avaliar schema/prompt/modelo e amostra sanitizada;
   - 503 busy: capacidade local; revisar concorrência antes de escalar;
   - 503 provider_error/circuit_open: dependência externa; evitar loops de retry;
   - 504: orçamento de tempo; investigar provedor e rede;
   - 500: erro de implementação; correlacionar request ID sem expor conteúdo.
4. Mitigar: interromper geração ou reverter a última versão. Não trocar para demo sem informar consumidores.
5. Validar recuperação com tráfego controlado e avaliação; encerrar incidente somente após estabilização.

## Deploy e rollback

Pipeline proposto: testes -> avaliação offline -> build -> homologação com avaliação real e carga -> aprovação operacional -> deploy gradual.
O workflow incluído termina em um smoke test HTTP do container; não publica imagem nem faz deploy. O smoke test aceita somente loopback e recusa inferência se o serviço não estiver em modo demo.

Antes de exposição externa: TLS, gateway com limite de corpo/taxa por cliente, secret manager, RBAC conforme necessidade, network policies, coleta de métricas, limites de custo e proteção de logs.
Bearer compartilhado é suficiente para a demo local, não representa identidade/autorização por cliente.

Publicar uma imagem imutável por digest. Manter versão anterior e configuração associada.
Rollback: restaurar o digest/configuração anteriores, verificar readiness, rodar smoke test e observar erros/latência.
Não alterar prompt diretamente em runtime sem uma versão rastreável.

## Modelo de postmortem (não é incidente real)

- Resumo e período:
- Impacto medido, solicitações elegíveis e falhas:
- Detecção e lacunas de alerta:
- Linha do tempo com evidências:
- Causa e fatores contribuintes:
- Mitigação e critérios de recuperação:
- Ações com responsável, prazo e critério de verificação:
- O que funcionou e o que deve mudar:

## Limitações conhecidas

- Estado e métricas reiniciam com o processo; circuit breaker não coordena réplicas.
- Não há idempotência persistente; repetir manualmente uma geração pode gerar nova cobrança.
- Timeout no cliente não garante cancelamento/faturamento zero no provedor.
- Serviço não limita orçamento monetário global; apenas tamanho de input/saída e concorrência.
- Não há reconciliação de fatura, fila, dados rotulados, monitoramento de drift ou avaliação humana implantada.
- Dependências diretas são fixadas; transitivas e imagem-base ainda não usam lock/digest.
