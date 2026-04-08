"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  AJ MODA - DIAGNÓSTICO DE ANÚNCIO DO MERCADO LIVRE                           ║
║  Lê /items/{mlb}, /description e /health e pede um laudo ao Gemini.          ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import json
import os
import re
import sys

import requests
from google import genai
from google.genai import types

# ─── CONFIGURAÇÕES ───────────────────────────────────────────────────────────
TOKEN_FILE = "meli_tokens.json"
GEMINI_KEY_FILE = "gemini_key.txt"
GEMINI_MODEL = "gemini-2.5-flash"
ML_BASE_URL = "https://api.mercadolibre.com"


def load_gemini_api_key() -> str:
    """
    Carrega a chave do Gemini, em ordem de prioridade:
      1. Variável de ambiente GEMINI_API_KEY
      2. Arquivo local gemini_key.txt (que NÃO deve ser commitado)
    Nunca hardcoded — chaves expostas em repo público são automaticamente
    revogadas pelo Google.
    """
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if key:
        return key

    if os.path.exists(GEMINI_KEY_FILE):
        with open(GEMINI_KEY_FILE, "r", encoding="utf-8") as f:
            key = f.read().strip()
        if key:
            return key

    print("❌ Erro: chave do Gemini não encontrada.")
    print("   Defina a variável de ambiente GEMINI_API_KEY ou crie um")
    print(f"   arquivo '{GEMINI_KEY_FILE}' (já está no .gitignore) contendo")
    print("   apenas a chave gerada em https://aistudio.google.com/app/apikey")
    sys.exit(1)

# Credenciais da aplicação AJ MODA (mesmas do gerar_token.py).
# Necessárias para usar o refresh_token e renovar o access_token.
ML_CLIENT_ID = "516207596659548"
ML_CLIENT_SECRET = "ClU8y12DuAFf7SDEeh5dp22aViwu9l3i"

# MLB = anúncio (ex.: MLB123456789). MLBU = produto do catálogo universal.
# As rotas /items/{id}, /description e /health só aceitam MLB de ANÚNCIO.
MLB_PATTERN = re.compile(r"^MLB\d+$")
MLBU_PATTERN = re.compile(r"^MLBU\d+$")


class TokenExpiredError(RuntimeError):
    """Levantada quando a API do Meli devolve 401 (token expirado/invalidado)."""


# ─── TOKEN ───────────────────────────────────────────────────────────────────
def load_tokens() -> dict:
    if not os.path.exists(TOKEN_FILE):
        print(f"❌ Erro: {TOKEN_FILE} não encontrado. Rode o gerar_token.py primeiro.")
        sys.exit(1)
    try:
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"❌ Erro: {TOKEN_FILE} está corrompido ({e}).")
        sys.exit(1)


def save_tokens(tokens: dict) -> None:
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(tokens, f)


def refresh_access_token(refresh_token: str) -> dict:
    """Troca o refresh_token por um novo access_token via OAuth do Meli."""
    print("🔄 Token expirado. Renovando via refresh_token...")

    payload = {
        "grant_type": "refresh_token",
        "client_id": ML_CLIENT_ID,
        "client_secret": ML_CLIENT_SECRET,
        "refresh_token": refresh_token,
    }
    headers = {
        "accept": "application/json",
        "content-type": "application/x-www-form-urlencoded",
    }

    try:
        res = requests.post(
            f"{ML_BASE_URL}/oauth/token", data=payload, headers=headers, timeout=20
        )
    except requests.RequestException as e:
        raise RuntimeError(f"Falha de rede ao renovar token: {e}") from e

    if res.status_code != 200:
        raise RuntimeError(
            f"Falha ao renovar token (HTTP {res.status_code}): {res.text[:300]}\n"
            "O refresh_token também pode ter expirado — rode o gerar_token.py."
        )

    new_tokens = res.json()
    if "access_token" not in new_tokens:
        raise RuntimeError(f"Resposta de refresh sem access_token: {new_tokens}")

    save_tokens(new_tokens)
    print("✅ Token renovado com sucesso e gravado em meli_tokens.json.")
    return new_tokens


