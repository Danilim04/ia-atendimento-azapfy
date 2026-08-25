# Deploy

Como o bot chega em produção. Três ferramentas, cada uma com um papel:

| Ferramenta | Papel | Onde |
|---|---|---|
| **Terraform** | VM (Hetzner) + DNS (Cloudflare, desligado por ora) | `infra/terraform/` — rodado à mão |
| **Ansible** | Estado da VM: user deploy, hardening, ufw, docker, `/opt/azapfy-bot` | `infra/ansible/` — 1º job da pipeline |
| **Pipeline** | Build das imagens + deploy via `deploy/deploy-remote.sh` | `.github/workflows/deploy.yml` |

## O servidor

Uma única VPS (`62.238.63.240`, Hetzner `tenant-azapfy`, id `159386755`) —
**compartilhada com a stack omni-route**: é nela que rodam o Traefik (80/443),
o Chatwoot e a Evolution API do tenant azapfy. O bot roda AO LADO, sem publicar
porta nenhuma na internet:

```
WhatsApp → Evolution → Chatwoot ──webhook──► gateway (Go)  ──POST /chat──► brain (Python)
                ▲                            http://azapfy-bot:8080        http://brain:8001
                └────── respostas via API ─────────┘
        (tudo por DENTRO da rede docker omniroute_default / azapfy-bot_default)
```

- O gateway entra na rede `omniroute_default` com o alias **`azapfy-bot`** —
  o webhook do Chatwoot aponta para `http://azapfy-bot:8080/webhook?token=…`
  e o gateway fala com a API do Chatwoot em `http://chatwoot-rails:3000`.
- O cérebro só existe na rede interna da stack do bot (`azapfy-bot_default`).
- Estado no servidor: **só** o volume `gateway-data` (sqlite do gate de
  identidade). O `.env` é reescrito por inteiro a cada deploy; imagens chegam
  por `docker save | ssh docker load` (sem registry).

## Pipeline (`.github/workflows/deploy.yml`)

Dispara a cada push na `main` (ou `Run workflow` com uma tag à escolha):

1. **ansible** — converge o estado da VM (`configure-server.yml`, role `base`).
2. **test-go** — `go vet` + `go test` do gateway (paralelo ao ansible).
3. **deploy** — builda `azapfy-bot:brain-<v>` e `azapfy-bot:gateway-<v>` (cache
   GHA), renderiza o `.env` dos secrets (`deploy/env/render-env.sh`, fail-fast
   se faltar secret) e roda `deploy/deploy-remote.sh`: rsync da allowlist →
   save/load das imagens → `.env` → `compose up --wait` → `healthcheck.sh`
   (inclui o portão do caminho do webhook pela rede do Chatwoot).

**Rollback**: `Run workflow` com uma `version` anterior (a VPS guarda as 3
últimas tags de cada serviço) ou re-rodar a pipeline num commit antigo.

### Secrets (Settings → Secrets and variables → Actions)

| Secret | O que é |
|---|---|
| `SSH_PRIVATE_KEY` | chave privada do user `deploy` da VPS (par autorizado via Ansible) |
| `OPENROUTER_API_KEY` | chave do OpenRouter (cérebro) |
| `MONGO_URI` | Mongo da Azapfy (lookup de usuário do gate) |
| `WEBHOOK_TOKEN` | segredo do `?token=` da URL de webhook cadastrada no Chatwoot |
| `TOOLS_API_TOKEN` | segredo compartilhado cérebro↔gateway (tools SAC) |
| `SAC_API_TOKEN` · `SAC_SERVICE_COD` · `CHATWOOT_API_TOKEN` | opcionais (SAC; o token do Chatwoot é só bootstrap/override) |

O `CHATWOOT_API_TOKEN` de verdade é **estado da VM**: a pipeline "Configurar
Chatwoot" grava o access token do usuário "Zapin (bot)" em
`/opt/azapfy-bot/.chatwoot-token` (o valor nunca sai da máquina) e o
`apply-server-state.sh` o aplica no `.env` — nesta hora e em todo Deploy.

Sem registry de imagens ⇒ sem secrets de Docker Hub/GHCR. Para migrar para
registry no futuro, troque o passo 3 do `deploy-remote.sh` por push/pull.

## Primeira vez num servidor novo

1. `infra/terraform`: ajuste o `terraform.tfvars`, `terraform init && apply`
   (cria/adota a VM); atualize o `ansible_host` no inventário.
2. Autorize a chave do CI:
   `ansible-playbook playbooks/bootstrap.yml -e "{\"deploy_ssh_public_key\": \"$(cat ~/.ssh/azapfy_deploy.pub)\"}"`
   (conectando como root; depois disso tudo entra como `deploy`).
3. Cadastre os secrets acima e rode a pipeline **Deploy** (converge o estado
   via Ansible e sobe a stack).
4. Rode a pipeline **Configurar Chatwoot (caixa do bot)** com a conta/caixa
   alvo — ela cria etiquetas, o usuário "Zapin (bot)", o webhook e a
   automação da caixa (`deploy/chatwoot/setup-inbox.rb`, idempotente), grava
   o token do bot como estado da VM (`.chatwoot-token`) e recarrega o
   gateway. **Sem passo manual**: ao final dela o bot está atendendo.

## Break-glass (deploy da máquina local, sem Actions)

```bash
IMAGE_TAG=v-manual-1 OPENROUTER_API_KEY=… MONGO_URI=… CHATWOOT_API_TOKEN=… \
  WEBHOOK_TOKEN=… TOOLS_API_TOKEN=… \
  ./deploy/env/render-env.sh > /tmp/prod.env

./deploy/deploy-remote.sh --host 62.238.63.240 --version v-manual-1 \
  --env-file /tmp/prod.env --key ~/.ssh/azapfy_deploy
```

O script builda localmente (sem `--skip-build`) e segue o mesmo caminho da
pipeline. Diagnóstico na VPS: `cd /opt/azapfy-bot && docker compose ps`,
`docker compose logs -f gateway brain` e `./deploy/healthcheck.sh`.

## DNS (desligado, pronto para ligar)

Hoje nada do bot é exposto na internet. Quando precisar de URL pública
(ex.: webhook externo): preencha `bot_hosts` no `infra/terraform/terraform.tfvars`
(+ `terraform apply` com `CLOUDFLARE_API_TOKEN`) e descomente os labels
Traefik no `docker-compose.prod.yml` — o Traefik do servidor já termina TLS.

## O que a pipeline NÃO faz

- **Terraform** não roda no CI (state local, um operador) — `plan/apply` à mão.
- **pytest do cérebro** não roda no CI (suíte pesada, torch): rode local.
- **Registro do webhook no Chatwoot** é manual (uma vez, passo 4 acima).
