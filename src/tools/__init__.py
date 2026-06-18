from src.tools.crm_mocks import (
    CRM_TOOLS,
    abrir_novo_chamado,
    buscar_cliente_por_telefone,
    rastrear_nota_fiscal,
    verificar_chamados_abertos,
)
from src.tools.rag_tool import consultar_base_conhecimento
from src.tools.web_search import buscar_na_web_azapfy

__all__ = [
    "CRM_TOOLS",
    "abrir_novo_chamado",
    "buscar_cliente_por_telefone",
    "buscar_na_web_azapfy",
    "consultar_base_conhecimento",
    "rastrear_nota_fiscal",
    "verificar_chamados_abertos",
]