# ─── VALIDAÇÃO RIGOROSA DE MLB vs MLBU ───────────────────────────────────────
def validar_mlb(codigo: str) -> str:
    """
    Valida se o código é um MLB de ANÚNCIO válido.
    Rejeita estritamente IDs do catálogo universal (MLBU), pois a rota
    /items/{id} só responde para IDs de anúncio.
    """
    codigo = (codigo or "").strip().upper()

    if not codigo:
        print("❌ Erro: nenhum código foi informado.")
        sys.exit(1)

    if MLBU_PATTERN.match(codigo):
        print("\n" + "=" * 64)
        print("❌ ERRO: VOCÊ INFORMOU UM ID DE PRODUTO (MLBU), NÃO DE ANÚNCIO.")
        print("=" * 64)
        print("Este script audita ANÚNCIOS (MLB), não produtos do catálogo (MLBU).")
        print("")
        print("🔎 Diferença:")
        print("   • MLB  = ID do seu anúncio       (ex.: MLB123456789)")
        print("   • MLBU = ID do catálogo universal (ex.: MLBU987654321)")
        print("")
        print("💡 Abra o seu anúncio na conta do vendedor e copie o código")
        print("   que aparece na URL ou em 'Dados do anúncio'. Ele começa")
        print("   com MLB seguido apenas de dígitos (sem o 'U').")
        sys.exit(1)

    if not MLB_PATTERN.match(codigo):
        print(
            f"❌ Erro: '{codigo}' não tem o formato esperado. "
            "Use MLB seguido apenas de dígitos (ex.: MLB123456789)."
        )
        sys.exit(1)

    return codigo


# ─── API DO MERCADO LIVRE ────────────────────────────────────────────────────
def _get_json(url: str, headers: dict) -> tuple[int, dict]:
    try:
        res = requests.get(url, headers=headers, timeout=20)
    except requests.RequestException as e:
        raise RuntimeError(f"Falha de rede ao chamar {url}: {e}") from e

    try:
        payload = res.json() if res.content else {}
    except ValueError:
        payload = {}
    return res.status_code, payload


def get_ml_data(mlb: str, access_token: str) -> dict:
    headers = {"Authorization": f"Bearer {access_token}"}

    print(f"\n🔎 Puxando raio-x do anúncio {mlb} na API do Mercado Livre...")

    # 1. Dados básicos e tags
    status_item, item_data = _get_json(f"{ML_BASE_URL}/items/{mlb}", headers)

    if status_item == 401:
        raise TokenExpiredError(
            "Token de acesso inválido ou expirado."
        )
    if status_item == 403:
        raise RuntimeError(
            f"Acesso negado ao anúncio {mlb}. Ele pode não pertencer a esta conta."
        )
    if status_item == 404:
        # Segunda camada de defesa contra MLBU: se o usuário burlou o regex
        # (ex.: colou um ID estranho), o Meli responde 404 na rota de anúncio.
        msg = (
            f"Anúncio {mlb} não encontrado (HTTP 404). "
            "Confira se o código é de um ANÚNCIO (MLB) e não de um PRODUTO (MLBU) "
            "do catálogo."
        )
        raise RuntimeError(msg)
    if status_item != 200:
        raise RuntimeError(
            f"Erro inesperado ao consultar /items/{mlb} (HTTP {status_item}): "
            f"{str(item_data)[:300]}"
        )

    # Terceira camada de defesa: o payload de catálogo (MLBU) não traz os
    # campos típicos de um anúncio.
    if not isinstance(item_data, dict) or "title" not in item_data or "price" not in item_data:
        raise RuntimeError(
            "A resposta da API não contém os campos de um anúncio (title/price). "
            "O código informado provavelmente é de um PRODUTO (MLBU) e não de um "
            "ANÚNCIO (MLB)."
        )

    # 2. Descrição
    status_desc, desc_data = _get_json(
        f"{ML_BASE_URL}/items/{mlb}/description", headers
    )
    if status_desc not in (200, 404):
        print(f"⚠️  Aviso: /description retornou HTTP {status_desc}.")
    if not isinstance(desc_data, dict):
        desc_data = {}

    # 3. Termômetro de saúde
    status_health, health_data = _get_json(
        f"{ML_BASE_URL}/items/{mlb}/health", headers
    )
    if status_health not in (200, 404):
        print(f"⚠️  Aviso: /health retornou HTTP {status_health}.")
    if not isinstance(health_data, dict):
        health_data = {}

    return {
        "id": item_data.get("id", mlb),
        "titulo": item_data.get("title", "N/A"),
        "preco": item_data.get("price", "N/A"),
        "moeda": item_data.get("currency_id", "BRL"),
        "status": item_data.get("status", "N/A"),
        "categoria": item_data.get("category_id", "N/A"),
        "condicao": item_data.get("condition", "N/A"),
        "estoque": item_data.get("available_quantity", 0),
        "tipo_anuncio": item_data.get("listing_type_id", "N/A"),
        "permalink": item_data.get("permalink", ""),
        "tags": item_data.get("tags", []),
        "atributos": [
            {"nome": a.get("name"), "valor": a.get("value_name")}
            for a in item_data.get("attributes", [])
        ],
        "descricao": desc_data.get("plain_text") or "Sem descrição",
        "saude": health_data.get("health", "N/A"),
        "acoes_saude": health_data.get("actions", []),
    }


