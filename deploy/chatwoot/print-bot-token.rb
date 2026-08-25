# Imprime o access token do usuário do bot. Consumido pela pipeline
# configure-chatwoot, que o grava como ESTADO da VM (.chatwoot-token) — o
# redirecionamento acontece na própria VM, o valor nunca sai dela.
user = User.find_by!(email: 'zapin-bot@azapfy.com.br')
puts user.access_token.token
