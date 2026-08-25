#!/usr/bin/env bash
# ==============================================================================
# Deploy remoto por IMAGEM — FONTE ÚNICA do deploy (pipeline e break-glass).
# Roda no RUNNER (ou na máquina de quem depura), nunca no servidor.
#
#   deploy-remote.sh --host <ip> --version <tag> --env-file <env-renderizado> \
#     --key <chave-ssh> [--user deploy] [--skip-build]
#
# Transporte SEM registry: as imagens são construídas aqui e chegam à VPS por
# `docker save | ssh docker load` (não há credencial de Docker Hub/GHCR no
# projeto; para migrar p/ registry no futuro, troque o passo 3 por push+pull).
#
# O servidor recebe SÓ o necessário pra rodar a stack (allowlist + rsync
# --delete): compose files e o healthcheck. O .env chega por stdin (nunca por
# argv) e é reescrito POR INTEIRO a cada deploy — estado local é só o volume
# do sqlite (gateway-data), que o compose preserva.
# ==============================================================================
set -euo pipefail
cd "$(dirname "$0")/.."

HOST='' VERSION='' ENV_FILE='' KEY='' SSH_USER='deploy' BUILD=1
while [ $# -gt 0 ]; do
  case "$1" in
    --host)       HOST="$2"; shift 2 ;;
    --version)    VERSION="$2"; shift 2 ;;
    --env-file)   ENV_FILE="$2"; shift 2 ;;
    --key)        KEY="$2"; shift 2 ;;
    --user)       SSH_USER="$2"; shift 2 ;;
    --skip-build) BUILD=0; shift ;;
    *) echo "ERRO: parâmetro desconhecido: $1" >&2; exit 1 ;;
  esac
done
[ -n "$HOST" ] && [ -n "$VERSION" ] && [ -n "$ENV_FILE" ] && [ -n "$KEY" ] ||
  { echo "Uso: deploy-remote.sh --host <ip> --version <tag> --env-file <arq> --key <chave>" >&2; exit 1; }
[ -f "$ENV_FILE" ] || { echo "ERRO: env-file não existe: $ENV_FILE" >&2; exit 1; }

SSH_OPTS=(-i "$KEY" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15)
SSH=(ssh "${SSH_OPTS[@]}" "${SSH_USER}@${HOST}")
DEST=/opt/azapfy-bot
REPO=azapfy-bot
BRAIN_IMG="$REPO:brain-$VERSION"
GATEWAY_IMG="$REPO:gateway-$VERSION"

if [ "$BUILD" = 1 ]; then
  echo "→ [1/7] Build das imagens ($VERSION)…"
  docker build -t "$BRAIN_IMG" agente-ia/
  docker build -t "$GATEWAY_IMG" backend/
else
  echo "→ [1/7] Build pulado (--skip-build) — usando imagens locais existentes."
  docker image inspect "$BRAIN_IMG" "$GATEWAY_IMG" > /dev/null
fi

echo "→ [2/7] Allowlist + rsync da stack…"
staging="$(mktemp -d)"
trap 'rm -rf "$staging"' EXIT
mkdir -p "$staging/deploy/env"
cp docker-compose.yml docker-compose.prod.yml "$staging/"
cp deploy/healthcheck.sh "$staging/deploy/"
cp deploy/env/apply-server-state.sh "$staging/deploy/env/"
# --exclude protege o ESTADO da VM: .env (reescrito no passo 4) e
# .chatwoot-token (gravado pela pipeline configure-chatwoot).
rsync -az --delete --exclude='.env' --exclude='.chatwoot-token' \
  -e "ssh ${SSH_OPTS[*]}" \
  "$staging/" "${SSH_USER}@${HOST}:${DEST}/"
"${SSH[@]}" "chmod +x $DEST/deploy/healthcheck.sh $DEST/deploy/env/apply-server-state.sh"

echo "→ [3/7] Transferindo imagens (docker save | ssh docker load)…"
docker save "$BRAIN_IMG" "$GATEWAY_IMG" | gzip | "${SSH[@]}" 'gunzip | docker load'

echo "→ [4/7] .env (por stdin, chmod 600) + estado do servidor…"
"${SSH[@]}" "umask 077 && cat > $DEST/.env" < "$ENV_FILE"
# CHATWOOT_API_TOKEN vem do estado da VM (.chatwoot-token) quando existir —
# ver deploy/env/apply-server-state.sh.
"${SSH[@]}" "$DEST/deploy/env/apply-server-state.sh"

echo "→ [5/7] Up da stack (sem build)…"
"${SSH[@]}" "cd $DEST && docker compose up -d --remove-orphans --wait --wait-timeout 300"

echo "→ [6/7] Healthcheck (dentro da rede do Chatwoot)…"
"${SSH[@]}" "cd $DEST && ./deploy/healthcheck.sh"

echo "→ [7/7] Limpeza: mantém as 3 tags mais recentes de cada serviço…"
"${SSH[@]}" "for svc in brain gateway; do
  docker images '$REPO' --format '{{.Tag}} {{.CreatedAt}}' \
    | grep \"^\$svc-\" | sort -rk2 | tail -n +4 | awk '{print \$1}' \
    | xargs -r -I{} docker rmi '$REPO:{}' || true
done; docker image prune -f > /dev/null"

echo "✔ Deploy $VERSION concluído."
