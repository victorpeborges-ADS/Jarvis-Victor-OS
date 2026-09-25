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
