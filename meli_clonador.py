"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  AJ MODA - CLONADOR INTELIGENTE DE ANÚNCIOS                                 ║
║  Clona um anúncio base, otimiza com inteligência competitiva (espião)        ║
║  e IA (Gemini), e publica via POST /items.                                   ║
║                                                                              ║
║  Fluxo:                                                                      ║
║    Fase 1 → Extração do anúncio base (GET /items/{mlb})                      ║
║    Fase 2 → Espionagem de concorrentes (busca ML + Playwright fallback)      ║
║    Fase 3 → Cérebro Gemini (otimiza título, preço, descrição, atributos)     ║
║    Fase 4 → Montagem do payload POST /items                                  ║
║    Fase 5 → Publicação (POST /items + POST /items/{id}/description)          ║
║                                                                              ║
║  Segurança: sem --publish, faz apenas DRY-RUN (imprime o JSON).             ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import argparse
import json
import re
import sys

import requests
from google import genai
from google.genai import types

from meli_diagnostico import (
    ATTR_BLOCKLIST,
    GEMINI_MODEL,
    ML_BASE_URL,
    TokenExpiredError,
    _get_json,
    load_gemini_api_key,
    load_tokens,
    refresh_access_token,
    validar_mlb,
)
from meli_espiao import (
    buscar_concorrentes,
    calcular_preco_medio,
    top_palavras_chave,
)


