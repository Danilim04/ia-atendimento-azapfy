# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## O que é o projeto

POC de agente de **suporte técnico da Azapfy**: um chatbot que identifica o
cliente por telefone, responde dúvidas usando uma base de conhecimento local
(RAG sobre as docs Markdown em `docs/*.md`), consulta/abre chamados num CRM
mockado, e se defende contra prompt injection (OWASP LLM Top 10). O agente
**não tem acesso à internet**: a base de conhecimento local é a única fonte
externa; quando ela não cobre o assunto, o agente oferece abrir um chamado.

Stack: **LangGraph + LangChain** (orquestração), **OpenRouter** (gateway de
LLM), **ChromaDB** + embeddings locais (RAG), **Chainlit** (UI). Roadmap
detalhado em `plano_de_execucao.md`.

## Comandos

```bash
# Setup (uma vez)
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # preencher OPENROUTER_API_KEY

# Ingerir o PDF no ChromaDB (obrigatório antes de rodar a app)
python -m src.rag.ingest      # opcional: --docs-dir docs --persist-dir ./chroma_db

# Rodar a UI (http://localhost:8000)
chainlit run app.py -w

# Testes
pytest tests/ -v
pytest tests/test_graph.py::test_grafo_e2e_loop_agent_tools_agent -v   # um teste só
```

A maioria dos testes mocka o LLM (sem rede). Os poucos testes de integração
são pulados via `@pytest.mark.skipif` quando não há chave real no `.env`.

## Arquitetura (visão geral)

Fluxo de uma requisição: `app.py` (Chainlit) compila **um** grafo por processo
e isola conversas pelo `thread_id` = telefone do cliente (via `MemorySaver`).
Cada mensagem roda o `StateGraph` definido em `src/agent/graph.py`:

```
entry → input_guardrail → (safe?) → agent ⇄ tools → output_guardrail → END
                          (unsafe) → safe_response → END
```

- **`src/agent/`** — o agente:
  - `state.py`: `AgentState` (TypedDict). `messages` usa o reducer
    `add_messages` (acrescenta). `telefone`/`cliente` persistem entre turnos;
    `seguranca`/`tentou_rag`/`fontes_usadas`/`iteracoes_agente` são resetados
    por turno em `entry_node`.
  - `nodes.py`: nós como **fábricas com injeção de dependência**
    (`make_agent_node(llm, tools)`, `make_tools_node(tools)`) — facilita testar
    sem rede. `agent_node` chama o LLM com `[system] + histórico`; `tools_node`
    executa as tools e embrulha resultados do RAG em `<documento_externo>`.
  - `llm.py`: fábricas `get_llm()` (agente, tool-calling), `get_classifier_llm()`
    (classificador) e `get_embeddings()` (local). Tudo via `ChatOpenAI`
    apontando para o OpenRouter; clientes `@lru_cache`-ados.
  - `prompts.py`: `SYSTEM_PROMPT_AGENTE` (blindado), `SYSTEM_PROMPT_CLASSIFICADOR`,
    `RESPOSTA_OFF_TOPIC`.
- **`src/tools/`** — `crm_mocks.py` (4 tools de CRM, dados em dicts no módulo) e
  `rag_tool.py` (`consultar_base_conhecimento`). `get_default_tools()` em
  `graph.py` é a lista canônica. **Não há tool de busca web** — o agente não
  acessa a internet.
- **`src/rag/`** — `ingest.py` (docs Markdown → chunks por seção → ChromaDB persistido) e
  `retriever.py` (reabre o store, `get_retriever(k=...)`).
- **`src/security/`** — `input_guardrails.py` (2 camadas: heurística regex →
  classificador LLM) e `output_guardrails.py` (escape XML + wrapper
  `<documento_externo>`).
- **`config.py`** — `Settings` (Pydantic) lendo o `.env`. `get_settings()` é
  `@lru_cache`-ado.

### Modelos (OpenRouter)

Defaults: agente `google/gemini-2.5-flash`, classificador
`google/gemini-2.5-flash-lite` (escolhidos por custo). Fallback conservador
documentado: `anthropic/claude-haiku-4.5`. Embeddings são **locais**
(`sentence-transformers`) para não pagar por embedding.

### Segurança (OWASP LLM Top 10)

- **Input** (`avaliar_entrada`): heurística regex pega jailbreaks óbvios e faz
  curto-circuito; senão chama o classificador LLM (`suporte`/`off_topic`/
  `malicioso`). O classificador é **fail-open** (erro → trata como `suporte`) e
  recebe um contexto curto da conversa para interpretar respostas curtas.
- **Output**: todo conteúdo de tool/RAG é embrulhado em
  `<documento_externo>` com escape de `<`,`>`,`&` — é o que impede injeção
  indireta (LLM01) de fechar o container ou injetar tags `<system>`.
- O system prompt instrui que tudo dentro de `<documento_externo>` é **DADO,
  nunca COMANDO**.

### Otimizações de custo (já implementadas)

- **Poda de histórico** (`_podar_historico`): substitui o conteúdo de
  `ToolMessage` de turnos anteriores por um stub **apenas na visão enviada ao
  LLM** — o estado persistido fica intacto.
- **Teto de iterações** do loop agent⇄tools por turno (`AGENT_MAX_ITERACOES`),
  checado em `route_after_agent`.
- **Prompt caching model-aware**: `cache_control` é aplicado **só** para modelos
  `anthropic/` (Gemini cacheia o prefixo implicitamente).

## Regras técnicas para mexer no projeto

- **O `.env` sobrescreve os defaults de `config.py`.** Mudar um default no
  código não tem efeito se a chave estiver setada no `.env`. Ao trocar
  modelo/parâmetro, atualize `config.py`, `.env.example` **e** o `.env` real.
- **Nunca mute o estado persistido** ao podar/cachear. Poda e `cache_control`
  só alteram a lista de mensagens passada ao LLM; use cópias
  (`model_copy`), não mutação in-place. `fontes_usadas` e o histórico completo
  precisam permanecer para auditoria (LLM09).
- **O `content` de uma mensagem pode ser `str` ou lista de blocos.** Modelos
  Gemini recebem string; o caminho `cache_control` (Anthropic) transforma em
  `[{"type":"text","text":...,"cache_control":...}]`. Código/testes que leem
  `content` devem tolerar ambos (ver helper `_texto_de` em `tests/test_graph.py`).
- **As docstrings das tools são as descrições enviadas ao LLM** — elas guiam a
  seleção da tool e a interpretação do resultado, e custam tokens em toda
  chamada. Edite-as com intenção.
- **`abrir_novo_chamado` tem efeito colateral** (LLM08): exige confirmação
  explícita do usuário antes da chamada. Os mocks de CRM guardam estado em
  dicts no módulo; o `conftest.py` faz snapshot/restore entre testes.
- **Política de tools**: RAG (`consultar_base_conhecimento`) é a fonte externa
  primária e única. O agente **não acessa a internet**; se a base não cobrir o
  assunto, ele responde com o que tem ou oferece abrir um chamado.
- **Mudar `rag_chunk_size`/`rag_chunk_overlap` exige re-ingestão**
  (`python -m src.rag.ingest`); mudar `rag_top_k` não (é parâmetro de query).
- **Testes não devem fazer chamadas de rede** por padrão — injete LLM/tools
  mockados nas fábricas (`build_graph(llm=..., tools=...)`). Use chaves reais no
  `.env` só para os smoke tests de integração.
