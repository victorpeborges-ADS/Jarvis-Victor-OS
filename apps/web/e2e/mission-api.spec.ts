import { expect, test } from "@playwright/test";

test("painel da API sintética não apaga o DEMO e admite sessão ausente", async ({ page }) => {
  await page.goto("/missoes");
  await page.getByLabel("Nome").fill("Missão que permanece no navegador");
  await page.getByRole("button", { name: "Criar missão" }).click();
  await expect(page.getByRole("heading", { name: "Missão que permanece no navegador", exact: true })).toBeVisible();
  await page.getByTestId("mission-api-open").click();
  await expect(page.getByTestId("mission-api-panel")).toContainText("API local sintética");
  await page.getByRole("button", { name: "Ler missões da API" }).click();
  await expect(page.getByTestId("mission-api-panel")).toContainText("401");
  await expect(page.getByRole("heading", { name: "Missão que permanece no navegador", exact: true })).toBeVisible();
});

test("concessões de Missões dependem de clique explícito e habilitam importação sintética", async ({ page }) => {
  const passphrase = process.env.JARVIS_E2E_PASSPHRASE;
  if (!passphrase) throw new Error("Frase sintética E2E ausente");
  const title = `Missão manual fictícia ${Date.now()}`;
  await page.goto("/missoes");
  await page.getByLabel("Nome").fill(title);
  await page.getByRole("button", { name: "Criar missão" }).click();
  await page.goto("/integrado");
  await page.getByTestId("local-passphrase").fill(passphrase);
  await page.getByTestId("local-login-submit").click();
  await expect(page.getByRole("heading", { name: "Concessões locais" })).toBeVisible();
  await page.goto("/missoes");
  await page.getByTestId("mission-api-open").click();
  await page.getByRole("button", { name: "Conceder leitura e escrita de Missões (Escopo A)" }).click();
  await expect(page.getByTestId("mission-api-panel")).toContainText("mission:read e mission:write confirmadas");
  await page.getByRole("button", { name: "Prévia da importação" }).click();
  await expect(page.getByTestId("mission-api-panel")).toContainText("1 válida(s) para envio");
  await page.getByRole("button", { name: "Confirmar envio" }).click();
  await expect(page.getByTestId("mission-api-card").filter({ hasText: title })).toBeVisible();
});
