import { expect, test } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

test("R5 approval label stays readable inside the accessible mobile control", async ({ page }, testInfo) => {
  const widths = [320, 360, 390, 600, 767, 768, 769, 820, 1024, 1440];
  const evidenceDir = process.env.JARVIS_E2E_SCREENSHOT_DIR;
  if (evidenceDir) mkdirSync(evidenceDir, { recursive: true });
  for (const width of widths) {
    await page.setViewportSize({ width, height: width >= 768 ? 900 : 844 });
    await page.goto("/");
    const pageWidth = await page.evaluate(() => ({ viewport: window.innerWidth, content: document.documentElement.scrollWidth }));
    expect(pageWidth.viewport).toBe(width);
    expect(pageWidth.content).toBeLessThanOrEqual(width + 1);
    const nav = page.getByRole("navigation", { name: "Navegação mobile" });
    if (width < 768) {
      await expect(nav).toBeVisible();
      const approval = nav.getByRole("link", { name: "Aprovações" });
      const geometry = await approval.evaluate((element) => {
        const link = element.getBoundingClientRect();
        const labelElement = element.querySelector("span:last-child");
        const label = labelElement?.getBoundingClientRect();
        return {
          link: { left: link.left, right: link.right, top: link.top, bottom: link.bottom, width: link.width, height: link.height },
          label: label && { left: label.left, right: label.right, top: label.top, bottom: label.bottom, width: label.width, height: label.height },
          textWidth: labelElement?.scrollWidth,
          labelWidth: labelElement?.clientWidth,
          fontSize: labelElement && Number.parseFloat(getComputedStyle(labelElement).fontSize),
          whiteSpace: labelElement && getComputedStyle(labelElement).whiteSpace,
          scrollWidth: element.scrollWidth,
          clientWidth: element.clientWidth,
        };
      });
      console.log(`R5 nav bounds ${width}px ${JSON.stringify(geometry)}`);
      expect(geometry.label, `approval label geometry at ${width}px`).toBeTruthy();
      expect(geometry.label!.left).toBeGreaterThanOrEqual(geometry.link.left);
      expect(geometry.label!.top).toBeGreaterThanOrEqual(geometry.link.top);
      expect(geometry.label!.right).toBeLessThanOrEqual(geometry.link.right + 0.5);
      expect(geometry.label!.bottom).toBeLessThanOrEqual(geometry.link.bottom + 0.5);
      expect(geometry.link.left).toBeGreaterThanOrEqual(0);
      expect(geometry.link.right).toBeLessThanOrEqual(width);
      expect(geometry.link.height).toBeGreaterThanOrEqual(44);
      expect(geometry.scrollWidth).toBeLessThanOrEqual(geometry.clientWidth);
      expect(geometry.whiteSpace).toBe("nowrap");
      expect(geometry.fontSize).toBeGreaterThanOrEqual(12);
      expect(geometry.textWidth).toBeLessThanOrEqual(geometry.labelWidth! + 1);
      await page.waitForTimeout(400);
      const path = evidenceDir
        ? resolve(evidenceDir, `R5_NAV_${testInfo.project.name}_${width}px.png`)
        : testInfo.outputPath(`r5-nav-${width}px.png`);
      await page.screenshot({ path });
    } else {
      await expect(nav).toBeHidden();
      await page.waitForTimeout(400);
      const path = evidenceDir
        ? resolve(evidenceDir, `R5_NAV_${testInfo.project.name}_${width}px.png`)
        : testInfo.outputPath(`r5-nav-${width}px.png`);
      await page.screenshot({ path });
    }
  }
});
