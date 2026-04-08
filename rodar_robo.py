import time
from src.rpa.browser_manager import BrowserManager
from src.rpa.upseller_bot import UpSellerBot

def testar_robo_real():
    print(" Acordando o robô na janela isolada...")
    manager = BrowserManager(headless=False)
    contexto, pagina = manager.iniciar_navegador()
    
    dados_ia = {
        "title": "Conjunto Tricot Feminino Colete Com Botões AJ Moda",
        "price": "139.90",
        "description": "Descubra a sofisticação atemporal deste conjunto tricot encorpado..."
    }
    
    try:
        bot = UpSellerBot(pagina)
        bot.navegar_para_criacao('https://app.upseller.com/pt/products/mercado/up-create')
        time.sleep(3) 
        
        bot.selecionar_loja('JBA')
        time.sleep(1)
        
        print(" Passando o controle do teclado para o robô...")
        bot.preencher_rascunho_ml(dados_ia)
        
        print(" Anúncio preenchido! Analise a tela. Fechando em 15 segundos...")
        time.sleep(15)
        
    except Exception as e:
        print(f" Erro na execução real: {e}")
        
    finally:
        manager.fechar_navegador(contexto)
        print(" Fim do teste real.")

if __name__ == '__main__':
    testar_robo_real()
