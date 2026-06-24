// Package identity implementa o gate de identidade no edge: resolve quem está
// falando (telefone → base própria → pedir login → Mongo → confirmar um dado)
// ANTES de qualquer chamada ao cérebro. O agente só roda em sessão autenticada.
package identity

import (
	"context"
	"encoding/json"
	"log/slog"
	"strings"
	"time"

	"bot-azapfy/internal/mongo"
	"bot-azapfy/internal/store"
)

// UserRepo é a dependência de lookup no Mongo (satisfeita por *mongo.Repo).
type UserRepo interface {
	BuscarPorLogin(ctx context.Context, login string) (mongo.UsuarioDoc, bool, error)
}

// Acao é a decisão do gate para o orquestrador (engine) executar no Chatwoot.
type Acao string

const (
	AcaoPerguntar    Acao = "perguntar"     // enviar Reply e aguardar a próxima mensagem
	AcaoSaudar       Acao = "saudar"        // recém-identificado: enviar Reply (saudação), NÃO encaminhar
	AcaoEncaminhar   Acao = "encaminhar"    // identidade pronta: encaminhar a mensagem ao cérebro (Perfil != nil)
	AcaoRotearHumano Acao = "rotear_humano" // desistiu da identificação: enviar Reply e rotear p/ humano
	AcaoIgnorar      Acao = "ignorar"       // nada a fazer (ex.: já roteado p/ humano)
)

// Resultado é a saída de Process.
type Resultado struct {
	Acao   Acao
	Reply  string        // mensagem ao usuário (perguntar/saudar/rotear)
	Perfil *mongo.Perfil // preenchido em AcaoEncaminhar
}

// gateData é o JSON de trabalho persistido em store.GateState.Data. ConfirmValue
// é transitório: some quando a identidade é confirmada (não vai para o cache).
type gateData struct {
	Login        string        `json:"login,omitempty"`
	Tentativas   int           `json:"tentativas,omitempty"`
	Perfil       *mongo.Perfil `json:"perfil,omitempty"`
	ConfirmField string        `json:"confirm_field,omitempty"`
	ConfirmValue string        `json:"confirm_value,omitempty"`
}

// Mensagens do gate.
const (
	msgPedirLogin            = "Olá! Para te atender, qual é o seu login no sistema Azapfy?"
	msgLoginNaoEncontrado    = "Não encontrei esse login. Pode conferir e enviar novamente?"
	msgFalhaLogin            = "Não consegui localizar seu login. Vou te transferir para um atendente humano."
	msgSemAcesso             = "Seu acesso está inativo no sistema. Vou te transferir para um atendente humano."
	msgErroTemporario        = "Tive um problema ao consultar o sistema agora. Pode tentar novamente em instantes?"
	msgConfirmacaoNaoConfere = "Esse dado não confere com o cadastro. Pode informar novamente?"
	msgFalhaConfirmacao      = "Não consegui confirmar sua identidade. Vou te transferir para um atendente humano."
)

// Gate resolve a identidade por conversa.
type Gate struct {
	store         store.Store
	repo          UserRepo
	confirmField  string // "email" (default) | "nome"
	maxTentativas int
	ttl           time.Duration
	log           *slog.Logger
}

// New constrói o gate.
func New(st store.Store, repo UserRepo, confirmField string, maxTentativas int, ttl time.Duration, log *slog.Logger) *Gate {
	if log == nil {
		log = slog.Default()
	}
	if maxTentativas <= 0 {
		maxTentativas = 3
	}
	if confirmField != "nome" {
		confirmField = "email"
	}
	return &Gate{store: st, repo: repo, confirmField: confirmField, maxTentativas: maxTentativas, ttl: ttl, log: log}
}

// Process avança a máquina de estados do gate para uma mensagem do usuário.
func (g *Gate) Process(ctx context.Context, convID int64, phone, mensagem string) Resultado {
	gs, err := g.store.GetGate(ctx, convID)
	if err != nil {
		g.log.Error("getGate", "conversation_id", convID, "err", err)
	}
	state := store.GateNovo
	var gd gateData
	if gs != nil {
		state = gs.State
		gd = decodeGate(gs.Data)
	}

	switch state {
	case store.GateIdentificado:
		if gd.Perfil != nil {
			return Resultado{Acao: AcaoEncaminhar, Perfil: gd.Perfil}
		}
		return g.iniciar(ctx, convID, phone)
	case store.GateFalha:
		return Resultado{Acao: AcaoIgnorar}
	case store.GateAguardLogin:
		return g.tratarLogin(ctx, convID, phone, mensagem, gd)
	case store.GateAguardConfirm:
		return g.tratarConfirmacao(ctx, convID, phone, mensagem, gd)
	default: // novo
		if p := g.cacheHit(ctx, phone); p != nil {
			g.salvarGate(ctx, convID, store.GateIdentificado, gateData{Perfil: p})
			g.log.Info("identidade via cache (base própria)", "conversation_id", convID, "login", p.Login)
			return Resultado{Acao: AcaoEncaminhar, Perfil: p}
		}
		return g.iniciar(ctx, convID, phone)
	}
}

// cacheHit devolve o perfil em cache para o telefone, se válido.
func (g *Gate) cacheHit(ctx context.Context, phone string) *mongo.Perfil {
	if phone == "" {
		return nil
	}
	ci, err := g.store.GetIdentity(ctx, phone)
	if err != nil {
		g.log.Error("getIdentity", "err", err)
		return nil
	}
	if ci == nil {
		return nil
	}
	var p mongo.Perfil
	if json.Unmarshal([]byte(ci.Perfil), &p) != nil || !p.Encontrado {
		return nil
	}
	return &p
}

