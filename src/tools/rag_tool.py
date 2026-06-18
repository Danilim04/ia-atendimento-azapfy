"""Tool LangChain para consultar a base de conhecimento interna (RAG)."""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from src.config import get_settings
from src.rag.retriever import get_retriever


@tool
def consultar_base_conhecimento(pergunta: str) -> dict[str, Any]:
    """Consulta a base de conhecimento técnico interna da Azapfy (PDF indexado).

    Use SEMPRE esta tool ANTES de tentar `buscar_na_web_azapfy` — é a fonte
    de verdade primária para dúvidas operacionais e técnicas sobre os
    produtos Azapfy. Retorna trechos relevantes do PDF de conhecimento,
    cada um com a página de origem para que a resposta possa citar a fonte.

    Se o resultado vier vazio (`encontrado=False`) ou claramente irrelevante
    para a pergunta, aí sim recorra à busca na web como fallback.

    Args:
        pergunta: Pergunta do usuário em linguagem natural (em português).

    Returns:
        Dicionário com:
          - encontrado (bool): True se houve ao menos um chunk retornado.
          - total (int): número de chunks devolvidos.
          - chunks (list[dict]): cada item tem
              - texto (str): trecho do PDF.
              - pagina (int | None): página humana (1-indexada) do PDF.
              - source (str): nome do arquivo PDF de origem.
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
        page = d.metadata.get("page")
        chunks.append(
            {
                "texto": d.page_content,
                "pagina": (page + 1) if isinstance(page, int) else None,
                "source": d.metadata.get("source", "desconhecido"),
            }
        )

    return {
        "encontrado": len(chunks) > 0,
        "total": len(chunks),
        "chunks": chunks,
    }
