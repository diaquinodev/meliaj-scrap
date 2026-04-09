"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  AJ MODA - DIAGNÓSTICO DE ANÚNCIO DO MERCADO LIVRE                           ║
║  Lê /items/{mlb}, /description e /health e pede um laudo ao Gemini.          ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

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

# Atributos que NUNCA devem ser sugeridos nem enviados via PUT /items.
# Duas razões distintas:
#   (a) Identificadores de produto (GTIN/EAN/UPC/ISBN) têm formato
#       rígido (números de 8 a 14 dígitos com checksum) — texto livre
#       quebra o PUT com HTTP 400.
#   (b) Atributos de grade de variação (COLOR/SIZE/MAIN_COLOR) vivem
#       em variation.attribute_combinations, não em item.attributes.
#       Mandá-los no nível raiz causa "Same attributes are used in
#       more than of item.attributes, variation.attribute_combinations
#       and variation.attributes". Gestão de variações foge do escopo.
# A blocklist é usada em dois lugares:
#   1) filtrar_atributos_candidatos() — removidos antes de chegar na IA
#   2) aplicar_melhorias() — removidos de novo antes do PUT, por segurança
ATTR_BLOCKLIST = {
    # Identificadores de produto
    "GTIN", "EAN", "UPC", "ISBN",
    # Atributos de variação (não vão no nível raiz)
    "COLOR", "SIZE", "MAIN_COLOR",
}


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
        "seller_id": item_data.get("seller_id"),
        "titulo": item_data.get("title", "N/A"),
        "preco": item_data.get("price", "N/A"),
        "moeda": item_data.get("currency_id", "BRL"),
        "status": item_data.get("status", "N/A"),
        "sub_status": item_data.get("sub_status", []) or [],
        "categoria": item_data.get("category_id", "N/A"),
        "condicao": item_data.get("condition", "N/A"),
        "estoque": item_data.get("available_quantity", 0),
        "vendidos_total": item_data.get("sold_quantity", 0),
        "tipo_anuncio": item_data.get("listing_type_id", "N/A"),
        "permalink": item_data.get("permalink", ""),
        "tags": item_data.get("tags", []),
        "atributos": [
            {"id": a.get("id"), "nome": a.get("name"), "valor": a.get("value_name")}
            for a in item_data.get("attributes", [])
        ],
        "descricao": desc_data.get("plain_text") or "Sem descrição",
        "saude": health_data.get("health", "N/A"),
        "acoes_saude": health_data.get("actions", []),
    }


# ─── ENDPOINTS EXTRAS DO MERCADO LIVRE ───────────────────────────────────────
def get_visits_30d(mlb: str, headers: dict) -> int | None:
    """Total de visitas nos últimos 30 dias."""
    status, data = _get_json(
        f"{ML_BASE_URL}/items/{mlb}/visits/time_window?last=30&unit=day", headers
    )
    if status != 200 or not isinstance(data, dict):
        return None
    results = data.get("results") or []
    if results and isinstance(results, list):
        return sum(r.get("total", 0) for r in results if isinstance(r, dict))
    return data.get("total_visits")


def get_recent_sales(mlb: str, seller_id, headers: dict, days: int = 30) -> int | None:
    """Quantidade de pedidos pagos para este item nos últimos N dias."""
    if not seller_id:
        return None
    date_from = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
        "%Y-%m-%dT%H:%M:%S.000-00:00"
    )
    url = (
        f"{ML_BASE_URL}/orders/search"
        f"?seller={seller_id}&item={mlb}"
        f"&order.date_created.from={date_from}"
        f"&order.status=paid"
    )
    status, data = _get_json(url, headers)
    if status != 200 or not isinstance(data, dict):
        return None
    return (data.get("paging") or {}).get("total")


def get_questions(mlb: str, headers: dict, limit: int = 15) -> list:
    """Perguntas recentes do anúncio."""
    status, data = _get_json(
        f"{ML_BASE_URL}/questions/search?item={mlb}&limit={limit}", headers
    )
    if status != 200 or not isinstance(data, dict):
        return []
    return data.get("questions") or []


def get_reviews(mlb: str, headers: dict) -> dict:
    """Reviews públicos do anúncio."""
    status, data = _get_json(f"{ML_BASE_URL}/reviews/item/{mlb}", headers)
    if status != 200 or not isinstance(data, dict):
        return {}
    return data