# ─── FASE 1: EXTRAÇÃO DO ANÚNCIO BASE ──────────────────────────────────────
def extrair_anuncio_base(mlb: str, access_token: str) -> dict:
    """
    GET /items/{mlb} — captura o payload completo do anúncio.
    Retorna os campos relevantes para clonagem.
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    print(f"\n📋 Fase 1 — Extraindo esqueleto do anúncio {mlb}...")

    status, data = _get_json(f"{ML_BASE_URL}/items/{mlb}", headers)

    if status == 401:
        raise TokenExpiredError("Token expirado ao consultar /items.")
    if status == 404:
        raise RuntimeError(f"Anúncio {mlb} não encontrado (404).")
    if status != 200 or not isinstance(data, dict):
        raise RuntimeError(
            f"Erro ao consultar /items/{mlb} (HTTP {status}): "
            f"{str(data)[:300]}"
        )

    if "title" not in data or "price" not in data:
        raise RuntimeError(
            "Resposta não contém campos de anúncio (title/price). "
            "Pode ser um MLBU de catálogo."
        )

    # Descrição (separada da rota principal)
    status_desc, desc_data = _get_json(
        f"{ML_BASE_URL}/items/{mlb}/description", headers
    )
    descricao = ""
    if status_desc == 200 and isinstance(desc_data, dict):
        descricao = desc_data.get("plain_text") or ""

    # Fotos: array de URLs (source) para reusar no POST
    pictures_source = []
    for pic in data.get("pictures") or []:
        url = pic.get("secure_url") or pic.get("url")
        if url:
            pictures_source.append({"source": url})

    # Atributos: filtrar os que são relevantes para clonagem
    # (remove read_only que o Meli gerencia sozinho)
    attrs_clone = []
    for a in data.get("attributes") or []:
        aid = a.get("id") or ""
        # Pula atributos bloqueados
        if aid.upper() in ATTR_BLOCKLIST:
            continue
        # Pula atributos que o Meli gera automaticamente
        tags = a.get("tags") or {}
        if isinstance(tags, dict) and tags.get("read_only"):
            continue
        entry = {"id": aid, "value_name": a.get("value_name")}
        if a.get("value_id"):
            entry["value_id"] = a["value_id"]
        attrs_clone.append(entry)

    # Variations: repassa fielmente (crítico em moda)
    variations_clone = []
    for v in data.get("variations") or []:
        var = {}
        if v.get("attribute_combinations"):
            var["attribute_combinations"] = v["attribute_combinations"]
        if v.get("price"):
            var["price"] = v["price"]
        if v.get("available_quantity") is not None:
            var["available_quantity"] = v["available_quantity"]
        # Fotos da variação
        pic_ids = v.get("picture_ids") or []
        if pic_ids:
            var["picture_ids"] = pic_ids
        if v.get("seller_custom_field"):
            var["seller_custom_field"] = v["seller_custom_field"]
        if var:
            variations_clone.append(var)

    # Sale terms (garantia etc.)
    sale_terms_clone = []
    for st in data.get("sale_terms") or []:
        entry = {"id": st.get("id")}
        if st.get("value_id"):
            entry["value_id"] = st["value_id"]
        elif st.get("value_name"):
            entry["value_name"] = st["value_name"]
        sale_terms_clone.append(entry)

    base = {
        "id_original": data.get("id"),
        "title": data.get("title", ""),
        "price": data.get("price"),
        "currency_id": data.get("currency_id", "BRL"),
        "category_id": data.get("category_id"),
        "condition": data.get("condition", "new"),
        "buying_mode": data.get("buying_mode", "buy_it_now"),
        "listing_type_id": data.get("listing_type_id", "gold_special"),
        "available_quantity": data.get("available_quantity", 1),
        "pictures": pictures_source,
        "attributes": attrs_clone,
        "variations": variations_clone,
        "sale_terms": sale_terms_clone,
        "seller_custom_field": data.get("seller_custom_field"),
        "shipping": _extrair_shipping(data.get("shipping") or {}),
        "descricao_original": descricao,
        "permalink_original": data.get("permalink", ""),
        "tags": data.get("tags") or [],
    }

    print(f"   ✓ Título: {base['title']}")
    print(f"   ✓ Preço: {base['currency_id']} {base['price']}")
    print(f"   ✓ Categoria: {base['category_id']}")
    print(f"   ✓ Fotos: {len(base['pictures'])}")
    print(f"   ✓ Atributos: {len(base['attributes'])}")
    print(f"   ✓ Variações: {len(base['variations'])}")
    print(f"   ✓ Descrição: {len(base['descricao_original'])} chars")

    return base


def _extrair_shipping(shipping: dict) -> dict:
    """Campos de shipping aceitos no POST /items."""
    s: dict = {}
    if shipping.get("free_shipping") is not None:
        s["free_shipping"] = shipping["free_shipping"]
    if shipping.get("local_pick_up") is not None:
        s["local_pick_up"] = shipping["local_pick_up"]
    if shipping.get("logistic_type"):
        s["logistic_type"] = shipping["logistic_type"]
    return s


# ─── FASE 2: ESPIONAGEM ────────────────────────────────────────────────────
def espionar_concorrentes(titulo: str, access_token: str) -> dict:
    """
    Usa a engine do meli_espiao.py para buscar concorrentes pelo título
    e calcular preço médio + top palavras-chave.
    """
    print(f"\n🕵️  Fase 2 — Espionando concorrentes para: '{titulo}'...")

    concorrentes = buscar_concorrentes(titulo, access_token)
    if not concorrentes:
        print("   ⚠️  Nenhum concorrente encontrado. Continuando sem dados competitivos.")
        return {
            "concorrentes": [],
            "preco_medio": None,
            "top_palavras": [],
        }

    preco_medio = calcular_preco_medio(concorrentes)
    top_palavras = top_palavras_chave(concorrentes, titulo, n=5)

    print(f"   ✓ {len(concorrentes)} concorrentes capturados")
    print(f"   ✓ Preço médio: R$ {preco_medio}" if preco_medio else "   ⚠️  Preço médio: N/A")
    print(f"   ✓ Top palavras: {', '.join(top_palavras)}")

    return {
        "concorrentes": concorrentes[:15],
        "preco_medio": preco_medio,
        "top_palavras": top_palavras,
    }


# ─── FASE 3: CÉREBRO GEMINI ────────────────────────────────────────────────
def gerar_otimizacao_gemini(base: dict, intel: dict) -> dict:
    """
    Envia o payload base + dados competitivos ao Gemini.
    Retorna: novo_titulo, novo_preco, nova_descricao, novos_atributos.
    """
    print("\n🧠 Fase 3 — Gemini otimizando o novo anúncio...")

    api_key = load_gemini_api_key()
    client = genai.Client(api_key=api_key)

    # Resumo dos concorrentes para o prompt (compacto)
    conc_resumo = [
        {"title": c["title"][:100], "price": c["price"]}
        for c in intel.get("concorrentes", [])[:10]
    ]

    # Atributos atuais para o Gemini poder sugerir override
    attrs_atuais = [
        {"id": a["id"], "value_name": a.get("value_name", "")}
        for a in base["attributes"][:30]
    ]

    prompt = f"""
