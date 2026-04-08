"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  AGENTE AUTÔNOMO - SISTEMA BLINDADO (IMGBB + UX/UI + AUTO-CATEGORIA)         ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import os
import glob
import json
import base64
import requests
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from PIL import Image

# ─── 1. CREDENCIAIS ──────────────────────────────────────────────────────────
GEMINI_API_KEY = "AIzaSyBHFb1Ihy4GvWlLRMB9OcWkTZCrtnSDv38"
ML_ACCESS_TOKEN = "APP_USR-516207596659548-031112-e8a1c3cd239321cb59141e7e045c1977-2029196212"
IMGBB_API_KEY = "23e0c4f611df81b410b21b943cae4da1" # 🚀 Sua nova chave do ImgBB!

# ─── 2. CONTRATO DE DADOS DA IA (COM UX/UI) ──────────────────────────────────
class FichaTecnicaML(BaseModel):
    title: str = Field(description="Título SEO para Mercado Livre (Máx 60 chars). Obrigatório conter a estampa exata (ex: Onça, Tie Dye, Lisa).")
    description: str = Field(description="""
        Descrição LONGA, VENDEDORA e COM ESPAÇAMENTO (UX/UI).
        É OBRIGATÓRIO usar quebras de linha duplas para separar os blocos e criar respiro visual.
        
        Siga EXATAMENTE esta estrutura:
        1. Frase curta e de impacto sobre o produto.
        2. (Pule uma linha)
        3. Parágrafo curto (2 linhas) sobre a ocasião de uso e como ele valoriza o corpo.
        4. (Pule uma linha)
        5. Crie uma lista de tópicos usando hifens (-) com os detalhes: Tecido, Caimento, Elasticidade, Transparência (se houver).
        6. (Pule uma linha)
        7. Parágrafo final curto garantindo a qualidade e o envio imediato.
    """)
    fabric: str = Field(description="Tecido identificado na foto (ex: Tule, Suplex, Algodão).")
    model_field: str = Field(description="Palavra-chave forte do modelo para SEO.")
    sleeve_type: str = Field(description="Tipo de manga exato da foto (ex: 'Manga longa', 'Manga curta', 'Regata').")
    search_term: str = Field(description="Termo curto para buscar a categoria (ex: 'Body Feminino').")

# ─── 3. PROCESSAMENTO E UPLOAD DE FOTOS (VIA IMGBB) ──────────────────────────
def processar_fotos_locais(nome_pasta="fotos_produto"):
    print(f"📸 Procurando fotos na pasta '{nome_pasta}'...")
    extensoes = ['*.jpg', '*.jpeg', '*.png', '*.webp']
    arquivos = []
    for ext in extensoes:
        arquivos.extend(glob.glob(f"{nome_pasta}/{ext}"))
    return arquivos[:10] if arquivos else None

def fazer_upload_imgbb(caminho_foto):
    nome_arquivo = os.path.basename(caminho_foto)
    print(f"☁️ Subindo '{nome_arquivo}' para o ImgBB...")
    url = "https://api.imgbb.com/1/upload"
    
    try:
        with open(caminho_foto, "rb") as file:
            payload = {
                "key": IMGBB_API_KEY,
                "image": base64.b64encode(file.read()),
            }
            res = requests.post(url, data=payload)
            
        if res.status_code == 200:
            link_direto = res.json()["data"]["url"]
            print(f"✅ Link gerado com sucesso: {link_direto}")
            return link_direto
        else:
            print(f"❌ Erro no ImgBB: {res.text}")
            return None
    except Exception as e:
        print(f"❌ Erro local ao ler a foto: {e}")
        return None

# ─── 4. MÓDULO CÉREBRO (GEMINI AI) ───────────────────────────────────────────
def extrair_dados_da_peca(lista_caminhos_fotos, detalhes_manuais):
    print("🤖 Iniciando Visão Computacional do Gemini (Analisando as fotos locais)...")
    imagens_pil = []
    for caminho in lista_caminhos_fotos:
        img = Image.open(caminho)
        img.thumbnail((800, 800))
        imagens_pil.append(img)
    
    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = f"""Atue como Especialista de E-commerce e Copywriter Sênior.
    Analise TODAS as fotos enviadas. Preste EXTREMA ATENÇÃO à estampa real e características.
    Detalhes adicionais: "{detalhes_manuais}".
    Gere o JSON respeitando ESTRITAMENTE o formato de espaçamento e tópicos exigido na descrição."""
    
    conteudos_envio = imagens_pil + [prompt]
    response = client.models.generate_content(
        model='gemini-2.5-flash', contents=conteudos_envio,
        config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=FichaTecnicaML, temperature=0.2)
    )
    return json.loads(response.text)

