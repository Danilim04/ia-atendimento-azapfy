"""Servidor HTTP do cérebro (Contrato A) — integração Chatwoot via backend Go.

O backend Go (transporte Chatwoot + gate de identidade) chama `POST /chat`
**somente quando o usuário já está identificado**, enviando a mensagem e o
perfil mínimo (`identidade`) resolvido. Este serviço roda o grafo LangGraph
(Épico 7), isolando conversas por `conversation_id` (= `thread_id` do
`MemorySaver`), e devolve a resposta + ações opcionais para o Chatwoot.

Rodar:
    uvicorn server:app --host 0.0.0.0 --port 8001

Contrato A — request:
    {"conversation_id": "...", "canal": "whatsapp", "mensagem": "...",
     "identidade": {...}, "telefone": "...", "session_token": "..."}
Contrato A — resposta:
    {"reply": "...", "acoes": [], "fontes": [...]}

Obs.: `session_token` é aceito e ignorado nesta fase. Ele só passa a importar
no plano deferido (tools MCP), onde o Python o repassa ao Go para escopar as
consultas de dados ao usuário autorizado.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import FastAPI
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel, Field

from src.agent.graph import build_graph


logger = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    conversation_id: str
    mensagem: str
    canal: str = "whatsapp"
    identidade: Optional[dict[str, Any]] = None
    telefone: Optional[str] = None
    session_token: Optional[str] = None


class ChatResponse(BaseModel):
    reply: str
    acoes: list[dict[str, Any]] = Field(default_factory=list)
    fontes: list[str] = Field(default_factory=list)


def _extrair_reply(valores: dict) -> str:
    """Último texto do agente. Tolera `content` str ou lista de blocos (Anthropic)."""
    for m in reversed(valores.get("messages") or []):
        if isinstance(m, AIMessage):
            conteudo = m.content
            if isinstance(conteudo, str):
                return conteudo
            if isinstance(conteudo, list):
                return "".join(
                    b.get("text", "") for b in conteudo if isinstance(b, dict)
                )
    return ""


async def processar_chat(graph: Any, req: ChatRequest) -> ChatResponse:
    """Roda o grafo para uma mensagem do Contrato A e devolve a resposta.

    Função pura (recebe o grafo por injeção) — testável sem servidor/rede.
    A `identidade` entra no estado e é injetada no system prompt como DADO
    (ver `nodes._build_system_message`).
    """
    config = {"configurable": {"thread_id": req.conversation_id}}
    inputs: dict[str, Any] = {
        "identidade": req.identidade,
        "messages": [HumanMessage(content=req.mensagem)],
    }
    if req.telefone:
        inputs["telefone"] = req.telefone

    valores = await graph.ainvoke(inputs, config=config)
    return ChatResponse(
        reply=_extrair_reply(valores),
        fontes=list(valores.get("fontes_usadas") or []),
    )


# ---------------------------------------------------------------------------
# App FastAPI — grafo compilado uma vez por processo (isolamento por thread_id).
# ---------------------------------------------------------------------------

_GRAPH: Any = None


def _get_graph():
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    return _GRAPH


app = FastAPI(title="Azapfy Suporte IA — cérebro")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    return await processar_chat(_get_graph(), req)
