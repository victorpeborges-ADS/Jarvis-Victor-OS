import { expect, test } from "@playwright/test";
import path from "path";

const shots = path.resolve(__dirname, "../../../docs/screenshots/a11y");

function contrast(foreground: string, background: string) {
  const parse = (value: string) => value.match(/\d+/g)?.slice(0, 3).map(Number) ?? [0, 0, 0];
  const channel = (value: number) => {
    const ratio = value / 255;
    return ratio <= 0.04045 ? ratio / 12.92 : ((ratio + 0.055) / 1.055) ** 2.4;
  };
  const luminance = (value: string) => {
    const [red, green, blue] = parse(value);
    return 0.2126 * channel(red) + 0.7152 * channel(green) + 0.0722 * channel(blue);
  };
  const [lighter, darker] = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
  return (lighter + 0.05) / (darker + 0.05);
}

test.describe("Gate 1.3.2 — drawer e foco", () => {
  test("abre, contém o foco, fecha com Escape e restaura o acionador", async ({ page }, info) => {
    await page.goto("/");
    const opener = page.getByRole("button", { name: "Por que isso importa" });
    await opener.focus();
    await opener.press("Enter");
    const dialog = page.getByRole("dialog");
    const close = page.getByTestId("drawer-close");
    await expect(dialog).toBeVisible();
    await expect(close).toBeFocused();
    await expect(page.locator("main")).toHaveAttribute("inert", "");

    await page.keyboard.press("Tab");
    await expect(close).toBeFocused();
    await page.keyboard.press("Shift+Tab");
    await expect(close).toBeFocused();

    await page.screenshot({ path: path.join(shots, `drawer-${info.project.name}.png`) });
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await expect(opener).toBeFocused();
    await expect(page.locator("main")).not.toHaveAttribute("inert", "");
  });

  test("foco visível e contraste do texto auxiliar", async ({ page }, info) => {
    await page.goto("/inbox");
    const help = page.getByTestId("demo-storage-limits");
    await help.focus().catch(() => undefined);
    const link = page.getByRole("link", { name: "Ver em Domínios" }).first();
    await link.focus();
    const measured = await link.evaluate((element) => {
      const style = getComputedStyle(element);
      const helpNode = document.querySelector("[data-testid='demo-storage-limits']");
      const helpStyle = helpNode ? getComputedStyle(helpNode) : null;
      const body = getComputedStyle(document.body);
      return {
        outlineWidth: style.outlineWidth,
        outlineStyle: style.outlineStyle,
        outlineColor: style.outlineColor,
        helpColor: helpStyle?.color ?? "",
        background: body.backgroundColor
      };
    });
    expect(measured.outlineStyle).not.toBe("none");
    expect(parseFloat(measured.outlineWidth)).toBeGreaterThanOrEqual(2);
    expect(contrast(measured.helpColor, measured.background)).toBeGreaterThanOrEqual(4.5);
    await page.screenshot({ path: path.join(shots, `foco-${info.project.name}.png`) });
  });
});
