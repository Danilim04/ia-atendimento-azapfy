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

// LoginExtractor extrai o identificador (login) de uma mensagem em linguagem
// natural — fallback quando a normalização determinística não casa nenhum
// usuário (ex.: "meu login é joao", "pode usar o email joao@x.com").
// Satisfeito pelo cérebro Python (LLM com saída JSON estruturada).
//
// Importante (anti-injection): o valor devolvido é apenas um CANDIDATO. A
// autorização continua sendo o lookup no Mongo + a confirmação de um dado
// (email/nome). O LLM nunca concede acesso; no pior caso devolve um login que
// não existe ou que falha na confirmação.
type LoginExtractor interface {
	ExtrairLogin(ctx context.Context, mensagem string) (string, error)
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

// nomeAssistente é o nome com que o bot se apresenta nas saudações.
// Trocar aqui muda o nome em todas as mensagens.
const nomeAssistente = "Zapin"

// Mensagens do gate — tom acolhedor e mineiro, mas sempre claras sobre o passo.
const (
	msgPedirLogin            = "Uai, oi sô! 😄 Eu sô o " + nomeAssistente + ", atendente virtual da Azapfy, e vô cuidar de ocê hoje. Pra eu te atender direitinho, cê me passa o seu login no sistema?"
	msgLoginNaoEncontrado    = "Ô sô, num achei esse login aqui não. Dá uma conferidinha e me manda de novo, ó? 🙏"
	msgFalhaLogin            = "Pó, num consegui achar seu login de jeito nenhum. Mas fica sussa que eu já vô te passar pra um atendente da equipe, tá bão? 🤝"
	msgSemAcesso             = "Ó, parece que seu acesso tá inativo no sistema, viu sô. Vô te encaminhar pra um atendente resolver isso contigo num instantinho. 🤝"
	msgErroTemporario        = "Vixe, deu um trem aqui no sistema agora e num consegui consultar. Me dá um tempim e tenta de novo, ó? 🙏"
	msgConfirmacaoNaoConfere = "Hmm, esse dado num bateu com o que tenho no cadastro não, uai. Cê pode me mandar de novo, sô?"
	msgFalhaConfirmacao      = "Num consegui confirmar quem é ocê, mas relaxa! Vô te transferir pra um atendente nosso pra cuidar de ocê melhor, tá? 🤝"
)

// Gate resolve a identidade por conversa.
type Gate struct {
	store         store.Store
	repo          UserRepo
	extractor     LoginExtractor // opcional: fallback de extração de login via IA
	confirmField  string         // "email" (default) | "nome"
	maxTentativas int
	ttl           time.Duration
	log           *slog.Logger
}

// New constrói o gate. `extractor` é opcional (nil = sem fallback de IA: só a
// normalização determinística resolve o login).
func New(st store.Store, repo UserRepo, confirmField string, maxTentativas int, ttl time.Duration, extractor LoginExtractor, log *slog.Logger) *Gate {
	if log == nil {
		log = slog.Default()
	}
	if maxTentativas <= 0 {
		maxTentativas = 3
	}
	if confirmField != "nome" {
		confirmField = "email"
	}
	return &Gate{store: st, repo: repo, extractor: extractor, confirmField: confirmField, maxTentativas: maxTentativas, ttl: ttl, log: log}
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
	if strings.TrimSpace(mensagem) == "" {
		return Resultado{Acao: AcaoPerguntar, Reply: msgPedirLogin}
	}

	doc, login, found, err := g.resolverLogin(ctx, convID, mensagem)
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
		return doc.Nome, "Ó, pra eu ter certeza que é ocê mesmo, me fala seu nome completo do cadastro, sô?"
	}
	return doc.Email, "Só pra confirmar que é ocê mesmo, qual é o e-mail que cê cadastrou na conta?"
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

// resolverLogin tenta identificar o usuário a partir da mensagem em duas
// etapas: (1) candidatos DETERMINÍSTICOS — a própria mensagem, sua versão em
// minúsculas e, quando ela é um CPF/CNPJ formatado puro, os dígitos; (2) se
// nada casar e houver extractor, pede à IA o login embutido na frase e tenta os
// candidatos dele. Devolve o doc, o login que casou e found.
//
// O lookup no Mongo é a validação real: candidatos que não existem simplesmente
// não casam (não há risco em tentar vários).
func (g *Gate) resolverLogin(ctx context.Context, convID int64, mensagem string) (mongo.UsuarioDoc, string, bool, error) {
	if doc, login, found, err := g.tentarCandidatos(ctx, mensagem); found || err != nil {
		return doc, login, found, err
	}

	if g.extractor == nil {
		return mongo.UsuarioDoc{}, "", false, nil
	}
	extraido, err := g.extractor.ExtrairLogin(ctx, mensagem)
	if err != nil {
		// Fail-soft: sem IA, seguimos só com o determinístico (já falhou) →
		// trata como não encontrado, e o usuário tenta de novo.
		g.log.Warn("extrator de login indisponível; seguindo sem fallback", "conversation_id", convID, "err", err)
		return mongo.UsuarioDoc{}, "", false, nil
	}
	if strings.TrimSpace(extraido) == "" {
		return mongo.UsuarioDoc{}, "", false, nil
	}
	g.log.Info("login extraído por IA", "conversation_id", convID, "login_extraido", extraido)
	return g.tentarCandidatos(ctx, extraido)
}

// tentarCandidatos busca no Mongo cada candidato derivado de `texto` na ordem,
// devolvendo o primeiro que existir.
func (g *Gate) tentarCandidatos(ctx context.Context, texto string) (mongo.UsuarioDoc, string, bool, error) {
	for _, c := range loginCandidatos(texto) {
		doc, found, err := g.repo.BuscarPorLogin(ctx, c)
		if err != nil {
			return mongo.UsuarioDoc{}, "", false, err
		}
		if found {
			return doc, c, true, nil
		}
	}
	return mongo.UsuarioDoc{}, "", false, nil
}

// loginCandidatos deriva, de um texto, as formas de login a tentar no Mongo:
// o texto cru (trim), sua versão minúscula e — só quando é um CPF/CNPJ
// formatado PURO — os dígitos. A versão só-dígitos é restrita a CPF/CNPJ puro
// de propósito: extrair dígitos de uma frase ("tenho 2 contas, login joao")
// casaria um usuário errado; frases ficam para o extractor (IA).
func loginCandidatos(texto string) []string {
	texto = strings.TrimSpace(texto)
	if texto == "" {
		return nil
	}
	seen := map[string]bool{}
	var out []string
	add := func(c string) {
		c = strings.TrimSpace(c)
		if c != "" && !seen[c] {
			seen[c] = true
			out = append(out, c)
		}
	}
	add(texto)
	add(strings.ToLower(texto))
	if d := cpfCnpjDigitos(texto); d != "" {
		add(d)
	}
	return out
}

// cpfCnpjDigitos devolve apenas os dígitos quando `s` é um CPF/CNPJ formatado
// puro (só dígitos e os separadores . - / e espaço). Se houver qualquer letra
// ou outro símbolo (logo, não é um CPF/CNPJ isolado), devolve "" — esse caso
// fica para o extractor de IA, evitando casar dígitos soltos de uma frase.
func cpfCnpjDigitos(s string) string {
	s = strings.TrimSpace(s)
	if s == "" {
		return ""
	}
	var digitos strings.Builder
	for _, r := range s {
		switch {
		case r >= '0' && r <= '9':
			digitos.WriteByte(byte(r))
		case r == '.' || r == '-' || r == '/' || r == ' ':
			// separador aceitável de CPF/CNPJ — ignora
		default:
			return "" // tem letra/outro símbolo → não é CPF/CNPJ puro
		}
	}
	return digitos.String()
}

// normalizar deixa a comparação de confirmação tolerante a caixa e espaços.
func normalizar(s string) string {
	return strings.Join(strings.Fields(strings.ToLower(strings.TrimSpace(s))), " ")
}

func saudacao(p *mongo.Perfil) string {
	if p != nil && p.Nome != "" {
		return "Que bão te ver por aqui, " + primeiroNome(p.Nome) + "! 😄 Aqui é o " +
			nomeAssistente + ", atendente virtual da Azapfy. Em que que eu posso te ajudar hoje, sô?"
	}
	return "Que bão te ver por aqui! 😄 Aqui é o " + nomeAssistente +
		", atendente virtual da Azapfy. Em que que eu posso te ajudar hoje, sô?"
}

// primeiroNome devolve só o primeiro nome — mais caloroso que o nome completo.
func primeiroNome(nome string) string {
	if campos := strings.Fields(nome); len(campos) > 0 {
		return campos[0]
	}
	return nome
}
