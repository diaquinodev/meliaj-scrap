import requests
import json
import os
import google.generativeai as genai

# --- CONFIGURAÇÕES ---
TOKEN_FILE = "meli_tokens.json"
GEMINI_API_KEY = "AIzaSyD7rJNdjuWUB2ZrWUOUEZxdwphdUXEwzTc" # Cole sua chave aqui
genai.configure(api_key=GEMINI_API_KEY)

def load_tokens():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, 'r') as f:
            return json.load(f)
    print("❌ Erro: meli_tokens.json não encontrado. Faça a autenticação primeiro.")
    exit()

def get_ml_data(mlb, access_token):
    headers = {"Authorization": f"Bearer {access_token}"}
    
    print(f"\n🔎 Puxando raio-x do anúncio {mlb} da API do Mercado Livre...")
    
    # 1. Dados Básicos e Tags
    res_item = requests.get(f"https://api.mercadolibre.com/items/{mlb}", headers=headers)
    item_data = res_item.json() if res_item.status_code == 200 else {}
    
    # 2. A Descrição
    res_desc = requests.get(f"https://api.mercadolibre.com/items/{mlb}/description", headers=headers)
    desc_data = res_desc.json() if res_desc.status_code == 200 else {}
    
    # 3. Termômetro de Saúde
    res_health = requests.get(f"https://api.mercadolibre.com/items/{mlb}/health", headers=headers)
    health_data = res_health.json() if res_health.status_code == 200 else {}

    return {
        "titulo": item_data.get("title", "N/A"),
        "preco": item_data.get("price", "N/A"),
        "status": item_data.get("status", "N/A"),
        "tags": item_data.get("tags", []),
        "atributos": [{"nome": a.get("name"), "valor": a.get("value_name")} for a in item_data.get("attributes", [])],
        "descricao": desc_data.get("plain_text", "Sem descrição"),
        "saude": health_data.get("health", "N/A"),
        "acoes_saude": health_data.get("actions", [])
    }

def auditar_com_gemini(dados_ml):
    print("🧠 Injetando dados no Gemini para Auditoria Estrita de Conversão...")
    
    prompt = f"""
    Você é um auditor nível sênior de Mercado Livre e e-commerce de moda.
    Analise os dados deste anúncio e crie um laudo de diagnóstico focado em conversão, regras do Meli e SEO.
    
    DADOS OBTIDOS DA API:
    - Título: {dados_ml['titulo']}
    - Preço: R$ {dados_ml['preco']}
    - Nível de Saúde (Meli): {dados_ml['saude']}
    - Tags internas (Meli): {dados_ml['tags']}
    - Ações corretivas exigidas pelo Meli: {dados_ml['acoes_saude']}
    - Descrição Atual: {dados_ml['descricao']}
    - Atributos preenchidos: {dados_ml['atributos']}
    
    INSTRUÇÕES CRÍTICAS PARA A RESPOSTA (JSON):
    Seja extremamente detalhista. Aponte erros de copy, ausência de atributos técnicos que ajudam a vender roupas, e se o título está otimizado para o algoritmo.
    Na "descricao_otimizada", escreva um copy persuasivo, com espaçamento, usando a técnica AIDA, e sem emojis proibidos pela plataforma.
    
    Retorne EXCLUSIVAMENTE um JSON com esta exata estrutura:
    {{
        "nota_geral": número de 0 a 10,
        "pontos_positivos": ["lista", "de", "coisas", "boas"],
        "pontos_criticos": ["lista", "de", "erros", "encontrados"],
        "descricao_otimizada": "Texto completo da nova descrição."
    }}
    """
    
    try:
        model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            system_instruction="Você é um especialista em regras de ranqueamento do Mercado Livre.",
            generation_config={"response_mime_type": "application/json"}
        )
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"❌ Erro na IA: {e}")
        exit()

if __name__ == "__main__":
    tokens = load_tokens()
    
    MLB = input("👉 Digite o MLB do anúncio que deseja auditar (ex: MLB123456789): ").strip()
    
    dados = get_ml_data(MLB, tokens['access_token'])
    
    if dados['titulo'] == "N/A":
        print("❌ MLB não encontrado. Verifique se o código está correto e pertence a esta conta.")
        exit()
        
    print(f"\n✅ Anúncio capturado: {dados['titulo']}")
    print(f"🌡️ Saúde oficial na API: {dados['saude'] * 100 if isinstance(dados['saude'], float) else dados['saude']}%")
    
    laudo_json = auditar_com_gemini(dados)
    laudo = json.loads(laudo_json)
    
    print("\n" + "="*60)
    print("📊 LAUDO DE QUALIDADE - AJ MODA AUDITOR")
    print("="*60)
    print(f"⭐ NOTA DE CONVERSÃO: {laudo.get('nota_geral')}/10")
    
    print("\n✅ PONTOS FORTES:")
    for p in laudo.get('pontos_positivos', []):
        print(f"  [+] {p}")
        
    print("\n⚠️ PONTOS CRÍTICOS (Ajustar para vender mais):")
    for c in laudo.get('pontos_criticos', []):
        print(f"  [-] {c}")
        
    print("\n📝 NOVA DESCRIÇÃO OTIMIZADA (Pronta para copiar e colar):")
    print("-" * 60)
    print(laudo.get('descricao_otimizada'))
    print("-" * 60)
    print("\n✅ Diagnóstico concluído.")