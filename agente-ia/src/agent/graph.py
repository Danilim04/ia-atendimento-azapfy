"""Construção do StateGraph (Épico 7).

`build_graph()` aceita injeção opcional de `llm`, `tools` e `checkpointer`
para facilitar testes — em produção o default é o LLM do OpenRouter
(via `get_llm()`), todas as tools dos Épicos 2-4, e `MemorySaver`.

Uso:

    graph = build_graph()
    out = graph.invoke(
        {"telefone": "11999990001", "messages": [HumanMessage("oi")]},
        config={"configurable": {"thread_id": "11999990001"}},
    )
"""

from __future__ import annotations

from typing import Any, Optional

from langchain_core.tools import BaseTool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from src.agent.llm import get_llm
from src.agent.nodes import (
    entry_node,
    input_guardrail_node,
    make_agent_node,
    make_tools_node,
    output_guardrail_node,
    route_after_agent,
    route_after_input_guardrail,
    safe_response_node,
)
from src.agent.state import AgentState
from src.tools.crm_mocks import rastrear_nota_fiscal
from src.tools.rag_tool import consultar_base_conhecimento
from src.tools.sac_tools import SAC_TOOLS


def get_default_tools() -> list[BaseTool]:
    """Tools canônicas: RAG + rastreio de NF (mock) + chamados reais (SAC via Go).

    O agente não acessa a internet. A identidade do relator (nome/e-mail/grupo)
    vem do gate via Contrato A, então não há `buscar_cliente_por_telefone` aqui;
    abrir/listar chamados são as tools reais do SAC (`SAC_TOOLS`). O rastreio de
    NF segue mockado (fase seguinte).
    """
    return [consultar_base_conhecimento, rastrear_nota_fiscal, *SAC_TOOLS]


def build_graph(
    llm: Optional[Any] = None,
    tools: Optional[list[BaseTool]] = None,
    checkpointer: Optional[Any] = None,
):
    """Compila o grafo. Defaults de produção podem ser sobrescritos para testes."""
    if llm is None:
        llm = get_llm()
    if tools is None:
        tools = get_default_tools()
    if checkpointer is None:
        checkpointer = MemorySaver()

    workflow: StateGraph = StateGraph(AgentState)

    workflow.add_node("entry", entry_node)
    workflow.add_node("input_guardrail", input_guardrail_node)
    workflow.add_node("agent", make_agent_node(llm, tools))
    workflow.add_node("tools", make_tools_node(tools))
    workflow.add_node("output_guardrail", output_guardrail_node)
    workflow.add_node("safe_response", safe_response_node)

    workflow.set_entry_point("entry")
    workflow.add_edge("entry", "input_guardrail")
    workflow.add_conditional_edges(
        "input_guardrail",
        route_after_input_guardrail,
        {"agent": "agent", "safe_response": "safe_response"},
    )
    workflow.add_conditional_edges(
        "agent",
        route_after_agent,
        {"tools": "tools", "output_guardrail": "output_guardrail"},
    )
    workflow.add_edge("tools", "agent")
    workflow.add_edge("output_guardrail", END)
    workflow.add_edge("safe_response", END)

    return workflow.compile(checkpointer=checkpointer)