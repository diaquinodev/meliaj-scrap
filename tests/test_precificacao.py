"""Testes da lógica de precificação (get_factory_bi) e da limpeza de vendas."""
import pytest

from radar_app import get_factory_bi, limpar_vendas


def test_preco_minimo_cobre_custo_e_taxas():
    # (custo + taxa_fixa) / (1 - taxa_mkp) = (8 + 4) / 0.8
    calc = get_factory_bi(custo=8.0, gordura=40, margem_alvo=30)
    assert calc["minimo"] == pytest.approx(15.0)


def test_preco_venda_alvo_aplica_margem_sobre_o_custo():
    # ((8 * 1.30) + 4) / 0.8
    calc = get_factory_bi(custo=8.0, gordura=40, margem_alvo=30)
    assert calc["venda_alvo"] == pytest.approx(18.0)


def test_preco_vitrine_inclui_gordura_para_promocao():
    # venda_alvo / (1 - 0.40)
    calc = get_factory_bi(custo=8.0, gordura=40, margem_alvo=30)
    assert calc["vitrine"] == pytest.approx(30.0)


def test_max_desconto_leva_vitrine_ate_o_preco_minimo():
    calc = get_factory_bi(custo=8.0, gordura=40, margem_alvo=30)
    preco_com_desconto = calc["vitrine"] * (1 - calc["max_desconto"] / 100)
    assert preco_com_desconto == pytest.approx(calc["minimo"])


def test_lucro_real_e_a_margem_sobre_o_custo_depois_das_taxas():
    # o lucro real equivale a custo * margem_alvo
    calc = get_factory_bi(custo=8.0, gordura=40, margem_alvo=30)
    assert calc["lucro"] == pytest.approx(8.0 * 0.30)


def test_kit_3_pecas_usa_custo_triplicado():
    calc = get_factory_bi(custo=8.0, gordura=40, margem_alvo=30)
    # kit: ((24 * 1.30) + 4) / 0.8 = 44.0 -> vitrine = 44.0 / 0.6
    assert calc["kit3_vitrine"] == pytest.approx(44.0 / 0.6)
    # lucro do kit = custo do kit * margem_alvo
    assert calc["kit3_lucro"] == pytest.approx(24.0 * 0.30)


def test_taxas_customizadas_alteram_preco_minimo():
    calc = get_factory_bi(custo=10.0, gordura=0, margem_alvo=0, taxa_mkp=0.10, taxa_fixa=0.0)
    assert calc["minimo"] == pytest.approx(10.0 / 0.9)
    assert calc["max_desconto"] == pytest.approx(0.0)


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("+500 vendidos", 500),
        ("1.200 vendidos", 1200),
        ("0", 0),
        ("sem vendas", 0),
        ("", 0),
        (None, 0),
    ],
)
def test_limpar_vendas(texto, esperado):
    assert limpar_vendas(texto) == esperado
