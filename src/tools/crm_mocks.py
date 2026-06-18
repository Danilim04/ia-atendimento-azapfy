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

# Notas fiscais da MERCADORIA transportada (não é cobrança/assinatura). Cada NF
# tem uma posição no ciclo de entrega da Azapfy (expedição → rota → transbordo →
# entrega) e o status da comprovação de entrega. Indexadas pelo número da NF;
# `id_cliente` permite não vazar NF de outro cliente (LLM06).
_NOTAS_FISCAIS: dict[str, dict[str, Any]] = {
    # Mariana (CLI-1001): uma a caminho, uma já entregue e validada.
    "NF-1042": {
        "id_cliente": "CLI-1001",
        "etapa": "em_rota",
        "comprovacao": "pendente",
        "ocorrencia": None,
        "atualizado_em": "2026-06-15T09:12:00Z",
    },
    "NF-1043": {
        "id_cliente": "CLI-1001",
        "etapa": "entregue",
        "comprovacao": "validada",
        "ocorrencia": None,
        "atualizado_em": "2026-06-12T17:40:00Z",
    },
    # Ricardo (CLI-1002): parada em transbordo por divergência de endereço.
    "NF-2001": {
        "id_cliente": "CLI-1002",
        "etapa": "transbordo",
        "comprovacao": "pendente",
        "ocorrencia": "endereco_divergente",
        "atualizado_em": "2026-06-14T11:05:00Z",
    },
    # Júlia (CLI-1003): entregue, mas a comprovação foi rejeitada na auditoria.
    "NF-3001": {
        "id_cliente": "CLI-1003",
        "etapa": "entregue",
        "comprovacao": "rejeitada",
        "ocorrencia": "foto_ilegivel",
        "atualizado_em": "2026-06-10T08:22:00Z",
    },
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
        telefone: Telefone do cliente, com ou sem máscara.

    Returns:
        dict: id_cliente, nome, plano, status_conta, encontrado (bool).
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
        dict: id_cliente, total (int), chamados (list com id, assunto, status,
        criado_em).
    """
    chamados = _CHAMADOS.get(id_cliente, [])
    return {
        "id_cliente": id_cliente,
        "total": len(chamados),
        "chamados": [dict(c) for c in chamados],
    }


@tool
def rastrear_nota_fiscal(id_cliente: str, numero_nota: str) -> dict[str, Any]:
    """Rastreia uma nota fiscal (NF da mercadoria) no ciclo de entrega da Azapfy.

    Use quando o cliente quiser saber EM QUE PONTO está uma NF específica da qual
    ele já tem o número: etapa do transporte (expedição → rota → transbordo →
    entrega), se a comprovação de entrega foi validada/rejeitada e se há ocorrência.

    NÃO use para dúvidas do tipo "como/onde encontro a NF no painel", "a nota não
    aparece na Pesquisa" ou "como funciona o módulo X" — isso é how-to e vai para
    `consultar_base_conhecimento`. Esta tool também não trata cobrança/fatura da
    assinatura Azapfy (a Azapfy não vende isso ao cliente final aqui).

    Args:
        id_cliente: Identificador interno do cliente (ex.: "CLI-1001").
        numero_nota: Número da nota fiscal, ex.: "NF-1042".

    Returns:
        dict: numero_nota, etapa ("expedicao"|"em_rota"|"transbordo"|"entregue"),
        comprovacao ("pendente"|"validada"|"rejeitada"), ocorrencia (str | None),
        atualizado_em (ISO 8601 UTC), encontrado (bool).
    """
    numero = (numero_nota or "").strip().upper()
    registro = _NOTAS_FISCAIS.get(numero)
    # Só devolve a NF se ela pertencer ao cliente da sessão — não vaza NF de
    # outro cliente nem confirma a existência de números alheios (LLM06).
    if registro is None or registro["id_cliente"] != id_cliente:
        return {
            "id_cliente": id_cliente,
            "numero_nota": numero or numero_nota,
            "encontrado": False,
        }

    return {
        "id_cliente": id_cliente,
        "numero_nota": numero,
        "etapa": registro["etapa"],
        "comprovacao": registro["comprovacao"],
        "ocorrencia": registro["ocorrencia"],
        "atualizado_em": registro["atualizado_em"],
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
        dict: ticket_id, id_cliente, assunto (resumo sanitizado), status
        ("aberto"), criado_em (ISO 8601 UTC).
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
    rastrear_nota_fiscal,
    abrir_novo_chamado,
]
