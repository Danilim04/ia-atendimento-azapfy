"""Testes das tools de chamado (SAC) — sem rede: `httpx.post` é stubado.

Cobrem: payload/headers enviados ao gateway Go, a injeção do `telefone` a partir
do ESTADO (relator nunca vem do LLM) e o fail-soft em falha de rede.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from src.agent.nodes import make_tools_node
from src.tools import sac_tools
from src.tools.sac_tools import (
    SAC_TOOLS,
    abrir_chamado_suporte,
    consultar_tipos_de_chamado,
    listar_chamados_abertos,
)


class _FakeResp:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:  # sempre 2xx neste fake
        return None

    def json(self) -> dict:
        return self._payload


@pytest.fixture
def captura(monkeypatch):
    """Stub de `httpx.post`: registra as chamadas e devolve `resposta`."""
    chamadas: list[dict] = []
    estado = {"resposta": {"status": True}}

    def fake_post(url, json=None, headers=None, timeout=None):  # noqa: A002
        chamadas.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return _FakeResp(estado["resposta"])

    monkeypatch.setattr(sac_tools.httpx, "post", fake_post)
    return chamadas, estado


def test_abrir_chamado_envia_payload_e_token(captura):
    chamadas, estado = captura
    estado["resposta"] = {
        "status": True,
        "protocolo": "ZPRS25207690",
        "link": "https://atendimento.azapfy.com.br/chat/x/AZAPERS/ZPRS25207690",
    }
    out = abrir_chamado_suporte.invoke(
        {
            "resumo": "App travando",
            "descricao": "Trava ao bipar",
            "categoria": "APLICATIVO",
            "ocorrencia": "LENTIDÃO OU TRAVAMENTOS",
            "prioridade": "ALTA",
            "telefone": "5531983857490",
        }
    )
    assert out["protocolo"] == "ZPRS25207690"
    enviado = chamadas[-1]
    assert enviado["url"].endswith("/tools/sac/criar")
    assert enviado["headers"]["X-Tools-Token"] == ""  # default do .env.example
    assert enviado["json"]["categoria"] == "APLICATIVO"
    assert enviado["json"]["telefone"] == "5531983857490"


def test_telefone_vem_do_estado_via_tools_node(captura):
    """O LLM NÃO passa telefone; o tools_node injeta o da sessão (identidade)."""
    chamadas, estado = captura
    estado["resposta"] = {"status": True, "protocolo": "ZP1", "link": "http://x/AZAPERS/ZP1"}
    node = make_tools_node(SAC_TOOLS)
    ai = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "abrir_chamado_suporte",
                "id": "call-1",
                "args": {
                    "resumo": "R",
                    "descricao": "D",
                    "categoria": "APLICATIVO",
                    "ocorrencia": "LENTIDÃO OU TRAVAMENTOS",
                    "prioridade": "MEDIA",
                },
            }
        ],
    )
    out = node({"messages": [ai], "telefone": "5531999990000"})

    # O payload que foi pro Go recebeu o telefone do estado, não do LLM.
    assert chamadas[-1]["json"]["telefone"] == "5531999990000"
    # E o resultado da tool virou ToolMessage com o protocolo.
    tool_msgs = out["messages"]
    assert tool_msgs and tool_msgs[0].name == "abrir_chamado_suporte"
    assert "ZP1" in tool_msgs[0].content


def test_listar_e_consultar_tipos_endpoints(captura):
    chamadas, estado = captura
    estado["resposta"] = {"status": True, "total": 0, "chamados": []}
    listar_chamados_abertos.invoke({"telefone": "5531999990000"})
    assert chamadas[-1]["url"].endswith("/tools/sac/listar")

    estado["resposta"] = {"status": True, "categorias": [], "ocorrencias": []}
    consultar_tipos_de_chamado.invoke({"telefone": "5531999990000"})
    assert chamadas[-1]["url"].endswith("/tools/sac/tipos")


def test_falha_de_rede_retorna_status_false(monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError("conexão recusada")

    monkeypatch.setattr(sac_tools.httpx, "post", boom)
    out = listar_chamados_abertos.invoke({"telefone": "5531999990000"})
    assert out["status"] is False
    assert "erro" in out


def test_telefone_fora_do_schema_do_modelo():
    """`telefone` é InjectedToolArg: não aparece no schema que o LLM preenche."""
    campos = abrir_chamado_suporte.tool_call_schema.model_fields
    assert "telefone" not in campos
    assert "resumo" in campos and "categoria" in campos
