"""Fábricas de LLM e embeddings (Épico 5).

Centraliza a criação dos clientes LLM apontando para o OpenRouter
(`https://openrouter.ai/api/v1`) via `ChatOpenAI`, e provê os embeddings
locais usados pelo RAG. Mantém os clientes cacheados para reuso entre
chamadas dentro do mesmo processo.

Headers de boa cidadania exigidos pelo OpenRouter (`HTTP-Referer` e
`X-Title`) são injetados automaticamente a partir das settings — eles
ajudam o OpenRouter a roteamento e ranking, e identificam o app na
dashboard.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING, Optional

from src.config import Settings, get_settings

if TYPE_CHECKING:
    from langchain_core.embeddings import Embeddings
    from langchain_core.language_models.chat_models import BaseChatModel


def _openrouter_headers(settings: Settings) -> dict[str, str]:
    return {
        "HTTP-Referer": settings.app_referer,
        "X-Title": settings.app_title,
    }


def _build_chat_openrouter(
    model: str,
    temperature: float,
    settings: Optional[Settings] = None,
) -> "BaseChatModel":
    from langchain_openai import ChatOpenAI

    settings = settings or get_settings()
    return ChatOpenAI(
        base_url=settings.openrouter_base_url,
        api_key=settings.openrouter_api_key,
        model=model,
        temperature=temperature,
        default_headers=_openrouter_headers(settings),
    )


@lru_cache(maxsize=1)
def get_llm() -> "BaseChatModel":
    """LLM principal do agente (suporta tool-calling)."""
    settings = get_settings()
    return _build_chat_openrouter(
        model=settings.openrouter_model,
        temperature=settings.llm_temperature,
        settings=settings,
    )


@lru_cache(maxsize=1)
def get_classifier_llm() -> "BaseChatModel":
    """LLM barato/rápido usado pelo classificador de segurança (Épico 6).

    Temperature fixa em 0.0 — classificação é determinística por design.
    """
    settings = get_settings()
    return _build_chat_openrouter(
        model=settings.openrouter_classifier_model,
        temperature=0.0,
        settings=settings,
    )


@lru_cache(maxsize=1)
def get_embeddings() -> "Embeddings":
    """Embeddings locais via `sentence-transformers` em CPU.

    Mantemos os embeddings locais (não-OpenRouter) para evitar custo por
    embedding em ingest/retrieval e para permitir rodar o POC offline.
    Se um dia migrarmos para embeddings remotos, este é o ponto de troca.
    """
    from langchain_huggingface import HuggingFaceEmbeddings

    settings = get_settings()
    return HuggingFaceEmbeddings(
        model_name=settings.embeddings_model,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )