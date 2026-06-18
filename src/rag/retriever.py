"""Wrapper para reabrir o ChromaDB persistido e expor um retriever pronto.

A fábrica de embeddings vive em `src.agent.llm` (Épico 5); este módulo
apenas re-exporta `get_embeddings` para manter o caminho histórico
(`from src.rag.retriever import get_embeddings`) funcionando.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Optional

from src.agent.llm import get_embeddings
from src.rag.ingest import COLLECTION_NAME

if TYPE_CHECKING:
    from langchain_chroma import Chroma
    from langchain_core.embeddings import Embeddings
    from langchain_core.vectorstores import VectorStoreRetriever


__all__ = ["get_embeddings", "get_vector_store", "get_retriever"]


def get_vector_store(
    persist_dir: Optional[Path] = None,
    embeddings: Optional["Embeddings"] = None,
) -> "Chroma":
    """Reabre o ChromaDB persistido (sem reingerir)."""
    from langchain_chroma import Chroma

    if persist_dir is None:
        from src.config import get_settings

        persist_dir = get_settings().chroma_persist_dir
    if embeddings is None:
        embeddings = get_embeddings()

    return Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=embeddings,
        persist_directory=str(Path(persist_dir)),
    )


def get_retriever(
    k: int = 4,
    persist_dir: Optional[Path] = None,
    embeddings: Optional["Embeddings"] = None,
) -> "VectorStoreRetriever":
    """Retorna um retriever top-k pronto para `.invoke(pergunta)`."""
    store = get_vector_store(persist_dir, embeddings)
    return store.as_retriever(search_kwargs={"k": k})
