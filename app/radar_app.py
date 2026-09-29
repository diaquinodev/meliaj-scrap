"""Dashboard de demonstração e cliente do serviço de rascunhos."""

import os
import sys
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

# Compatível com streamlit run app/radar_app.py a partir da raiz.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.demo import demo_listings
from app.pricing import get_factory_bi
from app.scraping import ScrapeError, limpar_vendas, scrape_ml_advanced


def convert_df_to_csv(df):
    """Neutraliza células de texto interpretáveis como fórmula em planilhas."""
    def safe_cell(value):
        if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
            return "'" + value
        return value
    safe = df.apply(lambda column: column.map(safe_cell))
    return safe.to_csv(index=False).encode("utf-8-sig")


def main():
    st.set_page_config(page_title="Marketplace Intelligence", page_icon="🎯", layout="wide")
    st.title("Marketplace Intelligence")
    st.caption("Pesquisa de mercado, simulação de preço e rascunhos com IA sujeitos a revisão humana.")
    with st.sidebar:
        st.header("Simulação de preço")
        custo = st.number_input("Custo unitário (R$)", min_value=0.01, value=8.0)
        retorno = st.number_input("Retorno sobre custo (%)", min_value=0.0, value=30.0)
        promo = st.slider("Desconto promocional (%)", 0, 70, 40)
        taxa = st.number_input("Taxa percentual simulada (%)", min_value=0.0, max_value=99.0, value=20.0)
        fixa = st.number_input("Taxa fixa por venda (R$)", min_value=0.0, value=4.0)
        st.caption("Hipóteses configuráveis. Não incluem frete, impostos e devoluções; não são taxas oficiais.")

    if st.button("Carregar demonstração offline", type="primary"):
        st.session_state["data"] = demo_listings()
        st.session_state["source"] = "Dados sintéticos de demonstração"

    with st.expander("Coleta de anúncios públicos (opcional)"):
        st.caption("A coleta pode ser bloqueada ou ficar incompatível com mudanças no HTML. Não contorna restrições de acesso.")
        with st.form("search"):
            query = st.text_input("Termo de busca")
            limit = st.number_input("Máximo de anúncios", min_value=1, max_value=500, value=50)
            run = st.form_submit_button("Consultar mercado")
        if run:
            progress = st.progress(0.0)
            try:
                rows = scrape_ml_advanced(query, int(limit), progress=progress.progress)
                st.session_state["data"] = rows
                st.session_state["source"] = f"Coleta pública: {query.strip()}"
            except (ScrapeError, ValueError) as exc:
                st.error(str(exc))
                st.session_state.pop("data", None)
                st.session_state.pop("source", None)
            finally:
                progress.empty()

    calc = get_factory_bi(custo, promo, retorno, taxa / 100, fixa)
    columns = st.columns(4)
    for col, label, value in zip(columns,
            ["Ponto de equilíbrio", "Preço-alvo", "Preço de vitrine", "Resultado unitário estimado"],
            [calc["minimo"], calc["venda_alvo"], calc["vitrine"], calc["lucro"]]):
        col.metric(label, f"R$ {value:.2f}")
    st.caption(f"Kit de 3: vitrine R$ {calc['kit3_vitrine']:.2f}; resultado estimado R$ {calc['kit3_lucro']:.2f}. Uma taxa fixa por kit.")

    catalog, analytics, ai = st.tabs(["Catálogo", "Análise da amostra", "Rascunho com IA"])
    rows = st.session_state.get("data", [])
    with catalog:
        if not rows:
            st.info("Carregue a demonstração ou execute uma consulta.")
        else:
            st.caption(st.session_state["source"])
            df = pd.DataFrame(rows).sort_values("preco")
            st.dataframe(df, hide_index=True, column_config={
                "link": st.column_config.LinkColumn("Anúncio"),
                "preco": st.column_config.NumberColumn("Preço", format="R$ %.2f"),
            }, use_container_width=True)
            st.download_button("Exportar CSV", convert_df_to_csv(df), "amostra_mercado.csv", "text/csv")
    with analytics:
        if rows:
            df = pd.DataFrame(rows)
            df["vendas_num"] = df["vendas"].apply(limpar_vendas)
            st.scatter_chart(df, x="preco", y="vendas_num")
            st.caption("Contagens públicas aproximadas, sem janela temporal. Ausência de informação é representada como 0 no gráfico. A amostra mistura produtos e kits; não mede participação de mercado.")
        else:
            st.info("Carregue dados para visualizar a amostra.")
    with ai:
        st.write("Gere um rascunho pelo serviço local. A resposta informa modo, versão do prompt, latência e uso de tokens.")
        st.caption("Inicie a API conforme o README. O modo demo usa uma fixture determinística, sem chamar um LLM.")
        with st.form("draft"):
            name = st.text_input("Nome do produto", value="Body feminino")
            details = st.text_area("Fatos confirmados sobre o produto")
            material = st.text_input("Material confirmado (opcional)")
            token = st.text_input("Token do serviço local", type="password", value=os.getenv("SERVICE_API_TOKEN", ""))
            generate = st.form_submit_button("Gerar rascunho para revisão")
        if generate:
            try:
                response = requests.post("http://127.0.0.1:8001/v1/drafts",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"name": name, "details": details, "material": material or None}, timeout=(5, 65))
                if response.status_code == 200:
                    st.session_state["draft"] = response.json()
                else:
                    st.session_state.pop("draft", None)
                    st.error(f"Serviço retornou HTTP {response.status_code}. Verifique os campos e a configuração.")
            except requests.RequestException:
                st.session_state.pop("draft", None)
                st.error("Não foi possível consultar o serviço local. Verifique se a API está iniciada.")
        if "draft" in st.session_state:
            result = st.session_state["draft"]
            st.warning("Rascunho: revise todas as afirmações antes de usar. Nenhum anúncio foi publicado.")
            st.text(result["draft"]["title"])
            st.text(result["draft"]["description"])
            st.json({key: value for key, value in result.items() if key != "draft"})


if __name__ == "__main__":
    main()
