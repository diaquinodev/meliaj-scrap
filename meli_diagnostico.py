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


# ─── RESOLUÇÃO MLBU → MLB ────────────────────────────────────────────────────
def resolver_mlbu_para_mlb(mlbu: str, access_token: str) -> str | None:
    """
    Dado um MLBU (produto do catálogo universal), encontra o MLB do
    anúncio do vendedor autenticado que está publicado para esse
    produto. Retorna None se o vendedor não tiver nenhum anúncio
    vinculado ao MLBU (nem ao seu parent, se existir).

    Fluxo rigoroso:
      1. GET /products/{mlbu} para descobrir se existe parent_id
         (família de catálogo). Se sim, inclui o parent na busca.
      2. GET /users/me para obter o seller_id.
      3. Para cada candidato (mlbu e parent_id), faz
         GET /sites/MLB/search?seller_id=X&catalog_product_id=ID
         e VERIFICA que o catalog_product_id devolvido no JSON bate
         exatamente com o que foi pedido — o Meli retorna a lista
         genérica do vendedor quando não encontra match, então a
         verificação evita falso positivo.
    """
    headers = {"Authorization": f"Bearer {access_token}"}

    # 1. Tenta descobrir o parent_id do catálogo (família).
    candidato_ids: list[str] = [mlbu]
    status, produto = _get_json(f"{ML_BASE_URL}/products/{mlbu}", headers)
    if status == 401:
        raise TokenExpiredError("Token expirado ao consultar /products.")
    if status == 200 and isinstance(produto, dict):
        parent_id = produto.get("parent_id")
        if parent_id and parent_id != mlbu:
            print(f"   📦 {mlbu} pertence à família {parent_id} — incluindo na busca.")
            candidato_ids.append(parent_id)
    elif status == 404:
        print(f"   ⚠️  /products/{mlbu} não encontrado — seguindo só com o MLBU.")

    # 2. Descobre o seller_id do usuário autenticado.
    status, me = _get_json(f"{ML_BASE_URL}/users/me", headers)
    if status == 401:
        raise TokenExpiredError("Token expirado ao consultar /users/me.")
    if status != 200 or not isinstance(me, dict):
        print(f"⚠️  Não foi possível identificar o vendedor autenticado (HTTP {status}).")
        return None
    seller_id = me.get("id")
    if not seller_id:
        return None

    # 3. Busca em /sites/MLB/search para cada candidato, com
    #    VERIFICAÇÃO RIGOROSA do catalog_product_id retornado.
    for cat_id in candidato_ids:
        url = (
            f"{ML_BASE_URL}/sites/MLB/search"
            f"?seller_id={seller_id}&catalog_product_id={cat_id}"
        )
        status, data = _get_json(url, headers)
        if status == 401:
            raise TokenExpiredError("Token expirado em /sites/MLB/search.")
        if status != 200 or not isinstance(data, dict):
            continue

        for result in data.get("results") or []:
            if not isinstance(result, dict):
                continue
            returned_cat_id = result.get("catalog_product_id")
            # RIGOR: só aceita match EXATO — se o Meli não achar o
            # catalog_product_id pedido, ele devolve a lista genérica
            # do vendedor, então um simples "results[0]" causaria
            # falso positivo.
            if returned_cat_id != cat_id:
                continue
            mlb = result.get("id")
            if mlb:
                print(
                    f"   ✓ Match exato para catalog_product_id={cat_id}: "
                    f"anúncio {mlb}"
                )
                return mlb

        print(f"   ⚠️  Nenhum match exato encontrado para {cat_id}.")

    return None


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

    # Raio-X de SIZE_GRID_ID: verifica se o anúncio tem Tabela de Medidas
    # vinculada. Crítico em moda — sem tabela, a taxa de devolução dispara.
    # O atributo pode aparecer no root (.attributes) OU dentro de variations;
    # basta encontrar um valor não-vazio em qualquer lugar.
    size_grid_id_valor = None
    for a in item_data.get("attributes") or []:
        if a.get("id") == "SIZE_GRID_ID":
            size_grid_id_valor = a.get("value_name") or a.get("value_id")
            break
    if not size_grid_id_valor:
        for v in item_data.get("variations") or []:
            for a in v.get("attributes") or []:
                if a.get("id") == "SIZE_GRID_ID":
                    size_grid_id_valor = a.get("value_name") or a.get("value_id")
                    break
            if size_grid_id_valor:
                break
    tem_tabela_medidas = bool(size_grid_id_valor)

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
        "tem_tabela_medidas": tem_tabela_medidas,
        "size_grid_id": size_grid_id_valor,
    }


