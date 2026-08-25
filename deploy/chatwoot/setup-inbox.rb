# ==============================================================================
# Provisiona a integração do bot numa conta/caixa do Chatwoot — IDEMPOTENTE
# (rodar de novo não duplica nada; corrige o que tiver sido apagado).
#
# Roda DENTRO do container rails do Chatwoot, via pipeline
# .github/workflows/configure-chatwoot.yml (ou à mão, para depurar):
#
#   sed -e "s/__BOT_WEBHOOK_TOKEN__/<token>/" -e "s/__ACCOUNT_ID__/1/" \
#       -e "s/__INBOX_ID__/2/" deploy/chatwoot/setup-inbox.rb \
#     | ssh deploy@<vm> 'docker exec -i omniroute-chatwoot-rails-1 \
#         bundle exec rails runner -'
#
# Os placeholders __X__ são substituídos pela pipeline ANTES do envio; o token
# viaja só por stdin (nunca por argv/ps). O que ele cria:
#
#   1. Etiquetas fila-bot / fila-humano — o gateway SÓ processa conversa com
#      fila-bot e troca para fila-humano na passagem de bastão.
#   2. Usuário dedicado "Zapin (bot)" (admin na conta) — o access token DELE é
#      o CHATWOOT_API_TOKEN do gateway; nada de token de pessoa.
#   3. Webhook da conta → http://azapfy-bot:8080/webhook?token=… (rede docker
#      interna), assinando message_created + conversation_updated.
#   4. Automação: conversa NOVA da caixa __INBOX_ID__ ganha fila-bot — é o que
#      faz o bot atender a caixa de entrada.
# ==============================================================================

token      = '__BOT_WEBHOOK_TOKEN__'
account_id = '__ACCOUNT_ID__'.to_i
inbox_id   = '__INBOX_ID__'.to_i
bot_email  = 'zapin-bot@azapfy.com.br'

raise 'placeholder __BOT_WEBHOOK_TOKEN__ não substituído' if token.include?('__')

acc = Account.find(account_id)
inbox = acc.inboxes.find(inbox_id) # falha cedo se a caixa não existir na conta

# 1. Etiquetas do roteamento bot/humano
{ 'fila-bot' => '#1F93FF', 'fila-humano' => '#F97316' }.each do |title, color|
  acc.labels.find_or_create_by!(title: title) { |l| l.color = color }
end

# 2. Usuário dedicado do bot
user = User.find_by(email: bot_email)
unless user
  user = User.new(name: 'Zapin (bot)', email: bot_email,
                  password: SecureRandom.hex(24) + 'aA1!')
  user.skip_confirmation! if user.respond_to?(:skip_confirmation!)
  user.save!
end
au = AccountUser.find_or_initialize_by(account_id: acc.id, user_id: user.id)
au.role = :administrator
au.save!

# 3. Webhook conta → gateway
url = "http://azapfy-bot:8080/webhook?token=#{token}"
webhook = acc.webhooks.find_or_initialize_by(url: url)
webhook.subscriptions = %w[message_created conversation_updated]
webhook.save!
# Remove webhooks antigos do bot (ex.: token rotacionado) — nunca os de outros
acc.webhooks.where('url LIKE ?', 'http://azapfy-bot:%').where.not(id: webhook.id).destroy_all

# 4. Conversa nova da caixa → fila-bot
rule = acc.automation_rules.find_or_initialize_by(name: 'Fila do bot (Zapin)')
rule.event_name = 'conversation_created'
rule.description = "Conversas novas da caixa #{inbox.name} entram na fila-bot"
rule.conditions = [{ 'attribute_key' => 'inbox_id', 'filter_operator' => 'equal_to',
                     'values' => [inbox.id] }]
rule.actions = [{ 'action_name' => 'add_label', 'action_params' => ['fila-bot'] }]
rule.active = true
rule.save!

puts "SETUP_OK conta=#{acc.id} caixa=#{inbox.id}(#{inbox.name}) " \
     "labels=#{acc.labels.pluck(:title).join(',')} webhook_id=#{webhook.id} " \
     "rule_id=#{rule.id} bot_user_id=#{user.id}"
