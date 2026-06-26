package identity

import (
	"context"
	"errors"
	"path/filepath"
	"testing"
	"time"

	"bot-azapfy/internal/mongo"
	"bot-azapfy/internal/store"
)

type fakeRepo struct {
	docs map[string]mongo.UsuarioDoc
}

func (f fakeRepo) BuscarPorLogin(_ context.Context, login string) (mongo.UsuarioDoc, bool, error) {
	d, ok := f.docs[login]
	return d, ok, nil
}

// fakeExtractor simula o cérebro: devolve, para uma mensagem, o login que ele
// "extraiu". `chamado` registra se foi acionado (p/ checar que o determinístico
// não cai no fallback à toa). `err` força o caminho de indisponibilidade.
type fakeExtractor struct {
	respostas map[string]string
	err       error
	chamado   *bool
}

func (f fakeExtractor) ExtrairLogin(_ context.Context, mensagem string) (string, error) {
	if f.chamado != nil {
		*f.chamado = true
	}
	if f.err != nil {
		return "", f.err
	}
	return f.respostas[mensagem], nil
}

func docDaniel() mongo.UsuarioDoc {
	return mongo.UsuarioDoc{
		Login: "10596693664",
		Nome:  "Daniel Ferraz",
		Email: "daniel.ferraz@azapfy.com.br",
		Grupos: map[string]mongo.GrupoDoc{
			"AZAPERS": {
				Ativo: true, GrupoUser: "COLABORADOR", Area: "SAC",
				Bases: map[string]mongo.BaseDoc{
					"MATRIZ": {Nome: "MATRIZ", Sigla: "MAT", Modulos: map[string]mongo.ModuloDoc{
						"pesquisa":     {Ativo: true},
						"rastreamento": {Ativo: true},
					}},
				},
			},
			"AZAPFY": {Ativo: false}, // inativo: não deve entrar no perfil
		},
	}
}

func newGate(t *testing.T, repo UserRepo) (*Gate, store.Store) {
	t.Helper()
	return newGateComExtractor(t, repo, nil)
}

func newGateComExtractor(t *testing.T, repo UserRepo, extractor LoginExtractor) (*Gate, store.Store) {
	t.Helper()
	st, err := store.NewSQLite(filepath.Join(t.TempDir(), "gate.db"))
	if err != nil {
		t.Fatalf("store: %v", err)
	}
	t.Cleanup(func() { _ = st.Close() })
	return New(st, repo, "email", 3, time.Hour, extractor, nil), st
}

func TestGateFluxoFeliz(t *testing.T) {
	g, _ := newGate(t, fakeRepo{docs: map[string]mongo.UsuarioDoc{"10596693664": docDaniel()}})
	ctx := context.Background()
	const conv = int64(1)
	const phone = "5511999990001"

	if r := g.Process(ctx, conv, phone, "oi"); r.Acao != AcaoPerguntar {
		t.Fatalf("1º turno: esperava perguntar (login), veio %q", r.Acao)
	}
	if r := g.Process(ctx, conv, phone, "10596693664"); r.Acao != AcaoPerguntar {
		t.Fatalf("após login válido: esperava perguntar (confirmação), veio %q", r.Acao)
	}
	if r := g.Process(ctx, conv, phone, "errado@x.com"); r.Acao != AcaoPerguntar {
		t.Fatalf("confirmação errada: esperava perguntar de novo, veio %q", r.Acao)
	}
	// e-mail certo (caixa/espacos diferentes) → saudar
	r := g.Process(ctx, conv, phone, "  Daniel.Ferraz@AZAPFY.com.br ")
	if r.Acao != AcaoSaudar {
		t.Fatalf("confirmação certa: esperava saudar, veio %q", r.Acao)
	}
	// próxima mensagem → encaminhar ao cérebro, com perfil escopado
	r = g.Process(ctx, conv, phone, "como rastreio a NF 1?")
	if r.Acao != AcaoEncaminhar || r.Perfil == nil {
		t.Fatalf("identificado: esperava encaminhar com perfil, veio %q perfil=%v", r.Acao, r.Perfil)
	}
	if len(r.Perfil.Empresas) != 1 || r.Perfil.Empresas[0].GrupoEmpresa != "AZAPERS" {
		t.Fatalf("perfil deve conter só AZAPERS (AZAPFY inativo): %+v", r.Perfil.Empresas)
	}
}

func TestGateCacheHitNovaConversa(t *testing.T) {
	g, _ := newGate(t, fakeRepo{docs: map[string]mongo.UsuarioDoc{"10596693664": docDaniel()}})
	ctx := context.Background()
	const phone = "5511999990001"

	// Identifica na conversa 1.
	g.Process(ctx, 1, phone, "oi")
	g.Process(ctx, 1, phone, "10596693664")
	g.Process(ctx, 1, phone, "daniel.ferraz@azapfy.com.br")

	// Nova conversa, MESMO telefone → encaminha direto (base própria).
	r := g.Process(ctx, 2, phone, "tenho uma dúvida")
	if r.Acao != AcaoEncaminhar || r.Perfil == nil {
		t.Fatalf("cache hit: esperava encaminhar com perfil, veio %q perfil=%v", r.Acao, r.Perfil)
	}
}

