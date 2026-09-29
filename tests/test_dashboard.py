from pathlib import Path
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

from app.radar_app import convert_df_to_csv
from app.scraping import ScrapeError


def test_csv_neutralizes_formula_strings():
    data = pd.DataFrame({"titulo": ["=HYPERLINK(x)", "  @SUM(1)", "Normal"], "preco": [1.2, 2.3, 3.4]})
    text = convert_df_to_csv(data).decode("utf-8-sig")
    assert "'=HYPERLINK(x)" in text
    assert "'  @SUM(1)" in text
    assert "1.2" in text


def app():
    return AppTest.from_file(str(Path(__file__).parents[1] / "app" / "radar_app.py"), default_timeout=15)


def test_dashboard_demo_and_price_update():
    at = app().run()
    assert not at.exception
    at.button[0].click().run()
    assert not at.exception
    assert len(at.dataframe[0].value) == 5
    at.sidebar.number_input[0].set_value(10.0).run()
    assert not at.exception
    assert at.metric[0].value == "R$ 17.50"


def test_dashboard_handles_collection_failure():
    at = app().run()
    with patch("app.scraping.scrape_ml_advanced", side_effect=ScrapeError("Busca indisponível")):
        at.button[1].click().run()
    assert not at.exception
    assert at.error[0].value == "Busca indisponível"
