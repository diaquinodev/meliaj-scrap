"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  AJ MODA - ESPIÃO DE CONCORRÊNCIA DO MERCADO LIVRE                           ║
║  Busca os 15 primeiros resultados para um termo e pede ao Gemini um          ║
║  relatório de inteligência de mercado (preço médio, palavras vencedoras      ║
║  e estratégia de ataque).                                                    ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import argparse
import json
import re
import sys
from collections import Counter

import requests
from google import genai
from google.genai import types

# Reaproveita toda a infraestrutura de auth/chaves do auditor para não
# duplicar código nem divergir em caso de refatoração.
from meli_diagnostico import (
    GEMINI_MODEL,
    ML_BASE_URL,
    TokenExpiredError,
    load_gemini_api_key,
    load_tokens,
    refresh_access_token,
)

SEARCH_LIMIT = 15
TOP_PRINT = 5

# Stopwords em PT-BR que não devem entrar nas "palavras-chave vencedoras"
# (calculadas em Python para dar um baseline confiável ao Gemini).
STOPWORDS = {
    "a", "o", "e", "de", "do", "da", "dos", "das", "em", "no", "na",
    "para", "por", "com", "sem", "um", "uma", "uns", "umas", "se",
    "ao", "aos", "às", "à", "pra", "pro", "ou", "mais", "ate", "até",
}


class MeliSearchForbiddenError(RuntimeError):
    """Levantada quando /sites/MLB/search responde 403."""


# ─── BUSCA PÚBLICA NO MELI ───────────────────────────────────────────────────
def buscar_concorrentes(termo: str, access_token: str, limit: int = SEARCH_LIMIT) -> list:
    """
    GET /sites/MLB/search?q={termo}&limit=N
    Retorna a lista crua de 'results' (top N). Levanta TokenExpiredError
    em 401 para o main cuidar do refresh. Levanta MeliSearchForbiddenError
    em 403 — esse endpoint foi restringido pelo Meli para apps sem
    credencial de parceiro, e a exceção específica deixa o main dar uma
    mensagem acionável.
    """
    url = f"{ML_BASE_URL}/sites/MLB/search"
    params = {"q": termo, "limit": limit}
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        res = requests.get(url, params=params, headers=headers, timeout=20)
    except requests.RequestException as e:
        raise RuntimeError(f"Falha de rede em /sites/MLB/search: {e}") from e

    if res.status_code == 401:
        raise TokenExpiredError("Token expirado ao consultar /sites/MLB/search.")
    if res.status_code == 403:
        raise MeliSearchForbiddenError(
            f"/sites/MLB/search devolveu HTTP 403 para '{termo}'. "
            f"Body: {res.text[:200]}"
        )
    if res.status_code != 200:
        raise RuntimeError(
            f"Erro inesperado em /sites/MLB/search (HTTP {res.status_code}): "
            f"{res.text[:300]}"
        )

    try:
        data = res.json()
    except ValueError as e:
        raise RuntimeError(f"Resposta não-JSON em /sites/MLB/search: {e}") from e

    return data.get("results") or []


def extrair_concorrentes(results: list) -> list:
    """Normaliza os campos que interessam: id, title, price, seller, permalink."""
    concorrentes = []
    for r in results:
        if not isinstance(r, dict):
            continue
        seller = r.get("seller") or {}
        concorrentes.append(
            {
                "id": r.get("id"),
                "title": r.get("title") or "",
                "price": r.get("price"),
                "seller_nickname": seller.get("nickname") or seller.get("id") or "N/A",
                "permalink": r.get("permalink") or "",
            }
        )
    return concorrentes


# ─── ESTATÍSTICAS LOCAIS ─────────────────────────────────────────────────────
def calcular_preco_medio(concorrentes: list) -> float | None:
    precos = [c["price"] for c in concorrentes if isinstance(c.get("price"), (int, float))]
    if not precos:
        return None
    return round(sum(precos) / len(precos), 2)


_WORD_RE = re.compile(r"[A-Za-zÀ-ÿ0-9]+")


def tokenizar_titulo(titulo: str) -> list:
    """Quebra um título em tokens lowercase alfanuméricos."""
    return [t.lower() for t in _WORD_RE.findall(titulo or "")]


def top_palavras_chave(concorrentes: list, termo: str, n: int = 3) -> list:
    """
    Conta as palavras mais frequentes nos títulos, excluindo stopwords e
    as próprias palavras do termo de busca (que naturalmente dominariam
    o ranking e não dizem nada sobre a estratégia dos vendedores).
    """
    excluir = set(tokenizar_titulo(termo)) | STOPWORDS
    contador: Counter = Counter()
    for c in concorrentes:
        for token in tokenizar_titulo(c.get("title", "")):
            if len(token) <= 2:
                continue
            if token in excluir:
                continue
            contador[token] += 1
    return [w for w, _ in contador.most_common(n)]