# ─── AUDITORIA COM GEMINI (google-genai) ─────────────────────────────────────
def auditar_com_gemini(dados_ml: dict) -> dict:
    print("🧠 Injetando dados no Gemini (google-genai) para auditoria de conversão...")

    api_key = load_gemini_api_key()
    client = genai.Client(api_key=api_key)

    prompt = f"""
Analise os dados abaixo deste ANÚNCIO do Mercado Livre e produza um laudo
de diagnóstico com foco em CONVERSÃO, REGRAS DO MELI e SEO para MODA.

DADOS DA API DO MERCADO LIVRE:
- ID do Anúncio: {dados_ml['id']}
- Título: {dados_ml['titulo']}
- Preço: {dados_ml['moeda']} {dados_ml['preco']}
- Status: {dados_ml['status']}
- Tipo de anúncio: {dados_ml['tipo_anuncio']}
- Categoria: {dados_ml['categoria']}
- Condição: {dados_ml['condicao']}
- Estoque disponível: {dados_ml['estoque']}
- Nível de Saúde (Meli): {dados_ml['saude']}
- Tags internas (Meli): {dados_ml['tags']}
- Ações corretivas exigidas pelo Meli: {dados_ml['acoes_saude']}
- Descrição atual: {dados_ml['descricao']}
- Atributos preenchidos: {dados_ml['atributos']}

INSTRUÇÕES CRÍTICAS:
1. Seja extremamente detalhista. Aponte erros de copy, ausência de atributos
   técnicos que ajudam a vender ROUPA (gênero, tipo de tecido, composição,
   caimento, tipo de manga, decote, ocasião de uso, estação, etc.).
2. Avalie se o título está otimizado para o algoritmo do Meli: até 60
   caracteres, palavra-chave principal no início, sem caps-lock, sem
   ícones e sem símbolos proibidos pela plataforma.
3. Analise a saúde e as "acoes_saude" exigidas pelo Meli e traduza cada
   uma em ações claras para o vendedor.
4. Na "descricao_otimizada", escreva um copy persuasivo aplicando a técnica
   AIDA (Atenção, Interesse, Desejo, Ação), com quebras de linha e SEM
   emojis proibidos pela plataforma.
5. Responda EXCLUSIVAMENTE com JSON válido no schema pedido.
""".strip()

    system_instruction = (
        "Você é um auditor sênior de Mercado Livre e especialista em SEO e "
        "ranqueamento para e-commerce de moda. Responda sempre em português "
        "do Brasil, de forma objetiva, prática e acionável."
    )

    response_schema = {
        "type": "object",
        "properties": {
            "nota_geral": {
                "type": "number",
                "description": "Nota de 0 a 10 da qualidade geral do anúncio.",
            },
            "titulo_otimizado": {
                "type": "string",
                "description": "Título otimizado sugerido (até 60 caracteres).",
            },
            "pontos_positivos": {
                "type": "array",
                "items": {"type": "string"},
            },
            "pontos_criticos": {
                "type": "array",
                "items": {"type": "string"},
            },
            "atributos_faltantes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Atributos de moda ausentes ou mal preenchidos.",
            },
            "acoes_saude_recomendadas": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Tradução prática das ações exigidas pelo Meli.",
            },
            "descricao_otimizada": {
                "type": "string",
                "description": "Nova descrição completa aplicando AIDA.",
            },
        },
        "required": [
            "nota_geral",
            "titulo_otimizado",
            "pontos_positivos",
            "pontos_criticos",
            "atributos_faltantes",
            "acoes_saude_recomendadas",
            "descricao_otimizada",
        ],
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