func TestGateLoginNaoEncontradoRoteiaHumano(t *testing.T) {
	g, _ := newGate(t, fakeRepo{docs: map[string]mongo.UsuarioDoc{}})
	ctx := context.Background()
	const conv = int64(7)
	const phone = "5511000000000"

	g.Process(ctx, conv, phone, "oi") // pede login
	if r := g.Process(ctx, conv, phone, "naoexiste"); r.Acao != AcaoPerguntar {
		t.Fatalf("tentativa 1: esperava perguntar de novo, veio %q", r.Acao)
	}
	if r := g.Process(ctx, conv, phone, "naoexiste"); r.Acao != AcaoPerguntar {
		t.Fatalf("tentativa 2: esperava perguntar de novo, veio %q", r.Acao)
	}
	if r := g.Process(ctx, conv, phone, "naoexiste"); r.Acao != AcaoRotearHumano {
		t.Fatalf("tentativa 3 (máx): esperava rotear humano, veio %q", r.Acao)
	}
	// Depois de falhar, novas mensagens são ignoradas (já roteado).
	if r := g.Process(ctx, conv, phone, "oi de novo"); r.Acao != AcaoIgnorar {
		t.Fatalf("pós-falha: esperava ignorar, veio %q", r.Acao)
	}
}

func TestGateLoginCpfFormatadoNormaliza(t *testing.T) {
	// Banco guarda só dígitos ("10596693664"); cliente manda CPF pontuado.
	// Deve resolver SEM acionar a IA (normalização determinística de CPF/CNPJ).
	chamado := false
	repo := fakeRepo{docs: map[string]mongo.UsuarioDoc{"10596693664": docDaniel()}}
	g, _ := newGateComExtractor(t, repo, fakeExtractor{chamado: &chamado})
	ctx := context.Background()
	const conv = int64(11)
	const phone = "5511999990002"

	g.Process(ctx, conv, phone, "oi") // pede login
	if r := g.Process(ctx, conv, phone, "105.966.936-64"); r.Acao != AcaoPerguntar {
		t.Fatalf("CPF formatado: esperava perguntar (confirmação), veio %q", r.Acao)
	}
	if chamado {
		t.Fatal("não deveria chamar a IA quando o CPF formatado já normaliza")
	}
}

func TestGateLoginViaIAFallback(t *testing.T) {
	// Login não-numérico embutido em frase: determinístico falha, IA extrai.
	doc := docDaniel()
	doc.Login = "joao"
	repo := fakeRepo{docs: map[string]mongo.UsuarioDoc{"joao": doc}}
	extractor := fakeExtractor{respostas: map[string]string{"meu login é joao": "joao"}}
	g, _ := newGateComExtractor(t, repo, extractor)
	ctx := context.Background()
	const conv = int64(12)
	const phone = "5511999990003"

	g.Process(ctx, conv, phone, "oi") // pede login
	if r := g.Process(ctx, conv, phone, "meu login é joao"); r.Acao != AcaoPerguntar {
		t.Fatalf("login via IA: esperava perguntar (confirmação), veio %q", r.Acao)
	}
}

func TestGateExtractorIndisponivelNaoQuebra(t *testing.T) {
	// IA fora do ar + login não resolvível deterministicamente → trata como
	// não encontrado (pede de novo), sem erro fatal.
	repo := fakeRepo{docs: map[string]mongo.UsuarioDoc{"joao": docDaniel()}}
	extractor := fakeExtractor{err: errors.New("brain offline")}
	g, _ := newGateComExtractor(t, repo, extractor)
	ctx := context.Background()
	const conv = int64(13)

	g.Process(ctx, conv, "5511999990004", "oi")
	if r := g.Process(ctx, conv, "5511999990004", "meu login é joao"); r.Acao != AcaoPerguntar {
		t.Fatalf("IA indisponível: esperava perguntar de novo, veio %q", r.Acao)
	}
}

func TestGateLoginInativoRoteiaHumano(t *testing.T) {
	inativo := mongo.UsuarioDoc{
		Login: "999", Nome: "Fulano", Email: "f@x.com",
		Grupos: map[string]mongo.GrupoDoc{"AZAPFY": {Ativo: false}},
	}
	g, _ := newGate(t, fakeRepo{docs: map[string]mongo.UsuarioDoc{"999": inativo}})
	ctx := context.Background()
	const conv = int64(9)

	g.Process(ctx, conv, "5511222220000", "oi")
	r := g.Process(ctx, conv, "5511222220000", "999")
	if r.Acao != AcaoRotearHumano {
		t.Fatalf("login sem empresa ativa: esperava rotear humano, veio %q", r.Acao)
	}
}
