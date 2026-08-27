package engine

import (
	"strings"
	"testing"
)

func TestStripAssinatura(t *testing.T) {
	casos := []struct{ in, want string }{
		{"**Claude:**\n105.966.936.64", "105.966.936.64"},
		{"*Fulano de Tal:*\nmeu email é x@y.com", "meu email é x@y.com"},
		{"sem assinatura nenhuma", "sem assinatura nenhuma"},
		{"**negrito** no meio não é assinatura", "**negrito** no meio não é assinatura"},
		{"  **Bot:**  \noi", "oi"},
	}
	for _, c := range casos {
		if got := StripAssinatura(c.in); got != c.want {
			t.Errorf("StripAssinatura(%q) = %q, esperava %q", c.in, got, c.want)
		}
	}
}

func TestFormatWhatsApp(t *testing.T) {
	casos := []struct{ in, want string }{
		{"**Zapin (bot):** resposta", "*Zapin (bot):* resposta"},
		{"# Título\ntexto", "*Título*\ntexto"},
		{"veja [o chamado](https://x.com/t/1)", "veja o chamado: https://x.com/t/1"},
		{"[https://x.com](https://x.com)", "https://x.com"},
		{"texto simples", "texto simples"},
	}
	for _, c := range casos {
		if got := FormatWhatsApp(c.in); got != c.want {
			t.Errorf("FormatWhatsApp(%q) = %q, esperava %q", c.in, got, c.want)
		}
	}
}

func TestQuebrarMensagemRespeitaLimiteEParagrafos(t *testing.T) {
	texto := strings.Repeat("frase curta. ", 30) + "\n\n" + strings.Repeat("outra frase. ", 30)
	partes := QuebrarMensagem(texto, 200)
	if len(partes) < 2 {
		t.Fatalf("esperava várias partes, veio %d", len(partes))
	}
	for i, p := range partes {
		if n := len([]rune(p)); n > 200 {
			t.Errorf("parte %d tem %d runas (> 200)", i, n)
		}
		if strings.TrimSpace(p) == "" {
			t.Errorf("parte %d vazia", i)
		}
	}
	// Conteúdo preservado (sem perder palavras).
	junto := strings.Join(partes, " ")
	if !strings.Contains(junto, "frase curta.") || !strings.Contains(junto, "outra frase.") {
		t.Error("conteúdo perdido na quebra")
	}
}

func TestQuebrarMensagemSemLimite(t *testing.T) {
	if partes := QuebrarMensagem("abc", 0); len(partes) != 1 || partes[0] != "abc" {
		t.Fatalf("max=0 deveria devolver o texto inteiro: %v", partes)
	}
	if partes := QuebrarMensagem("   ", 100); partes != nil {
		t.Fatalf("texto vazio deveria devolver nil: %v", partes)
	}
}
