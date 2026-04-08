"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  MERCADO LIVRE - GERADOR DE TOKEN OAUTH 2.0 (MODO LOCAL / GOOGLE REDIRECT)   ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import requests
import json

# ─── CREDENCIAIS DA APLICAÇÃO AJ MODA ────────────────────────────────────────
CLIENT_ID = "516207596659548"
CLIENT_SECRET = "ClU8y12DuAFf7SDEeh5dp22aViwu9l3i"
REDIRECT_URI = "https://www.google.com"

# ⚠️ PASSO CRÍTICO: Cole aqui o código "TG-" que você pescou na URL do Google
CODE = "TG-69b19f17c578530001590726-2029196212" 

def gerar_access_token():
    print("🔄 Trocando o código temporário pelo Token de Acesso definitivo...")
    
    url = "https://api.mercadolibre.com/oauth/token"
    
    payload = {
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": CODE,
        "redirect_uri": REDIRECT_URI
    }
    
    headers = {
        "accept": "application/json",
        "content-type": "application/x-www-form-urlencoded"
    }

    try:
        response = requests.post(url, data=payload, headers=headers)
        data = response.json()
        
        if response.status_code == 200:
            print("\n✅ SUCESSO! Token Gerado com a sua Chave Oficial:\n")
            print("="*60)
            print(f"🔑 ACCESS TOKEN: {data.get('access_token')}")
            print("-" * 60)
            print(f"🔄 REFRESH TOKEN: {data.get('refresh_token')}")
            print("="*60)
            print(f"⏳ EXPIRA EM: {data.get('expires_in')} segundos (6 horas)")
        else:
            print("\n❌ ERRO NA TROCA DO CÓDIGO:")
            print(json.dumps(data, indent=4))
            print("\nLembrete: O código TG- expira super rápido ou se for usado duas vezes.")
            
    except Exception as e:
        print(f"Erro na requisição: {e}")

if __name__ == "__main__":
    gerar_access_token()