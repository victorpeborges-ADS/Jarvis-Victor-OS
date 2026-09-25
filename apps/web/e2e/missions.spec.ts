import { expect, test } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

const shots = process.env.JARVIS_E2E_SCREENSHOT_DIR ?? resolve(process.cwd(), "../../docs/nightly/captures");

test("missão sintética executa skills, mantém proveniência e sobrevive ao reload", async ({ page }, info) => {
  const apiCalls: string[] = [];
  page.on("request", (request) => { if (request.url().includes("/real/")) apiCalls.push(request.url()); });
  await page.goto("/missoes");
  await expect(page.getByTestId("mission-simulation-banner")).toContainText("teto de custo 0");
  await expect(page.getByText(/Missões criadas aqui permanecem no armazenamento local/)).toBeVisible();
  await page.getByLabel("Nome").fill("Síntese de exemplo fictício");
  await page.getByRole("button", { name: "Criar missão" }).click();
  await expect(page.getByRole("heading", { name: "Síntese de exemplo fictício", exact: true })).toBeVisible();
  await expect(page.getByTestId("mission-task")).toHaveCount(3);

  const run = page.getByRole("button", { name: "Executar próxima etapa · simulada" });
  await run.click();
  await expect(page.getByText(/Uma etapa determinística foi concluída localmente/)).toBeVisible();
  await expect(page.getByTestId("mission-task").nth(0)).toContainText("Concluída");
  await run.click();
  await expect(page.getByRole("heading", { name: "Pacote de contexto sintético" })).toBeVisible();
  await run.click();
  await expect(page.getByRole("heading", { name: "Rascunho: Síntese de exemplo fictício" })).toBeVisible();
  await expect(page.getByText("MISSÃO SINTÉTICA · CONCLUÍDA")).toBeVisible();
  await expect(page.getByTestId("mission-artifact").last().getByText(/Origem: synthetic:mission:/)).toBeVisible();
  await expect(page.getByText(/skill 1.0.0/).last()).toBeVisible();
  await expect(page.getByText(/nenhuma informação foi enviada/i)).toBeVisible();
  await page.getByRole("button", { name: /Revisar fontes e decisão/ }).click();
  await expect(page.getByRole("dialog")).toContainText("Fontes e aprovação");
  await expect(page.getByRole("dialog")).toContainText("synthetic:mission:");
  await page.getByRole("button", { name: "Aprovar para uso local" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByText("Revisão: aprovado localmente")).toBeVisible();
  expect(apiCalls).toHaveLength(0);

  mkdirSync(shots, { recursive: true });
  await page.locator('nav[aria-label="Navegação mobile"]').evaluate((element) => element.remove());
  const screenshotStyle = await page.addStyleTag({ content: "header { position: static !important; }" });
  await page.screenshot({
    path: resolve(shots, `missions-${info.project.name}.png`),
    fullPage: true
  });
  await screenshotStyle.evaluate((element) => element.remove());
  await page.reload();
  await expect(page.getByRole("heading", { name: "Síntese de exemplo fictício", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Rascunho: Síntese de exemplo fictício" })).toBeVisible();
  await expect(page.getByText("Revisão: aprovado localmente")).toBeVisible();
  const storedKeys = await page.evaluate(() => Object.keys(localStorage));
  expect(storedKeys).toContain("jarvis.synthetic.missions.v1");
  expect(storedKeys.some((key) => key.startsWith("jarvis.real"))).toBe(false);
});

test("falha sintética admite retry e cancelamento local", async ({ page }) => {
  await page.goto("/missoes");
  await page.getByLabel("Nome").fill("Teste de retry local");
  await page.getByRole("button", { name: "Criar missão" }).click();
  await page.getByRole("button", { name: "Demonstrar falha/retry" }).click();
  await expect(page.getByText(/Falhou · tentativa 1/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Preparar retry local" })).toBeVisible();
  await page.getByRole("button", { name: "Preparar retry local" }).click();
  await expect(page.getByText(/Planejada · tentativa 2/)).toBeVisible();
  await page.getByRole("button", { name: "Cancelar" }).click();
  await expect(page.locator("p[role='status']")).toHaveText("Missão cancelada localmente.");
  await expect(page.getByText("MISSÃO SINTÉTICA · CANCELADA")).toBeVisible();
});