Você vai otimizar um CLONE de anúncio de moda feminina para o Mercado Livre.
Abaixo estão os dados do anúncio base e a inteligência competitiva.

=== ANÚNCIO BASE (ESQUELETO) ===
- Título original: {base['title']}
- Preço original: {base['currency_id']} {base['price']}
- Categoria: {base['category_id']}
- Qtd disponível: {base['available_quantity']}
- Variações: {len(base['variations'])} variação(ões)
- Tipo anúncio: {base['listing_type_id']}

=== ATRIBUTOS ATUAIS ===
{json.dumps(attrs_atuais, ensure_ascii=False, indent=2)}

=== DESCRIÇÃO ORIGINAL ===
{base['descricao_original'][:2000]}

=== INTELIGÊNCIA COMPETITIVA ===
- Preço médio dos concorrentes: R$ {intel.get('preco_medio') or 'N/A'}
- Top palavras-chave vencedoras: {intel.get('top_palavras') or []}
- Top 10 concorrentes:
{json.dumps(conc_resumo, ensure_ascii=False, indent=2)}

INSTRUÇÕES:

1. "novo_titulo": Crie um título OTIMIZADO para SEO (máximo 60 caracteres).
   - Coloque a palavra-chave principal no início.
   - Use palavras das "top palavras-chave vencedoras" quando fizer sentido.
   - Sem caps-lock total, sem emojis, sem caracteres proibidos.

2. "novo_preco": Sugira um preço estratégico (float) baseado no preço médio
   dos concorrentes. Se o preço original é maior que a média, sugira algo
   ligeiramente abaixo da média para ganhar ranking. Se já é competitivo,
   mantenha. Nunca sugira abaixo de 70% do preço original (proteger margem).

3. "nova_descricao": Reescreva a descrição usando o método AIDA
   (Atenção, Interesse, Desejo, Ação). Português do Brasil, tom profissional
   e persuasivo. Inclua detalhes sobre material, caimento e ocasião.
   Sem emojis proibidos pelo Meli. Quebre em parágrafos.

4. "novos_atributos": Array de atributos para injetar no novo anúncio.
   - OBRIGATÓRIO reescrever MODEL no formato [Tipo] + [Material] + [Ocasião]
     (ex: "Chamise Linho Casual", "Blazer Alfaiataria Trabalho").
   - Sugira outros atributos que agreguem valor ao SEO.
   - Use APENAS IDs que já existam nos atributos atuais ou que você sabe
     serem válidos para moda no Meli.
   - NUNCA sugira GTIN, EAN, UPC, ISBN, COLOR, SIZE, MAIN_COLOR.

