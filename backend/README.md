# bot-azapfy — gateway Chatwoot + gate de identidade

Backend em Go que recebe os webhooks do **Chatwoot** (WhatsApp), resolve a
**identidade** do usuário no edge (telefone → base própria → login → MongoDB da
Azapfy → confirmação de um dado) e, **só quando autenticado**, encaminha a
mensagem ao **cérebro Python** (LangGraph) via o **Contrato A** (`POST /chat`).

As **tools de dados (MCP)** — rastrear nota, chamados, pesquisar notas etc. —
ficam para a **fase seguinte**; este serviço entrega a fundação + a 1ª tool
(resolução de identidade).

## Fluxo

```
WhatsApp → Chatwoot ─webhook→ [bot-azapfy]
   (HMAC/token, dedup, worker pool)
        └─ gate de identidade (FSM + base própria SQLite)
             1ª msg → pede login → Mongo (BuscarPorLogin + projeção)
                    → confirma e-mail/nome → cacheia (telefone→perfil, TTL)
        │  (identificado)
        │  Contrato A: POST /chat {conversation_id, mensagem, identidade, telefone}
        ▼
   [cérebro Python] → reply → bot-azapfy → Chatwoot
```

A identidade é **resolvida no Go** e nunca é um argumento escolhido pelo LLM —
base do controle de acesso mecânico (não por prompt). O perfil transportado é
**mínimo**: empresas/bases com acesso ativo, módulos ativos e `grupo_user`.

## Pacotes

| Pacote | Papel |
|--------|-------|
| `internal/chatwoot` | tipos do webhook + cliente REST + verificação HMAC |
| `internal/webhook` | endpoint HTTP, autenticação, dedup, pool de workers |
| `internal/store` | SQLite: dedup, estado do gate, base própria (telefone→perfil) |
| `internal/mongo` | **1ª tool**: `BuscarPorLogin` + `Projetar` (grupos→empresas, só `ativo`) |
| `internal/identity` | gate FSM (pede login → confirma → identifica/roteia) |
| `internal/brain` | cliente do Contrato A (`POST /chat`) |
| `internal/engine` | orquestra webhook → gate → cérebro → Chatwoot |
| `cmd/bot` | wiring + servidor HTTP |

## Rodar

```bash
cp .env.example .env   # preencher Chatwoot + MONGO_URI + BRAIN_BASE_URL
go run ./cmd/bot
```

Pré-requisitos: Mongo da Azapfy acessível e o cérebro Python no ar
(`uvicorn server:app --port 8001` na pasta `../agente-ia` deste monorepo).

## Testes

```bash
go test ./...
```

- `internal/mongo`: projeção do doc de exemplo (AZAPERS incluído; **AZAPFY
  excluído** por `ativo=false`; módulos inativos fora).
- `internal/identity`: fluxo feliz (login → confirmação → identificado →
  encaminhar), cache hit em nova conversa, login inexistente/inativo → humano.

## Smoke test (curl)

Simula um `message_created` do Chatwoot (requer Mongo + cérebro no ar):

```bash
curl -sS "http://localhost:8080/webhook?token=$WEBHOOK_TOKEN" \
  -H 'Content-Type: application/json' \
  -H 'X-Chatwoot-Delivery: dev-1' \
  -d '{
    "event": "message_created",
    "message_type": "incoming",
    "content": "oi",
    "private": false,
    "sender": {"type": "contact", "phone_number": "+5511999990001"},
    "conversation": {"id": 123, "labels": ["fila-bot"]}
  }'
```

O bot responde pedindo o login; envie o login e depois o e-mail cadastrado em
mensagens subsequentes (mesma `conversation.id`) para concluir a identificação.

## Contrato A (Go → Python)

```jsonc
// POST {BRAIN_BASE_URL}/chat
{ "conversation_id": "123", "canal": "whatsapp", "mensagem": "...",
  "identidade": { "encontrado": true, "login": "...", "nome": "...",
                  "empresas": [ { "grupo_empresa": "...", "grupo_user": "...",
                    "area": "...", "bases": [ { "nome": "...", "sigla": "...",
                    "modulos_ativos": ["..."] } ] } ] },
  "telefone": "..." }
// resposta: { "reply": "...", "acoes": [], "fontes": ["..."] }
```