def get_moderations(mlb: str, headers: dict) -> list:
    """Ações de moderação aplicadas ao anúncio."""
    status, data = _get_json(f"{ML_BASE_URL}/items/{mlb}/moderations", headers)
    if status != 200:
        return []
    if isinstance(data, dict):
        return data.get("actions") or data.get("moderations") or []
    if isinstance(data, list):
        return data
    return []


def get_seller_info(headers: dict) -> dict:
    """Dados do vendedor autenticado (reputação, status, métricas)."""
    status, data = _get_json(f"{ML_BASE_URL}/users/me", headers)
    if status != 200 or not isinstance(data, dict):
        return {}
    return data


def get_category_attributes(category_id: str, headers: dict) -> list:
    """Todos os atributos definidos pela categoria do Meli."""
    if not category_id or category_id == "N/A":
        return []
    status, data = _get_json(
        f"{ML_BASE_URL}/categories/{category_id}/attributes", headers
    )
    if status != 200 or not isinstance(data, list):
        return []
    return data


def filtrar_atributos_candidatos(
    category_attrs: list, item_attrs: list, limit: int = 35
) -> list:
    """Atributos ainda não preenchidos no anúncio, prontos para a IA sugerir."""
    filled = {
        a.get("id") for a in (item_attrs or []) if a.get("valor") not in (None, "")
    }

    candidatos = []
    for attr in category_attrs or []:
        aid = attr.get("id")
        if not aid or aid in filled:
            continue

        # Nunca mostra identificadores de produto à IA — formato rígido
        # que causa HTTP 400 se preenchido com texto livre.
        if aid.upper() in ATTR_BLOCKLIST:
            continue

        tags = attr.get("tags") or {}
        if isinstance(tags, dict) and (tags.get("hidden") or tags.get("read_only")):
            continue

        candidato = {
            "id": aid,
            "nome": attr.get("name", ""),
            "value_type": attr.get("value_type", "string"),
        }

        valores = attr.get("values") or []
        if valores:
            candidato["allowed_values"] = [
                v.get("name") for v in valores[:20] if v.get("name")
            ]

        if isinstance(tags, dict) and tags.get("required"):
            candidato["required"] = True

        candidatos.append(candidato)

    candidatos.sort(key=lambda c: 0 if c.get("required") else 1)
    return candidatos[:limit]


def coletar_dados_extras(dados: dict, access_token: str) -> dict:
    """Enriquecimento: visitas, vendas, perguntas, reviews, moderações, reputação."""
    headers = {"Authorization": f"Bearer {access_token}"}
    mlb = dados["id"]

    print("\n📡 Coletando métricas e contexto extra:")

    visits_30d = get_visits_30d(mlb, headers)
    print(f"   • /visits (30d)      {'✓ '+str(visits_30d) if visits_30d is not None else '⚠ indisponível'}")

    sales_30d = get_recent_sales(mlb, dados.get("seller_id"), headers)
    print(f"   • /orders (30d)      {'✓ '+str(sales_30d) if sales_30d is not None else '⚠ indisponível'}")

    perguntas = get_questions(mlb, headers)
    print(f"   • /questions         {'✓ '+str(len(perguntas)) if perguntas else '⚠ 0'}")

    reviews = get_reviews(mlb, headers)
    nota_reviews = (reviews or {}).get("rating_average")
    print(f"   • /reviews           {'✓ '+str(nota_reviews) if nota_reviews else '⚠ sem reviews'}")

    moderations = get_moderations(mlb, headers)
    print(f"   • /moderations       {'✓ '+str(len(moderations)) if moderations else '⚠ 0 ou negado'}")

    seller = get_seller_info(headers)
    print(f"   • /users/me          {'✓' if seller else '⚠'}")

    category_attrs = get_category_attributes(dados.get("categoria"), headers)
    candidatos = filtrar_atributos_candidatos(category_attrs, dados.get("atributos", []))
    print(f"   • /categories/attrs  {'✓ '+str(len(candidatos))+' candidatos' if candidatos else '⚠'}")

    # Conversão: sold_30d / visits_30d
    conversao = None
    if visits_30d and visits_30d > 0 and sales_30d is not None:
        conversao = round((sales_30d / visits_30d) * 100, 2)

    dados["visits_30d"] = visits_30d
    dados["sales_30d"] = sales_30d
    dados["conversao_30d_pct"] = conversao
    dados["perguntas"] = perguntas
    dados["reviews"] = reviews
    dados["moderations"] = moderations
    dados["seller_info"] = seller
    dados["atributos_candidatos"] = candidatos
    return dados


