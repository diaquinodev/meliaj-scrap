import logging
import time
import os
import glob
from src.ia.gerador_anuncio import GeradorAnuncio
from src.rpa.browser_manager import BrowserManager
from src.rpa.upseller_bot import UpSellerBot

# Suas chaves (A primeira é a prioritária)
CHAVES_API = [
    "AIzaSyC1kQP3lT05QZdgFhLt628LB9zrfL7emTQ",
    "AIzaSyBHFb1Ihy4GvWlLRMB9OcWkTZCrtnSDv38", 
    "AIzaSyDSLwl86JOMpoZOzA5hag5VMDSDNBH7GZs"
]

PASTA_FOTOS = "fotos_produto"
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] [%(levelname)s] - %(message)s')
logger = logging.getLogger('FluxoFinal')

def executar():
    arquivos = glob.glob(os.path.join(PASTA_FOTOS, "*.[jJ][pP][gG]"))
    if not arquivos:
        return logger.error("Nenhuma foto encontrada em fotos_produto.")
    
    caminho_foto = arquivos[0]
    dados_gerados = None

    # FASE 1: Inteligência Artificial
    for i, chave in enumerate(CHAVES_API):
        logger.info(f"Analisando com a Chave {i+1}...")
        try:
            ia = GeradorAnuncio(api_key=chave)
            dados_gerados = ia.analisar_foto_local(caminho_foto)
            if dados_gerados: break
        except Exception as e:
            logger.warning(f"Erro na chave {i+1}. Tentando próxima...")
            continue

    # FASE 2: Automação RPA
    if dados_gerados:
        print(f"\n IA GEROU O TÍTULO: {dados_gerados['title']}")
        manager = BrowserManager()
        contexto, pagina = manager.iniciar_navegador()
        try:
            bot = UpSellerBot(pagina)
            # URL LIMPA: Sem colchetes ou parênteses de link
            url_alvo = "https://app.upseller.com/pt/products/mercado/up-create"
            
            bot.navegar_para_criacao(url_alvo)
            bot.selecionar_loja('JBA')
            bot.preencher_rascunho_ml(dados_gerados)
            
            logger.info(" ANÚNCIO PREENCHIDO COM SUCESSO!")
            time.sleep(15)
        except Exception as e:
            logger.error(f" Erro no Robô: {e}")
        finally:
            manager.fechar_navegador(contexto)
    else:
        logger.error("Não foi possível gerar dados com nenhuma chave.")

if __name__ == "__main__":
    executar()
