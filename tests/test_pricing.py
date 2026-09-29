import math
import pytest
from app.pricing import get_factory_bi


def test_price_covers_cost_fees_and_target_return():
    result = get_factory_bi(8, 40, 30)
    assert result["minimo"] == pytest.approx(15)
    assert result["venda_alvo"] == pytest.approx(18)
    assert result["vitrine"] == pytest.approx(30)
    assert result["lucro"] == pytest.approx(2.4)
    assert result["kit3_lucro"] == pytest.approx(7.2)
    assert result["vitrine"] * (1 - result["max_desconto"] / 100) == pytest.approx(result["minimo"])


@pytest.mark.parametrize("args", [
    (0, 20, 30), (-1, 20, 30), (8, 100, 30), (8, -1, 30),
    (8, 20, -30), (8, 20, 30, 1), (8, 20, 30, -.1),
    (8, 20, 30, .2, -1), (math.nan, 20, 30), (8, math.inf, 30),
])
def test_rejects_invalid_inputs(args):
    with pytest.raises(ValueError):
        get_factory_bi(*args)