func (g *Gate) iniciar(ctx context.Context, convID int64, phone string) Resultado {
	g.salvarGate(ctx, convID, store.GateAguardLogin, gateData{})
	return Resultado{Acao: AcaoPerguntar, Reply: msgPedirLogin}
}

func (g *Gate) tratarLogin(ctx context.Context, convID int64, phone, mensagem string, gd gateData) Resultado {
	login := strings.TrimSpace(mensagem)
	if login == "" {
		return Resultado{Acao: AcaoPerguntar, Reply: msgPedirLogin}
	}

	doc, found, err := g.repo.BuscarPorLogin(ctx, login)
	if err != nil {
		g.log.Error("buscarPorLogin", "conversation_id", convID, "err", err)
		return Resultado{Acao: AcaoPerguntar, Reply: msgErroTemporario}
	}
	if !found {
		gd.Tentativas++
		if gd.Tentativas >= g.maxTentativas {
			g.salvarGate(ctx, convID, store.GateFalha, gateData{})
			return Resultado{Acao: AcaoRotearHumano, Reply: msgFalhaLogin}
		}
		g.salvarGate(ctx, convID, store.GateAguardLogin, gd)
		return Resultado{Acao: AcaoPerguntar, Reply: msgLoginNaoEncontrado}
	}

	perfil := mongo.Projetar(doc)
	if !perfil.TemEmpresaAtiva() {
		g.salvarGate(ctx, convID, store.GateFalha, gateData{})
		g.log.Info("login sem empresa ativa", "conversation_id", convID, "login", login)
		return Resultado{Acao: AcaoRotearHumano, Reply: msgSemAcesso}
	}

	expected, pergunta := g.alvoConfirmacao(doc)
	if expected == "" {
		// Sem dado para confirmar: identifica direto (não há como confirmar).
		g.log.Warn("sem dado de confirmação no cadastro; identificando sem confirmar", "conversation_id", convID)
		return g.identificar(ctx, convID, phone, &perfil)
	}
	ngd := gateData{
		Login:        login,
		Perfil:       &perfil,
		ConfirmField: g.confirmField,
		ConfirmValue: normalizar(expected),
	}
	g.salvarGate(ctx, convID, store.GateAguardConfirm, ngd)
	g.log.Info("login resolvido, pedindo confirmação", "conversation_id", convID, "login", login, "confirm_field", g.confirmField)
	return Resultado{Acao: AcaoPerguntar, Reply: pergunta}
}

func (g *Gate) tratarConfirmacao(ctx context.Context, convID int64, phone, mensagem string, gd gateData) Resultado {
	if got := normalizar(mensagem); got != "" && got == gd.ConfirmValue {
		return g.identificar(ctx, convID, phone, gd.Perfil)
	}
	gd.Tentativas++
	if gd.Tentativas >= g.maxTentativas {
		g.salvarGate(ctx, convID, store.GateFalha, gateData{})
		return Resultado{Acao: AcaoRotearHumano, Reply: msgFalhaConfirmacao}
	}
	g.salvarGate(ctx, convID, store.GateAguardConfirm, gd)
	return Resultado{Acao: AcaoPerguntar, Reply: msgConfirmacaoNaoConfere}
}

// identificar grava o perfil na base própria (cache c/ TTL), marca o gate como
// identificado e devolve a saudação. O dado de confirmação NÃO é persistido.
func (g *Gate) identificar(ctx context.Context, convID int64, phone string, perfil *mongo.Perfil) Resultado {
	if phone != "" && perfil != nil {
		if b, err := json.Marshal(perfil); err == nil {
			_ = g.store.PutIdentity(ctx, &store.CachedIdentity{
				Phone:     phone,
				Login:     perfil.Login,
				Perfil:    string(b),
				ExpiresAt: time.Now().Add(g.ttl),
			})
		}
	}
	g.salvarGate(ctx, convID, store.GateIdentificado, gateData{Perfil: perfil})
	g.log.Info("identidade confirmada", "conversation_id", convID, "login", perfil.Login)
	return Resultado{Acao: AcaoSaudar, Reply: saudacao(perfil)}
}

// alvoConfirmacao devolve o valor esperado e a pergunta, conforme ConfirmField.
func (g *Gate) alvoConfirmacao(doc mongo.UsuarioDoc) (valor, pergunta string) {
	if g.confirmField == "nome" {
		return doc.Nome, "Para confirmar sua identidade, qual é o seu nome completo cadastrado?"
	}
	return doc.Email, "Para confirmar sua identidade, qual é o e-mail cadastrado na sua conta?"
}

func (g *Gate) salvarGate(ctx context.Context, convID int64, state string, gd gateData) {
	b, _ := json.Marshal(gd)
	if err := g.store.SetGate(ctx, &store.GateState{ConversationID: convID, State: state, Data: string(b)}); err != nil {
		g.log.Error("setGate", "conversation_id", convID, "err", err)
	}
}

func decodeGate(s string) gateData {
	var gd gateData
	if s != "" {
		_ = json.Unmarshal([]byte(s), &gd)
	}
	return gd
}

// normalizar deixa a comparação de confirmação tolerante a caixa e espaços.
func normalizar(s string) string {
	return strings.Join(strings.Fields(strings.ToLower(strings.TrimSpace(s))), " ")
}

func saudacao(p *mongo.Perfil) string {
	nome := "tudo certo"
	if p != nil && p.Nome != "" {
		nome = p.Nome
	}
	return "Tudo certo, " + nome + "! Como posso te ajudar com o suporte Azapfy?"
}
