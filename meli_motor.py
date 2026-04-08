"""
upseller_bot.py
───────────────
RPA via Playwright — cria anúncio no Mercado Livre através do Upseller.
A loja LOJAMARICOTA aparece no Upseller como "JBA" (CNPJ 2).

Instalação (uma vez só):
  pip install playwright --break-system-packages
  playwright install chromium

Uso:
  python upseller_bot.py
  python upseller_bot.py --headless        (sem abrir janela)
  python upseller_bot.py --debug           (para em cada etapa)
"""

import asyncio
import argparse
import os
import sys
from pathlib import Path
from playwright.async_api import async_playwright, Page, TimeoutError as PWTimeout

# ─────────────────────────────────────────────
# CONFIGURAÇÃO
# ─────────────────────────────────────────────

UPSELLER_URL  = "https://app.upseller.com/pt"
EMAIL         = "ajmoda.aj@gmail.com"
PASSWORD      = "Ajmodas12345#"
LOJA_ALVO     = "JBA"          # nome da loja no Upseller (= LOJAMARICOTA no Meli)

# ── Dados do anúncio ──────────────────────────
# Substitua pelos dados reais ou integre com a saída da IA
ANUNCIO = {
    "sku":         "AJM-VES-MET-001",
    "titulo":      "Vestido Feminino Metalizado Festa Balada P M G",
    "categoria":   "Vestidos",
    "marca":       "AJ Moda",
    "material":    "Poliéster",
    "preco":       149.90,
    "estoque":     25,
    "descricao": (
        "Vestido feminino metalizado, perfeito para carnaval, festas e baladas. "
        "Tecido com brilho intenso e caimento impecável. "
        "Disponível em P, M e G. Envio rápido por todo o Brasil."
    ),
    # Variantes: lista de (tamanho, cor, preco, estoque)
    "variantes": [
        ("P",  "Prata",   149.90, 8),
        ("M",  "Prata",   149.90, 10),
        ("G",  "Prata",   149.90, 7),
        ("P",  "Dourado", 149.90, 5),
        ("M",  "Dourado", 149.90, 7),
        ("G",  "Dourado", 149.90, 5),
    ],
    # Fotos locais (substitua pelos caminhos reais)
    # Aceita JPG/PNG até 2MB cada, máximo 9 fotos
    "fotos": [
        # "C:/fotos/vestido_prata_frente.jpg",
        # "C:/fotos/vestido_prata_costas.jpg",
    ],
}

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

async def espera_e_clica(page: Page, seletor: str, timeout: int = 10000):
    """Aguarda elemento visível e clica."""
    await page.wait_for_selector(seletor, state="visible", timeout=timeout)
    await page.click(seletor)

async def espera_e_preenche(page: Page, seletor: str, valor: str, timeout: int = 10000):
    """Aguarda campo, limpa e preenche."""
    await page.wait_for_selector(seletor, state="visible", timeout=timeout)
    await page.fill(seletor, "")
    await page.fill(seletor, valor)

async def screenshot(page: Page, nome: str):
    """Salva screenshot para debug."""
    path = f"debug_{nome}.png"
    await page.screenshot(path=path)
    print(f"   📸 Screenshot: {path}")

async def pausar(page: Page, debug: bool, msg: str):
    if debug:
        input(f"\n[DEBUG] {msg} — Pressione Enter para continuar...")

# ─────────────────────────────────────────────
# ETAPAS
# ─────────────────────────────────────────────

async def fazer_login(page: Page, debug: bool):
    print("\n-- Etapa 1: Login --")
    await page.goto(f"{UPSELLER_URL}/login", wait_until="networkidle")

    # Preenche email e senha automaticamente
    await espera_e_preenche(page, 'input[type="email"], input[name="email"], input[placeholder*="mail" i]', EMAIL)
    await espera_e_preenche(page, 'input[type="password"]', PASSWORD)
    print("   OK: Email e senha preenchidos")

    # TRAVA CAPTCHA - bot para aqui, voce resolve manualmente
    print("\n" + "="*55)
    print("  PAUSADO - Acao necessaria no browser:")
    print("")
    print("  1. Olhe o browser que abriu")
    print("  2. Preencha o CAPTCHA")
    print("  3. Clique em Login")
    print("  4. Aguarde o dashboard carregar completamente")
    print("  5. Volte AQUI e pressione Enter")
    print("")
    print("  ATENCAO: NAO feche o browser!")
    print("="*55)
    input("  >> Pressione Enter apos estar no dashboard... ")
    print("="*55 + "\n")

    await screenshot(page, "02_dashboard")
    print("   OK: Login confirmado, continuando automacao...")

