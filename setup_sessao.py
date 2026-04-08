from src.rpa.browser_manager import BrowserManager

def configurar_sessao():
    print("🚀 Iniciando o Navegador Fantasma para salvar sua sessão...")
    manager = BrowserManager(headless=False)
    contexto, pagina = manager.iniciar_navegador()

    print("🌐 Acessando a página de Login do UpSeller...")
    # Indo direto para a página de login do sistema
    pagina.goto("https://www.upseller.com/pt/login", timeout=60000)

    print("\n" + "="*70)
    print("🛑 AÇÃO MANUAL NECESSÁRIA NO NAVEGADOR 🛑")
    print("1. Vá para o navegador que acabou de abrir (tem um ícone do Chromium).")
    print("2. Faça o login na sua conta da AJ Moda no UpSeller.")
    print("3. IMPORTANTE: Feche os pop-ups iniciais e deixe na tela do Painel Inicial.")
    print("4. Quando estiver tudo certo, volte aqui neste terminal.")
    print("="*70 + "\n")

    input("👉 Pressione [ENTER] aqui no terminal DEPOIS que estiver logado para salvar...")

    print("💾 Salvando os cookies de sessão e encerrando o navegador...")
    manager.fechar_navegador(contexto)
    print("✅ Mágica feita! Sessão salva na pasta 'sessao_navegador'. O robô agora tem a chave da casa.")

if __name__ == "__main__":
    configurar_sessao()