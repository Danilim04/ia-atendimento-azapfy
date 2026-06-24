# Suporte Técnico Azapfy — Agente IA + Gateway Chatwoot

Monorepo com **dois projetos** que se integram pelo **Contrato A** (`POST /chat`):

- **`agente-ia/`** — o cérebro: agente de IA de suporte técnico, em **LangGraph + LangChain + Chainlit**, com RAG local (ChromaDB) como única fonte externa (o agente **não acessa a internet**) e defesa contra prompt injection (**OWASP LLM Top 10**).
- **`backend/`** — o gateway em **Go**: recebe os webhooks do **Chatwoot** (WhatsApp), resolve a **identidade** do usuário no edge (telefone → login → MongoDB Azapfy → confirmação) e, só quando autenticado, encaminha a mensagem ao cérebro via o Contrato A.

Fluxo: `WhatsApp → Chatwoot → backend/ (Go) → agente-ia/server.py (POST /chat) → grafo → resposta`.

## Estrutura

```
ia-atendimento-suporte-azapfy/
├── agente-ia/                 # cérebro Python
│   ├── app.py                 # UI Chainlit (harness de dev)
│   ├── server.py              # API FastAPI do Contrato A (POST /chat, /health)
│   ├── src/
│   │   ├── config.py          # Configurações (.env via Pydantic Settings)
│   │   ├── agent/             # LangGraph: state, nodes, graph, prompts, llm
│   │   ├── tools/             # CRM mocks, RAG tool, identidade mock
│   │   ├── rag/               # Pipeline docs → ChromaDB e retriever
│   │   └── security/          # Guardrails de input/output (AppSec)
│   ├── tests/  docs/  chroma_db/  requirements.txt
│   └── plano_de_execucao.md   # roadmap do agente
└── backend/                   # gateway Go (Chatwoot + gate de identidade)
    ├── cmd/bot/  internal/  go.mod
    └── README.md
```

## Setup

```bash
# Agente Python
cd agente-ia
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # preencher OPENROUTER_API_KEY
python -m src.rag.ingest        # popular o ChromaDB
chainlit run app.py -w          # UI dev
uvicorn server:app --port 8001  # API do Contrato A

# Gateway Go
cd backend
cp .env.example .env            # Chatwoot + MONGO_URI + BRAIN_BASE_URL
go test ./...
go run ./cmd/bot
```

## Próximos passos

Roadmap do agente em [`agente-ia/plano_de_execucao.md`](./agente-ia/plano_de_execucao.md);
detalhes do gateway em [`backend/README.md`](./backend/README.md).