async def selecionar_loja(page: Page, debug: bool):
    """
    No Upseller, a seleção de loja pode aparecer como um dropdown no topo
    ou ao entrar na tela de anúncios. Tentamos as duas abordagens.
    """
    print(f"\n── Etapa 2: Selecionando loja '{LOJA_ALVO}' ──")

    # Tenta encontrar seletor de loja no header
    seletores_loja = [
        f'text="{LOJA_ALVO}"',
        f'[title*="{LOJA_ALVO}"]',
        f'option:has-text("{LOJA_ALVO}")',
        '[class*="store-select"], [class*="shop-select"], [class*="loja"]',
    ]

    for sel in seletores_loja:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=3000):
                await el.click()
                print(f"   ✅ Loja selecionada via: {sel}")
                await pausar(page, debug, "Após selecionar loja")
                return
        except Exception:
            continue

    print(f"   ⚠️  Seletor de loja não encontrado — continuando (pode ser selecionado na tela de anúncio)")


async def navegar_para_criar_anuncio(page: Page, debug: bool):
    print("\n── Etapa 3: Navegando para Criar Anúncio ──")

    # Tenta via menu lateral
    menu_itens = [
        'text="Anúncios"',
        'text="Gestão de Anúncios"',
        '[href*="listing"], [href*="anuncio"], [href*="product"]',
    ]

    for sel in menu_itens:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=3000):
                await el.click()
                await page.wait_for_load_state("networkidle", timeout=8000)
                break
        except Exception:
            continue

    await screenshot(page, "03_listagem")

    # Clica em "Criar Anúncio" / "Novo Produto"
    botoes_criar = [
        'button:has-text("Criar Anúncio")',
        'button:has-text("Novo Anúncio")',
        'button:has-text("Novo Produto")',
        'a:has-text("Criar Anúncio")',
        '[class*="create"], [class*="add-product"]',
        'button:has-text("+")',
    ]

    criou = False
    for sel in botoes_criar:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=3000):
                await el.click()
                await page.wait_for_load_state("networkidle", timeout=8000)
                criou = True
                print(f"   ✅ Clicou em criar via: {sel}")
                break
        except Exception:
            continue

    if not criou:
        # Fallback: tenta URL direta comum do Upseller
        await page.goto(f"{UPSELLER_URL}/listing/create", wait_until="networkidle")
        print("   ⚠️  Tentando URL direta /listing/create")

    await screenshot(page, "04_criar_anuncio")
    await pausar(page, debug, "Após abrir formulário de criação")


async def selecionar_plataforma_e_loja(page: Page, debug: bool):
    """Seleciona Mercado Livre e a loja JBA no formulário de criação."""
    print("\n── Etapa 4: Selecionando plataforma e loja ──")

    # Seleciona Mercado Livre se houver seleção de plataforma
    ml_seletores = [
        'text="Mercado Livre"',
        'img[alt*="Mercado"], [class*="mercado"]',
        '[data-platform="mercadolivre"]',
    ]

    for sel in ml_seletores:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=3000):
                await el.click()
                print("   ✅ Mercado Livre selecionado")
                break
        except Exception:
            continue

    await page.wait_for_timeout(1000)

    # Seleciona a loja JBA
    loja_seletores = [
        f'text="{LOJA_ALVO}"',
        f'option:has-text("{LOJA_ALVO}")',
        f'[title="{LOJA_ALVO}"]',
        f'[data-name="{LOJA_ALVO}"]',
    ]

    for sel in loja_seletores:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=3000):
                await el.click()
                print(f"   ✅ Loja '{LOJA_ALVO}' selecionada")
                break
        except Exception:
            continue

    await screenshot(page, "05_plataforma_loja")
    await pausar(page, debug, "Após selecionar plataforma/loja")


