import { test, expect } from "@playwright/test";

const passphrase = process.env.JARVIS_E2E_PASSPHRASE;
const domainId = "dom_synthetic_h";
const calendarId = "sim_calendar_h";
const syntheticTitle = "Compromisso sintético H-1";

test("voltar do DEMO mantém as concessões quando o escopo muda durante o carregamento", async ({ page }) => {
  if (!passphrase || passphrase.length < 12) throw new Error("Frase sintética de E2E ausente.");
  const failedGrants: string[] = [];
  page.on("requestfailed", (request) => {
    if (request.url().endsWith("/real/grants") && request.method() === "GET") {
      failedGrants.push(request.failure()?.errorText ?? "desconhecido");
    }
  });

  await page.goto("/integrado");
  await page.getByTestId("local-passphrase").fill(passphrase);
  await page.getByTestId("local-login-submit").click();
  await expect(page.getByRole("heading", { name: "Concessões locais" })).toBeVisible();
  await page.getByTestId("domain-filter").selectOption(domainId);
  await page.getByTestId("grant-domain").selectOption(domainId);
  const revokeReading = page.getByRole("button", { name: "Revogar leitura Escopo sintético H" });
  const revokeInventory = page.getByRole("button", { name: "Revogar inventário Escopo sintético H" });
  if (await revokeReading.count()) {
    await revokeReading.click();
    await expect(revokeReading).toHaveCount(0);
  }
  if (await revokeInventory.count()) {
    await revokeInventory.click();
    await expect(revokeInventory).toHaveCount(0);
  }
  await expect(page.getByTestId("grant-create")).toBeEnabled();
  await page.getByTestId("grant-create").click();
  await page.getByTestId("grant-inventory").click();
  const calendarCard = page.locator(`[data-testid="calendar-card"][data-calendar-id="${calendarId}"]`);
  await expect(calendarCard).toBeVisible();
  const classify = calendarCard.getByRole("button", { name: `Classificar ${calendarId}` });
  if (await classify.count()) {
    await page.getByTestId(`calendar-domain-${calendarId}`).selectOption(domainId);
    await classify.click();
  }
  await calendarCard.getByRole("button", { name: `Sincronizar ${calendarId}` }).click();
  await expect(page.getByTestId("integrated-events").getByText(syntheticTitle)).toBeVisible();

  await page.getByRole("link", { name: "Mudar para modo DEMO" }).click();
  await expect(page.getByText(/DEMO ·/).first()).toBeVisible();

  let delayedGrantGet = false;
  await page.route("**/real/grants", async (route) => {
    if (route.request().method() === "GET" && !delayedGrantGet) {
      delayedGrantGet = true;
      await new Promise((resolve) => setTimeout(resolve, 1200));
    }
    await route.continue();
  });

  const reloadedGrants = page.waitForResponse((response) =>
    response.url().endsWith("/real/grants") && response.request().method() === "GET"
  );
  await page.getByRole("link", { name: "Abrir integração sintética com API local" }).click();
  await expect(page.getByRole("heading", { name: "Concessões locais" })).toBeVisible();
  await expect(page.getByText(/Sessão local ativa/)).toBeVisible();
  await page.getByTestId("domain-filter").selectOption(domainId);
  const reloaded = await reloadedGrants;
  expect(reloaded.status(), "o carregamento das concessões não pode ser cancelado ao trocar o escopo").toBe(200);
  expect(failedGrants, `GET /real/grants abortado: ${failedGrants.join(", ")}`).toEqual([]);
  await expect(page.getByTestId("grant-card").filter({ hasText: "Calendar fictício" }).filter({ hasText: "Escopo sintético H" })).toBeVisible();
  await expect(page.getByTestId("integrated-events").getByText(syntheticTitle)).toBeVisible();

  await page.unroute("**/real/grants");
  const revokeReadingDone = page.getByRole("button", { name: "Revogar leitura Escopo sintético H" });
  const revokeInventoryDone = page.getByRole("button", { name: "Revogar inventário Escopo sintético H" });
  await revokeReadingDone.click();
  await expect(revokeReadingDone).toHaveCount(0);
  await revokeInventoryDone.click();
  await expect(revokeInventoryDone).toHaveCount(0);
});
