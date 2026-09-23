import { test, expect } from "@playwright/test";

const DOMAIN_IDS = [
  "dom_trabalho",
  "dom_medsyn",
  "dom_crivo",
  "dom_carreira",
  "dom_aprender",
  "dom_saude",
  "dom_financas",
  "dom_familia"
] as const;

test.describe("Gate 1.3 — isolamento e persistência DEMO", () => {
  test("nota com id único persiste no domínio após navegar e recarregar", async ({ page }) => {
    const trace = `trace-${Date.now()}-${test.info().project.name}`;
    await page.goto("/inbox");
    await page.getByTestId("capture-input").fill(`Nota ${trace}`);
    await page.getByTestId("domain-select").selectOption("dom_crivo");
    await page.getByTestId("capture-save").click();

    const card = page.getByTestId("capture-card").filter({ hasText: trace });
    await expect(card).toBeVisible();
    const captureId = await card.getAttribute("data-capture-id");
    expect(captureId).toBeTruthy();
    await expect(card).toHaveAttribute("data-domain-id", "dom_crivo");

    await page.locator('a[href="/dominios"]:visible').click();
    await expect(page).toHaveURL(/\/dominios/);
    await page.getByTestId("domain-tab-dom_crivo").click();
    const stored = page.getByTestId("domain-capture").filter({ hasText: trace });
    await expect(stored).toBeVisible();
    await expect(stored).toHaveAttribute("data-capture-id", captureId!);
    await expect(stored).toHaveAttribute("data-domain-id", "dom_crivo");

    await page.reload();
    await expect(page.getByTestId("domain-capture").filter({ hasText: trace })).toHaveAttribute("data-capture-id", captureId!);

    await page.getByTestId("domain-tab-dom_medsyn").click();
    await expect(page.getByTestId("domain-captures").getByText(trace)).toHaveCount(0);
  });

  test("oito domínios isolados, menção CRIVO não vaza, sem domínio fica de fora", async ({ page }) => {
    await page.goto("/dominios");

    for (const id of DOMAIN_IDS) {
      await page.getByTestId(`domain-tab-${id}`).click();
      const foreign = page.getByTestId("domain-events").locator(`[data-domain-id]:not([data-domain-id="${id}"])`);
      await expect(foreign).toHaveCount(0);
      const foreignCaptures = page.getByTestId("domain-captures").locator(`[data-domain-id]:not([data-domain-id="${id}"])`);
      await expect(foreignCaptures).toHaveCount(0);
    }

    await page.getByTestId("domain-tab-dom_medsyn").click();
    await expect(page.getByTestId("domain-events").getByText("MedSyn — pauta interna que cita CRIVO no título")).toBeVisible();

    await page.getByTestId("domain-tab-dom_crivo").click();
    await expect(page.getByTestId("domain-events").getByText("MedSyn — pauta interna que cita CRIVO no título")).toHaveCount(0);
    await expect(page.getByTestId("domain-captures").getByText(/triagem por similaridade/)).toBeVisible();

    await page.getByTestId("domain-tab-todos").click();
    await expect(page.getByTestId("domain-unassigned").getByText("Registro sem domínio atribuído")).toBeVisible();
    await expect(page.getByTestId("domain-unassigned").getByText("Registro com domínio desconhecido")).toBeVisible();
    await expect(page.getByTestId("domain-events").getByText("Registro sem domínio atribuído")).toHaveCount(0);
  });
});
