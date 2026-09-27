import { expect, test } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

test("QA visual noturna: dez larguras sem overflow e sobreposição nas telas principais", async ({ page }, info) => {
  test.skip(info.project.name !== "desktop", "A inspeção cobre os seis viewports num único projeto.");
  const shots = process.env.JARVIS_E2E_SCREENSHOT_DIR ?? process.env.JARVIS_NIGHTLY_CAPTURE_DIR ?? resolve(process.cwd(), "../../exports/nightly/2026-09-26/captures");
  const widths = [320, 360, 390, 600, 767, 768, 769, 820, 1024, 1440];
  const layoutRoutes = ["/", "/conversa", "/inbox", "/dominios", "/aprovacoes", "/fontes", "/missoes", "/integrado"] as const;
  const captureRoutes = [["/missoes", "missoes"], ["/integrado", "integrado"]] as const;
  mkdirSync(shots, { recursive: true });
  for (const width of widths) {
    await page.setViewportSize({ width, height: width < 500 ? 844 : 900 });
    for (const route of layoutRoutes) {
      await page.goto(route);
      await expect(page.locator("main")).toBeVisible();
      const dimensions = await page.evaluate(() => ({
        content: document.documentElement.scrollWidth,
        viewport: window.innerWidth,
        mainRight: document.querySelector("main")?.getBoundingClientRect().right ?? 0,
        headerOverlap: (() => {
          const row = document.querySelector("header > div");
          if (!row) return false;
          const visible = Array.from(row.children).filter((element) => getComputedStyle(element).display !== "none");
          const bounds = visible.map((element) => element.getBoundingClientRect());
          return bounds.some((current, index) => index > 0 && current.left < bounds[index - 1].right - 1);
        })(),
        offscreenControls: Array.from(document.querySelectorAll("a, button, input, select, textarea, [tabindex]"))
          .filter((element) => getComputedStyle(element).display !== "none" && element.getClientRects().length > 0)
          .filter((element) => {
            const rect = element.getBoundingClientRect();
            return rect.left < -1 || rect.right > window.innerWidth + 1;
          }).length,
        uncontainedTables: Array.from(document.querySelectorAll<HTMLElement>("table, [role='table']"))
          .filter((table) => table.scrollWidth > table.clientWidth + 1)
          .filter((table) => !table.parentElement || !["auto", "scroll"].includes(getComputedStyle(table.parentElement).overflowX)).length,
        mobileNavTargets: Array.from(document.querySelectorAll<HTMLElement>("nav[aria-label='Navegação mobile'] a, nav[aria-label='Navegação mobile'] button"))
          .map((element) => ({ width: element.getBoundingClientRect().width, height: element.getBoundingClientRect().height })),
        offenders: Array.from(document.querySelectorAll("body *"))
          .filter((element) => element.getBoundingClientRect().right > window.innerWidth + 1)
          .slice(0, 8).map((element) => `${element.tagName.toLowerCase()}.${String(element.className).slice(0, 60)}`),
      }));
      expect(dimensions.content, `${route} em ${width}px: ${dimensions.offenders.join(", ")}`).toBeLessThanOrEqual(dimensions.viewport + 1);
      expect(dimensions.mainRight, `${route} main ultrapassa ${width}px`).toBeLessThanOrEqual(width + 1);
      expect(dimensions.headerOverlap, `${route} header se sobrepõe em ${width}px`).toBe(false);
      expect(dimensions.offscreenControls, `${route} possui controles fora da tela em ${width}px`).toBe(0);
      expect(dimensions.uncontainedTables, `${route} possui tabela sem rolagem própria em ${width}px`).toBe(0);
      if (width < 768) {
        expect(dimensions.mobileNavTargets, `${route} não oferece cinco áreas de navegação mobile em ${width}px`).toHaveLength(5);
        for (const target of dimensions.mobileNavTargets) {
          expect(target.width, `${route} alvo de navegação tem menos de 44px de largura em ${width}px`).toBeGreaterThanOrEqual(44);
          expect(target.height, `${route} alvo de navegação tem menos de 44px de altura em ${width}px`).toBeGreaterThanOrEqual(44);
        }
      }

      if (route === "/missoes" && width === 768) {
        const trigger = page.getByRole("button", { name: "Perguntar ao JARVIS — comando universal" });
        await expect(trigger).toBeVisible();
        const box = await trigger.boundingBox();
        expect(box?.width).toBeGreaterThanOrEqual(44);
        expect(box?.height).toBeGreaterThanOrEqual(44);
        await page.screenshot({ path: resolve(shots, "R1_MISSOES_768_DEPOIS.png"), animations: "disabled" });
      }

      const captureName = captureRoutes.find(([captureRoute]) => captureRoute === route)?.[1];
      if (captureName) {
        await page.screenshot({ path: resolve(shots, `web-r1-${captureName}-${width}.png`), fullPage: true, animations: "disabled" });
      }
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
  await expect(dialog.getByRole("link", { name: /Integração local/ })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(more).toBeFocused();
  await more.click();
  await dialog.getByRole("link", { name: /Integração local/ }).click();
  await expect(page).toHaveURL(/\/integrado$/);
  await expect(nav.getByRole("button", { name: "Mais" })).toHaveAttribute("aria-expanded", "false");
});
