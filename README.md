# Marketplace Intelligence — case de LLMOps e confiabilidade

Projeto de Diego Aquino para apoiar pesquisa de anúncios e preparação de rascunhos de e-commerce.
O foco deste case é transformar um protótipo em um serviço **testável e observável**, com contratos de dados e tratamento de falhas.

**Status:** demonstração local e referência de implementação. Não é evidência de operação em produção, SLA cumprido, ganho de conversão ou experiência em treinamento de modelos.

## Comece pela demonstração

Python **3.12**. Na raiz do repositório:

~~~powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m pytest
python -m evaluation.run --output evaluation-report.json
python -m streamlit run app/radar_app.py
~~~

No dashboard, clique em **Carregar demonstração offline**. Os dados são sintéticos, sem chave de API ou consulta ao marketplace. As dependências precisam estar instaladas antes da apresentação.

Para usar a aba de rascunhos, inicie a API em outro terminal, com o mesmo ambiente:

~~~powershell
$env:SERVICE_API_TOKEN = python -c "import secrets; print(secrets.token_urlsafe(32))"
$env:LLM_MODE = "demo"
python -m uvicorn intelligence.api:create_app --factory --host 127.0.0.1 --port 8001
~~~

Guarde o token gerado e informe-o no dashboard. Alternativamente, configure a mesma variável nos dois terminais.
No Linux/macOS, ative o ambiente com `source .venv/bin/activate` e use `export NOME=valor`.

