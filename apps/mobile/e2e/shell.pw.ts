import { expect, test } from "@playwright/test";

test("shell navega e mantém outbox sintética local após reload", async ({ page }) => {
  const externalRequests: string[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).origin !== "http://127.0.0.1:5173") externalRequests.push(request.url());
  });
  await page.goto("/");
  await expect(page.getByText("SOMENTE SINTÉTICO")).toBeVisible();
  await page.getByRole("button", { name: "Inbox" }).click();
  await page.getByLabel("Texto de teste").fill("Ideia fictícia para revisão local");
  await expect(page.getByRole("button", { name: "Salvar localmente" })).toBeDisabled();
  await page.getByLabel("Confirmo que o texto é fictício").check();
  await page.getByRole("button", { name: "Salvar localmente" }).click();
  await expect(page.getByRole("status")).toContainText("nada foi enviado");
  await expect(page.getByText("Ideia fictícia para revisão local")).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "Inbox" }).click();
  await expect(page.getByText("Ideia fictícia para revisão local")).toBeVisible();
  expect(externalRequests).toEqual([]);
  const stored = await page.evaluate(() => JSON.parse(localStorage.getItem("jarvis.mobile.synthetic.outbox.v1") ?? "[]"));
  expect(stored).toHaveLength(1);
  expect(stored[0].synthetic).toBe(true);
});

test("Missões, aprovações e integrações expõem capacidades reais", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Missões" }).click();
  await expect(page.getByText("SIMULAÇÃO · CUSTO 0")).toBeVisible();
  await expect(page.getByText("Esta tela é ilustrativa e não executa tarefas.")).toBeVisible();
  await page.getByRole("button", { name: "Aprovações" }).click();
  await expect(page.getByText("API NÃO CONECTADA")).toBeVisible();
  await page.getByRole("button", { name: "Mais" }).click();
  await page.getByRole("button", { name: "Integrações" }).click();
  await expect(page.getByText("NÃO CONFIGURADO")).toBeVisible();
});