# ─── ANÁLISE COM GEMINI ──────────────────────────────────────────────────────
def analisar_com_gemini(
    termo: str,
    concorrentes: list,
    preco_medio_py: float | None,
    top_palavras_py: list,
) -> dict:
    print("🧠 Pedindo laudo de inteligência de mercado ao Gemini...")

    api_key = load_gemini_api_key()
    client = genai.Client(api_key=api_key)

    concorrentes_compactos = [
        {
            "id": c["id"],
            "title": c["title"][:120],
            "price": c["price"],
            "seller": c["seller_nickname"],
        }
        for c in concorrentes
    ]

    prompt = f"""
Você é um Analista de Inteligência de Mercado da marca AJ Moda, que vende
roupa feminina no Mercado Livre. Analise os 15 primeiros resultados da
busca pelo termo "{termo}" e devolva um JSON estruturado com insights
acionáveis para desbancar esses concorrentes.

=== TERMO DE BUSCA ===
{termo}

=== TOP {SEARCH_LIMIT} CONCORRENTES (ORDEM DE RANKING DO MELI) ===
{json.dumps(concorrentes_compactos, ensure_ascii=False, indent=2)}

=== ESTATÍSTICAS PRÉ-CALCULADAS (PARA VOCÊ VALIDAR) ===
- preco_medio (Python, sobre os 15): R$ {preco_medio_py if preco_medio_py is not None else 'N/A'}
- top 3 palavras mais repetidas nos títulos (Python, excluindo o termo de busca
  e stopwords): {top_palavras_py}

INSTRUÇÕES:
1. Em "preco_medio" devolva EXATAMENTE o valor numérico calculado acima
   (já é o preço médio real dos 15 resultados; não invente números).
2. Em "palavras_chave_vencedoras" devolva exatamente 3 palavras. Comece
   pelas do cálculo Python, mas você pode refinar trocando palavras
   ambíguas por termos mais comerciais e relevantes para moda feminina
   (ex.: "linho", "chamise", "resort", "alfaiataria"). NUNCA repita
   palavras do termo de busca.
3. Em "estrategia_ataque" escreva UM parágrafo curto (4-6 frases)
   aconselhando a AJ Moda sobre:
     - que faixa de preço usar para ficar competitivo sem queimar margem;
     - que título copiar/adaptar para aparecer nesse ranking;
     - qual ângulo diferenciador (material, caimento, ocasião) usar
       para não virar commodity.
4. Responda EXCLUSIVAMENTE com JSON válido no schema pedido.
""".strip()

    system_instruction = (
        "Você é um analista sênior de inteligência competitiva para "
        "e-commerce de moda feminina no Mercado Livre. Seja objetivo, "
        "prático e data-driven. Responda em português do Brasil."
    )

    response_schema = {
        "type": "object",
        "properties": {
            "preco_medio": {
                "type": "number",
                "description": "Preço médio dos 15 concorrentes (em BRL).",
            },
            "palavras_chave_vencedoras": {
                "type": "array",
                "description": "3 palavras-chave mais repetidas nos títulos vencedores, excluindo o termo de busca.",
                "items": {"type": "string"},
            },
            "estrategia_ataque": {
                "type": "string",
                "description": "Parágrafo curto de estratégia para a AJ Moda desbancar esses 15.",
            },
        },
        "required": ["preco_medio", "palavras_chave_vencedoras", "estrategia_ataque"],
    }

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                response_schema=response_schema,
                temperature=0.4,
            ),
        )
    except Exception as e:
        print(f"❌ Erro na IA Gemini: {e}")
        sys.exit(1)

    raw = (response.text or "").strip()
    if not raw:
        print("❌ Gemini retornou resposta vazia.")
        sys.exit(1)

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"❌ Gemini não retornou JSON válido: {e}")
        print(f"Resposta bruta: {raw[:500]}")
        sys.exit(1)


# ─── RELATÓRIO ───────────────────────────────────────────────────────────────
def _fmt_brl(v) -> str:
    if not isinstance(v, (int, float)):
        return "N/A"
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def imprimir_relatorio(
    termo: str,
    concorrentes: list,
    preco_medio_py: float | None,
    top_palavras_py: list,
    laudo: dict,
) -> None:
    print("\n" + "=" * 72)
    print("🕵️  ESPIÃO DE CONCORRÊNCIA — AJ MODA")
    print("=" * 72)
    print(f"🔎 Termo       : {termo}")
    print(f"📦 Analisados  : {len(concorrentes)} anúncios (top {SEARCH_LIMIT} do Meli)")
    print(f"💰 Preço médio : {_fmt_brl(preco_medio_py)} (cálculo Python)")
    print(f"🔑 Top palavras: {', '.join(top_palavras_py) or '(nenhuma)'} (Python)")

    print("\n" + "-" * 72)
    print(f"🏆 TOP {TOP_PRINT} CONCORRENTES (ranking do Meli)")
    print("-" * 72)
    for i, c in enumerate(concorrentes[:TOP_PRINT], start=1):
        titulo = c["title"][:70]
        preco = _fmt_brl(c["price"])
        print(f"\n  #{i}  {titulo}")
        print(f"       💰 {preco}   👤 {c['seller_nickname']}   🆔 {c['id']}")
        if c.get("permalink"):
            print(f"       🔗 {c['permalink']}")

    print("\n" + "=" * 72)
    print("🧠 LAUDO DE INTELIGÊNCIA (Gemini)")
    print("=" * 72)
    print(f"\n💰 Preço médio (Gemini)  : {_fmt_brl(laudo.get('preco_medio'))}")

    palavras = laudo.get("palavras_chave_vencedoras") or []
    print(f"🔑 Palavras vencedoras   : {', '.join(palavras) if palavras else '(nenhuma)'}")

    print("\n⚔️  ESTRATÉGIA DE ATAQUE:")
    print("-" * 72)
    print(laudo.get("estrategia_ataque") or "(nenhuma)")
    print("-" * 72)
    print("\n✅ Espionagem concluída.")


