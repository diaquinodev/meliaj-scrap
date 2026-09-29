from unittest.mock import Mock
import pytest
import requests

from app.scraping import ScrapeError, limpar_vendas, parse_listings, safe_url, scrape_ml_advanced


def card(item="1", price="1.299", cents="90"):
    return f"""
    <li class="ui-search-layout__item">
      <a class="poly-component__title" href="https://example.com/{item}#tracking">Produto {item}</a>
      <s class="andes-money-amount"><span class="andes-money-amount__fraction">2.000</span></s>
      <div class="poly-price__current"><span class="andes-money-amount">
        <span class="andes-money-amount__fraction">{price}</span>
        <span class="andes-money-amount__cents">{cents}</span>
      </span></div>
    </li>"""


def test_current_price_cents_missing_image_and_phrases():
    row = parse_listings(card())[0]
    assert row["preco"] == 1299.90
    assert row["imagem"] == ""
    assert row["nota"] == "N/A"
    assert row["vendas"] == "Não informado"
    assert row["link"] == "https://example.com/1"


def test_rating_and_sales_are_not_positional():
    html = card().replace("</li>", '<span class="poly-phrase-label">+1,5 mil vendidos</span><span class="poly-phrase-label">3.9</span></li>')
    row = parse_listings(html)[0]
    assert row["nota"] == "3.9"
    assert limpar_vendas(row["vendas"]) == 1500


@pytest.mark.parametrize("text,expected", [("+1.000 vendidos", 1000), ("+1,5 mil vendidos", 1500), ("2 milhões vendidos", 2000000), (None, 0), ("Não informado", 0)])
def test_sales(text, expected):
    assert limpar_vendas(text) == expected


@pytest.mark.parametrize("url", ["javascript:alert(1)", "data:text/html,a", "//example.com", "https://[invalid"])
def test_rejects_unsafe_links(url):
    assert safe_url(url) == ""


def test_limit_and_deduplication():
    session = Mock()
    session.get.return_value.text = card() + card() + card("2") + card("3")
    rows = scrape_ml_advanced("body feminino", 2, session=session, sleep=Mock())
    assert len(rows) == 2
    assert session.get.call_count == 1
    assert session.get.call_args.kwargs["timeout"] == (5, 20)
    session.close.assert_not_called()


def test_pagination_and_repeated_page_stop():
    session, sleep = Mock(), Mock()
    session.get.return_value.text = card()
    rows = scrape_ml_advanced("body", 5, session=session, sleep=sleep)
    assert len(rows) == 1
    assert session.get.call_count == 2
    sleep.assert_called_once_with(1)


def test_http_failure_is_not_silently_swallowed():
    session = Mock()
    session.get.return_value.raise_for_status.side_effect = requests.HTTPError("403")
    with pytest.raises(ScrapeError):
        scrape_ml_advanced("body", session=session)
    assert session.get.call_count == 1


def test_empty_or_changed_html_has_explicit_error():
    session = Mock()
    session.get.return_value.text = "<html>blocked</html>"
    with pytest.raises(ScrapeError):
        scrape_ml_advanced("body", session=session)


@pytest.mark.parametrize("query,limit", [("", 1), ("body", 0), ("body", 501), ("body", True)])
def test_input_validation(query, limit):
    with pytest.raises(ValueError):
        scrape_ml_advanced(query, limit)
