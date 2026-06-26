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
import os
from typing import Any, Optional

from fastapi import FastAPI
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel, Field

from src.agent.graph import build_graph
from src.identity.login_extractor import extrair_login


def _setup_logging() -> None:
    """Configura o logging-raiz para o cérebro.

    Sob uvicorn, sem isto os loggers de `src.*` (guardrails, tools, nós) ficam
    em WARNING e seus `logger.info(...)` somem. Nível controlado por `LOG_LEVEL`
    (DEBUG/INFO/WARNING/ERROR; default INFO). Use `LOG_LEVEL=DEBUG` para ver a
    query do RAG, os tool_calls do agente e o uso de tokens.
    """
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        force=True,
    )
    # Garante o nível mesmo que uvicorn reconfigure só os loggers dele.
    logging.getLogger("src").setLevel(level)


_setup_logging()

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


class ExtractLoginRequest(BaseModel):
    mensagem: str


class ExtractLoginResponse(BaseModel):
    login: Optional[str] = None


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
    login = (req.identidade or {}).get("login") if req.identidade else None
    logger.info(
        "chat_request conversation_id=%s canal=%s telefone=%s login=%s identificado=%s mensagem=%r",
        req.conversation_id,
        req.canal,
        req.telefone,
        login,
        bool(req.identidade and req.identidade.get("encontrado")),
        req.mensagem,
    )

    config = {"configurable": {"thread_id": req.conversation_id}}
    inputs: dict[str, Any] = {
        "identidade": req.identidade,
        "messages": [HumanMessage(content=req.mensagem)],
    }
    if req.telefone:
        inputs["telefone"] = req.telefone

    valores = await graph.ainvoke(inputs, config=config)
    resposta = ChatResponse(
        reply=_extrair_reply(valores),
        fontes=list(valores.get("fontes_usadas") or []),
    )
    logger.info(
        "chat_response conversation_id=%s len_reply=%d fontes=%s",
        req.conversation_id,
        len(resposta.reply),
        resposta.fontes,
    )
    logger.debug(
        "chat_response_full conversation_id=%s reply=%r",
        req.conversation_id,
        resposta.reply,
    )
    return resposta


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


@app.post("/extract-login", response_model=ExtractLoginResponse)
async def extract_login(req: ExtractLoginRequest) -> ExtractLoginResponse:
    """Extrai o login embutido numa frase (fallback do gate Go).

    O valor é só um candidato — quem autoriza é o gate (Mongo + confirmação).
    """
    logger.info("extract_login_request mensagem=%r", req.mensagem)
    resultado = extrair_login(req.mensagem)
    logger.info("extract_login_response login=%r", resultado.get("login"))
    return ExtractLoginResponse(login=resultado.get("login"))
