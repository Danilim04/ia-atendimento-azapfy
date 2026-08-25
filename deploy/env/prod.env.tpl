# ==============================================================================
# .env de PRODUÇÃO — renderizado pela pipeline (render-env.sh/envsubst) e
# gravado por inteiro em /opt/azapfy-bot/.env a cada deploy. NÃO EDITAR na VPS:
# qualquer mudança manual é sobrescrita no próximo deploy. Linha
# adicionada/removida AQUI reflete no servidor no próximo deploy.
#
# (Diferente do omni-route não há "bloco gerenciado": esta stack não gera
# segredos no servidor — TODO o .env vem de GitHub Secrets/vars, então o
# arquivo inteiro é gerenciado. O único estado local é o sqlite no volume.)
# ==============================================================================

# --- Imagens (chegam via docker load — ver deploy-remote.sh) ------------------
IMAGE_REPO=azapfy-bot
IMAGE_TAG=${IMAGE_TAG}
COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml

# --- Cérebro: OpenRouter ------------------------------------------------------
OPENROUTER_API_KEY=${OPENROUTER_API_KEY}
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_MODEL=google/gemini-2.5-flash
OPENROUTER_CLASSIFIER_MODEL=google/gemini-2.5-flash-lite
APP_REFERER=https://azapfy.com.br
APP_TITLE=Azapfy Suporte IA

# --- Cérebro: tuning ----------------------------------------------------------
LLM_TEMPERATURE=0.2
RAG_TOP_K=3
RAG_CHUNK_SIZE=800
RAG_CHUNK_OVERLAP=120
AGENT_MAX_ITERACOES=5
EMBEDDINGS_MODEL=sentence-transformers/all-MiniLM-L6-v2

# --- Observabilidade ----------------------------------------------------------
LOG_LEVEL=info

# --- Gateway: Chatwoot (por DENTRO da rede docker do servidor) ----------------
CHATWOOT_BASE_URL=http://chatwoot-rails:3000
CHATWOOT_ACCOUNT_ID=1
# Preenchido pelo ESTADO da VM (.chatwoot-token → apply-server-state.sh) por
# cima do que o CI renderizar; o secret é só bootstrap/override manual.
CHATWOOT_API_TOKEN=${CHATWOOT_API_TOKEN}
WEBHOOK_TOKEN=${WEBHOOK_TOKEN}
WEBHOOK_SECRET=
# Base interna que o Chatwoot alcança — vira a URL a cadastrar no webhook.
PUBLIC_BASE_URL=http://azapfy-bot:8080

# --- Gateway: etiquetas / gate ------------------------------------------------
LABEL_BOT=fila-bot
LABEL_HUMANO=fila-humano
# Caixa de entrada cujas conversas NOVAS o gateway etiqueta com fila-bot no
# conversation_created (2 = caixa "whatsapp" da conta Omni Route; 0 = todas).
INBOX_ID=2
CONFIRM_FIELD=email
MAX_TENTATIVAS=3
IDENTITY_TTL=24h

# --- Gateway: Mongo da Azapfy -------------------------------------------------
MONGO_URI=${MONGO_URI}
MONGO_DB=azapfy3
MONGO_COLLECTION=users
MONGO_TIMEOUT=8s
BRAIN_TIMEOUT=60s

# --- SAC / chamados -----------------------------------------------------------
SAC_BASE_URL=https://api3.azapfy.com.br
SAC_PORTAL_URL=https://atendimento.azapfy.com.br
SAC_SERVICE_COD=${SAC_SERVICE_COD}
SAC_GRUPO_EMP=AZAPERS
SAC_EMPRESA=AZAPERS
SAC_TIMEZONE=America/Sao_Paulo
SAC_API_TOKEN=${SAC_API_TOKEN}
SAC_CONFIG_TTL=10m
# Segredo compartilhado cérebro↔gateway (X-Tools-Token) — mesmo valor nos dois:
TOOLS_API_TOKEN=${TOOLS_API_TOKEN}
SAC_TOOLS_TOKEN=${TOOLS_API_TOKEN}
SAC_TOOLS_TIMEOUT=30
