"""Estado compartilhado do grafo do agente (Épico 7).

`messages` usa o reducer `add_messages` do LangGraph — qualquer nó que
retornar `{"messages": [...]}` *acrescenta* à lista existente, com
deduplicação por id quando aplicável. Os demais campos são substituídos
(reducer default).

`telefone` e `cliente` persistem entre turnos (via `MemorySaver`).
`seguranca`, `tentou_rag`, `fontes_usadas` e `iteracoes_agente` são
*reiniciados por turno* no `entry_node` — citações, veredito de segurança e
contagem de iterações valem só para a resposta atual.
"""

from __future__ import annotations

from typing import Annotated, Any, NotRequired, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """Estado do grafo. `messages` é obrigatório; os demais são opcionais."""

    messages: Annotated[list[BaseMessage], add_messages]

    telefone: NotRequired[str]
    cliente: NotRequired[dict[str, Any] | None]
    seguranca: NotRequired[dict[str, Any] | None]
    tentou_rag: NotRequired[bool]
    fontes_usadas: NotRequired[list[str]]
    iteracoes_agente: NotRequired[int]