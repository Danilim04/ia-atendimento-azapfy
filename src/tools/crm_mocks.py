"""Tools mockadas que simulam o CRM/backend da Azapfy.

Estas tools são decoradas com `@tool` do LangChain e suas docstrings são lidas
pelo LLM para escolher qual chamar — por isso elas descrevem com clareza
*quando* usar cada uma e *quais* parâmetros enviar.

As respostas são determinísticas em função do input (2–3 variações por tool),
o que permite exercitar múltiplos caminhos do agente sem depender de dados
reais ou aleatoriedade.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from langchain_core.tools import tool


# ---------------------------------------------------------------------------
# "Banco de dados" mockado
# ---------------------------------------------------------------------------

_CLIENTES: dict[str, dict[str, Any]] = {
    "11999990001": {
        "id_cliente": "CLI-1001",
        "nome": "Mariana Souza",
        "plano": "Pro",
        "status_conta": "ativo",
    },
    "11999990002": {
        "id_cliente": "CLI-1002",
        "nome": "Ricardo Almeida",
        "plano": "Business",
        "status_conta": "inadimplente",
    },
    "11999990003": {
        "id_cliente": "CLI-1003",
        "nome": "Júlia Pereira",
        "plano": "Starter",
        "status_conta": "ativo",
    },
}

_CHAMADOS: dict[str, list[dict[str, Any]]] = {
    "CLI-1001": [],
    "CLI-1002": [
        {
            "id": "TCK-7781",
            "assunto": "Falha intermitente na captura de etiqueta",
            "status": "em_andamento",
            "criado_em": "2026-04-29T10:14:00Z",
        }
    ],
    "CLI-1003": [
        {
            "id": "TCK-7790",
            "assunto": "Erro 500 ao gerar relatório de coletas",
            "status": "aberto",
            "criado_em": "2026-05-02T16:42:00Z",
        },
        {
            "id": "TCK-7795",
            "assunto": "Integração Bling parou de sincronizar",
            "status": "aguardando_cliente",
            "criado_em": "2026-05-04T09:05:00Z",
        },
        {
            "id": "TCK-7801",
            "assunto": "Solicitação de novo usuário no painel",
            "status": "aberto",
            "criado_em": "2026-05-05T11:20:00Z",
        },
    ],
}


def _normalizar_telefone(telefone: str) -> str:
    """Mantém apenas os dígitos do telefone (ex.: `(11) 99999-0001` → `11999990001`)."""
    return re.sub(r"\D", "", telefone or "")


def _mascarar_telefone(telefone: str) -> str:
    """Mascara o telefone deixando visíveis apenas os 4 últimos dígitos (LLM06)."""
    digitos = _normalizar_telefone(telefone)
    if len(digitos) <= 4:
        return "*" * len(digitos)
    return "*" * (len(digitos) - 4) + digitos[-4:]


# ---------------------------------------------------------------------------
# Tools expostas para o agente
# ---------------------------------------------------------------------------


@tool
def buscar_cliente_por_telefone(telefone: str) -> dict[str, Any]:
    """Identifica o cliente Azapfy a partir do telefone informado.

    Use esta tool no início da sessão (ou sempre que o telefone do cliente
    mudar) para obter `id_cliente`, `nome`, `plano` e `status_conta`. O
    `id_cliente` retornado é exigido pelas demais tools de CRM.

    Args:
        telefone: Telefone do cliente. Aceita formatos com ou sem máscara
            (ex.: "11999990001" ou "(11) 99999-0001").

    Returns:
        Dicionário com:
          - id_cliente (str): identificador interno do cliente, ou None se
            o telefone não estiver cadastrado.
          - nome (str | None)
          - plano (str | None): "Starter", "Pro" ou "Business".
          - status_conta (str | None): "ativo", "inadimplente" ou "suspenso".
          - encontrado (bool): False quando o telefone não está na base.
    """
    digitos = _normalizar_telefone(telefone)
    cliente = _CLIENTES.get(digitos)
    if cliente is None:
        return {
            "id_cliente": None,
            "nome": None,
            "plano": None,
            "status_conta": None,
            "encontrado": False,
            "telefone_consultado": _mascarar_telefone(digitos),
        }
    return {**cliente, "encontrado": True}


@tool
def verificar_chamados_abertos(id_cliente: str) -> dict[str, Any]:
    """Lista chamados em aberto (tickets) do cliente no sistema de suporte.

    Use quando o cliente perguntar sobre chamados, tickets, status de
    atendimento ou andamento de problemas reportados. Sempre passe o
    `id_cliente` retornado por `buscar_cliente_por_telefone`.

    Args:
        id_cliente: Identificador interno do cliente (ex.: "CLI-1001").

    Returns:
        Dicionário com:
          - id_cliente (str)
          - total (int)
          - chamados (list[dict]): cada item tem `id`, `assunto`, `status`
            ("aberto" | "em_andamento" | "aguardando_cliente") e `criado_em`
            (ISO 8601 UTC).
    """
    chamados = _CHAMADOS.get(id_cliente, [])
    return {
        "id_cliente": id_cliente,
        "total": len(chamados),
        "chamados": [dict(c) for c in chamados],
    }


@tool
def consultar_nota_fiscal(id_cliente: str, mes_referencia: str) -> dict[str, Any]:
    """Consulta o status da nota fiscal/fatura de um cliente em um mês de referência.

    Use para perguntas sobre pagamento, fatura, boleto ou nota fiscal de um
    período específico. O mês de referência segue o formato "AAAA-MM".

    Args:
        id_cliente: Identificador interno do cliente (ex.: "CLI-1002").
        mes_referencia: Mês de referência no formato "AAAA-MM" (ex.: "2026-04").

    Returns:
        Dicionário com:
          - id_cliente (str)
          - mes_referencia (str)
          - status (str): "pago", "em_aberto" ou "vencido".
          - valor (float): valor em reais.
          - vencimento (str): data de vencimento (ISO 8601, AAAA-MM-DD).
          - encontrado (bool): False se não houver fatura para o mês.
    """
    if not re.fullmatch(r"\d{4}-\d{2}", mes_referencia or ""):
        return {
            "id_cliente": id_cliente,
            "mes_referencia": mes_referencia,
            "encontrado": False,
            "erro": "mes_referencia deve estar no formato AAAA-MM",
        }

    valores_por_plano = {
        "CLI-1001": 249.90,  # Pro
        "CLI-1002": 599.00,  # Business
        "CLI-1003": 99.90,   # Starter
    }
    valor = valores_por_plano.get(id_cliente)
    if valor is None:
        return {
            "id_cliente": id_cliente,
            "mes_referencia": mes_referencia,
            "encontrado": False,
        }

    ano, mes = (int(p) for p in mes_referencia.split("-"))
    vencimento = f"{ano:04d}-{mes:02d}-10"

    # 3 variações determinísticas baseadas no id_cliente:
    # CLI-1001 → pago / CLI-1002 → vencido / CLI-1003 → em_aberto
    if id_cliente == "CLI-1001":
        status = "pago"
    elif id_cliente == "CLI-1002":
        status = "vencido"
    else:
        status = "em_aberto"

    return {
        "id_cliente": id_cliente,
        "mes_referencia": mes_referencia,
        "status": status,
        "valor": valor,
        "vencimento": vencimento,
        "encontrado": True,
    }


@tool
def abrir_novo_chamado(id_cliente: str, resumo: str) -> dict[str, Any]:
    """Abre um novo chamado (ticket) de suporte técnico para o cliente.

    AÇÃO COM EFEITO COLATERAL: cria um registro no sistema de tickets.
    Só chame esta tool após o cliente ter confirmado explicitamente que
    deseja abrir o chamado e qual é o resumo do problema (LLM08 — Excessive
    Agency).

    Args:
        id_cliente: Identificador interno do cliente (ex.: "CLI-1001").
        resumo: Descrição curta do problema (1–2 frases). Será sanitizada
            (limite de 280 caracteres, sem quebras de linha excessivas).

    Returns:
        Dicionário com:
          - ticket_id (str)
          - id_cliente (str)
          - assunto (str): resumo já sanitizado.
          - status (str): sempre "aberto" no momento da criação.
          - criado_em (str): timestamp ISO 8601 UTC.
    """
    resumo_limpo = (resumo or "").strip()
    resumo_limpo = re.sub(r"\s+", " ", resumo_limpo)
    if len(resumo_limpo) > 280:
        resumo_limpo = resumo_limpo[:277] + "..."

    if not resumo_limpo:
        return {
            "ticket_id": None,
            "id_cliente": id_cliente,
            "status": "rejeitado",
            "erro": "resumo do chamado não pode ser vazio",
        }

    # ID determinístico em função do (cliente, resumo) — facilita testes e
    # evita "duplicatas" quando o agente reexecuta a tool no mesmo turno.
    seed = abs(hash((id_cliente, resumo_limpo))) % 9000 + 1000
    ticket_id = f"TCK-{seed}"

    chamados_existentes = _CHAMADOS.setdefault(id_cliente, [])
    novo = {
        "id": ticket_id,
        "assunto": resumo_limpo,
        "status": "aberto",
        "criado_em": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    chamados_existentes.append(novo)

    return {
        "ticket_id": ticket_id,
        "id_cliente": id_cliente,
        "assunto": resumo_limpo,
        "status": "aberto",
        "criado_em": novo["criado_em"],
    }


CRM_TOOLS = [
    buscar_cliente_por_telefone,
    verificar_chamados_abertos,
    consultar_nota_fiscal,
    abrir_novo_chamado,
]
