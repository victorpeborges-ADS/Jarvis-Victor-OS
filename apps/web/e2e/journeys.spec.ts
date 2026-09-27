import { test, expect } from "@playwright/test";

test.describe("Gate 1.2 — 3 jornadas E2E + regressões", () => {
  test("Jornada 1: entender o dia em 5s — Agora mostra próximo, prioridade e alerta", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText(/PRÓXIMO COMPROMISSO/)).toBeVisible({ timeout: 10000 });
    await expect(page.getByText("Daily MedSyn — revisão sprint").first()).toBeVisible();
    await expect(page.getByText(/PRIORIDADE ESSENCIAL/)).toBeVisible();
    await expect(page.getByText("Finalizar slides demo MedSyn")).toBeVisible();
    await expect(page.getByText(/ALERTA COM CONSEQUÊNCIA/)).toBeVisible();
    await expect(page.getByText(/COMPROMISSOS · 3/)).toBeVisible();
    await expect(page.getByText(/MENSAGENS · 2/)).toBeVisible();
    await page.getByRole("button", { name: /Por que isso importa/i }).click();
    await expect(page.getByText("ORIGEM DAS INFORMAÇÕES", { exact: true }).first()).toBeVisible();
    await page.getByRole("button", { name: /Fechar/i }).click();
    await expect(page.getByText("Linha do tempo — hoje")).toBeVisible();
  });

  test("Jornada 2: resolver conflito — alternativas selecionáveis sem escrita externa", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("link", { name: /Resolver conflito/i }).click();
    await expect(page).toHaveURL(/aprovacoes/);
    await expect(page.getByRole("heading", { name: /Mover Academia para 17h\?/ })).toBeVisible();
    await expect(page.getByText("RESUMO DA MUDANÇA")).toBeVisible();
    await expect(page.getByText("Antecipar academia para 17h")).toBeVisible();
    await expect(page.getByText("Manter academia 18h mas encurtar")).toBeVisible();

    await page.getByRole("radio", { name: /Manter academia 18h/i }).check();
    await page.getByRole("button", { name: /Aprovar sugestão B — somente nesta tela/i }).click();
    await expect(page.getByText(/Sugestão aprovada nesta demonstração \(opção B\)/i)).toBeVisible();
    await expect(page.getByText(/nenhuma conta foi alterada/i)).toBeVisible();

    await page.getByRole("button", { name: /Reabrir/i }).click();
    await page.getByRole("button", { name: /Rejeitar/i }).click();
    await expect(page.getByText(/Rejeitado — nenhuma alteração/i)).toBeVisible();
  });

  test("Jornada 3: capturar ideia e relacionar a projeto — sem criar reunião", async ({ page }) => {
    await page.goto("/inbox");
    await expect(page.getByText("NOVA CAPTURA")).toBeVisible();
    const textarea = page.getByPlaceholder("Ex.: Ideia para organizar referências do projeto CRIVO...");
    await textarea.fill("Ideia teste E2E: validar jornada 3 em ambiente mock");
    await page.getByRole("button", { name: /Classificar e salvar/i }).click();
    await expect(page.getByText("Ideia teste E2E")).toBeVisible();
    await expect(page.getByText(/Captura classificada e salva/i)).toBeVisible();
    await expect(page.getByTestId("capture-card").filter({ hasText: "Ideia teste E2E" })).toHaveAttribute("data-domain-id", "dom_crivo");
    await page.getByRole("link", { name: /Ver em Domínios/i }).first().click();
    await expect(page).toHaveURL(/dominios/);
    await expect(page.getByRole("heading", { name: "Domínios", exact: true })).toBeVisible();
    const crivoFilter = page.getByTestId("domain-tab-dom_crivo");
    await expect(crivoFilter).toBeVisible();
    await crivoFilter.click();
    await expect(page.getByTestId("domain-context")).toContainText("CRIVO");
    await expect(page.getByTestId("domain-captures").getByText(/triagem por similaridade/i)).toBeVisible();
    await expect(page.getByText(/não recupera/i)).toBeVisible();
  });

  test("Estados honestos: simulação, desatualizado e DEMO sempre visíveis", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText(/Demonstração ·/).first()).toBeVisible();
    await expect(page.getByText(/Dados possivelmente desatualizados/)).toBeVisible();
    await page.goto("/fontes");
    await expect(page.getByText(/Estado das fontes de exemplo/)).toBeVisible();
    // Preferir main: sidebar desktop tem o mesmo texto mas pode estar hidden em mobile
    const main = page.locator("main");
    await expect(main.getByText(/exemplo · desatualizado/).first()).toBeVisible();
    await expect(main.getByText(/exemplo · atualizado/).first()).toBeVisible();
    await expect(page.getByText(/^connected$/)).toHaveCount(0);
  });

  test("Acessibilidade: navegação por teclado e foco visível", async ({ page }) => {
    await page.goto("/");
    await page.keyboard.press("Tab");
    await expect(page.getByText("Pular para o conteúdo")).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("button", { name: "Perguntar ao JARVIS — comando universal" })).toBeVisible();
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.getByRole("navigation", { name: /Navegação mobile/ })).toBeVisible();
  });

  test("Regressão mobile: conteúdo não fica sob a bottom nav", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/inbox");
    const nav = page.getByRole("navigation", { name: /Navegação mobile/ });
    await expect(nav).toBeVisible();
    const navBox = await nav.boundingBox();
    expect(navBox).toBeTruthy();

    const cta = page.getByRole("button", { name: /Classificar e salvar/i });
    await cta.scrollIntoViewIfNeeded();
    const ctaBox = await cta.boundingBox();
    expect(ctaBox).toBeTruthy();
    // CTA visível no viewport acima da nav (não sobreposto)
    expect(ctaBox!.y + ctaBox!.height).toBeLessThanOrEqual(navBox!.y + 2);

    await page.goto("/aprovacoes");
    const approve = page.getByRole("button", { name: /Aprovar sugestão A — somente nesta tela/i });
    await approve.scrollIntoViewIfNeeded();
    const approveBox = await approve.boundingBox();
    const navBox2 = await nav.boundingBox();
    expect(approveBox!.y + approveBox!.height).toBeLessThanOrEqual(navBox2!.y + 2);
  });

  test("404 personalizada em português com recuperação", async ({ page }) => {
    await page.goto("/rota-inexistente-gate12");
    await expect(page.getByRole("heading", { name: "404" })).toBeVisible();
    await expect(page.getByText(/Página não encontrada/i)).toBeVisible();
    await expect(page.getByRole("link", { name: /Voltar ao Agora/i })).toBeVisible();
    await expect(page.getByText(/This page could not be found/i)).toHaveCount(0);
  });
});