# ─── CLI ─────────────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Espião de concorrência do Mercado Livre para a AJ Moda."
    )
    p.add_argument(
        "--q",
        required=True,
        help="Termo de busca (ex.: 'Conjunto Feminino Linho').",
    )
    return p.parse_args()


# ─── MAIN ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    args = parse_args()
    termo = (args.q or "").strip()
    if not termo:
        print("❌ Erro: --q não pode ser vazio.")
        sys.exit(1)

    tokens = load_tokens()
    access_token = tokens.get("access_token")
    if not access_token:
        print("❌ Erro: chave 'access_token' ausente em meli_tokens.json.")
        sys.exit(1)

    print(f"\n🔎 Buscando '{termo}' no Mercado Livre (top {SEARCH_LIMIT})...")
    try:
        results = buscar_concorrentes(termo, access_token)
    except TokenExpiredError:
        refresh_token = tokens.get("refresh_token")
        if not refresh_token:
            print("❌ Token expirado e nenhum refresh_token salvo. Rode o gerar_token.py.")
            sys.exit(1)
        try:
            tokens = refresh_access_token(refresh_token)
            access_token = tokens["access_token"]
            results = buscar_concorrentes(termo, access_token)
        except MeliSearchForbiddenError as e:
            print("\n" + "=" * 72)
            print("❌ ENDPOINT /sites/MLB/search BLOQUEADO (HTTP 403)")
            print("=" * 72)
            print(f"Detalhe: {e}")
            print(
                "\nO Mercado Livre restringiu a busca pública por termo (q=) "
                "para apps sem credencial de parceiro. Mesmo enviando o "
                "access_token válido da AJ Moda, todas as variações do "
                "endpoint (q, category, domain_id, seller_id) devolvem 403."
            )
            print(
                "\nCaminhos possíveis:\n"
                "  1. Registrar o app AJ Moda como parceiro Meli e pedir "
                "acesso ao /sites/MLB/search.\n"
                "  2. Usar o Mercado Livre Ads API, se disponível no seu plano.\n"
                "  3. Extrair os concorrentes via scraping do site público "
                "(playwright — você já tem instalado)."
            )
            sys.exit(2)
        except (RuntimeError, TokenExpiredError) as e:
            print(f"❌ {e}")
            sys.exit(1)
    except MeliSearchForbiddenError as e:
        print("\n" + "=" * 72)
        print("❌ ENDPOINT /sites/MLB/search BLOQUEADO (HTTP 403)")
        print("=" * 72)
        print(f"Detalhe: {e}")
        print(
            "\nO Mercado Livre restringiu a busca pública por termo (q=) "
            "para apps sem credencial de parceiro. Mesmo enviando o "
            "access_token válido da AJ Moda, todas as variações do "
            "endpoint (q, category, domain_id, seller_id) devolvem 403."
        )
        print(
            "\nCaminhos possíveis:\n"
            "  1. Registrar o app AJ Moda como parceiro Meli e pedir "
            "acesso ao /sites/MLB/search.\n"
            "  2. Usar o Mercado Livre Ads API, se disponível no seu plano.\n"
            "  3. Extrair os concorrentes via scraping do site público "
            "(playwright — você já tem instalado)."
        )
        sys.exit(2)
    except RuntimeError as e:
        print(f"❌ {e}")
        sys.exit(1)

    concorrentes = extrair_concorrentes(results)
    if not concorrentes:
        print("❌ Nenhum resultado retornado para esse termo.")
        sys.exit(1)

    print(f"✅ {len(concorrentes)} concorrentes capturados.")

    preco_medio_py = calcular_preco_medio(concorrentes)
    top_palavras_py = top_palavras_chave(concorrentes, termo, n=3)

    laudo = analisar_com_gemini(termo, concorrentes, preco_medio_py, top_palavras_py)
    imprimir_relatorio(termo, concorrentes, preco_medio_py, top_palavras_py, laudo)
