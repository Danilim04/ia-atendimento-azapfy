// Package engine orquestra: webhook → gate de identidade → (quando
// identificado) cérebro Python → resposta no Chatwoot.
package engine

import (
	"context"
	"log/slog"
	"strconv"
	"strings"

	"bot-azapfy/internal/brain"
	"bot-azapfy/internal/chatwoot"
	"bot-azapfy/internal/config"
	"bot-azapfy/internal/identity"
)

// Engine reúne as dependências do orquestrador.
type Engine struct {
	cfg   *config.Config
	cw    *chatwoot.Client
	gate  *identity.Gate
	brain *brain.Client
	log   *slog.Logger
}

// New constrói a engine.
func New(cfg *config.Config, cw *chatwoot.Client, gate *identity.Gate, brainClient *brain.Client, log *slog.Logger) *Engine {
	if log == nil {
		log = slog.Default()
	}
	return &Engine{cfg: cfg, cw: cw, gate: gate, brain: brainClient, log: log}
}

// HandleMessageCreated trata mensagens de entrada do cliente.
func (e *Engine) HandleMessageCreated(ctx context.Context, msg *chatwoot.MessageCreated) {
	convID := msg.Conversation.ID

	// Filtro de borda: só mensagens de entrada, do contato, não privadas.
	if !msg.MessageType.IsIncoming() || !msg.Sender.IsContact() || msg.Private {
		return
	}
	// Gate de etiqueta (opcional): só atua na fila do bot. Vazio = processa tudo.
	if e.cfg.LabelBot != "" && !chatwoot.HasLabel(msg.Conversation.Labels, e.cfg.LabelBot) {
		e.log.Info("mensagem ignorada: conversa sem a etiqueta do bot",
			"conversation_id", convID, "label_bot", e.cfg.LabelBot)
		return
	}

	content := strings.TrimSpace(msg.Content)
	if content == "" {
		return
	}
	phone := msg.Phone()

	res := e.gate.Process(ctx, convID, phone, content)
	e.log.Info("gate", "conversation_id", convID, "acao", res.Acao)

	switch res.Acao {
	case identity.AcaoPerguntar, identity.AcaoSaudar:
		e.send(ctx, convID, res.Reply)
	case identity.AcaoRotearHumano:
		e.send(ctx, convID, res.Reply)
		e.rotearHumano(ctx, &msg.Conversation)
	case identity.AcaoEncaminhar:
		e.encaminhar(ctx, &msg.Conversation, phone, content, res)
	case identity.AcaoIgnorar:
		// já roteado para humano — nada a fazer.
	}
}

// HandleConversationUpdated: nesta fase a identificação é dirigida pela primeira
// mensagem do cliente, então mudanças de etiqueta só são logadas.
func (e *Engine) HandleConversationUpdated(ctx context.Context, ev *chatwoot.ConversationUpdated) {
	e.log.Debug("conversation_updated (sem ação nesta fase)", "conversation_id", ev.Conversation.ID)
}

func (e *Engine) encaminhar(ctx context.Context, conv *chatwoot.Conversation, phone, content string, res identity.Resultado) {
	var login string
	if res.Perfil != nil {
		login = res.Perfil.Login
	}
	e.log.Debug("encaminhando ao cérebro",
		"conversation_id", conv.ID, "telefone", phone, "login", login, "mensagem", content)

	resp, err := e.brain.Chat(ctx, brain.ChatRequest{
		ConversationID: strconv.FormatInt(conv.ID, 10),
		Canal:          "whatsapp",
		Mensagem:       content,
		Identidade:     res.Perfil,
		Telefone:       phone,
	})
	if err != nil {
		e.log.Error("chamada ao cérebro", "conversation_id", conv.ID, "err", err)
		e.send(ctx, conv.ID, "Tive um problema técnico ao processar sua mensagem. Pode tentar novamente em instantes?")
		return
	}
	reply := strings.TrimSpace(resp.Reply)
	if reply == "" {
		reply = "Desculpe, não consegui formular uma resposta agora. Pode reformular?"
	}
	e.log.Debug("resposta do cérebro",
		"conversation_id", conv.ID, "fontes", resp.Fontes, "reply", reply)
	e.send(ctx, conv.ID, reply)
}

func (e *Engine) rotearHumano(ctx context.Context, conv *chatwoot.Conversation) {
	if e.cfg.LabelHumano == "" {
		return
	}
	newLabels := chatwoot.ReplaceLabel(conv.Labels, e.cfg.LabelBot, e.cfg.LabelHumano)
	if err := e.cw.SetLabels(ctx, conv.ID, newLabels); err != nil {
		e.log.Error("rotear para humano", "conversation_id", conv.ID, "err", err)
	}
}

func (e *Engine) send(ctx context.Context, convID int64, content string) {
	if content == "" {
		return
	}
	if err := e.cw.SendMessage(ctx, convID, content, false); err != nil {
		e.log.Error("enviar mensagem", "conversation_id", convID, "err", err)
	}
}
