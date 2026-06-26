"""Tools reais de chamados (SAC) — abrir, listar e consultar ocorrências.

Estas tools **não** falam direto com o SAC: elas chamam o gateway Go
(`/tools/sac/*`), que resolve a identidade do relator a partir do telefone
(cache do gate) e monta a requisição. Assim os campos do RELATOR (nome,
e-mail, telefone, grupo) vêm da identidade verificada — **nunca** do LLM. O
agente só decide o conteúdo (resumo/descrição) e a classificação
(categoria/ocorrência/prioridade), que o Go valida contra a config do SAC.

`telefone` é um `InjectedToolArg`: fica fora do schema que o modelo vê e é
preenchido pelo `tools_node` a partir do estado da sessão.

As docstrings abaixo são lidas pelo LLM para escolher e usar a tool — edite com
intenção (elas custam tokens e guiam o comportamento).
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

import httpx
from langchain_core.tools import InjectedToolArg, tool

from src.config import get_settings


logger = logging.getLogger(__name__)


def _post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    """POST no gateway Go. Falha de rede vira `{status: False, erro: ...}`."""
    settings = get_settings()
    url = settings.sac_tools_base_url.rstrip("/") + path
    headers = {"X-Tools-Token": settings.sac_tools_token}
    safe_payload = {k: v for k, v in payload.items() if k != "telefone"}
    logger.info("sac_tool_call path=%s payload=%s", path, safe_payload)
    try:
        resp = httpx.post(
            url, json=payload, headers=headers, timeout=settings.sac_tools_timeout
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001 — devolvemos a falha pro agente decidir
        logger.warning("sac_tool_falhou path=%s erro=%s", path, exc)
        return {"status": False, "erro": "o sistema de chamados está indisponível agora"}
    logger.info("sac_tool_result path=%s status=%s", path, data.get("status"))
    return data


@tool
def consultar_tipos_de_chamado(
    telefone: Annotated[str, InjectedToolArg] = "",
) -> dict[str, Any]:
    """Lista as categorias e ocorrências válidas para abrir um chamado no SAC.

    Chame ANTES de `abrir_chamado_suporte` para escolher a `categoria` e a
    `ocorrencia` que melhor descrevem o problema do cliente — só valores desta
    lista são aceitos na abertura. Cada item traz `categoria`, `ocorrencia`
    (o nome do tipo) e uma `descricao` que ajuda a casar o problema relatado.

    Returns:
        dict: status (bool), categorias (list[str]), ocorrencias (list de
        {categoria, ocorrencia, descricao, prazo}).
    """
    return _post("/tools/sac/tipos", {"telefone": telefone})


@tool
def abrir_chamado_suporte(
    resumo: str,
    descricao: str,
    categoria: str,
    ocorrencia: str,
    prioridade: str = "MEDIA",
    empresa: str = "",
    telefone: Annotated[str, InjectedToolArg] = "",
) -> dict[str, Any]:
    """Abre um chamado de suporte no SAC, já preenchido e categorizado.

    AÇÃO COM EFEITO COLATERAL (LLM08): cria um chamado real. Só chame DEPOIS de
    o cliente confirmar explicitamente que quer abrir (ex.: "pode abrir", "sim").
    O chamado nasce pronto para o atendente: grupo, setor e prazo são definidos
    pelo gateway; você só fornece o conteúdo e a classificação.

    Antes de chamar, escolha `categoria` e `ocorrencia` a partir de
    `consultar_tipos_de_chamado` (valores fora da lista são recusados com
    motivo "ocorrencia_invalida" — nesse caso, reconsulte e tente de novo).

    Args:
        resumo: título curto do problema (1 linha). Será registrado em MAIÚSCULAS.
        descricao: descrição detalhada do que está acontecendo (preserva a caixa).
        categoria: categoria válida (de `consultar_tipos_de_chamado`).
        ocorrencia: ocorrência válida dentro da categoria.
        prioridade: BAIXA | MEDIA | ALTA | URGENTE (default MEDIA). Use ALTA/
            URGENTE só quando o impacto for claramente alto (operação parada).
        empresa: informe SÓ quando o cliente tiver mais de uma empresa e o
            gateway pedir para desambiguar (motivo "empresa_ambigua").

    Returns:
        dict: status (bool); em sucesso, protocolo, link (URL do chat do
        chamado) e prioridade. Em falha, erro e às vezes motivo
        ("ocorrencia_invalida" | "empresa_ambigua" | "nao_identificado").
        SEMPRE envie o `link` ao cliente e oriente-o a continuar pelo chat do
        chamado.
    """
    return _post(
        "/tools/sac/criar",
        {
            "telefone": telefone,
            "resumo": resumo,
            "descricao": descricao,
            "categoria": categoria,
            "ocorrencia": ocorrencia,
            "prioridade": prioridade,
            "grupo_emp": empresa,
        },
    )


@tool
def listar_chamados_abertos(
    telefone: Annotated[str, InjectedToolArg] = "",
) -> dict[str, Any]:
    """Lista os chamados EM ABERTO do cliente (pendentes / em andamento) no SAC.

    Use quando o cliente perguntar sobre seus chamados, tickets, protocolos ou
    o andamento de algo que reportou. A identidade já é da sessão — não peça
    nem invente identificadores. Ao responder, envie o `link` de cada chamado
    para o cliente acompanhar/conversar pelo chat do chamado.

    Returns:
        dict: status (bool), total (int), chamados (list de {protocolo, resumo,
        status, categoria, ocorrencia, dt_abertura, link}).
    """
    return _post("/tools/sac/listar", {"telefone": telefone})


SAC_TOOLS = [
    consultar_tipos_de_chamado,
    abrir_chamado_suporte,
    listar_chamados_abertos,
]

# Tools cujo `telefone` o `tools_node` injeta a partir do estado (a identidade
# do relator vem do gate, nunca do LLM).
TOOLS_COM_CONTEXTO_SESSAO = frozenset(t.name for t in SAC_TOOLS)
