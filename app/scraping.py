"""Coleta limitada e parser testável sem chamadas externas."""

import re
import time
from urllib.parse import quote, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup


class ScrapeError(RuntimeError):
    """Falha explícita da coleta, inclusive quando resultados seriam parciais."""


def limpar_vendas(value):
    """Interpreta contagens públicas aproximadas, como '+1,5 mil vendidos'."""
    text = str(value).lower().strip()
    match = re.search(r"(\d[\d.,]*)\s*(milhões|milhão|mil)?", text)
    if not match:
        return 0
    number, suffix = match.groups()
    if suffix:
        number = number.replace(".", "").replace(",", ".")
        multiplier = 1000 if suffix == "mil" else 1000000
    else:
        number = number.replace(".", "").replace(",", "")
        multiplier = 1
    try:
        return int(float(number) * multiplier)
    except ValueError:
        return 0


def safe_url(value):
    value = str(value or "").strip()
    try:
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            return ""
        return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))
    except ValueError:
        return ""


def parse_listings(html):
    """Aceita cards incompletos e prefere o preço atual ao preço riscado."""
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("li.ui-search-layout__item")
    if not cards:
        cards = soup.select(".poly-card") or soup.select(".ui-search-result__wrapper")
    rows = []
    for card in cards:
        title = card.select_one(".poly-component__title, .ui-search-item__title")
        money = card.select_one(".poly-price__current .andes-money-amount, .ui-search-price__second-line .andes-money-amount")
        if money is None:
            money = next((node for node in card.select(".andes-money-amount")
                          if node.name not in {"s", "del"} and node.find_parent(["s", "del"]) is None
                          and "andes-money-amount--previous" not in node.get("class", [])), None)
        if title is None or money is None:
            continue
        fraction = money.select_one(".andes-money-amount__fraction")
        cents = money.select_one(".andes-money-amount__cents")
        if fraction is None:
            continue
        try:
            integer = re.sub(r"[.\s]", "", fraction.get_text(strip=True))
            decimal = cents.get_text(strip=True) if cents else "00"
            if not integer.isdigit() or not re.fullmatch(r"\d{1,2}", decimal):
                continue
            price = float(f"{integer}.{decimal.zfill(2)}")
            if price <= 0:
                continue
        except ValueError:
            continue
        anchor = title if title.name == "a" else card.select_one("a[href]")
        link = safe_url(anchor.get("href")) if anchor else ""
        image = card.select_one("img")
        discount = card.select_one(".poly-price__disc_label, .ui-search-price__discount")
        rating = card.select_one(".poly-reviews__rating, .ui-search-reviews__rating-number")
        phrases = [node.get_text(" ", strip=True) for node in card.select(".poly-phrase-label")]
        sales = next((text for text in phrases if "vendid" in text.lower()), "Não informado")
        rating_text = rating.get_text(strip=True) if rating else next(
            (text for text in phrases if re.fullmatch(r"[0-5][.,]\d", text)), "N/A")
        rows.append({
            "titulo": title.get_text(" ", strip=True), "preco": price,
            "imagem": safe_url(image.get("data-src") or image.get("src")) if image else "",
            "desconto": discount.get_text(strip=True) if discount else "0%",
            "nota": rating_text, "vendas": sales, "link": link,
        })
    return rows


def scrape_ml_advanced(query, limit=500, *, session=None, progress=None, sleep=time.sleep):
    """Até 10 páginas, sem retry de bloqueios, com timeout e pausa entre páginas.

    Uma falha interrompe a operação: não apresenta coleta parcial como completa.
    session/sleep injetáveis permitem testes determinísticos e sem rede.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("Informe um termo de busca.")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
        raise ValueError("Limite deve ser um inteiro entre 1 e 500.")
    owned = session is None
    client = session if session is not None else requests.Session()
    base = "https://lista.mercadolivre.com.br/" + quote("-".join(query.split()), safe="-")
    rows, seen = [], set()
    try:
        for page in range(10):
            if page:
                sleep(1)
            url = base if page == 0 else f"{base}_Desde_{1 + page * 50}"
            try:
                response = client.get(url, timeout=(5, 20), headers={"User-Agent": "VitrineOps/1.0"})
                response.raise_for_status()
            except requests.RequestException as exc:
                raise ScrapeError(f"Coleta interrompida na página {page + 1}. Verifique conexão ou restrições de acesso.") from exc
            parsed = parse_listings(response.text)
            if not parsed:
                raise ScrapeError(f"Página {page + 1} sem anúncios reconhecidos: busca vazia, bloqueio ou alteração do HTML.")
            added = 0
            for row in parsed:
                key = row["link"] or (row["titulo"], row["preco"])
                if key in seen:
                    continue
                seen.add(key)
                rows.append(row)
                added += 1
                if len(rows) >= limit:
                    break
            if progress:
                progress(min(len(rows) / limit, 1.0))
            if len(rows) >= limit or not added:
                break
    finally:
        if owned:
            client.close()
    return rows