# ─── DETECTOR DE RED FLAGS ───────────────────────────────────────────────────
BAD_TAGS = {
    "incomplete_technical_specs": "Atributos técnicos incompletos",
    "bad_quality_picture": "Qualidade ruim das fotos",
    "poor_quality_thumbnail": "Thumbnail de baixa qualidade",
    "bad_quality_thumbnail": "Thumbnail de baixa qualidade",
    "dragged_bids": "Anúncio arrastado (lances suspeitos)",
    "moderated": "Anúncio moderado",
}


def detectar_red_flags(dados: dict) -> list:
    flags = []

    for tag in dados.get("tags") or []:
        if tag in BAD_TAGS:
            flags.append(("ANÚNCIO", BAD_TAGS[tag]))

    for ss in dados.get("sub_status") or []:
        flags.append(("SUB_STATUS", str(ss)))

    status = dados.get("status")
    if status == "under_review":
        flags.append(("CRÍTICO", "Anúncio sob revisão (under_review)"))
    elif status == "paused":
        flags.append(("AVISO", "Anúncio pausado"))
    elif status == "closed":
        flags.append(("CRÍTICO", "Anúncio fechado"))

    for mod in (dados.get("moderations") or [])[:5]:
        if isinstance(mod, dict):
            msg = mod.get("reason") or mod.get("description") or mod.get("type") or str(mod)[:120]
        else:
            msg = str(mod)[:120]
        flags.append(("MODERAÇÃO", msg))

    seller = dados.get("seller_info") or {}
    rep = seller.get("seller_reputation") or {}
    level = rep.get("level_id")
    if level in ("1_red", "2_orange", "3_yellow"):
        flags.append(("CONTA", f"Reputação baixa: {level}"))

    metrics = rep.get("metrics") or {}
    for nome, chave in (
        ("Cancelamentos", "cancellations"),
        ("Reclamações", "claims"),
        ("Atraso de despacho", "delayed_handling_time"),
    ):
        rate = (metrics.get(chave) or {}).get("rate") or 0
        if isinstance(rate, (int, float)) and rate > 0.02:
            flags.append(("CONTA", f"{nome}: {rate*100:.1f}%"))

    for ra in (seller.get("status") or {}).get("required_action", []) or []:
        flags.append(("CONTA", f"Ação requerida: {ra}"))

    return flags


