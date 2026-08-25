#!/usr/bin/env bash
# ==============================================================================
# Renderiza o .env de produção para stdout. Roda no RUNNER da pipeline; os
# valores chegam pelo ambiente (GitHub Secrets/vars).
#
#   IMAGE_TAG=v1.2.3 OPENROUTER_API_KEY=… ./render-env.sh > prod.env
#
# Falha se alguma var exigida estiver vazia — fail-fast: um secret esquecido
# aborta o deploy em vez de zerar silenciosamente uma chave no servidor.
# ==============================================================================
set -euo pipefail
cd "$(dirname "$0")"

required=(IMAGE_TAG OPENROUTER_API_KEY MONGO_URI CHATWOOT_API_TOKEN
  WEBHOOK_TOKEN TOOLS_API_TOKEN)

faltando=()
for var in "${required[@]}"; do
  [ -n "${!var:-}" ] || faltando+=("$var")
done
if [ "${#faltando[@]}" -gt 0 ]; then
  echo "ERRO: variáveis exigidas vazias/ausentes: ${faltando[*]}" >&2
  exit 1
fi

# Lista EXPLÍCITA de substituições — o envsubst não toca em mais nada.
# Vars OPCIONAIS (fora da lista required, ex.: SAC_*) podem vir vazias: a
# chave entra vazia e o gateway trata como não configurada.
vars='$IMAGE_TAG $OPENROUTER_API_KEY $MONGO_URI $CHATWOOT_API_TOKEN $WEBHOOK_TOKEN $TOOLS_API_TOKEN $SAC_API_TOKEN $SAC_SERVICE_COD'
envsubst "$vars" < prod.env.tpl