A documentação interativa fica em [localhost:8001/docs](http://localhost:8001/docs).
Autentique pelo botão **Authorize** para executar `POST /v1/drafts`:

~~~json
{
  "name": "Body feminino",
  "details": "Cor preta. Manga longa.",
  "material": null
}
~~~

O modo `demo` é uma **fixture determinística**, não uma chamada de IA. A resposta inclui `requires_review: true`, versão do prompt e latência. Tokens/custo desconhecidos aparecem como `null`, nunca como zero inventado.

## Arquitetura do case

~~~mermaid
flowchart LR
  DATA[HTML público ou fixture sintética] --> PARSER[Parser e normalização]
  PARSER --> UI[Dashboard Streamlit]
  UI --> PRICE[Precificação determinística]
  UI --> API[FastAPI autenticada]
  API --> LIMIT[Concorrência limitada e circuit breaker]
  LIMIT --> MODEL[Adapter Demo ou Gemini]
  MODEL --> VALID[Schema e material confirmado]
  VALID --> REVIEW[Rascunho para revisão humana]
  API --> OBS[Métricas Prometheus e logs sem conteúdo]
~~~

- `app/scraping.py`: parser separado da rede; preço atual com centavos; campos ausentes; deduplicação; limite de 500 itens/10 páginas; timeout; pausa; falhas explícitas.
- `app/pricing.py`: cálculos em Decimal, validação de parâmetros e contrato compatível com o protótipo.
- `intelligence/`: API, contratos Pydantic, prompt versionado, adapters de provedor e controles de confiabilidade.
- `evaluation/`: cinco casos sintéticos de regressão de contrato e afirmações proibidas; gera relatório e código de saída para CI.
- `tests/`: casos de preço, HTML incompleto, erros HTTP, auth, saída inválida, timeout, circuit breaker, concorrência e dashboard.
- `monitoring/`, `deploy/`: regras de alerta e exemplo Kubernetes para homologação.

O dashboard não publica anúncios. Os scripts originais em `agentes/`, `integracoes/`, `rpa/` e `api/jarvis_api.py` foram preservados como **experimentos legados**, fora do caminho de demonstração e sem as garantias do novo serviço. Alguns fazem uploads/publicações reais quando executados com credenciais. Não estão incluídos na imagem Docker do case.

A antiga SWOT direta no dashboard foi substituída pelo fluxo de rascunho observável. Não há conclusão automática sobre monopólio ou participação de mercado a partir da amostra.

## Inferência real, quando desejada

Configure as variáveis antes de iniciar o serviço (o serviço não carrega `.env` automaticamente):

~~~powershell
$env:LLM_MODE = "gemini"
$env:GEMINI_API_KEY = "sua-chave"
$env:GEMINI_MODEL = "gemini-2.5-flash"
~~~

`SERVICE_API_TOKEN` continua obrigatório. O modelo é configurável; disponibilidade e acesso dependem da sua conta.
Chamadas reais enviam os dados informados ao provedor e podem gerar custo.

Controles implementados:
- timeout de 20s configurável, limite de saída de 2048 tokens e nenhuma repetição automática de chamadas faturáveis;
- até quatro gerações simultâneas por processo; excesso retorna 503;
- após três falhas consecutivas, circuito aberto por 30s; uma tentativa de prova após o intervalo;
- 502 para saída inválida; 503 para indisponibilidade; 504 para timeout;
- material da saída deve coincidir exatamente com o material informado; ausência permanece `null`;
- token Bearer na geração e nas métricas; revisão humana obrigatória no contrato;
- nenhuma ferramenta de publicação conectada ao LLM.

**Limite da validação:** JSON válido e material correto não garantem que todas as frases sejam verdadeiras. Prompt injection e alucinações semânticas ainda exigem avaliação adversarial e revisão humana.

## Avaliação

~~~powershell
python -m evaluation.run --output evaluation-report.json
# Opcional, com credenciais e custo de inferência:
python -m evaluation.run --live --output evaluation-live-report.json
~~~

A execução padrão verifica o pipeline com fixture; **100% nessa suíte não representa acurácia do Gemini**.
A execução `--live` mede um conjunto pequeno: tamanho do título, material, revisão humana e termos proibidos.
Não há LLM-as-judge, avaliação humana automatizada, dados rotulados de clientes, medição de drift nem fine-tuning.
Veja o [roteiro da entrevista](docs/entrevista.md) para discutir esses limites e a evolução.

## Observabilidade e operação

`GET /metrics` exporta:
- tentativas por resultado e histograma de latência;
- tokens de entrada/saída reportados pelo provedor, incluindo thinking tokens na saída quando disponíveis;
- estimativa de custo e contagem de respostas sem usage completo;
- gerações em andamento.

Para estimar custo, configure `LLM_INPUT_PRICE_PER_MILLION` e `LLM_OUTPUT_PRICE_PER_MILLION` com tarifas conferidas para o modelo/conta. Sem ambas, o custo permanece desconhecido. Essa fórmula simplificada não reconcilia descontos, cache, faixas de preço ou fatura.
Custos de respostas rejeitadas são contados quando o provedor retorna usage; falhas sem usage não podem ser contabilizadas com precisão.

Logs `intelligence` usam JSON com request ID, resultado, modo e latência. Configure nível INFO no coletor/logging do servidor para capturá-los. Não incluem prompt, resposta ou segredo.

[Runbook e SLOs propostos](docs/operacao.md) descrevem indicadores, incidentes, rollback e limites.

## Container e Kubernetes

~~~powershell
docker build -t marketplace-intelligence:case .
docker run --rm -p 127.0.0.1:8001:8001 -e SERVICE_API_TOKEN -e LLM_MODE=demo marketplace-intelligence:case
~~~

A imagem executa como usuário não root e inclui apenas o serviço de rascunhos.
O CI executa testes, avaliação offline e build da imagem. Nenhuma credencial de inferência é necessária no CI.

`deploy/kubernetes.yaml` é um exemplo sem Ingress público. Antes de aplicar, substitua a imagem por uma versão publicada, crie o Secret indicado e dimensione recursos por teste de carga.
Duas réplicas não demonstram alta disponibilidade por si só: ainda faltam distribuição entre nós/zonas, políticas de rede, TLS, controle de taxa por cliente, coleta de métricas e teste de falhas do cluster.
Circuit breaker e limite de concorrência são por processo, não globais. Use um worker por pod neste exemplo.

## Premissas de preço e dados

A fórmula original calcula **retorno sobre custo**, não margem sobre receita:

~~~text
preço-alvo = (custo × (1 + retorno/100) + taxa_fixa) / (1 - taxa_percentual)
preço-vitrine = preço-alvo / (1 - desconto/100)
~~~

Taxas são hipóteses editáveis, não tabela oficial. Frete, impostos e devoluções estão fora do cálculo. Kit considera uma taxa fixa por venda.
Valores são exibidos com duas casas; antes de uma cobrança real, defina política de arredondamento monetário.
As vendas públicas são aproximadas e sem período conhecido; ausência não significa zero vendas.
Anúncios e kits não são necessariamente comparáveis. A coleta não representa todo o mercado.

## Próximos passos priorizados

1. Homologar o adapter com chamadas reais e avaliação humana de um conjunto representativo.
2. Configurar telemetria, TLS, secrets manager e limites de custo/taxa por cliente.
3. Medir carga e disponibilidade antes de assumir SLO/SLA externo.
4. Persistir jobs, aprovação e auditoria; adicionar fila e orquestração quando houver tarefas longas e reprocessamento.
5. Medir mudança na distribuição dos inputs e qualidade; avaliar RAG apenas se houver base factual versionada relevante.

Desenvolvido por [Diego Aquino](https://github.com/diaquinodev).
