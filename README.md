"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  Radar Elite Pro - GOOGLE GEMINI 3 & ENTERPRISE SEO PIM                      ║
║  Versão: 34.0.0 | Deep Scraping (10 Pags), Tabela Visual Completa & IA Agente║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
import re
from statistics import mean
from google import genai
from google.genai import types
from PIL import Image

# ─── Configuração de UI ──────────────────────────────────────────────────────
st.set_page_config(page_title="Radar Elite v34", page_icon="🎯", layout="wide")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    html, body, [class*="css"]  { font-family: 'Inter', sans-serif; background-color: #f8fafc; }
    
    div[data-testid="stMetric"] { background: white; padding: 20px !important; border-radius: 16px !important; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05) !important; border: 1px solid #e2e8f0 !important; }
    .pricing-panel { background: white; padding: 25px; border-radius: 16px; margin-bottom: 25px; border: 2px solid #e2e8f0; box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.05); }
    .kit-panel { background: #eff6ff; padding: 20px; border-radius: 12px; margin-top: 15px; border: 1px dashed #3b82f6; text-align: center; }
    
    .custom-table-container { height: 600px; overflow-y: auto; border: 1px solid #e2e8f0; border-radius: 12px; background: white; margin-bottom: 20px; }
    .custom-table { width: 100%; border-collapse: collapse; font-size: 14px; }
    .custom-table th { padding: 12px 16px; text-align: left; background: #f1f5f9; position: sticky; top: 0; z-index: 10; color: #475569;}
    .custom-table td { padding: 10px 16px; border-bottom: 1px solid #e2e8f0; vertical-align: middle; color: #334155;}
    
    .thumb-img { width: 50px; height: 50px; object-fit: cover; border-radius: 6px; transition: transform 0.3s ease; border: 1px solid #e2e8f0; }
    .thumb-img:hover { transform: scale(3.5); z-index: 999; position: relative; border-color: #2563eb; box-shadow: 0 10px 20px rgba(0,0,0,0.2); }
</style>
""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════════
#  LÓGICA MATEMÁTICA
# ═══════════════════════════════════════════════════════════════════════════════

def get_factory_bi(custo, gordura, margem_alvo, taxa_mkp=0.20, taxa_fixa=4.0):
    preco_minimo = (custo + taxa_fixa) / (1 - taxa_mkp)
    lucro_bruto = custo * (1 + (margem_alvo / 100))
    preco_venda_alvo = (lucro_bruto + taxa_fixa) / (1 - taxa_mkp)
    preco_vitrine = preco_venda_alvo / (1 - (gordura / 100))
    max_desconto_perc = ((preco_vitrine - preco_minimo) / preco_vitrine) * 100
    lucro_real = preco_venda_alvo - custo - (preco_venda_alvo * taxa_mkp) - taxa_fixa
    
    custo_kit3 = custo * 3
    preco_venda_kit3 = ((custo_kit3 * (1 + (margem_alvo / 100))) + taxa_fixa) / (1 - taxa_mkp)
    lucro_real_kit3 = preco_venda_kit3 - custo_kit3 - (preco_venda_kit3 * taxa_mkp) - taxa_fixa
    
    return {
        "minimo": preco_minimo, "venda_alvo": preco_venda_alvo, "vitrine": preco_vitrine, 
        "max_desconto": max_desconto_perc, "lucro": lucro_real,
        "kit3_vitrine": preco_venda_kit3 / (1 - (gordura / 100)), "kit3_lucro": lucro_real_kit3
    }

def limpar_vendas(vendas_str):
    try: return int(''.join(re.findall(r'\d+', str(vendas_str))))
    except: return 0

def render_custom_table(df):
    # Tabela visual completa com todos os dados solicitados
    html = "<div class='custom-table-container'><table class='custom-table'><thead><tr><th>Foto</th><th>Título</th><th>Preço</th><th>Oferta</th><th>Vendas</th><th>⭐</th><th>Ação</th></tr></thead><tbody>"
    for _, row in df.iterrows():
        img_tag = f"<img src='{row['imagem']}' class='thumb-img'>" if row['imagem'] else ""
        html += f"<tr><td>{img_tag}</td><td style='max-width:300px;'>{row['titulo']}</td><td style='font-weight:bold; color:#0f172a;'>R$ {row['preco']:.2f}</td><td style='color:#10b981;'>{row['desconto']}</td><td>{row['vendas']}</td><td>{row['nota']}</td><td><a href='{row['link']}' target='_blank' style='color:#2563eb;'>Link</a></td></tr>"
    return html + "</tbody></table></div>"

def convert_df_to_csv(df):
    return df.to_csv(index=False).encode('utf-8')

# ═══════════════════════════════════════════════════════════════════════════════
#  MOTOR DE EXTRAÇÃO MASSIVA (10 PÁGINAS)
# ═══════════════════════════════════════════════════════════════════════════════

def scrape_ml_advanced(query: str, limit: int = 500) -> list:
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    results = []
    offsets = [1 + (i * 50) for i in range(10)] # 10 páginas = 500 itens
    progress_bar = st.progress(0)
    
    for i, offset in enumerate(offsets):
        url = f"https://lista.mercadolivre.com.br/{query.replace(' ', '-')}" if offset == 1 else f"https://lista.mercadolivre.com.br/{query.replace(' ', '-')}_Desde_{offset}"
        try:
            r = requests.get(url, headers=headers, timeout=10)
            soup = BeautifulSoup(r.text, "html.parser")
            cards = soup.find_all("li", class_="ui-search-layout__item") or soup.find_all("div", class_=re.compile(r"poly-card|ui-search-result__wrapper"))
            
            if not cards: break # Freio se acabar as páginas antes da 10ª
            
            for card in cards:
                title_el = card.select_one(".poly-component__title, .ui-search-item__title")
                price_fraction = card.select_one(".andes-money-amount__fraction")
                
                # Extraindo Desconto, Estrelas e Vendas
                discount_label = card.select_one(".poly-price__disc_label, .ui-search-price__discount")
                phrases = card.select(".poly-phrase-label")
                nota = phrases[0].text if len(phrases) > 0 and "4." in phrases[0].text or "5." in phrases[0].text else "N/A"
                vendas = phrases[1].text if len(phrases) > 1 else (phrases[0].text if len(phrases) > 0 and "vendido" in phrases[0].text else "0")
                
                if title_el and price_fraction:
                    img_el = card.select_one("img.poly-component__picture") or card.select_one("img[data-testid='picture']") or card.find("img")
                    img_url = (img_el.get("data-src") or img_el.get("src") or "").replace("-I.webp", "-W.webp")
                    
                    results.append({
                        "imagem": img_url, 
                        "titulo": title_el.text.strip(), 
                        "preco": float(price_fraction.text.replace('.', '')),
                        "desconto": discount_label.text if discount_label else "0%",
                        "nota": nota,
                        "vendas": vendas, 
                        "link": title_el.get("href", "").split("#")[0]
                    })
            progress_bar.progress((i + 1) / len(offsets))
        except: continue
    progress_bar.empty()
    return results

# ═══════════════════════════════════════════════════════════════════════════════
#  INTERFACE DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    with st.sidebar:
        st.markdown("<h2 style='font-size: 24px;'>🏢 Intelligence AJ Moda</h2>", unsafe_allow_html=True)
        api_key = st.text_input("🔑 Chave IA (Google Gemini 3)", type="password")
        
        st.divider()
        st.markdown("### 📸 Reforço de Dados")
        upload_foto = st.file_uploader("Upload da Peça", type=["jpg", "png"])
        reforco_manual = st.text_area("📋 Detalhes (Opcional)", placeholder="Ex: Tecido Suplex com 8% elastano, Gola V. Sem bojo.", help="Insira aqui tudo o que a IA não consegue ver na foto.")
        
        st.divider()
        st.markdown("### ⚙️ Parâmetros de Fábrica")
        custo = st.number_input("Custo Unitário 1 Peça (R$)", value=8.0)
        margem = st.number_input("Margem Alvo (%)", value=30.0)
        gordura = st.slider("Gordura Promo (%)", 0, 70, 40)

    st.markdown("<h1 style='text-align: center;'>Radar Elite <span style='color: #2563eb;'>Strategist v34.0</span></h1>", unsafe_allow_html=True)

    query = st.text_input("🔍 Qual nicho vamos minerar?", placeholder="Ex: Body Feminino Tule")
    
    if st.button("🚀 INICIAR VARREDURA PROFUNDA (10 PÁGINAS)", use_container_width=True):
        if query:
            with st.spinner("Varrendo 10 páginas no Mercado Livre..."):
                st.session_state['data'] = scrape_ml_advanced(query, 500)
                st.session_state['q'] = query

    if 'data' in st.session_state:
        df = pd.DataFrame(st.session_state['data'])
        calc = get_factory_bi(custo, gordura, margem)
        
        df['vendas_num'] = df['vendas'].apply(limpar_vendas)
        concorrentes_reais = df[(df['preco'] > 5.0) & (df['vendas_num'] >= 50)]
        preco_concorrente = concorrentes_reais['preco'].min() if not concorrentes_reais.empty else df['preco'].min()
        
        st.markdown(f"""
        <div class='pricing-panel'>
            <h4>Estratégia Principal (1 Peça) vs Mercado</h4><hr>
            <div style='display: flex; justify-content: space-between; text-align: center;'>
                <div><p style='margin:0;'>Vitrine</p><h3>R$ {calc['vitrine']:.2f}</h3></div>
                <div><p style='margin:0;'>Desconto Limite</p><h3 style='color:#3b82f6;'>{calc['max_desconto']:.1f}%</h3></div>
                <div><p style='margin:0;'>Break-even</p><h3 style='color:#ef4444;'>R$ {calc['minimo']:.2f}</h3></div>
                <div><p style='margin:0;'>Líder Barato</p><h3 style='color:#10b981;'>R$ {preco_concorrente:.2f}</h3></div>
            </div>
            <div class='kit-panel'>
                <h5 style='margin-bottom: 5px; color:#1e40af;'>📦 Oportunidade: Ativação de KIT 3 Peças</h5>
                <p style='margin:0; font-size:14px; color:#334155;'>
                    Diluindo a taxa fixa da plataforma, cadastre um Kit 3 Peças por <b>R$ {calc['kit3_vitrine']:.2f}</b>.<br>
                    Seu lucro puro por venda salta para <b><span style='color:#10b981; font-weight:bold;'>R$ {calc['kit3_lucro']:.2f}</span></b>.
                </p>
            </div>
        </div>
        """, unsafe_allow_html=True)

        t1, t2, t3 = st.tabs(["📋 Catálogo Visual Completo", "📊 Radar de Monopólio", "📦 Agente de Cadastro (SEO)"])
        
        # ─── ABA 1: TABELA COMPLETA COM FOTOS, OFERTAS E ESTRELAS ───
        with t1:
            st.write(render_custom_table(df.sort_values(by="preco")), unsafe_allow_html=True)
            csv_data = convert_df_to_csv(df)
            st.download_button(label="📥 Exportar Dados para Excel (CSV)", data=csv_data, file_name=f"concorrentes_{query.replace(' ', '_')}.csv", mime="text/csv")

        # ─── ABA 2: RADAR DE MONOPÓLIO (GRÁFICOS) ───
        with t2:
            df_grafico = df[df['vendas_num'] > 0][['preco', 'vendas_num']].rename(columns={'preco': 'Preço (R$)', 'vendas_num': 'Volume de Vendas'})
            if not df_grafico.empty:
                st.scatter_chart(data=df_grafico, x='Preço (R$)', y='Volume de Vendas', color="#2563eb", height=400)
            
            if api_key:
                if st.button("💡 Gerar SWOT Numérica"):
                    with st.spinner("Desenhando plano de guerra..."):
                        try:
                            top_vendedores = df.sort_values(by="vendas_num", ascending=False).head(5)['titulo'].tolist()
                            prompt_swot = f"Nicho: {query}. Nosso Break-even: R$ {calc['minimo']:.2f}. Líder Barato: R$ {preco_concorrente:.2f}. Lucro Unitário: R$ {calc['lucro']:.2f}. Lucro Kit 3: R$ {calc['kit3_lucro']:.2f}. Faça uma análise SWOT agressiva baseada nesses números."
                            client = genai.Client(api_key=api_key)
                            res = client.models.generate_content(model="gemini-2.5-flash", contents=prompt_swot)
                            st.markdown(res.text)
                        except Exception as e: st.error(f"Erro: {e}")

        # ─── ABA 3: AGENTE AUTÔNOMO DE CADASTRO ───
        with t3:
            st.markdown("### 🤖 Gerador Automático de Ficha Técnica")
            if not upload_foto:
                st.warning("👈 Suba a foto da peça e preencha os detalhes para gerar o anúncio otimizado.")
            elif api_key:
                try:
                    img_produto = Image.open(upload_foto)
                    st.image(img_produto, width=200)
                    
                    top_titulos = df.sort_values(by="vendas_num", ascending=False).head(10)['titulo'].tolist()
                    
                    prompt_pim = f"""Atue como Especialista Sênior em SEO da AJ Moda. 
                    DADOS DA PEÇA: {reforco_manual}
                    TÍTULOS DOS LÍDERES: {top_titulos[:5]}
                    
                    GERE O CADASTRO ESTRATÉGICO:

                    ## 🥊 1. Quebra de Objeções (Copy)
                    Liste 2 reclamações comuns para esse tipo de peça e como o nosso produto resolve isso.

                    ## 📦 2. MERCADO LIVRE (Indexação Técnica)
                    ```text
                    [4 Títulos ML, máximo 60 caracteres. Tente roubar palavras dos líderes]
                    ```
                    - **Campo "Modelo":** Liste 5 termos técnicos que NÃO repetem os títulos gerados.
                    - **Ocasião:** Defina baseado na foto e reforço.

                    ## 🛍️ 3. SHOPEE (Filtros e SEO)
                    ```text
                    [4 Títulos Shopee, máximo 120 caracteres, ZERO EMOJIS]
                    ```
                    - **Tags:** Sugira Estilo, Ocasião e Material exatos.

                    ## 📝 4. DESCRIÇÃO MASTER (One-Click Copy)
                    ```markdown
                    [Descrição AIDA. Destaque Fabricação Própria. Quebre as objeções levantadas. ZERO EMOJIS. Use tópicos limpos.]
                    ```
                    
                    ## 🔑 5. Palavras-Chave de Fundo
                    ```text
                    [25 palavras de indexação separadas apenas por ESPAÇO, que não estejam nos títulos]
                    ```
                    """
                    
                    if st.button("✨ Gerar Cadastro Otimizado (One-Click Copy)"):
                        with st.spinner("Extraindo SEO da concorrência e lendo a foto..."):
                            client = genai.Client(api_key=api_key)
                            res = client.models.generate_content(model="gemini-2.5-flash", contents=[img_produto, prompt_pim])
                            st.markdown(res.text)
                except Exception as e: st.error(f"Erro: {e}")

if __name__ == "__main__":
    main()