async def preencher_info_basica(page: Page, debug: bool):
    print("\n── Etapa 5: Preenchendo informações básicas ──")

    # SKU
    campos_sku = [
        'input[placeholder*="SKU" i]',
        'input[name*="sku" i]',
        'input[label*="SKU" i]',
    ]
    for sel in campos_sku:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=2000):
                await el.fill(ANUNCIO["sku"])
                print(f"   ✅ SKU preenchido: {ANUNCIO['sku']}")
                break
        except Exception:
            continue

    # Título
    campos_titulo = [
        'input[placeholder*="título" i], input[placeholder*="titulo" i]',
        'input[placeholder*="nome" i]',
        'input[name*="title" i], input[name*="titulo" i]',
        'textarea[placeholder*="título" i]',
    ]
    for sel in campos_titulo:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=2000):
                await el.fill(ANUNCIO["titulo"])
                print(f"   ✅ Título preenchido: {ANUNCIO['titulo'][:40]}...")
                break
        except Exception:
            continue

    # Descrição
    campos_desc = [
        'textarea[placeholder*="descrição" i], textarea[placeholder*="descricao" i]',
        'textarea[name*="description" i]',
        '[class*="description"] textarea',
        '[class*="descricao"] textarea',
    ]
    for sel in campos_desc:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=2000):
                await el.fill(ANUNCIO["descricao"])
                print("   ✅ Descrição preenchida")
                break
        except Exception:
            continue

    await screenshot(page, "06_info_basica")
    await pausar(page, debug, "Após informações básicas")


async def preencher_preco_e_estoque(page: Page, debug: bool):
    print("\n── Etapa 6: Preço e estoque ──")

    # Preço
    campos_preco = [
        'input[placeholder*="preço" i], input[placeholder*="preco" i]',
        'input[name*="price" i], input[name*="preco" i]',
        'input[type="number"][class*="price" i]',
    ]
    for sel in campos_preco:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=2000):
                await el.fill(str(ANUNCIO["preco"]))
                print(f"   ✅ Preço: R$ {ANUNCIO['preco']}")
                break
        except Exception:
            continue

    # Estoque
    campos_estoque = [
        'input[placeholder*="estoque" i], input[placeholder*="quantidade" i]',
        'input[name*="stock" i], input[name*="quantity" i]',
        'input[placeholder*="Stock" i]',
    ]
    for sel in campos_estoque:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=2000):
                await el.fill(str(ANUNCIO["estoque"]))
                print(f"   ✅ Estoque: {ANUNCIO['estoque']}")
                break
        except Exception:
            continue

    await screenshot(page, "07_preco_estoque")
    await pausar(page, debug, "Após preço e estoque")


async def fazer_upload_fotos(page: Page, debug: bool):
    print("\n── Etapa 7: Upload de fotos ──")

    if not ANUNCIO["fotos"]:
        print("   ⚠️  Nenhuma foto configurada. Pulando upload.")
        print("   💡 Adicione os caminhos das fotos em ANUNCIO['fotos'] no script")
        return

    # Aceita input file visível ou oculto
    file_inputs = [
        'input[type="file"]',
        '[class*="upload"] input',
        '[class*="media"] input[type="file"]',
    ]

    for sel in file_inputs:
        try:
            el = page.locator(sel).first
            # set_input_files funciona mesmo em inputs ocultos
            fotos_existentes = [f for f in ANUNCIO["fotos"] if Path(f).exists()]
            if not fotos_existentes:
                print("   ⚠️  Nenhuma foto encontrada nos caminhos configurados")
                return
            await el.set_input_files(fotos_existentes)
            print(f"   ✅ {len(fotos_existentes)} foto(s) enviada(s)")
            await page.wait_for_timeout(3000)  # aguarda upload
            break
        except Exception as e:
            continue

    await screenshot(page, "08_fotos")
    await pausar(page, debug, "Após upload de fotos")


async def preencher_variantes(page: Page, debug: bool):
    print("\n── Etapa 8: Variantes ──")

    # Tenta habilitar modo variantes
    variante_btns = [
        'button:has-text("Variante")',
        'button:has-text("Variantes")',
        'text="Com Variantes"',
        '[class*="variant"] button',
        'label:has-text("Variante")',
    ]

    for sel in variante_btns:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=2000):
                await el.click()
                await page.wait_for_timeout(1000)
                print("   ✅ Modo variantes ativado")
                break
        except Exception:
            continue

    await screenshot(page, "09_variantes")
    await pausar(page, debug, "Após configurar variantes")


