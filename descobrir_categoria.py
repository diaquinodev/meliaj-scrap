import requests
import json

# Seu Token (Ainda válido)
ML_ACCESS_TOKEN = "APP_USR-516207596659548-031112-e8a1c3cd239321cb59141e7e045c1977-2029196212"

def descobrir_categoria_oficial(termo_busca):
    # Usando o endpoint exato que você achou na documentação (Site MLB = Brasil)
    url = f"https://api.mercadolibre.com/sites/MLB/domain_discovery/search?limit=1&q={termo_busca}"
    
    headers = {
        "Authorization": f"Bearer {ML_ACCESS_TOKEN}"
    }

    print(f"🔍 Perguntando ao Mercado Livre qual é a categoria de: '{termo_busca}'...")
    
    resposta = requests.get(url, headers=headers)
    
    if resposta.status_code == 200:
        dados = resposta.json()
        if dados:
            print("\n✅ RESPOSTA DO MERCADO LIVRE:")
            print(f"Categoria Oficial: {dados[0]['category_name']}")
            print(f"ID EXATO PARA USAR: {dados[0]['category_id']}")
            print("="*50)
        else:
            print("Nenhuma categoria encontrada.")
    else:
        print("\n❌ ERRO:")
        print(json.dumps(resposta.json(), indent=4))

if __name__ == "__main__":
    # Vamos buscar o Body Feminino
    descobrir_categoria_oficial("Body Feminino")