# ─── ENDPOINTS EXTRAS DO MERCADO LIVRE ───────────────────────────────────────
def get_visits(mlb: str, headers: dict, days: int = 15) -> int | None:
    """Total de visitas nos últimos N dias (padrão: 15)."""
    status, data = _get_json(
        f"{ML_BASE_URL}/items/{mlb}/visits/time_window?last={days}&unit=day", headers
    )
    if status != 200 or not isinstance(data, dict):
        return None
    results = data.get("results") or []
    if results and isinstance(results, list):
        return sum(r.get("total", 0) for r in results if isinstance(r, dict))
    return data.get("total_visits")


def get_recent_sales(mlb: str, seller_id, headers: dict, days: int = 15) -> int | None:
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


def get_questions(mlb: str, headers: dict, limit: int = 20) -> list:
    """Perguntas recentes do anúncio."""
    status, data = _get_json(
        f"{ML_BASE_URL}/questions/search?item={mlb}&limit={limit}", headers
    )
    if status != 200 or not isinstance(data, dict):
        return []
    return data.get("questions") or []


def contar_perguntas_sem_resposta(perguntas: list) -> int:
    """Conta quantas perguntas não têm resposta (status != ANSWERED)."""
    return sum(
        1 for q in perguntas
        if isinstance(q, dict) and q.get("status") != "ANSWERED"
    )


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
    """Atributos ainda não preenchidos no anúncio, prontos para a IA sugerir.

    Exceção estratégica: MODEL é SEMPRE incluído, mesmo quando já preenchido,
    porque é um hack de SEO — a IA reescreve no formato
    [Tipo] + [Material] + [Ocasião] para turbinar o ranqueamento.
    """
    filled_map = {
        a.get("id"): a.get("valor")
        for a in (item_attrs or [])
        if a.get("id")
    }
    filled = {
        aid for aid, valor in filled_map.items() if valor not in (None, "")
    }

    candidatos = []
    for attr in category_attrs or []:
        aid = attr.get("id")
        if not aid:
            continue

        aid_upper = aid.upper()
        is_model = aid_upper == "MODEL"

        # Já preenchidos são descartados, EXCETO MODEL (SEO override).
        if aid in filled and not is_model:
            continue

        # Nunca mostra identificadores de produto à IA — formato rígido
        # que causa HTTP 400 se preenchido com texto livre.
        if aid_upper in ATTR_BLOCKLIST:
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

        if is_model:
            # Marcadores para a IA entender que deve sobrescrever.
            candidato["current_value"] = filled_map.get(aid)
            candidato["override_with_seo_hack"] = True
            candidato["seo_hack_format"] = "[Tipo] + [Material] + [Ocasião]"

        candidatos.append(candidato)

    # MODEL no topo (hack de SEO), depois required, depois o resto.
    def _rank(c: dict) -> tuple:
        if (c.get("id") or "").upper() == "MODEL":
            return (0, 0)
        return (1, 0 if c.get("required") else 1)

    candidatos.sort(key=_rank)
    return candidatos[:limit]


