"""Modelo simplificado: retorno sobre custo, não margem sobre receita."""

from decimal import Decimal, InvalidOperation


def _number(value, name):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{name} deve ser um número finito.") from None
    if not result.is_finite():
        raise ValueError(f"{name} deve ser um número finito.")
    return result


def get_factory_bi(custo, gordura, margem_alvo, taxa_mkp=0.20, taxa_fixa=4.0):
    """Preserva o contrato original; margem_alvo é retorno percentual sobre custo.

    Taxas são hipóteses configuráveis, não uma tabela oficial do marketplace.
    Uma taxa fixa por venda/kit. Frete e impostos não estão incluídos.
    Mantém precisão decimal no cálculo e converte somente na saída para a UI.
    """
    custo, gordura, retorno, taxa, fixa = [
        _number(value, name) for value, name in (
            (custo, "Custo"), (gordura, "Desconto"),
            (margem_alvo, "Retorno"), (taxa_mkp, "Taxa percentual"),
            (taxa_fixa, "Taxa fixa"),
        )
    ]
    if custo <= 0 or fixa < 0 or retorno < 0:
        raise ValueError("Custo deve ser positivo; taxa fixa e retorno não negativos.")
    if not 0 <= taxa < 1 or not 0 <= gordura < 100:
        raise ValueError("Taxa deve estar em [0, 1) e desconto em [0, 100).")
    liquido = 1 - taxa
    promo = 1 - gordura / 100
    minimo = (custo + fixa) / liquido
    alvo = (custo * (1 + retorno / 100) + fixa) / liquido
    vitrine = alvo / promo
    kit = (custo * 3 * (1 + retorno / 100) + fixa) / liquido
    return {key: float(value) for key, value in {
        "minimo": minimo, "venda_alvo": alvo, "vitrine": vitrine,
        "max_desconto": (1 - minimo / vitrine) * 100,
        "lucro": alvo * liquido - custo - fixa,
        "kit3_vitrine": kit / promo,
        "kit3_lucro": kit * liquido - custo * 3 - fixa,
    }.items()}
