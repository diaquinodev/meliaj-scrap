import sys
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  MERCADO LIVRE - GERADOR DE TOKEN OAUTH 2.0 (MODO LOCAL / GOOGLE REDIRECT)   ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import requests
import json
import os

from dotenv import load_dotenv

load_dotenv()

# ─── CREDENCIAIS DA APLICAÇÃO LOJA DE MODA ────────────────────────────────────────
CLIENT_ID = os.getenv("ML_CLIENT_ID")
CLIENT_SECRET = os.getenv("ML_CLIENT_SECRET")
REDIRECT_URI = "https://www.google.com"

# Código "TG-..." retornado na URL de redirecionamento após autorizar o app:
#   python integracoes/mercadolivre_oauth.py TG-xxxxxxxx
CODE = (sys.argv[1] if len(sys.argv) > 1 else "") 

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
