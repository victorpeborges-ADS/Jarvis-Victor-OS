import { expect, test } from "@playwright/test";

test("Conversa fica a um toque na navegação mobile", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  const nav = page.getByRole("navigation", { name: "Navegação mobile" });
  await nav.getByRole("link", { name: "Perguntar" }).click();
  await expect(page).toHaveURL(/\/conversa$/);
  await expect(page.getByRole("heading", { name: "Perguntar ao JARVIS" })).toBeVisible();
});

test("atalho do cabeçalho abre sugestão já preenchida na conversa", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");
  const palette = page.getByRole("region", { name: "Atalhos para começar" });
  await page.getByRole("button", { name: "Perguntar ao JARVIS — comando universal" }).click();
  await expect(palette).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(palette).toHaveCount(0);
  await page.keyboard.press("Control+k");
  await expect(palette).toBeVisible();
  await palette.getByRole("link", { name: "Resumir o dia com evidências" }).click();
  await expect(page).toHaveURL(/\/conversa\?pergunta=/);
  await expect(page.getByRole("textbox", { name: "Mensagem para o JARVIS" })).toHaveValue("Resumir o dia com evidências");
  await expect(page.getByRole("log")).toContainText("As respostas são pré-definidas");
});

test("ações de exportação e pedido de remoção dão resposta visível", async ({ page }) => {
  await page.goto("/fontes");
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Exportar dados de exemplo (JSON)" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("jarvis-dados-de-exemplo.json");
  await expect(page.getByRole("status")).toContainText("Arquivo de exemplo exportado.");

  await page.getByRole("button", { name: "Solicitar remoção dos dados de exemplo" }).click();
  await expect(page.getByRole("status")).toContainText("Pedido registrado nesta tela");
  await expect(page.getByRole("status")).toContainText("nenhum dado pessoal é armazenado aqui");
});

test("plural da fila de aprovação acompanha a quantidade", async ({ page }) => {
  await page.goto("/aprovacoes");
  await expect(page.getByText("1 pendente", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: /Aprovar sugestão A/ }).click();
  await expect(page.getByText("0 pendentes", { exact: true })).toBeVisible();
});
