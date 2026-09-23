import { test, expect } from "@playwright/test";

test.describe("Gate 1 — 3 jornadas E2E", () => {
  test("Jornada 1: entender o dia em 5s — Agora mostra próximo, prioridade e alerta", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText("PRÓXIMO COMPROMISSO")).toBeVisible();
    await expect(page.getByText("Daily MedSyn — revisão sprint")).toBeVisible();
    await expect(page.getByText("PRIORIDADE ESSENCIAL")).toBeVisible();
    await expect(page.getByText("Finalizar slides demo MedSyn")).toBeVisible();
    await expect(page.getByText("ALERTA COM CONSEQUÊNCIA")).toBeVisible();
    // Prova de proveniência
    await page.getByRole("button", { name: /Ver por que isso importa/i }).click();
    await expect(page.getByText("PROVENIÊNCIA")).toBeVisible();
    await page.getByRole("button", { name: /Fechar/i }).click();
    // Navegação precisa ser visível em 5s de leitura — sem scroll excessivo
    await expect(page.getByText("Linha do tempo — hoje")).toBeVisible();
  });

  test("Jornada 2: resolver conflito sem alteração externa — Aprovações com 2 alternativas", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("link", { name: /Resolver conflito/i }).click();
    await expect(page).toHaveURL(/aprovacoes/);
    await expect(page.getByText("Mover Academia para 17h?")).toBeVisible();
    await expect(page.getByText("DIFF EM LINGUAGEM NATURAL")).toBeVisible();
    await expect(page.getByText("Antecipar academia para 17h")).toBeVisible();
    await expect(page.getByText("Manter academia 18h mas encurtar")).toBeVisible();
    // Aprovar é rascunho local, não escreve no Calendar
    await page.getByRole("button", { name: /Aprovar Alt A/i }).click();
    await expect(page.getByText(/Aprovado — nenhuma escrita externa/i)).toBeVisible();
    await expect(page.getByText(/idempotente/i)).toBeVisible();
    // Rejeitar não cria efeito colateral
    await page.getByRole("button", { name: /Reabrir/i }).click();
    await page.getByRole("button", { name: /Rejeitar/i }).click();
    await expect(page.getByText(/Rejeitado — nenhuma alteração/i)).toBeVisible();
  });

  test("Jornada 3: capturar ideia e relacionar a projeto — sem criar reunião", async ({ page }) => {
    await page.goto("/inbox");
    await expect(page.getByText("NOVA CAPTURA — JORNADA 3")).toBeVisible();
    const textarea = page.getByPlaceholder("Ex: Ideia CRIVO — triagem por similaridade semântica com embeddings locais...");
    await textarea.fill("Ideia teste E2E: validar jornada 3 em ambiente mock");
    await page.getByRole("button", { name: /Classificar e salvar/i }).click();
    await expect(page.getByText("Ideia teste E2E")).toBeVisible();
    await expect(page.getByText("CRIVO")).toBeVisible();
    // Verificar vínculo em Domínios
    await page.getByRole("link", { name: /Ver em Domínios/i }).first().click();
    await expect(page).toHaveURL(/dominios/);
    await expect(page.getByText("Domínios")).toBeVisible();
    await page.getByRole("button", { name: /^CRIVO/ }).click();
    await expect(page.getByText(/triagem por similaridade/i)).toBeVisible();
    await expect(page.getByText(/Não criei reunião nem e-mail/)).toBeVisible();
  });

  test("Estados honestos: mock, stale e DEMO sempre visíveis", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText("Gate 1 · mock")).toBeVisible();
    await expect(page.getByText("DEMO")).toBeVisible();
    await expect(page.getByText(/Dados possivelmente desatualizados/)).toBeVisible();
    await page.goto("/fontes");
    await expect(page.getByText(/Estado dos conectores — Gate 1 mock/)).toBeVisible();
    await expect(page.getByText(/stale/)).toBeVisible();
  });

  test("Acessibilidade: navegação por teclado e foco visível", async ({ page }) => {
    await page.goto("/");
    // Skip link
    await page.keyboard.press("Tab");
    await expect(page.getByText("Pular para o conteúdo")).toBeFocused();
    await page.keyboard.press("Enter");
    // Header deve ter comando universal acessível
    await expect(page.getByLabel(/Perguntar ao JARVIS — comando universal/)).toBeVisible();
    // Bottom nav em mobile
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.getByRole("navigation", { name: /Navegação mobile/ })).toBeVisible();
  });
});
