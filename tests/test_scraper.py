"""Testa o parser do scraper (scrape_ml_advanced) com HTML simulado, sem acesso à rede."""
import radar_app


class _RespostaFalsa:
    def __init__(self, texto):
        self.text = texto


class _BarraFalsa:
    def progress(self, *_args, **_kwargs):
        pass

    def empty(self):
        pass


HTML_UMA_PAGINA = """
<ol>
  <li class="ui-search-layout__item">
    <a class="poly-component__title" href="https://produto.mercadolivre.com.br/MLB-1#pos=1">Body Feminino Tule</a>
    <img class="poly-component__picture" src="https://http2.mlstatic.com/foto-I.webp">
    <span class="andes-money-amount__fraction">1.299</span>
    <span class="poly-price__disc_label">10% OFF</span>
    <span class="poly-phrase-label">4.8</span>
    <span class="poly-phrase-label">+500 vendidos</span>
  </li>
  <li class="ui-search-layout__item">
    <a class="poly-component__title" href="https://produto.mercadolivre.com.br/MLB-2">Item sem preço</a>
  </li>
</ol>
"""


def _simular(monkeypatch, paginas):
    """Devolve `paginas` em sequência; depois disso, uma página sem resultados."""
    chamadas = []

    def get_falso(url, **_kwargs):
        chamadas.append(url)
        idx = len(chamadas) - 1
        return _RespostaFalsa(paginas[idx] if idx < len(paginas) else "<html></html>")

    monkeypatch.setattr(radar_app.requests, "get", get_falso)
    monkeypatch.setattr(radar_app.st, "progress", lambda *_a, **_k: _BarraFalsa())
    return chamadas


def test_extrai_campos_do_card_e_ignora_item_sem_preco(monkeypatch):
    _simular(monkeypatch, [HTML_UMA_PAGINA])
    resultados = radar_app.scrape_ml_advanced("body feminino")

    assert len(resultados) == 1
    item = resultados[0]
    assert item["titulo"] == "Body Feminino Tule"
    assert item["preco"] == 1299.0
    assert item["desconto"] == "10% OFF"
    assert item["nota"] == "4.8"
    assert item["vendas"] == "+500 vendidos"
    assert item["link"] == "https://produto.mercadolivre.com.br/MLB-1"  # sem o #fragmento
    assert item["imagem"].endswith("-W.webp")  # troca -I.webp por -W.webp


def test_para_de_paginar_quando_nao_ha_cards(monkeypatch):
    chamadas = _simular(monkeypatch, [HTML_UMA_PAGINA])
    radar_app.scrape_ml_advanced("body feminino")

    # 1ª página com resultados; a 2ª vem vazia e interrompe a varredura
    assert len(chamadas) == 2
    assert chamadas[0] == "https://lista.mercadolivre.com.br/body-feminino"
    assert chamadas[1] == "https://lista.mercadolivre.com.br/body-feminino_Desde_51"
