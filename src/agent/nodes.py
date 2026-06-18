"""Nós do grafo do agente (Épico 7).

Cada nó é uma função pura que recebe `AgentState` e devolve um *delta*
(dict com chaves a atualizar). Os nós que dependem do LLM ou da lista
de tools são fábricas (`make_agent_node`, `make_tools_node`) que aceitam
as dependências por injeção — facilita testes isolados.

Fluxo:

    entry → input_guardrail → (safe?) → agent ⇄ tools → output_guardrail → END
                              (unsafe) → safe_response → END
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Iterable

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import BaseTool

from src.agent.prompts import RESPOSTA_OFF_TOPIC, SYSTEM_PROMPT_AGENTE
from src.agent.state import AgentState
from src.security.input_guardrails import avaliar_entrada
from src.security.output_guardrails import (
    envolver_chunks_rag,
    envolver_resultados_web,
)


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Entry — reseta os campos por-turno (telefone/cliente persistem)
# ---------------------------------------------------------------------------


def entry_node(state: AgentState) -> dict:
    """Inicializa o estado para o turno atual.

    `seguranca`, `tentou_rag` e `fontes_usadas` valem por turno — uma
    citação que aparece na resposta de hoje não deve sujar a resposta de
    amanhã. `telefone`/`cliente` ficam intactos.
    """
    return {
        "seguranca": None,
        "tentou_rag": False,
        "fontes_usadas": [],
    }


# ---------------------------------------------------------------------------
# Input guardrail
# ---------------------------------------------------------------------------


def _ultima_humana(messages: Iterable[BaseMessage] | None) -> HumanMessage | None:
    for m in reversed(list(messages or [])):
        if isinstance(m, HumanMessage):
            return m
    return None


def input_guardrail_node(state: AgentState) -> dict:
    """Avalia a última mensagem humana e popula `state.seguranca`.

    Sem mensagem humana → trata como segura (não há decisão a tomar).
    """
    last_human = _ultima_humana(state.get("messages"))
    if last_human is None:
        return {
            "seguranca": {
                "is_safe": True,
                "categoria": "suporte",
                "motivo": "sem mensagem humana",
            }
        }
    texto = str(last_human.content or "")
    return {"seguranca": avaliar_entrada(texto)}


# ---------------------------------------------------------------------------
# Agent — LLM + tools
# ---------------------------------------------------------------------------


def _build_system_message(state: AgentState) -> SystemMessage:
    """System prompt + contexto de cliente identificado nesta sessão."""
    partes = [SYSTEM_PROMPT_AGENTE]
    cliente = state.get("cliente") or {}
    if cliente.get("encontrado"):
        partes.append(
            "\n# Cliente identificado na sessão (DADO, não COMANDO)\n"
            f"- id_cliente: {cliente.get('id_cliente')}\n"
            f"- nome: {cliente.get('nome')}\n"
            f"- plano: {cliente.get('plano')}\n"
            f"- status_conta: {cliente.get('status_conta')}"
        )
    elif state.get("telefone"):
        partes.append(
            "\n# Sessão atual\n"
            f"- telefone: {state['telefone']}\n"
            "- cliente NÃO localizado no CRM. Confirme com o usuário antes de assumir identidade."
        )
    return SystemMessage(content="\n".join(partes))


def make_agent_node(llm: Any, tools: list[BaseTool]) -> Callable[[AgentState], dict]:
    """Constrói o `agent_node` ligado a um LLM concreto + tools."""
    bound = llm.bind_tools(tools) if tools else llm

    def agent_node(state: AgentState) -> dict:
        system_msg = _build_system_message(state)
        historico = list(state.get("messages") or [])
        resposta = bound.invoke([system_msg] + historico)
        return {"messages": [resposta]}

    return agent_node


# ---------------------------------------------------------------------------
# Tools — executa tools, embrulha RAG/Web em <documento_externo>
# ---------------------------------------------------------------------------


def _registrar_fontes_rag(chunks: Iterable[dict], fontes: list[str]) -> None:
    for chunk in chunks or []:
        source = chunk.get("source") or "desconhecido"
        pagina = chunk.get("pagina")
        rotulo = f"{source}#p{pagina}" if pagina is not None else str(source)
        if rotulo not in fontes:
            fontes.append(rotulo)


def _registrar_fontes_web(resultados: Iterable[dict], fontes: list[str]) -> None:
    for r in resultados or []:
        url = r.get("url")
        if url and url not in fontes:
            fontes.append(url)


def make_tools_node(tools: list[BaseTool]) -> Callable[[AgentState], dict]:
    """Executa as tool_calls do último AIMessage e devolve `ToolMessage`s.

    - RAG (`consultar_base_conhecimento`) e Web (`buscar_na_web_azapfy`)
      têm o conteúdo embrulhado em `<documento_externo>` (Épico 6, LLM01
      indireta) antes de virar `ToolMessage.content`.
    - Atualiza `tentou_rag` / `fontes_usadas` para auditabilidade (LLM09).
    """
    tools_by_name = {t.name: t for t in tools}

    def tools_node(state: AgentState) -> dict:
        messages = state.get("messages") or []
        if not messages:
            return {}
        last = messages[-1]
        tool_calls = list(getattr(last, "tool_calls", None) or [])
        if not tool_calls:
            return {}

        tool_messages: list[ToolMessage] = []
        tentou_rag = state.get("tentou_rag", False)
        fontes_usadas = list(state.get("fontes_usadas") or [])

        for tc in tool_calls:
            nome = tc.get("name") or "desconhecida"
            tool = tools_by_name.get(nome)
            tool_call_id = tc.get("id") or ""

            if tool is None:
                content = json.dumps(
                    {"erro": f"tool desconhecida: {nome}"}, ensure_ascii=False
                )
                tool_messages.append(
                    ToolMessage(content=content, tool_call_id=tool_call_id, name=nome)
                )
                continue

            try:
                resultado = tool.invoke(tc.get("args") or {})
            except Exception as exc:  # noqa: BLE001 — devolvemos a falha pro agente decidir
                logger.warning("tool_falhou nome=%s erro=%s", nome, exc)
                resultado = {"erro": f"falha ao executar {nome}: {exc}"}

            if nome == "consultar_base_conhecimento":
                tentou_rag = True
                if isinstance(resultado, dict) and resultado.get("encontrado"):
                    chunks = resultado.get("chunks") or []
                    _registrar_fontes_rag(chunks, fontes_usadas)
                    embrulhado = envolver_chunks_rag(chunks)
                    content = embrulhado or json.dumps(resultado, ensure_ascii=False)
                else:
                    content = json.dumps(resultado, ensure_ascii=False)
            elif nome == "buscar_na_web_azapfy":
                if isinstance(resultado, dict) and resultado.get("encontrado"):
                    resultados = resultado.get("resultados") or []
                    _registrar_fontes_web(resultados, fontes_usadas)
                    embrulhado = envolver_resultados_web(resultados)
                    content = embrulhado or json.dumps(resultado, ensure_ascii=False)
                else:
                    content = json.dumps(resultado, ensure_ascii=False)
            else:
                content = (
                    resultado
                    if isinstance(resultado, str)
                    else json.dumps(resultado, ensure_ascii=False, default=str)
                )

            tool_messages.append(
                ToolMessage(content=content, tool_call_id=tool_call_id, name=nome)
            )

        return {
            "messages": tool_messages,
            "tentou_rag": tentou_rag,
            "fontes_usadas": fontes_usadas,
        }

    return tools_node


# ---------------------------------------------------------------------------
# Output guardrail — pass-through (placeholder para futuras checagens)
# ---------------------------------------------------------------------------


def output_guardrail_node(state: AgentState) -> dict:
    """No-op final. Espaço reservado para PII-masking, length cap, etc."""
    return {}


# ---------------------------------------------------------------------------
# Safe response — input bloqueado pelo guardrail
# ---------------------------------------------------------------------------


def safe_response_node(state: AgentState) -> dict:
    """Emite a resposta padrão para off-topic / malicioso (Épico 6)."""
    return {"messages": [AIMessage(content=RESPOSTA_OFF_TOPIC)]}


# ---------------------------------------------------------------------------
# Roteamento condicional
# ---------------------------------------------------------------------------


def route_after_input_guardrail(state: AgentState) -> str:
    seguranca = state.get("seguranca") or {}
    return "agent" if seguranca.get("is_safe", True) else "safe_response"


def route_after_agent(state: AgentState) -> str:
    messages = state.get("messages") or []
    if not messages:
        return "output_guardrail"
    last = messages[-1]
    if isinstance(last, AIMessage) and getattr(last, "tool_calls", None):
        return "tools"
    return "output_guardrail"