5. Responda EXCLUSIVAMENTE com JSON válido no schema pedido.
""".strip()

    system_instruction = (
        "Você é o diretor de e-commerce da AJ Moda, especialista em "
        "Mercado Livre, SEO para moda feminina e precificação competitiva. "
        "Responda em português do Brasil, de forma objetiva e acionável."
    )

    response_schema = {
        "type": "object",
        "properties": {
            "novo_titulo": {
                "type": "string",
                "description": "Título otimizado (max 60 chars, SEO).",
            },
            "novo_preco": {
                "type": "number",
                "description": "Preço estratégico sugerido (float em BRL).",
            },
            "nova_descricao": {
                "type": "string",
                "description": "Descrição AIDA completa em português.",
            },
            "novos_atributos": {
                "type": "array",
                "description": "Atributos otimizados para o clone.",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "value_name": {"type": "string"},
                    },
                    "required": ["id", "value_name"],
                },
            },
        },
        "required": ["novo_titulo", "novo_preco", "nova_descricao", "novos_atributos"],
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
        resultado = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"❌ Gemini não retornou JSON válido: {e}")
        print(f"Resposta bruta: {raw[:500]}")
        sys.exit(1)

    novo_titulo = (resultado.get("novo_titulo") or "").strip()
    if len(novo_titulo) > 60:
        print(f"   🛡️  Título Gemini tem {len(novo_titulo)} chars — truncando para 60.")
        novo_titulo = novo_titulo[:60].rsplit(" ", 1)[0]
        resultado["novo_titulo"] = novo_titulo

    print(f"   ✓ Novo título: {resultado['novo_titulo']}")
    print(f"   ✓ Novo preço: R$ {resultado['novo_preco']}")
    print(f"   ✓ Nova descrição: {len(resultado.get('nova_descricao', ''))} chars")
    print(f"   ✓ Atributos otimizados: {len(resultado.get('novos_atributos', []))}")

    return resultado


# ─── FASE 4: MONTAGEM DO PAYLOAD POST /items ───────────────────────────────
def montar_payload_post(base: dict, otimizacao: dict) -> dict:
    """
    Constrói o JSON final para POST /items a partir do esqueleto base
    e das otimizações do Gemini.
    """
    print("\n🔧 Fase 4 — Montando payload de publicação...")

    # Atributos: parte dos originais + override com sugestões do Gemini
    attrs_por_id = {}
    for a in base["attributes"]:
        aid = (a.get("id") or "").upper()
        if aid not in ATTR_BLOCKLIST:
            attrs_por_id[a["id"]] = a

    # Override com atributos do Gemini (blocklist dupla)
    ignorados = []
    for a in otimizacao.get("novos_atributos") or []:
        aid = (a.get("id") or "").strip()
        val = (a.get("value_name") or "").strip()
        if not aid or not val:
            continue
        if aid.upper() in ATTR_BLOCKLIST:
            ignorados.append(aid)
            continue
        attrs_por_id[aid] = {"id": aid, "value_name": val}

    if ignorados:
        print(
            f"   🛡️  Blocklist: removidos {len(ignorados)} atributo(s) "
            f"do Gemini: {', '.join(ignorados)}"
        )

    attrs_final = list(attrs_por_id.values())

    payload: dict = {
        "title": otimizacao["novo_titulo"],
        "category_id": base["category_id"],
        "price": otimizacao["novo_preco"],
        "currency_id": base["currency_id"],
        "available_quantity": base["available_quantity"],
        "buying_mode": base["buying_mode"],
        "condition": base["condition"],
        "listing_type_id": base["listing_type_id"],
        "pictures": base["pictures"],
        "attributes": attrs_final,
    }

    # Variações: repassa fielmente do original (crítico em moda)
    if base["variations"]:
        payload["variations"] = base["variations"]
        print(f"   ✓ {len(base['variations'])} variação(ões) repassadas do original")

    # Sale terms (garantia)
    if base["sale_terms"]:
        payload["sale_terms"] = base["sale_terms"]

    # Shipping
    if base["shipping"]:
        payload["shipping"] = base["shipping"]

    # seller_custom_field
    if base.get("seller_custom_field"):
        payload["seller_custom_field"] = base["seller_custom_field"]

    print(f"   ✓ Payload montado: {len(json.dumps(payload))} bytes")
    print(f"   ✓ Título: {payload['title']}")
    print(f"   ✓ Preço: {payload['currency_id']} {payload['price']}")
    print(f"   ✓ Fotos: {len(payload['pictures'])}")
    print(f"   ✓ Atributos: {len(payload['attributes'])}")

    return payload


# ─── FASE 5: PUBLICAÇÃO ────────────────────────────────────────────────────
def publicar_anuncio(
    payload: dict, descricao: str, access_token: str
) -> str | None:
    """
    POST /items → cria o anúncio.
    POST /items/{novo_id}/description → injeta a descrição AIDA.
    Retorna o novo MLB ID ou None se falhar.
    """
    print("\n🚀 Fase 5 — Publicando no Mercado Livre...")

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    # POST /items
    try:
        res = requests.post(
            f"{ML_BASE_URL}/items",
            headers=headers,
            json=payload,
            timeout=30,
        )
    except requests.RequestException as e:
        print(f"❌ Falha de rede em POST /items: {e}")
        return None

    if res.status_code == 401:
        raise TokenExpiredError("Token expirado ao publicar.")

    if res.status_code not in (200, 201):
        print(f"\n❌ POST /items falhou (HTTP {res.status_code}):")
        try:
            err = res.json()
            print(json.dumps(err, ensure_ascii=False, indent=2)[:2000])

            # Dica: detalhar campos problemáticos
            for cause in (err.get("cause") or []):
                if isinstance(cause, dict):
                    code = cause.get("code", "")
                    refs = cause.get("references") or []
                    msg = cause.get("message", "")
                    print(f"   💡 {code}: {msg} → {refs}")
        except ValueError:
            print(res.text[:1000])
        return None

    novo_data = res.json()
    novo_id = novo_data.get("id")
    permalink = novo_data.get("permalink", "")
    print(f"\n✅ Anúncio criado com sucesso!")
    print(f"   🆔 Novo ID   : {novo_id}")
    print(f"   🔗 Permalink : {permalink}")

    # POST /items/{novo_id}/description
    if descricao and novo_id:
        print(f"\n📝 Injetando descrição AIDA ({len(descricao)} chars)...")
        try:
            res_desc = requests.post(
                f"{ML_BASE_URL}/items/{novo_id}/description",
                headers=headers,
                json={"plain_text": descricao},
                timeout=20,
            )
        except requests.RequestException as e:
            print(f"⚠️  Falha de rede ao enviar descrição: {e}")
            return novo_id

        if res_desc.status_code in (200, 201):
            print("   ✓ Descrição publicada com sucesso.")
        else:
            print(
                f"   ⚠️  POST /description falhou (HTTP {res_desc.status_code}): "
                f"{res_desc.text[:300]}"
            )

    return novo_id


# ─── DRY-RUN: IMPRESSÃO DO PAYLOAD ─────────────────────────────────────────
def imprimir_dry_run(payload: dict, descricao: str) -> None:
    """Imprime o payload e a descrição que SERIAM enviados."""
    print("\n" + "=" * 72)
    print("🟡 DRY-RUN — NADA FOI PUBLICADO")
    print("=" * 72)

    print("\n📤 PAYLOAD POST /items:")
    print("-" * 72)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print("-" * 72)

    print(f"\n📝 DESCRIÇÃO (POST /items/ID/description) — {len(descricao)} chars:")
    print("-" * 72)
    print(descricao[:3000])
    if len(descricao) > 3000:
        print(f"... (truncado, total {len(descricao)} chars)")
    print("-" * 72)

    print(
        "\n💡 Para publicar de verdade, rode novamente com --publish:\n"
        f"   python meli_clonador.py --mlb {payload.get('_mlb_original', 'MLB...')} --publish"
    )
    print("\n✅ Dry-run concluído.")


# ─── CLI ─────────────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Clona, otimiza e publica anúncios do Mercado Livre. "
            "Sem --publish, faz apenas DRY-RUN."
        )
    )
    p.add_argument(
        "--mlb", required=True,
        help="MLB do anúncio base (esqueleto para clonagem).",
    )
    p.add_argument(
        "--publish", action="store_true",
        help="Publica de verdade via POST /items (sem esta flag, faz DRY-RUN).",
    )
    return p.parse_args()


# ─── MAIN ────────────────────────────────────────────────────────────────────
def _run_com_token(args, tokens: dict, access_token: str) -> None:
    """Executa o fluxo principal. Separado do main para facilitar retry."""
    mlb = validar_mlb((args.mlb or "").strip().upper())

    # Fase 1: Extração
    base = extrair_anuncio_base(mlb, access_token)

    # Fase 2: Espionagem
    intel = espionar_concorrentes(base["title"], access_token)

    # Fase 3: Cérebro Gemini
    otimizacao = gerar_otimizacao_gemini(base, intel)

    # Fase 4: Montagem
    payload = montar_payload_post(base, otimizacao)
    descricao = (otimizacao.get("nova_descricao") or "").strip()

    # Fase 5: Publicação ou DRY-RUN
    if args.publish:
        # Guarda o MLB original para referência
        novo_id = publicar_anuncio(payload, descricao, access_token)
        if novo_id:
            print(f"\n🎉 Clone publicado: {mlb} → {novo_id}")
        else:
            print("\n❌ Publicação falhou. Revise o payload acima e tente novamente.")
            sys.exit(1)
    else:
        payload["_mlb_original"] = mlb  # ref para a dica de --publish
        imprimir_dry_run(payload, descricao)


if __name__ == "__main__":
    args = parse_args()

    tokens = load_tokens()
    access_token = tokens.get("access_token")
    if not access_token:
        print("❌ Erro: chave 'access_token' ausente em meli_tokens.json.")
        sys.exit(1)

    try:
        _run_com_token(args, tokens, access_token)
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
            _run_com_token(args, tokens, access_token)
        except (RuntimeError, TokenExpiredError) as e:
            print(f"❌ {e}")
            sys.exit(1)
    except RuntimeError as e:
        print(f"❌ {e}")
        sys.exit(1)
