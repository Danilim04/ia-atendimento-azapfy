"""Tool LangChain para consultar a base de conhecimento interna (RAG)."""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from src.config import get_settings
from src.rag.retriever import get_retriever


@tool
def consultar_base_conhecimento(pergunta: str) -> dict[str, Any]:
    """Consulta a base de conhecimento técnico interna da Azapfy (docs indexadas).

    Fonte de verdade primária para dúvidas técnicas/operacionais sobre os
    produtos Azapfy (plataforma Web, app do motorista, módulos, mercado) — use
    ANTES de `buscar_na_web_azapfy`. Faça apenas UMA consulta por turno; se vier
    vazia (`encontrado=False`) ou irrelevante, recorra à web como fallback.

    Args:
        pergunta: Pergunta do usuário em linguagem natural (em português).

    Returns:
        dict: encontrado (bool), total (int), chunks (list com texto, secao,
        source) para citar a fonte.
    """
    pergunta = (pergunta or "").strip()
    if not pergunta:
        return {
            "encontrado": False,
            "total": 0,
            "chunks": [],
            "erro": "pergunta vazia",
        }

    settings = get_settings()
    try:
        retriever = get_retriever(k=settings.rag_top_k)
        docs = retriever.invoke(pergunta)
    except Exception as exc:  # noqa: BLE001 — devolvemos a falha pro agente decidir
        return {
            "encontrado": False,
            "total": 0,
            "chunks": [],
            "erro": f"falha no retriever: {exc}",
        }

    chunks = []
    for d in docs:
        chunks.append(
            {
                "texto": d.page_content,
                "secao": d.metadata.get("secao") or None,
                "source": d.metadata.get("source", "desconhecido"),
            }
        )

    return {
        "encontrado": len(chunks) > 0,
        "total": len(chunks),
        "chunks": chunks,
    }
