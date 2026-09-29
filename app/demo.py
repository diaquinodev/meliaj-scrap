"""Dados sintéticos, sem imagens remotas ou consulta ao marketplace."""


def demo_listings():
    return [
        {"titulo": name, "preco": price, "vendas": sales, "nota": rating,
         "desconto": discount, "imagem": "", "link": ""}
        for name, price, sales, rating, discount in [
            ("Body feminino liso — exemplo A", 39.90, "+100 vendidos", "4.8", "10%"),
            ("Body manga longa — exemplo B", 54.99, "+1,5 mil vendidos", "4.6", "0%"),
            ("Kit 3 bodies — exemplo C", 99.50, "+50 vendidos", "4.9", "15%"),
            ("Body sem avaliação — exemplo D", 29.90, "Não informado", "N/A", "0%"),
            ("Body gola alta — exemplo E", 64.70, "+500 vendidos", "4.7", "5%"),
        ]
    ]
