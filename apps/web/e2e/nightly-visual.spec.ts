import { expect, test } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

test("QA visual noturna: seis larguras sem overflow nas jornadas DEMO e API", async ({ page }, info) => {
  test.skip(info.project.name !== "desktop", "A inspeção cobre os seis viewports num único projeto.");
  const shots = process.env.JARVIS_NIGHTLY_CAPTURE_DIR ?? resolve(process.cwd(), "../../exports/nightly/2026-09-26/captures");
  mkdirSync(shots, { recursive: true });
  for (const width of [360, 390, 768, 1024, 1440, 1920]) {
    await page.setViewportSize({ width, height: width < 500 ? 844 : 900 });
    for (const [route, name] of [["/missoes", "missoes"], ["/integrado", "integrado"]] as const) {
      await page.goto(route);
      await expect(page.locator("main")).toBeVisible();
      const dimensions = await page.evaluate(() => ({
        content: document.documentElement.scrollWidth,
        viewport: window.innerWidth,
        offenders: Array.from(document.querySelectorAll("body *"))
          .filter((element) => element.getBoundingClientRect().right > window.innerWidth + 1)
          .slice(0, 8).map((element) => `${element.tagName.toLowerCase()}.${String(element.className).slice(0, 60)}`),
      }));
      await page.screenshot({ path: resolve(shots, `web-${name}-${width}.png`), fullPage: true, animations: "disabled" });
      expect(dimensions.content, `${name} em ${width}px: ${dimensions.offenders.join(", ")}`).toBeLessThanOrEqual(dimensions.viewport + 1);
    }
  }
});

test("navegação mobile Mais mantém áreas acessíveis por teclado", async ({ page }, info) => {
  test.skip(info.project.name !== "mobile", "Fluxo próprio da navegação mobile.");
  await page.goto("/missoes");
  const nav = page.getByRole("navigation", { name: "Navegação mobile" });
  const more = nav.getByRole("button", { name: "Mais" });
  await more.click();
  const dialog = page.getByRole("dialog", { name: "Mais áreas" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("link", { name: /API local sintética/ })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(more).toBeFocused();
  await more.click();
  await dialog.getByRole("link", { name: /API local sintética/ }).click();
  await expect(page).toHaveURL(/\/integrado$/);
  await expect(nav.getByRole("button", { name: "Mais" })).toHaveAttribute("aria-expanded", "false");
});
