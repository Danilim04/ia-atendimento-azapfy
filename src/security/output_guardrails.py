"""Output guardrails — defesa contra prompt injection indireta (LLM01 indireta).

Tudo que vem de fonte externa (RAG ou qualquer tool com texto livre) passa por
este módulo ANTES de ser injetado em uma mensagem que vai para o LLM.

Estratégia:

1. **Delimitar:** envolver o conteúdo em `<documento_externo source="...">...</documento_externo>`,
   pareando com a regra explícita do `SYSTEM_PROMPT_AGENTE` de tratar tudo
   ali dentro como DADO (não COMANDO).
2. **Sanitizar:** XML-escapar `<`, `>` e `&` no conteúdo, impedindo que o
   atacante feche o delimitador com `</documento_externo>` ou injete tags
   de chat (`<system>`, `<user>`, etc.) que confundam o modelo.

Não tentamos remover instruções imperativas em linguagem natural ("ignore
o sistema") — isso é responsabilidade da regra anti-injection do system
prompt + classificador de input. Aqui só garantimos a integridade do
container.
"""

from __future__ import annotations

import html
from typing import Iterable, Mapping


def _sanitizar_conteudo(texto: object) -> str:
    """XML-escape de `<`, `>`, `&` no conteúdo + remoção de NULs.

    `quote=False` mantém `"` e `'` legíveis (só importam em atributos).
    """
    if not isinstance(texto, str):
        texto = "" if texto is None else str(texto)
    texto = texto.replace("\x00", "")
    return html.escape(texto, quote=False)


def _escape_attr(valor: object) -> str:
    if not isinstance(valor, str):
        valor = "" if valor is None else str(valor)
    return html.escape(valor, quote=True)


def envolver_dado_externo(
    conteudo: object,
    source: str = "desconhecido",
    **extra_attrs: object,
) -> str:
    """Envolve conteúdo externo em `<documento_externo ...>...</documento_externo>`.

    Args:
        conteudo: texto bruto vindo de RAG, web ou outra tool externa.
        source: identificador de origem (nome do arquivo, URL, etc.).
        **extra_attrs: atributos opcionais (`secao="..."`, `origem="rag"`, ...).

    Returns:
        String pronta para concatenar a uma mensagem que o LLM vai ler.
    """
    pares = [f'source="{_escape_attr(source)}"']
    for chave, valor in extra_attrs.items():
        pares.append(f'{chave}="{_escape_attr(valor)}"')
    abertura = "<documento_externo " + " ".join(pares) + ">"
    return f"{abertura}\n{_sanitizar_conteudo(conteudo)}\n</documento_externo>"


def envolver_chunks_rag(chunks: Iterable[Mapping[str, object]]) -> str:
    """Formata os chunks devolvidos por `consultar_base_conhecimento`.

    Espera dicts no formato `{texto, secao, source}` (saída da tool RAG).
    Chunks vazios são ignorados.
    """
    blocos: list[str] = []
    for chunk in chunks:
        texto = chunk.get("texto")
        if not texto:
            continue
        source = str(chunk.get("source") or "desconhecido")
        extras: dict[str, object] = {"origem": "rag"}
        secao = chunk.get("secao")
        if secao:
            extras["secao"] = secao
        blocos.append(envolver_dado_externo(texto, source=source, **extras))
    return "\n\n".join(blocos)