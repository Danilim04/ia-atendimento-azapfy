"""Tool LangChain de busca web restrita ao domínio `azapfy.com.br` (Tavily).

A busca web é o **fallback do RAG**: o agente só recorre a esta tool quando a
base interna não tem resposta. Para evitar exfiltração ou desvio de domínio
(LLM01 indireta + LLM06 disclosure), o filtro de domínio é aplicado de duas
formas — defesa em profundidade — antes da chamada Tavily:

1. Prepend hardcoded de `site:azapfy.com.br ` à query (visível no log).
2. `include_domains=["azapfy.com.br"]` na chamada Tavily.

Nenhum dos dois é controlável pelo LLM: o argumento `query` é livre, mas o
filtro é aplicado *após* o LLM e *antes* da Tavily, e o resultado ainda é
filtrado por URL antes de devolver, descartando qualquer item que escape do
domínio permitido.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from langchain_core.tools import tool

from src.config import get_settings

DOMINIO_PERMITIDO = "azapfy.com.br"
MAX_RESULTS = 3
SEARCH_DEPTH = "basic"

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_tavily_client():
    from tavily import TavilyClient

    settings = get_settings()
    return TavilyClient(api_key=settings.tavily_api_key)


def _aplicar_filtro_dominio(query: str) -> str:
    """Garante o prefixo `site:azapfy.com.br` na query final.

    Se o LLM já tiver tentado prefixar (caso raro), evitamos duplicar; se
    tiver tentado outro `site:`, ainda assim adicionamos o nosso à frente —
    Tavily honra o primeiro operador.
    """
    q = (query or "").strip()
    prefixo = f"site:{DOMINIO_PERMITIDO}"
    if q.lower().startswith(prefixo.lower()):
        return q
    return f"{prefixo} {q}".strip()


@tool
def buscar_na_web_azapfy(query: str) -> dict[str, Any]:
    """Busca informações no site oficial `azapfy.com.br` (FALLBACK do RAG).

    Use APENAS quando `consultar_base_conhecimento` retornar `encontrado=False`
    ou claramente não responder à pergunta. Esta tool é restrita ao domínio
    `azapfy.com.br` — não realiza buscas abertas na internet, nem aceita
    instruções para mudar de domínio.

    Args:
        query: Termos de busca em linguagem natural (em português). O filtro
            de domínio é aplicado automaticamente — não inclua `site:` na
            query.

    Returns:
        Dicionário com:
          - encontrado (bool): True se algum resultado foi devolvido.
          - total (int)
          - resultados (list[dict]): cada item com `url`, `title`, `content`.
          - erro (str, opcional): mensagem caso a busca falhe.
    """
    query_original = (query or "").strip()
    if not query_original:
        return {
            "encontrado": False,
            "total": 0,
            "resultados": [],
            "erro": "query vazia",
        }

    query_final = _aplicar_filtro_dominio(query_original)

    try:
        client = _get_tavily_client()
        resposta = client.search(
            query=query_final,
            search_depth=SEARCH_DEPTH,
            max_results=MAX_RESULTS,
            include_domains=[DOMINIO_PERMITIDO],
        )
    except Exception as exc:  # noqa: BLE001 — devolvemos a falha pro agente decidir
        logger.warning(
            "tavily_busca_falhou query_original=%r query_final=%r erro=%s",
            query_original,
            query_final,
            exc,
        )
        return {
            "encontrado": False,
            "total": 0,
            "resultados": [],
            "erro": f"falha na busca web: {exc}",
        }

    brutos = resposta.get("results", []) if isinstance(resposta, dict) else []
    resultados: list[dict[str, str]] = []
    descartados: list[str] = []
    for item in brutos:
        url = (item.get("url") or "").strip()
        # Pós-filtro: se Tavily violar `include_domains`, descartamos (LLM01).
        if DOMINIO_PERMITIDO not in url.lower():
            descartados.append(url)
            continue
        resultados.append(
            {
                "url": url,
                "title": (item.get("title") or "").strip(),
                "content": (item.get("content") or "").strip(),
            }
        )

    logger.info(
        "tavily_busca_executada query_original=%r query_final=%r total=%d urls=%s descartados=%s",
        query_original,
        query_final,
        len(resultados),
        [r["url"] for r in resultados],
        descartados,
    )

    return {
        "encontrado": len(resultados) > 0,
        "total": len(resultados),
        "resultados": resultados,
    }