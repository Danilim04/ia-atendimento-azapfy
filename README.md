# Agente de Suporte Técnico Azapfy

POC de agente de IA para atendimento técnico, construído com **LangGraph + LangChain + Chainlit**, com RAG local (ChromaDB) como única fonte externa (o agente **não acessa a internet**) e camada de segurança contra prompt injection seguindo o **OWASP LLM Top 10**.

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# preencher OPENROUTER_API_KEY
```

## Estrutura

```
src/
├── config.py           # Configurações (.env via Pydantic Settings)
├── agent/              # LangGraph: state, nodes, graph, prompts, llm factory
├── tools/              # CRM mocks, RAG tool
├── rag/                # Pipeline PDF → ChromaDB e retriever
└── security/           # Guardrails de input/output (AppSec)
```

## Próximos passos

Consulte o roadmap completo em [`plano_de_execucao.md`](./plano_de_execucao.md).