async def publicar(page: Page, debug: bool) -> bool:
    print("\n── Etapa 9: Publicando ──")
    await screenshot(page, "10_antes_publicar")

    botoes_publicar = [
        'button:has-text("Publicar")',
        'button:has-text("Salvar e Publicar")',
        'button:has-text("Criar Anúncio")',
        'button:has-text("Confirmar")',
        '[type="submit"]:has-text("Publicar")',
    ]

    for sel in botoes_publicar:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=3000):
                await pausar(page, debug, f"PRESTES A CLICAR EM PUBLICAR ({sel})")
                await el.click()
                print(f"   ✅ Clicou em publicar via: {sel}")
                break
        except Exception:
            continue

    # Aguarda resposta — sucesso ou erro
    await page.wait_for_timeout(4000)
    await screenshot(page, "11_resultado")

    # Detecta mensagem de sucesso
    sucesso_seletores = [
        'text="publicado"',
        'text="sucesso"',
        'text="Anúncio criado"',
        '[class*="success"], [class*="sucesso"]',
        '.ant-message-success',
        '.el-message--success',
    ]

    for sel in sucesso_seletores:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=5000):
                print(f"\n{'='*50}")
                print("✅ ANÚNCIO PUBLICADO COM SUCESSO!")
                print(f"   Loja: {LOJA_ALVO} (LOJAMARICOTA no Meli)")
                print(f"{'='*50}")
                return True
        except Exception:
            continue

    # Detecta mensagem de erro
    erro_seletores = [
        '[class*="error"], [class*="erro"]',
        '.ant-message-error',
        '.el-message--error',
        'text="erro"',
        'text="falhou"',
    ]

    for sel in erro_seletores:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=3000):
                texto_erro = await el.inner_text()
                print(f"\n❌ Erro detectado na tela: {texto_erro}")
                return False
        except Exception:
            continue

    # Não detectou nem sucesso nem erro — captura URL atual
    url_atual = page.url
    print(f"\n⚠️  Resultado inconclusivo.")
    print(f"   URL atual: {url_atual}")
    print(f"   Verifique os screenshots debug_10_antes_publicar.png e debug_11_resultado.png")
    return False


# ─────────────────────────────────────────────
# FLUXO PRINCIPAL
# ─────────────────────────────────────────────

async def run(headless: bool, debug: bool):
    print("="*55)
    print("  UPSELLER BOT — AJ MODA")
    print(f"  Loja: {LOJA_ALVO} → LOJAMARICOTA (Mercado Livre)")
    print("="*55)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            args=["--start-maximized"] if not headless else [],
        )
        context = await browser.new_context(
            viewport={"width": 1400, "height": 900},
            locale="pt-BR",
        )
        page = await context.new_page()

        # Intercepta e loga erros de rede relevantes
        page.on("response", lambda r: print(f"   [NET] {r.status} {r.url[:80]}")
                if r.status >= 400 and "api" in r.url else None)

        try:
            await fazer_login(page, debug)
            await selecionar_loja(page, debug)
            await navegar_para_criar_anuncio(page, debug)
            await selecionar_plataforma_e_loja(page, debug)
            await preencher_info_basica(page, debug)
            await preencher_preco_e_estoque(page, debug)
            await fazer_upload_fotos(page, debug)
            await preencher_variantes(page, debug)
            sucesso = await publicar(page, debug)

            if not sucesso:
                print("\n💡 O bot preencheu os campos mas não confirmou publicação.")
                print("   Verifique os screenshots para ver onde parou.")
                print("   Rode com --debug para pausar em cada etapa e inspecionar.")

        except PWTimeout as e:
            print(f"\n❌ Timeout: {e}")
            await screenshot(page, "ERRO_timeout")
            print("   O Upseller demorou mais que o esperado.")
            print("   Tente rodar com --debug para identificar qual etapa falhou.")

        except Exception as e:
            print(f"\n❌ Erro inesperado: {e}")
            await screenshot(page, "ERRO_inesperado")
            raise

        finally:
            if debug:
                input("\n[DEBUG] Script finalizado. Pressione Enter para fechar o browser...")
            await browser.close()


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Upseller Bot — AJ MODA")
    parser.add_argument("--headless", action="store_true",
                        help="Rodar sem abrir janela do browser")
    parser.add_argument("--debug", action="store_true",
                        help="Pausar em cada etapa para inspeção")
    args = parser.parse_args()

    # No Windows, evita erro de event loop com asyncio
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    asyncio.run(run(headless=args.headless, debug=args.debug))