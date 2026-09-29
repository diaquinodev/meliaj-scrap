"""Testes do contrato Pydantic da IA (FichaTecnicaML), sem chamar a API do Gemini."""
import pytest
from pydantic import ValidationError

from agente_ficha_tecnica import FichaTecnicaML

CAMPOS = ["title", "description", "fabric", "model_field", "sleeve_type", "search_term"]

DADOS_VALIDOS = {
    "title": "Body Feminino Tule Estampa Onça",
    "description": "Frase de impacto.\n\n- Tecido: Tule",
    "fabric": "Tule",
    "model_field": "Body",
    "sleeve_type": "Manga longa",
    "search_term": "Body Feminino",
}


def test_schema_aceita_dados_completos():
    ficha = FichaTecnicaML(**DADOS_VALIDOS)
    assert ficha.model_dump() == DADOS_VALIDOS


def test_schema_tem_todos_os_campos_obrigatorios():
    schema = FichaTecnicaML.model_json_schema()
    assert sorted(schema["required"]) == sorted(CAMPOS)


@pytest.mark.parametrize("campo", CAMPOS)
def test_schema_rejeita_campo_ausente(campo):
    dados = {k: v for k, v in DADOS_VALIDOS.items() if k != campo}
    with pytest.raises(ValidationError):
        FichaTecnicaML(**dados)


def test_processar_fotos_locais_limita_a_10_e_filtra_extensoes(tmp_path):
    from agente_ficha_tecnica import processar_fotos_locais

    for i in range(12):
        (tmp_path / f"foto{i}.jpg").write_bytes(b"x")
    (tmp_path / "leia-me.txt").write_text("nao e foto")

    fotos = processar_fotos_locais(str(tmp_path))
    assert len(fotos) == 10
    assert all(f.endswith(".jpg") for f in fotos)


def test_processar_fotos_locais_pasta_vazia_retorna_none(tmp_path):
    from agente_ficha_tecnica import processar_fotos_locais

    assert processar_fotos_locais(str(tmp_path)) is None
