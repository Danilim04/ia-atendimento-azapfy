// Package config carrega a configuração da aplicação a partir de variáveis de
// ambiente (com suporte opcional a um arquivo .env).
package config

import (
	"bufio"
	"fmt"
	"os"
	"strings"
	"time"
)

// Config agrega todos os parâmetros de execução do gateway.
type Config struct {
	Port          string
	LogLevel      string // debug | info | warn | error
	PublicBaseURL string // URL pública (só para montar a URL do webhook nos logs)

	ChatwootBaseURL   string
	ChatwootAccountID string
	ChatwootAPIToken  string
	WebhookSecret     string
	WebhookToken      string // token na query da URL do webhook (?token=...)

	DBPath string

	// LabelBot: só processa conversas com esta etiqueta (gate de borda). Vazio =
	// processa toda mensagem de entrada do contato. LabelHumano: fila para onde a
	// conversa é roteada quando a identificação falha.
	LabelBot    string
	LabelHumano string

	// Mongo da Azapfy (lookup de usuário por login — a 1ª "tool").
	MongoURI        string
	MongoDB         string
	MongoCollection string
	MongoTimeout    time.Duration

	// Brain: serviço Python que roda o agente (Contrato A, POST /chat).
	BrainBaseURL string
	BrainTimeout time.Duration

	// Identidade / gate.
	ConfirmField  string        // dado pedido na confirmação: "email" (default) | "nome"
	MaxTentativas int           // tentativas de login/confirmação antes de rotear p/ humano
	IdentityTTL   time.Duration // validade do cache telefone→perfil (base própria)
}

// Load lê o .env (se existir) e em seguida o ambiente, validando os obrigatórios.
func Load() (*Config, error) {
	_ = loadDotEnv(".env")

	cfg := &Config{
		Port:              getenv("PORT", "8080"),
		LogLevel:          strings.ToLower(getenv("LOG_LEVEL", "info")),
		PublicBaseURL:     strings.TrimRight(getenv("PUBLIC_BASE_URL", ""), "/"),
		ChatwootBaseURL:   strings.TrimRight(getenv("CHATWOOT_BASE_URL", ""), "/"),
		ChatwootAccountID: getenv("CHATWOOT_ACCOUNT_ID", ""),
		ChatwootAPIToken:  getenv("CHATWOOT_API_TOKEN", ""),
		WebhookSecret:     getenv("WEBHOOK_SECRET", ""),
		WebhookToken:      getenv("WEBHOOK_TOKEN", ""),
		DBPath:            getenv("DB_PATH", "gateway.db"),
		LabelBot:          getenv("LABEL_BOT", "fila-bot"),
		LabelHumano:       getenv("LABEL_HUMANO", "fila-humano"),
		MongoURI:          getenv("MONGO_URI", ""),
		MongoDB:           getenv("MONGO_DB", "azapfy"),
		MongoCollection:   getenv("MONGO_COLLECTION", "users"),
		BrainBaseURL:      strings.TrimRight(getenv("BRAIN_BASE_URL", "http://localhost:8001"), "/"),
		ConfirmField:      strings.ToLower(getenv("CONFIRM_FIELD", "email")),
		MaxTentativas:     getenvInt("MAX_TENTATIVAS", 3),
	}

	var err error
	if cfg.MongoTimeout, err = parseDuration(getenv("MONGO_TIMEOUT", "8s")); err != nil {
		return nil, fmt.Errorf("MONGO_TIMEOUT inválido: %w", err)
	}
	if cfg.BrainTimeout, err = parseDuration(getenv("BRAIN_TIMEOUT", "60s")); err != nil {
		return nil, fmt.Errorf("BRAIN_TIMEOUT inválido: %w", err)
	}
	if cfg.IdentityTTL, err = parseDuration(getenv("IDENTITY_TTL", "24h")); err != nil {
		return nil, fmt.Errorf("IDENTITY_TTL inválido: %w", err)
	}

	var missing []string
	if cfg.ChatwootBaseURL == "" {
		missing = append(missing, "CHATWOOT_BASE_URL")
	}
	if cfg.ChatwootAccountID == "" {
		missing = append(missing, "CHATWOOT_ACCOUNT_ID")
	}
	if cfg.ChatwootAPIToken == "" {
		missing = append(missing, "CHATWOOT_API_TOKEN")
	}
	if cfg.MongoURI == "" {
		missing = append(missing, "MONGO_URI")
	}
	if len(missing) > 0 {
		return nil, fmt.Errorf("variáveis obrigatórias ausentes: %s", strings.Join(missing, ", "))
	}

	return cfg, nil
}

func getenv(key, def string) string {
	if v, ok := os.LookupEnv(key); ok && v != "" {
		return v
	}
	return def
}

func getenvInt(key string, def int) int {
	if v, ok := os.LookupEnv(key); ok && v != "" {
		var n int
		if _, err := fmt.Sscanf(v, "%d", &n); err == nil {
			return n
		}
	}
	return def
}

func parseDuration(s string) (time.Duration, error) {
	if s == "" {
		return 0, nil
	}
	return time.ParseDuration(s)
}

// loadDotEnv faz um carregamento mínimo de um arquivo .env (KEY=VALUE por linha,
// linhas iniciadas por # são ignoradas). Não sobrescreve variáveis já definidas.
func loadDotEnv(path string) error {
	f, err := os.Open(path)
	if err != nil {
		return err
	}
	defer f.Close()

	sc := bufio.NewScanner(f)
	for sc.Scan() {
		line := strings.TrimSpace(sc.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		key, val, ok := strings.Cut(line, "=")
		if !ok {
			continue
		}
		key = strings.TrimSpace(key)
		val = strings.Trim(strings.TrimSpace(val), `"'`)
		if _, exists := os.LookupEnv(key); !exists {
			_ = os.Setenv(key, val)
		}
	}
	return sc.Err()
}