# ─── 5. MÓDULO BÚSSOLA (CATEGORIAS DO ML) ────────────────────────────────────
def descobrir_categoria_oficial(termo_busca):
    url = f"https://api.mercadolibre.com/sites/MLB/domain_discovery/search?limit=1&q={termo_busca}"
    headers = {"Authorization": f"Bearer {ML_ACCESS_TOKEN}"}
    resposta = requests.get(url, headers=headers)
    if resposta.status_code == 200 and resposta.json(): return resposta.json()[0]['category_id']
    return "MLB195030"

# ─── 6. MÓDULO MOTOR (CRIADOR DE ANÚNCIOS) ───────────────────────────────────
def publicar_anuncio_no_ml(dados_ia, id_categoria, urls_fotos, preco_mercado):
    preco_com_margem = round(preco_mercado * 1.30, 2)
    print(f"\n🚀 Publicando Anúncio no valor de R$ {preco_com_margem}...")
    
    url_criacao = "https://api.mercadolibre.com/items"
    headers = {"Authorization": f"Bearer {ML_ACCESS_TOKEN}", "Content-Type": "application/json"}

    # 🔥 AGORA ENVIAMOS A URL DIRETA (O Mercado Livre adora isso)
    if urls_fotos:
        pictures_payload = [{"source": url} for url in urls_fotos if url is not None]
    else:
        pictures_payload = [{"source": "https://http2.mlstatic.com/D_NQ_NP_2X_894173-MLB95617158742_102025-F.webp"}]

    payload = {
        "family_name": dados_ia["title"], 
        "category_id": id_categoria,
        "price": preco_com_margem,
        "currency_id": "BRL",
        "available_quantity": 50,
        "buying_mode": "buy_it_now",
        "condition": "new",
        "listing_type_id": "gold_pro",
        "pictures": pictures_payload,
        "shipping": {"mode": "me2", "local_pick_up": False},
        "attributes": [
            {"id": "BRAND", "value_name": "AJ Moda"}, 
            {"id": "MODEL", "value_name": dados_ia["model_field"]},
            {"id": "ITEM_CONDITION", "value_id": "2230284"}, 
            {"id": "MATERIAL", "value_name": dados_ia["fabric"]},
            {"id": "SELLER_PACKAGE_WEIGHT", "value_name": "150 g"},
            {"id": "SELLER_PACKAGE_LENGTH", "value_name": "20 cm"},
            {"id": "SELLER_PACKAGE_WIDTH", "value_name": "15 cm"},
            {"id": "SELLER_PACKAGE_HEIGHT", "value_name": "5 cm"},
            {"id": "GENDER", "value_name": "Feminino"},
            {"id": "SLEEVE_TYPE", "value_name": dados_ia["sleeve_type"]}
        ]
    }

    resposta = requests.post(url_criacao, json=payload, headers=headers)
    
    if resposta.status_code == 201: 
        dados_anuncio = resposta.json()
        item_id = dados_anuncio.get('id')
        
        print("\n📝 Injetando a Descrição com UX/UI no Mercado Livre...")
        url_desc = f"https://api.mercadolibre.com/items/{item_id}/description"
        payload_desc = {"plain_text": dados_ia["description"]}
        res_desc = requests.post(url_desc, json=payload_desc, headers=headers)
        
        print("\n" + "="*70)
        print("🎉 ANÚNCIO CRIADO COM SUCESSO ABSOLUTO!")
        print(f"🏷️ Título: {dados_ia['title']}")
        print(f"🔗 Link Oficial: {dados_anuncio.get('permalink')}")
        print("="*70)
    else:
        print("\n⚠️ O MERCADO LIVRE RECUSOU A CRIAÇÃO:")
        print(json.dumps(resposta.json(), indent=4))

# ─── EXECUÇÃO CENTRAL ────────────────────────────────────────────────────────
if __name__ == "__main__":
    
    fotos_locais = processar_fotos_locais("fotos_produto")
    
    if fotos_locais:
        MEU_PRECO_DE_MERCADO = 39.90 
        detalhes = "Moda premium, envio imediato, caimento perfeito ao corpo."
        
        # 1. Hospeda as fotos no ImgBB e pega os Links!
        urls_fotos_nuvem = []
        for caminho in fotos_locais:
            link = fazer_upload_imgbb(caminho)
            if link: urls_fotos_nuvem.append(link)
                
        # 2. IA lê a foto e cria a copy matadora
        dados = extrair_dados_da_peca(fotos_locais, detalhes)
        
        if dados:
            # 3. Descobre ID da categoria e Pública
            id_cat = descobrir_categoria_oficial(dados["search_term"])
            publicar_anuncio_no_ml(dados, id_cat, urls_fotos_nuvem, MEU_PRECO_DE_MERCADO)
        else:
            print("\n❌ OPERAÇÃO ABORTADA: A IA falhou em analisar a imagem.")