# ─── IMPRESSÃO DO LAUDO ──────────────────────────────────────────────────────
def imprimir_laudo(laudo: dict, dados_ml: dict) -> None:
    print("\n" + "=" * 64)
    print("📊 LAUDO DE QUALIDADE - AJ MODA AUDITOR")
    print("=" * 64)
    print(f"🆔 Anúncio : {dados_ml['id']}")
    print(f"📌 Título  : {dados_ml['titulo']}")
    print(f"💰 Preço   : {dados_ml['moeda']} {dados_ml['preco']}")

    saude = dados_ml["saude"]
    if isinstance(saude, (int, float)):
        print(f"🌡️  Saúde  : {round(saude * 100, 1)}%")
    else:
        print(f"🌡️  Saúde  : {saude}")

    print(f"\n⭐ NOTA DE CONVERSÃO (Gemini): {laudo.get('nota_geral')}/10")
    print(f"\n✏️  TÍTULO OTIMIZADO SUGERIDO:\n   {laudo.get('titulo_otimizado')}")

    print("\n✅ PONTOS FORTES:")
    for p in laudo.get("pontos_positivos") or ["(nenhum)"]:
        print(f"  [+] {p}")

    print("\n⚠️  PONTOS CRÍTICOS:")
    for c in laudo.get("pontos_criticos") or ["(nenhum)"]:
        print(f"  [-] {c}")

    print("\n🧵 ATRIBUTOS DE MODA FALTANTES:")
    for a in laudo.get("atributos_faltantes") or ["(nenhum)"]:
        print(f"  [!] {a}")

    print("\n🩺 AÇÕES DE SAÚDE RECOMENDADAS:")
    for a in laudo.get("acoes_saude_recomendadas") or ["(nenhuma)"]:
        print(f"  [>] {a}")

    print("\n📝 NOVA DESCRIÇÃO OTIMIZADA (pronta para copiar e colar):")
    print("-" * 64)
    print(laudo.get("descricao_otimizada"))
    print("-" * 64)
    print("\n✅ Diagnóstico concluído.")


# ─── MAIN ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    tokens = load_tokens()
    access_token = tokens.get("access_token")
    if not access_token:
        print("❌ Erro: chave 'access_token' ausente em meli_tokens.json.")
        sys.exit(1)

    entrada = input(
        "👉 Digite o MLB do ANÚNCIO a ser auditado (ex.: MLB123456789): "
    )
    mlb = validar_mlb(entrada)

    try:
        dados = get_ml_data(mlb, access_token)
    except TokenExpiredError:
        # Tenta renovar automaticamente usando o refresh_token salvo.
        refresh_token = tokens.get("refresh_token")
        if not refresh_token:
            print(
                "❌ Token expirado e nenhum refresh_token salvo. "
                "Rode o gerar_token.py."
            )
            sys.exit(1)
        try:
            tokens = refresh_access_token(refresh_token)
            access_token = tokens["access_token"]
            dados = get_ml_data(mlb, access_token)
        except (RuntimeError, TokenExpiredError) as e:
            print(f"❌ {e}")
            sys.exit(1)
    except RuntimeError as e:
        print(f"❌ {e}")
        sys.exit(1)

    print(f"✅ Anúncio capturado: {dados['titulo']}")

    laudo = auditar_com_gemini(dados)
    imprimir_laudo(laudo, dados)
