import { expect, test } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

test("R4 mobile nav labels stay inside their 44px controls", async ({ page }, testInfo) => {
  const widths = [320, 360, 390, 767, 768, 769, 1024, 1440];
  const evidenceDir = process.env.JARVIS_E2E_SCREENSHOT_DIR;
  if (evidenceDir) mkdirSync(evidenceDir, { recursive: true });
  await page.goto("/");
  for (const width of widths) {
    await page.setViewportSize({ width, height: width >= 768 ? 900 : 844 });
    const nav = page.getByRole("navigation", { name: "Navegação mobile" });
    if (width < 768) {
      await expect(nav).toBeVisible();
      const approval = nav.getByRole("link", { name: "Aprovações" });
      const geometry = await approval.evaluate((element) => {
        const link = element.getBoundingClientRect();
        const label = element.querySelector("span:last-child")?.getBoundingClientRect();
        return {
          link: { left: link.left, right: link.right, top: link.top, bottom: link.bottom, width: link.width, height: link.height },
          label: label && { left: label.left, right: label.right, top: label.top, bottom: label.bottom, width: label.width, height: label.height },
          scrollWidth: element.scrollWidth,
          clientWidth: element.clientWidth,
        };
      });
      console.log(`R4 nav bounds ${width}px ${JSON.stringify(geometry)}`);
      expect(geometry.label, `approval label geometry at ${width}px`).toBeTruthy();
      expect(geometry.label!.left).toBeGreaterThanOrEqual(geometry.link.left);
      expect(geometry.label!.top).toBeGreaterThanOrEqual(geometry.link.top);
      expect(geometry.label!.right).toBeLessThanOrEqual(geometry.link.right + 0.5);
      expect(geometry.label!.bottom).toBeLessThanOrEqual(geometry.link.bottom + 0.5);
      expect(geometry.link.left).toBeGreaterThanOrEqual(0);
      expect(geometry.link.right).toBeLessThanOrEqual(width);
      expect(geometry.link.height).toBeGreaterThanOrEqual(44);
      expect(geometry.scrollWidth).toBeLessThanOrEqual(geometry.clientWidth);
      const path = evidenceDir
        ? resolve(evidenceDir, `R4_NAV_${testInfo.project.name}_${width}px.png`)
        : testInfo.outputPath(`r4-nav-${width}px.png`);
      await page.screenshot({ path, fullPage: true });
    } else {
      await expect(nav).toBeHidden();
      const path = evidenceDir
        ? resolve(evidenceDir, `R4_NAV_${testInfo.project.name}_${width}px.png`)
        : testInfo.outputPath(`r4-nav-${width}px.png`);
      await page.screenshot({ path, fullPage: true });
    }
  }
});
