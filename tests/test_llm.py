"""Testes da fábrica de LLM/embeddings (Épico 5).

`ChatOpenAI` aceita ser instanciado sem fazer chamadas de rede, então os
testes inspecionam diretamente os atributos do cliente. `HuggingFaceEmbeddings`
faz download do modelo na inicialização — por isso `get_embeddings` é
testado via monkeypatch (a real instanciação acontece em `test_rag` com
um fake).
"""

from __future__ import annotations

import pytest
from langchain_openai import ChatOpenAI

from src.agent import llm as llm_factory
from src.config import get_settings


@pytest.fixture(autouse=True)
def _reset_factory_caches():
    llm_factory.get_llm.cache_clear()
    llm_factory.get_classifier_llm.cache_clear()
    llm_factory.get_embeddings.cache_clear()
    yield
    llm_factory.get_llm.cache_clear()
    llm_factory.get_classifier_llm.cache_clear()
    llm_factory.get_embeddings.cache_clear()


# ---------------------------------------------------------------------------
# get_llm
# ---------------------------------------------------------------------------


def test_get_llm_retorna_chatopenai():
    client = llm_factory.get_llm()
    assert isinstance(client, ChatOpenAI)


def test_get_llm_aponta_para_openrouter():
    client = llm_factory.get_llm()
    settings = get_settings()
    # langchain_openai expõe a base_url como `openai_api_base`.
    assert client.openai_api_base == settings.openrouter_base_url
    assert "openrouter.ai" in client.openai_api_base


def test_get_llm_usa_model_e_temperature_do_settings():
    client = llm_factory.get_llm()
    settings = get_settings()
    assert client.model_name == settings.openrouter_model
    assert client.temperature == settings.llm_temperature


def test_get_llm_injeta_headers_de_boa_cidadania_openrouter():
    client = llm_factory.get_llm()
    settings = get_settings()
    headers = client.default_headers or {}
    assert headers.get("HTTP-Referer") == settings.app_referer
    assert headers.get("X-Title") == settings.app_title


def test_get_llm_e_cacheado_por_processo():
    a = llm_factory.get_llm()
    b = llm_factory.get_llm()
    assert a is b


# ---------------------------------------------------------------------------
# get_classifier_llm
# ---------------------------------------------------------------------------


def test_get_classifier_llm_usa_modelo_classifier_e_temp_zero():
    client = llm_factory.get_classifier_llm()
    settings = get_settings()
    assert isinstance(client, ChatOpenAI)
    assert client.model_name == settings.openrouter_classifier_model
    # Classificação tem que ser determinística.
    assert client.temperature == 0.0


def test_classifier_e_principal_sao_clientes_distintos():
    principal = llm_factory.get_llm()
    classifier = llm_factory.get_classifier_llm()
    assert principal is not classifier


def test_classifier_tambem_aponta_para_openrouter_com_headers():
    client = llm_factory.get_classifier_llm()
    settings = get_settings()
    assert client.openai_api_base == settings.openrouter_base_url
    headers = client.default_headers or {}
    assert headers.get("HTTP-Referer") == settings.app_referer
    assert headers.get("X-Title") == settings.app_title


# ---------------------------------------------------------------------------
# get_embeddings — sem baixar modelo de verdade
# ---------------------------------------------------------------------------


def test_get_embeddings_constroi_huggingface_com_settings(monkeypatch):
    """Captura os kwargs passados para `HuggingFaceEmbeddings` sem baixar nada."""
    capturado: dict = {}

    class FakeHFEmbeddings:
        def __init__(self, **kwargs):
            capturado.update(kwargs)

    import src.agent.llm as llm_mod

    # Precisamos interceptar o import tardio dentro de get_embeddings.
    import langchain_huggingface

    monkeypatch.setattr(
        langchain_huggingface, "HuggingFaceEmbeddings", FakeHFEmbeddings
    )

    out = llm_mod.get_embeddings()
    assert isinstance(out, FakeHFEmbeddings)

    settings = get_settings()
    assert capturado["model_name"] == settings.embeddings_model
    assert capturado["model_kwargs"] == {"device": "cpu"}
    assert capturado["encode_kwargs"] == {"normalize_embeddings": True}


def test_retriever_reexporta_get_embeddings_do_llm_factory():
    """Garante o caminho de compatibilidade `from src.rag.retriever import get_embeddings`."""
    from src.rag.retriever import get_embeddings as embeddings_via_retriever

    assert embeddings_via_retriever is llm_factory.get_embeddings