def coletar_dados_extras(dados: dict, access_token: str) -> dict:
    """Enriquecimento com foco em janela de 15 dias + métricas de qualidade."""
    headers = {"Authorization": f"Bearer {access_token}"}
    mlb = dados["id"]
    DIAS = 15

    print(f"\n📡 Coletando métricas (janela de {DIAS} dias) e contexto:")

    visits = get_visits(mlb, headers, days=DIAS)
    print(f"   • /visits ({DIAS}d)     {'✓ '+str(visits) if visits is not None else '⚠ indisponível'}")

    sales = get_recent_sales(mlb, dados.get("seller_id"), headers, days=DIAS)
    print(f"   • /orders ({DIAS}d)     {'✓ '+str(sales) if sales is not None else '⚠ indisponível'}")

    perguntas = get_questions(mlb, headers)
    sem_resposta = contar_perguntas_sem_resposta(perguntas)
    print(f"   • /questions         ✓ {len(perguntas)} total | {sem_resposta} sem resposta")

    reviews = get_reviews(mlb, headers)
    nota_reviews = (reviews or {}).get("rating_average")
    total_reviews_count = (reviews or {}).get("paging", {}).get("total", 0)
    print(f"   • /reviews           {'✓ nota '+str(nota_reviews)+' ('+str(total_reviews_count)+' reviews)' if nota_reviews else '⚠ sem reviews'}")

    moderations = get_moderations(mlb, headers)
    print(f"   • /moderations       {'✓ '+str(len(moderations)) if moderations else '⚠ 0 ou negado'}")

    seller = get_seller_info(headers)
    print(f"   • /users/me          {'✓' if seller else '⚠'}")

    category_attrs = get_category_attributes(dados.get("categoria"), headers)
    candidatos = filtrar_atributos_candidatos(category_attrs, dados.get("atributos", []))
    print(f"   • /categories/attrs  {'✓ '+str(len(candidatos))+' candidatos' if candidatos else '⚠'}")

    # Conversão 15 dias: sold / visits
    conversao = None
    if visits and visits > 0 and sales is not None:
        conversao = round((sales / visits) * 100, 2)

    dados["visits_15d"] = visits
    dados["sales_15d"] = sales
    dados["conversao_15d_pct"] = conversao
    dados["perguntas"] = perguntas
    dados["perguntas_sem_resposta"] = sem_resposta
    dados["reviews"] = reviews
    dados["nota_reviews"] = nota_reviews
    dados["total_reviews"] = total_reviews_count
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
    print("🧠 Injetando dados no Gemini — modo Diretor de Growth (janela 15 dias)...")

    api_key = load_gemini_api_key()
    client = genai.Client(api_key=api_key)

    perguntas_resumo = [
        {
            "pergunta": q.get("text", "")[:300],
            "status": q.get("status", ""),
        }
        for q in (dados_ml.get("perguntas") or [])[:10]
        if q.get("text")
    ]

    prompt = f"""
Analise os dados abaixo deste ANÚNCIO do Mercado Livre e produza um
PLANO DE GROWTH com foco no funil Visitas → Vendas dos últimos 15 dias.

=== DADOS BÁSICOS DO ANÚNCIO ===
- ID: {dados_ml['id']}
- Título: {dados_ml['titulo']}
- Preço: {dados_ml['moeda']} {dados_ml['preco']}
- Status: {dados_ml['status']}  | Sub-status: {dados_ml.get('sub_status')}
- Tipo de anúncio: {dados_ml['tipo_anuncio']}
- Categoria: {dados_ml['categoria']}
- Condição: {dados_ml['condicao']}
- Estoque disponível: {dados_ml['estoque']}
- Vendas totais históricas: {dados_ml.get('vendidos_total', 0)}
- Saúde (Meli): {dados_ml['saude']}
- Tags internas: {dados_ml['tags']}
- Ações corretivas do Meli: {dados_ml['acoes_saude']}

=== FUNIL DE 15 DIAS ===
- Visitas (15d): {dados_ml.get('visits_15d', 'N/A')}
- Vendas (15d): {dados_ml.get('sales_15d', 'N/A')}
- Taxa de conversão (15d): {dados_ml.get('conversao_15d_pct', 'N/A')}%

=== MÉTRICAS DE QUALIDADE ===
- Perguntas: {len(dados_ml.get('perguntas') or [])} total | {dados_ml.get('perguntas_sem_resposta', 0)} sem resposta
- Nota média de reviews: {dados_ml.get('nota_reviews') or 'sem reviews'}
- Total de reviews: {dados_ml.get('total_reviews', 0)}
- Moderações/infrações: {len(dados_ml.get('moderations') or [])}

=== RAIO-X TABELA DE MEDIDAS ===
- tem_tabela_medidas: {dados_ml.get('tem_tabela_medidas', False)}
- SIZE_GRID_ID: {dados_ml.get('size_grid_id') or '(nenhum)'}

=== DESCRIÇÃO ATUAL ===
{dados_ml['descricao']}

=== ATRIBUTOS JÁ PREENCHIDOS ===
{json.dumps(dados_ml['atributos'], ensure_ascii=False)}

=== ATRIBUTOS_DISPONIVEIS_NA_CATEGORIA ===
IDs EXATOS da categoria {dados_ml['categoria']}.
Use APENAS estes IDs em "atributos_sugeridos". NÃO invente IDs.
Quando tem "allowed_values", escolha da lista.
{json.dumps(dados_ml.get('atributos_candidatos', []), ensure_ascii=False)}

=== PERGUNTAS RECENTES (com status) ===
{json.dumps(perguntas_resumo, ensure_ascii=False)}

INSTRUÇÕES CRÍTICAS:
1. NUNCA sugira GTIN, EAN, UPC, ISBN, COLOR, SIZE, MAIN_COLOR.
2. Use APENAS IDs da lista ATRIBUTOS_DISPONIVEIS_NA_CATEGORIA.
3. O "plano_de_acao_15_dias" deve ter EXATAMENTE 5 passos sequenciais,
   cada um com "dia" (ex.: "Dia 1-2"), "acao" (frase curta) e "detalhe"
   (o que fazer concretamente com título, fotos, preço ou descrição).
   Baseie-se na taxa de conversão do funil — se ela está abaixo de 1%,
   priorize ações de CTR (título/fotos); se está entre 1-3%, priorize
   preço/descrição; se está acima de 3%, foque em escala (estoque/ads).
4. Se tem perguntas sem resposta, alerte em pontos_criticos.
5. Se tem_tabela_medidas é False, alerte e recomende criar.
6. MODEL deve ser reescrito no formato [Tipo]+[Material]+[Ocasião].
7. Responda EXCLUSIVAMENTE com JSON válido no schema pedido.
""".strip()

    system_instruction = (
        "Você é o Diretor de Growth da AJ Moda, e-commerce de moda feminina "
        "no Mercado Livre. Seu papel é analisar o funil de conversão dos "
        "últimos 15 dias e produzir um plano de ação tático e data-driven.\n\n"
        "Responda em português do Brasil, de forma objetiva e acionável.\n\n"
        "REGRA DE SEO - ATRIBUTO MODEL (OBRIGATÓRIA):\n"
        "Sempre que MODEL aparecer em ATRIBUTOS_DISPONIVEIS_NA_CATEGORIA "
        "(mesmo já preenchido), reescreva no formato:\n"
        "    [Tipo] + [Material] + [Ocasião]\n"
        "Exemplos: 'Chamise Linho Casual', 'Blazer Alfaiataria Trabalho'.\n"
        "Máx 4 palavras, sem vírgulas, sem 'moda'/'feminino'. HACK DE SEO.\n\n"
        "REGRA DE TABELA DE MEDIDAS:\n"
        "Se tem_tabela_medidas=False, alerte em pontos_criticos e recomende "
        "criar/vincular tabela de medidas — crítico em moda."
    )

    response_schema = {
        "type": "object",
        "properties": {
            "nota_geral": {
                "type": "number",
                "description": "Nota de 0 a 10 da saúde do funil de conversão.",
            },
            "diagnostico_funil": {
                "type": "string",
                "description": (
                    "Parágrafo curto (3-4 frases) interpretando o funil "
                    "Visitas→Vendas dos 15 dias: onde está o gargalo?"
                ),
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
            "plano_de_acao_15_dias": {
                "type": "array",
                "description": "5 passos sequenciais para os próximos 15 dias.",
                "items": {
                    "type": "object",
                    "properties": {
                        "dia": {
                            "type": "string",
                            "description": "Janela temporal (ex: 'Dia 1-2').",
                        },
                        "acao": {
                            "type": "string",
                            "description": "Ação curta (ex: 'Reescrever título').",
                        },
                        "detalhe": {
                            "type": "string",
                            "description": "O que fazer concretamente.",
                        },
                    },
                    "required": ["dia", "acao", "detalhe"],
                },
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
            "diagnostico_funil",
            "titulo_otimizado",
            "pontos_positivos",
            "pontos_criticos",
            "plano_de_acao_15_dias",
            "atributos_sugeridos",
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
    print("📊 LAUDO DE GROWTH - AJ MODA ESTRATEGISTA")
    print("=" * 64)
    print(f"🆔 Anúncio : {dados_ml['id']}")
    print(f"📌 Título  : {dados_ml['titulo']}")
    print(f"💰 Preço   : {dados_ml['moeda']} {dados_ml['preco']}")

    saude = dados_ml["saude"]
    if isinstance(saude, (int, float)):
        print(f"🌡️  Saúde  : {round(saude * 100, 1)}%")
    else:
        print(f"🌡️  Saúde  : {saude}")

    # Funil de 15 dias
    v = dados_ml.get("visits_15d")
    s = dados_ml.get("sales_15d")
    c = dados_ml.get("conversao_15d_pct")
    print(f"📈 15 dias : visitas={v if v is not None else 'N/A'} | "
          f"vendas={s if s is not None else 'N/A'} | "
          f"conversão={c if c is not None else 'N/A'}%")

    # Métricas de qualidade
    sem_resp = dados_ml.get("perguntas_sem_resposta", 0)
    total_perguntas = len(dados_ml.get("perguntas") or [])
    nota_rev = dados_ml.get("nota_reviews")
    total_rev = dados_ml.get("total_reviews", 0)
    print(f"💬 Perguntas: {total_perguntas} total | {sem_resp} sem resposta"
          + (" ⚠️" if sem_resp > 0 else ""))
    print(f"⭐ Reviews : nota {nota_rev or 'N/A'} ({total_rev} reviews)")

    # Tabela de Medidas
    tem_grid = dados_ml.get("tem_tabela_medidas")
    grid_id = dados_ml.get("size_grid_id")
    if tem_grid:
        print(f"📏 Tabela  : ✓ presente (SIZE_GRID_ID={grid_id})")
    else:
        print("📏 Tabela  : ✗ AUSENTE — crítico em moda")

    # Red flags
    print("\n🚨 RED FLAGS:")
    if not red_flags:
        print("  (nenhum)")
    else:
        for categoria, msg in red_flags:
            print(f"  [{categoria}] {msg}")

    print(f"\n⭐ NOTA DO FUNIL (Gemini): {laudo.get('nota_geral')}/10")

    # Diagnóstico do funil
    diag = laudo.get("diagnostico_funil")
    if diag:
        print(f"\n🔬 DIAGNÓSTICO DO FUNIL:")
        print(f"   {diag}")

    print(f"\n✏️  TÍTULO OTIMIZADO:\n   {laudo.get('titulo_otimizado')}")

    print("\n✅ PONTOS FORTES:")
    for p in laudo.get("pontos_positivos") or ["(nenhum)"]:
        print(f"  [+] {p}")

    print("\n⚠️  PONTOS CRÍTICOS:")
    for cp in laudo.get("pontos_criticos") or ["(nenhum)"]:
        print(f"  [-] {cp}")

    # Plano de ação 15 dias
    plano = laudo.get("plano_de_acao_15_dias") or []
    if plano:
        print("\n🗓️  PLANO DE AÇÃO — PRÓXIMOS 15 DIAS:")
        print("-" * 64)
        for i, step in enumerate(plano, 1):
            dia = step.get("dia", f"Passo {i}")
            acao = step.get("acao", "")
            detalhe = step.get("detalhe", "")
            print(f"  [{dia}] {acao}")
            print(f"         {detalhe}")
        print("-" * 64)

    print("\n🧵 ATRIBUTOS SUGERIDOS (IDs para PUT):")
    attrs = laudo.get("atributos_sugeridos") or []
    if not attrs:
        print("  (nenhum)")
    else:
        for a in attrs:
            nome = a.get("nome_humano") or a.get("id")
            print(f"  [!] {a.get('id'):30s} = {a.get('value_name')}   ({nome})")

    faqs = laudo.get("respostas_perguntas_frequentes") or []
    if faqs:
        print("\n💬 RESPOSTAS SUGERIDAS:")
        for f in faqs:
            print(f"  Q: {f.get('pergunta')}")
            print(f"  A: {f.get('resposta_sugerida')}\n")

    print("\n📝 NOVA DESCRIÇÃO OTIMIZADA:")
    print("-" * 64)
    print(laudo.get("descricao_otimizada"))
    print("-" * 64)
    print("\n✅ Diagnóstico de Growth concluído.")


# ─── INJEÇÃO DAS MELHORIAS NO MERCADO LIVRE ─────────────────────────────────
def _extrair_campos_rejeitados(error_json: dict) -> set:
    """
    Lê a resposta de erro do Meli e devolve o conjunto de campos raiz
    citados como não-atualizáveis (field_not_updatable). Ex.: {"title"}.
    Só considera o `field_not_updatable` — outros erros são fatais.
    """
    rejeitados = set()
    for cause in (error_json or {}).get("cause") or []:
        if not isinstance(cause, dict):
            continue
        if cause.get("code") != "field_not_updatable":
            continue
        for ref in cause.get("references") or []:
            # refs vêm como "item.title", "item.attributes", etc.
            if isinstance(ref, str) and ref.startswith("item."):
                rejeitados.add(ref.split(".", 1)[1])
    return rejeitados


def _put_items_com_retry(mlb: str, item_payload: dict, headers: dict) -> None:
    """
    Tenta o PUT /items. Se o Meli responder 400 com `field_not_updatable`
    em um ou mais campos (ex.: título bloqueado por já ter vendas), remove
    os campos rejeitados do payload e tenta UMA vez de novo. Isso salva
    os atributos quando só o título está bloqueado.
    """
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
        return

    # 400 — tentar extrair campos não-atualizáveis e re-submeter sem eles.
    if res.status_code == 400:
        try:
            err = res.json()
        except ValueError:
            err = {}
        rejeitados = _extrair_campos_rejeitados(err)
        if rejeitados and any(f in item_payload for f in rejeitados):
            payload_retry = {k: v for k, v in item_payload.items() if k not in rejeitados}
            print(
                f"🛡️  Campos não-atualizáveis detectados ({', '.join(sorted(rejeitados))}) "
                f"— removidos do payload. Tentando novamente com: "
                f"{', '.join(sorted(payload_retry.keys())) or '(nada)'}."
            )
            if not payload_retry:
                print("⚠️  Nada restou para atualizar depois do filtro.")
                return
            try:
                res2 = requests.put(
                    f"{ML_BASE_URL}/items/{mlb}",
                    headers=headers,
                    json=payload_retry,
                    timeout=20,
                )
            except requests.RequestException as e:
                print(f"❌ Falha de rede no retry: {e}")
                return
            if res2.status_code == 200:
                print("✅ /items atualizado com sucesso (sem os campos bloqueados).")
            else:
                print(
                    f"❌ Retry também falhou (HTTP {res2.status_code}): "
                    f"{res2.text[:400]}"
                )
            return

    print(f"❌ PUT /items falhou (HTTP {res.status_code}): {res.text[:400]}")


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
        # Hard-enforce de 60 chars: o Meli rejeita com HTTP 400 e a IA
        # eventualmente extrapola mesmo sendo instruída no prompt.
        if len(novo_titulo) > 60:
            print(
                f"🛡️  Título sugerido tem {len(novo_titulo)} chars (limite 60). "
                "Ignorando a mudança de título."
            )
        else:
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
        _put_items_com_retry(mlb, item_payload, headers)

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
        "👉 Digite o MLB do anúncio ou MLBU do produto "
        "(ex.: MLB123456789 ou MLBU987654321): "
    )
    codigo = (entrada or "").strip().upper()

    if MLBU_PATTERN.match(codigo):
        # Catálogo universal: resolver para o MLB do anúncio do próprio
        # vendedor que publica esse produto.
        print(
            f"\n🔗 {codigo} é um produto do catálogo (MLBU). "
            "Procurando seu anúncio vinculado..."
        )
        try:
            mlb_resolvido = resolver_mlbu_para_mlb(codigo, access_token)
        except TokenExpiredError:
            refresh_token = tokens.get("refresh_token")
            if not refresh_token:
                print(
                    "❌ Token expirado e nenhum refresh_token salvo. "
                    "Rode o gerar_token.py."
                )
                sys.exit(1)
            tokens = refresh_access_token(refresh_token)
            access_token = tokens["access_token"]
            try:
                mlb_resolvido = resolver_mlbu_para_mlb(codigo, access_token)
            except TokenExpiredError as e:
                print(f"❌ {e}")
                sys.exit(1)

        if not mlb_resolvido:
            print(f"❌ Não foi possível encontrar um anúncio SEU vinculado ao {codigo}.")
            print("   Possíveis causas:")
            print("   • Você não tem anúncio publicado para esse produto do catálogo")
            print("   • O MLBU está digitado errado")
            print("   • O anúncio está pausado/fechado e fora do índice público")
            print(
                "   💡 Dica: abra o anúncio no seu painel do Meli e copie o "
                "MLB... que aparece na URL."
            )
            sys.exit(1)

        print(f"✅ Resolvido: {codigo} → {mlb_resolvido}")
        mlb = mlb_resolvido
    else:
        mlb = validar_mlb(codigo)

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