# ─── AUDITORIA COM GEMINI (google-genai) ─────────────────────────────────────
def auditar_com_gemini(dados_ml: dict) -> dict:
    print("🧠 Injetando dados no Gemini (google-genai) para auditoria de conversão...")

    api_key = load_gemini_api_key()
    client = genai.Client(api_key=api_key)

    perguntas_resumo = [
        {"pergunta": q.get("text", "")[:300]}
        for q in (dados_ml.get("perguntas") or [])[:10]
        if q.get("text")
    ]
    reviews_data = dados_ml.get("reviews") or {}
    rating_avg = reviews_data.get("rating_average")
    total_reviews = reviews_data.get("rating_levels", {}) if isinstance(reviews_data.get("rating_levels"), dict) else {}

    prompt = f"""
Analise os dados abaixo deste ANÚNCIO do Mercado Livre e produza um laudo
de diagnóstico com foco em CONVERSÃO, REGRAS DO MELI e SEO para MODA.

=== DADOS BÁSICOS DO ANÚNCIO ===
- ID do Anúncio: {dados_ml['id']}
- Título: {dados_ml['titulo']}
- Preço: {dados_ml['moeda']} {dados_ml['preco']}
- Status: {dados_ml['status']}  | Sub-status: {dados_ml.get('sub_status')}
- Tipo de anúncio: {dados_ml['tipo_anuncio']}
- Categoria: {dados_ml['categoria']}
- Condição: {dados_ml['condicao']}
- Estoque disponível: {dados_ml['estoque']}
- Vendas totais históricas: {dados_ml.get('vendidos_total', 0)}
- Nível de Saúde (Meli): {dados_ml['saude']}
- Tags internas (Meli): {dados_ml['tags']}
- Ações corretivas exigidas pelo Meli: {dados_ml['acoes_saude']}

=== PERFORMANCE (30 DIAS) ===
- Visitas: {dados_ml.get('visits_30d', 'N/A')}
- Vendas: {dados_ml.get('sales_30d', 'N/A')}
- Taxa de conversão: {dados_ml.get('conversao_30d_pct', 'N/A')}%

=== DESCRIÇÃO ATUAL ===
{dados_ml['descricao']}

=== ATRIBUTOS JÁ PREENCHIDOS ===
{json.dumps(dados_ml['atributos'], ensure_ascii=False)}

=== ATRIBUTOS_DISPONIVEIS_NA_CATEGORIA (ainda não preenchidos) ===
Estes são os IDs EXATOS aceitos pela categoria {dados_ml['categoria']}.
Use APENAS estes IDs em "atributos_sugeridos". NÃO invente IDs.
Quando um atributo tem "allowed_values", escolha APENAS um valor da lista.
{json.dumps(dados_ml.get('atributos_candidatos', []), ensure_ascii=False)}

=== PERGUNTAS RECENTES DOS COMPRADORES ===
{json.dumps(perguntas_resumo, ensure_ascii=False)}

=== REVIEWS ===
Nota média: {rating_avg} | Distribuição: {total_reviews}

INSTRUÇÕES CRÍTICAS:
1. NUNCA, em NENHUMA hipótese, sugira os atributos:
   - GTIN, EAN, UPC, ISBN — códigos de identificação com formato
     rígido numérico que quebram o PUT /items com HTTP 400 se
     preenchidos com texto livre.
   - COLOR, SIZE, MAIN_COLOR — são atributos de GRADE DE VARIAÇÃO e
     vivem em variation.attribute_combinations, não em item.attributes.
     Enviá-los no nível raiz causa "Same attributes are used in more
     than of item.attributes, variation.attribute_combinations".
   Se qualquer desses aparecer na lista ATRIBUTOS_DISPONIVEIS_NA_CATEGORIA,
   IGNORE-OS completamente.
2. Para cada atributo de moda que puder ser preenchido, use EXATAMENTE o
   "id" da lista ATRIBUTOS_DISPONIVEIS_NA_CATEGORIA. Não invente IDs nem
   use nomes em português como ID.
3. Avalie se o título está otimizado: até 60 caracteres, palavra-chave no
   início, sem caps-lock, sem ícones proibidos. Analise o que as perguntas
   dos compradores revelam sobre dúvidas que o título/descrição não cobrem.
4. Analise a saúde, tags, sub_status e ações do Meli, traduzindo em ações
   práticas. Se a taxa de conversão for baixa, recomende ações específicas.
5. Na "descricao_otimizada", aplique AIDA, com quebras de linha e sem
   emojis proibidos. ANTECIPE e responda as dúvidas que apareceram nas
   perguntas recentes dos compradores.
6. Em "respostas_perguntas_frequentes", para cada pergunta recente sugira
   uma resposta curta e persuasiva.
7. Responda EXCLUSIVAMENTE com JSON válido no schema pedido.
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
            "atributos_sugeridos": {
                "type": "array",
                "description": (
                    "Atributos a injetar via PUT /items. Use APENAS IDs da "
                    "lista ATRIBUTOS_DISPONIVEIS_NA_CATEGORIA."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "ID EXATO da lista fornecida.",
                        },
                        "value_name": {
                            "type": "string",
                            "description": "Valor a preencher.",
                        },
                        "nome_humano": {
                            "type": "string",
                            "description": "Nome legível do atributo.",
                        },
                    },
                    "required": ["id", "value_name", "nome_humano"],
                },
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
            "respostas_perguntas_frequentes": {
                "type": "array",
                "description": "Respostas sugeridas para as perguntas recentes.",
                "items": {
                    "type": "object",
                    "properties": {
                        "pergunta": {"type": "string"},
                        "resposta_sugerida": {"type": "string"},
                    },
                    "required": ["pergunta", "resposta_sugerida"],
                },
            },
        },
        "required": [
            "nota_geral",
            "titulo_otimizado",
            "pontos_positivos",
            "pontos_criticos",
            "atributos_sugeridos",
            "acoes_saude_recomendadas",
            "descricao_otimizada",
            "respostas_perguntas_frequentes",
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
def imprimir_laudo(laudo: dict, dados_ml: dict, red_flags: list) -> None:
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

    # Métricas de 30d
    v = dados_ml.get("visits_30d")
    s = dados_ml.get("sales_30d")
    c = dados_ml.get("conversao_30d_pct")
    print(f"📈 30 dias : visitas={v if v is not None else 'N/A'} | "
          f"vendas={s if s is not None else 'N/A'} | "
          f"conversão={c if c is not None else 'N/A'}%")

    # Red flags
    print("\n🚨 RED FLAGS DETECTADOS NO BACKEND:")
    if not red_flags:
        print("  (nenhum)")
    else:
        for categoria, msg in red_flags:
            print(f"  [{categoria}] {msg}")

    print(f"\n⭐ NOTA DE CONVERSÃO (Gemini): {laudo.get('nota_geral')}/10")
    print(f"\n✏️  TÍTULO OTIMIZADO SUGERIDO:\n   {laudo.get('titulo_otimizado')}")

    print("\n✅ PONTOS FORTES:")
    for p in laudo.get("pontos_positivos") or ["(nenhum)"]:
        print(f"  [+] {p}")

    print("\n⚠️  PONTOS CRÍTICOS:")
    for cp in laudo.get("pontos_criticos") or ["(nenhum)"]:
        print(f"  [-] {cp}")

    print("\n🧵 ATRIBUTOS SUGERIDOS (com IDs prontos para PUT):")
    attrs = laudo.get("atributos_sugeridos") or []
    if not attrs:
        print("  (nenhum)")
    else:
        for a in attrs:
            nome = a.get("nome_humano") or a.get("id")
            print(f"  [!] {a.get('id'):30s} = {a.get('value_name')}   ({nome})")

    print("\n🩺 AÇÕES DE SAÚDE RECOMENDADAS:")
    for a in laudo.get("acoes_saude_recomendadas") or ["(nenhuma)"]:
        print(f"  [>] {a}")

    faqs = laudo.get("respostas_perguntas_frequentes") or []
    if faqs:
        print("\n💬 RESPOSTAS SUGERIDAS PARA PERGUNTAS RECENTES:")
        for f in faqs:
            print(f"  Q: {f.get('pergunta')}")
            print(f"  A: {f.get('resposta_sugerida')}\n")

    print("\n📝 NOVA DESCRIÇÃO OTIMIZADA (pronta para copiar e colar):")
    print("-" * 64)
    print(laudo.get("descricao_otimizada"))
    print("-" * 64)
    print("\n✅ Diagnóstico concluído.")


# ─── INJEÇÃO DAS MELHORIAS NO MERCADO LIVRE ─────────────────────────────────
def aplicar_melhorias(
    mlb: str, laudo: dict, dados: dict, access_token: str, dry_run: bool = False
) -> None:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    item_payload = {}

    novo_titulo = (laudo.get("titulo_otimizado") or "").strip()
    if novo_titulo and novo_titulo != dados.get("titulo"):
        item_payload["title"] = novo_titulo

    attr_payload = []
    ignorados_blocklist = []
    for a in laudo.get("atributos_sugeridos") or []:
        aid = (a.get("id") or "").strip().upper()
        val = (a.get("value_name") or "").strip()
        if not aid or not val:
            continue
        # Blocklist dupla: mesmo que a IA alucine um GTIN/EAN/UPC, nunca
        # deixamos passar para o PUT /items — o Meli valida formato
        # rígido nesses campos e qualquer texto livre causa HTTP 400.
        if aid in ATTR_BLOCKLIST:
            ignorados_blocklist.append(aid)
            continue
        attr_payload.append({"id": aid, "value_name": val})
    if ignorados_blocklist:
        print(
            f"🛡️  Blocklist: removidos {len(ignorados_blocklist)} atributo(s) "
            f"sensíveis sugeridos pela IA: {', '.join(ignorados_blocklist)}"
        )
    if attr_payload:
        item_payload["attributes"] = attr_payload

    nova_descricao = (laudo.get("descricao_otimizada") or "").strip()
    descricao_atual = (dados.get("descricao") or "").strip()
    descricao_changed = bool(nova_descricao) and nova_descricao != descricao_atual

    if not item_payload and not descricao_changed:
        print("\n🟡 Nada para aplicar — a IA não sugeriu mudanças concretas.")
        return

    print("\n" + "=" * 64)
    print("📤 MUDANÇAS A APLICAR" + (" (DRY-RUN)" if dry_run else ""))
    print("=" * 64)

    if "title" in item_payload:
        print("\n✏️  TÍTULO:")
        print(f"   ANTES : {dados['titulo']}")
        print(f"   DEPOIS: {item_payload['title']}")

    if "attributes" in item_payload:
        print(f"\n🧵 ATRIBUTOS ({len(item_payload['attributes'])} novos):")
        for a in item_payload["attributes"]:
            print(f"   + {a['id']:30s} = {a['value_name']}")

    if descricao_changed:
        preview = nova_descricao.replace("\n", " ")[:200]
        print(f"\n📝 DESCRIÇÃO ({len(nova_descricao)} chars):")
        print(f"   Preview: {preview}{'...' if len(nova_descricao) > 200 else ''}")

    if dry_run:
        print("\n🟡 DRY-RUN: nada foi enviado ao Mercado Livre.")
        return

    confirm = input("\n⚠️  Confirma a aplicação destas mudanças? [s/N]: ").strip().lower()
    if confirm != "s":
        print("❌ Cancelado pelo usuário.")
        return

    if item_payload:
        try:
            res = requests.put(
                f"{ML_BASE_URL}/items/{mlb}",
                headers=headers,
                json=item_payload,
                timeout=20,
            )
        except requests.RequestException as e:
            print(f"❌ Falha de rede em PUT /items: {e}")
            return
        if res.status_code == 200:
            print("✅ /items atualizado com sucesso.")
        else:
            print(f"❌ PUT /items falhou (HTTP {res.status_code}): {res.text[:400]}")

    if descricao_changed:
        try:
            res = requests.put(
                f"{ML_BASE_URL}/items/{mlb}/description",
                headers=headers,
                json={"plain_text": nova_descricao},
                timeout=20,
            )
        except requests.RequestException as e:
            print(f"❌ Falha de rede em PUT /description: {e}")
            return
        if res.status_code == 200:
            print("✅ Descrição atualizada com sucesso.")
        else:
            print(f"❌ PUT /description falhou (HTTP {res.status_code}): {res.text[:400]}")

    print("\n🎉 Aplicação concluída.")


# ─── CLI ARGS ────────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Diagnóstico e otimização de anúncios do Mercado Livre via IA."
    )
    p.add_argument("--mlb", help="MLB do anúncio (se omitido, será solicitado).")
    g = p.add_mutually_exclusive_group()
    g.add_argument(
        "--apply",
        action="store_true",
        help="Aplica as melhorias sugeridas pela IA no anúncio (PUT).",
    )
    g.add_argument(
        "--dry-run",
        action="store_true",
        help="Mostra o que seria aplicado, sem enviar ao Meli.",
    )
    return p.parse_args()


# ─── MAIN ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    args = parse_args()

    tokens = load_tokens()
    access_token = tokens.get("access_token")
    if not access_token:
        print("❌ Erro: chave 'access_token' ausente em meli_tokens.json.")
        sys.exit(1)

    entrada = args.mlb or input(
        "👉 Digite o MLB do ANÚNCIO a ser auditado (ex.: MLB123456789): "
    )
    mlb = validar_mlb(entrada)

    try:
        dados = get_ml_data(mlb, access_token)
    except TokenExpiredError:
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

    # Enriquecimento: visitas, vendas, perguntas, reviews, moderações, reputação.
    dados = coletar_dados_extras(dados, access_token)

    # Red flags oficiais do backend.
    red_flags = detectar_red_flags(dados)

    laudo = auditar_com_gemini(dados)
    imprimir_laudo(laudo, dados, red_flags)

    if args.apply or args.dry_run:
        aplicar_melhorias(mlb, laudo, dados, access_token, dry_run=args.dry_run)
