"""Testes unitários das tools mockadas do CRM (Épico 2)."""

from __future__ import annotations

import re

import pytest

from src.tools.crm_mocks import (
    CRM_TOOLS,
    abrir_novo_chamado,
    buscar_cliente_por_telefone,
    consultar_nota_fiscal,
    verificar_chamados_abertos,
)


# ---------------------------------------------------------------------------
# buscar_cliente_por_telefone
# ---------------------------------------------------------------------------


def test_buscar_cliente_telefone_conhecido_retorna_schema_completo():
    resultado = buscar_cliente_por_telefone.invoke({"telefone": "11999990001"})
    assert resultado["encontrado"] is True
    assert resultado["id_cliente"] == "CLI-1001"
    assert resultado["nome"] == "Mariana Souza"
    assert resultado["plano"] in {"Starter", "Pro", "Business"}
    assert resultado["status_conta"] in {"ativo", "inadimplente", "suspenso"}


def test_buscar_cliente_aceita_telefone_com_mascara():
    resultado = buscar_cliente_por_telefone.invoke(
        {"telefone": "(11) 99999-0002"}
    )
    assert resultado["encontrado"] is True
    assert resultado["id_cliente"] == "CLI-1002"


def test_buscar_cliente_telefone_desconhecido_retorna_nao_encontrado():
    resultado = buscar_cliente_por_telefone.invoke({"telefone": "11000000000"})
    assert resultado["encontrado"] is False
    assert resultado["id_cliente"] is None
    # Telefone deve aparecer mascarado (LLM06 — sensitive info)
    assert resultado["telefone_consultado"].endswith("0000")
    assert resultado["telefone_consultado"].startswith("*")


# ---------------------------------------------------------------------------
# verificar_chamados_abertos — variações: 0, 1 e múltiplos chamados
# ---------------------------------------------------------------------------


def test_verificar_chamados_cliente_sem_tickets():
    resultado = verificar_chamados_abertos.invoke({"id_cliente": "CLI-1001"})
    assert resultado["total"] == 0
    assert resultado["chamados"] == []


def test_verificar_chamados_cliente_com_um_ticket():
    resultado = verificar_chamados_abertos.invoke({"id_cliente": "CLI-1002"})
    assert resultado["total"] == 1
    chamado = resultado["chamados"][0]
    assert set(chamado.keys()) >= {"id", "assunto", "status", "criado_em"}


def test_verificar_chamados_cliente_com_multiplos_tickets():
    resultado = verificar_chamados_abertos.invoke({"id_cliente": "CLI-1003"})
    assert resultado["total"] >= 2
    assert all("id" in c for c in resultado["chamados"])


# ---------------------------------------------------------------------------
# consultar_nota_fiscal — 3 variações de status
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "id_cliente,status_esperado",
    [
        ("CLI-1001", "pago"),
        ("CLI-1002", "vencido"),
        ("CLI-1003", "em_aberto"),
    ],
)
def test_consultar_nota_fiscal_variacoes_de_status(id_cliente, status_esperado):
    resultado = consultar_nota_fiscal.invoke(
        {"id_cliente": id_cliente, "mes_referencia": "2026-04"}
    )
    assert resultado["encontrado"] is True
    assert resultado["status"] == status_esperado
    assert isinstance(resultado["valor"], float)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", resultado["vencimento"])


def test_consultar_nota_fiscal_mes_invalido_retorna_erro():
    resultado = consultar_nota_fiscal.invoke(
        {"id_cliente": "CLI-1001", "mes_referencia": "abril/2026"}
    )
    assert resultado["encontrado"] is False
    assert "erro" in resultado


def test_consultar_nota_fiscal_cliente_inexistente():
    resultado = consultar_nota_fiscal.invoke(
        {"id_cliente": "CLI-9999", "mes_referencia": "2026-04"}
    )
    assert resultado["encontrado"] is False


# ---------------------------------------------------------------------------
# abrir_novo_chamado
# ---------------------------------------------------------------------------


def test_abrir_novo_chamado_retorna_ticket_aberto():
    resultado = abrir_novo_chamado.invoke(
        {
            "id_cliente": "CLI-1001",
            "resumo": "Painel não carrega após login",
        }
    )
    assert resultado["status"] == "aberto"
    assert resultado["ticket_id"].startswith("TCK-")
    assert resultado["assunto"] == "Painel não carrega após login"


def test_abrir_novo_chamado_sanitiza_resumo_longo_e_quebras():
    resumo = "  linha 1\n\n   linha 2  " + ("x" * 400)
    resultado = abrir_novo_chamado.invoke(
        {"id_cliente": "CLI-1001", "resumo": resumo}
    )
    assert "\n" not in resultado["assunto"]
    assert len(resultado["assunto"]) <= 280


def test_abrir_novo_chamado_resumo_vazio_e_rejeitado():
    resultado = abrir_novo_chamado.invoke(
        {"id_cliente": "CLI-1001", "resumo": "   "}
    )
    assert resultado["status"] == "rejeitado"
    assert resultado["ticket_id"] is None


def test_abrir_novo_chamado_id_deterministico_para_mesmo_input():
    payload = {"id_cliente": "CLI-1001", "resumo": "Erro X"}
    a = abrir_novo_chamado.invoke(payload)
    b = abrir_novo_chamado.invoke(payload)
    assert a["ticket_id"] == b["ticket_id"]


# ---------------------------------------------------------------------------
# Sanidade do agregado exportado
# ---------------------------------------------------------------------------


def test_crm_tools_lista_contem_as_quatro_tools():
    nomes = {t.name for t in CRM_TOOLS}
    assert nomes == {
        "buscar_cliente_por_telefone",
        "verificar_chamados_abertos",
        "consultar_nota_fiscal",
        "abrir_novo_chamado",
    }


def test_todas_as_tools_tem_docstring_para_o_llm():
    for t in CRM_TOOLS:
        assert t.description and len(t.description.strip()) > 30
