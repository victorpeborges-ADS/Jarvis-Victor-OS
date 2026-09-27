import { mkdir, writeFile } from "node:fs/promises";
import { resolve, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const baseUrl = process.env.JARVIS_CAPTURE_BASE_URL ?? "http://127.0.0.1:13000";
const phase = process.env.JARVIS_CAPTURE_PHASE ?? "after";
const repositoryRoot = resolve(fileURLToPath(new URL("../../../", import.meta.url)));
const outputRoot = resolve(process.env.JARVIS_CAPTURE_ROOT ?? join(repositoryRoot, "docs/r3/captures"));
const outputDir = join(outputRoot, phase);
const widths = [320, 390, 767, 768, 769, 1024, 1440];
const routes = [
  ["agora", "/"],
  ["perguntar", "/conversa"],
  ["entrada", "/inbox"],
  ["dominios", "/dominios"],
  ["aprovacoes", "/aprovacoes"],
  ["fontes", "/fontes"],
  ["missoes", "/missoes"],
  ["integracao", "/integrado"],
  ["nao-encontrado", "/r3-endereco-inexistente"]
];

await mkdir(outputDir, { recursive: true });
const browser = await chromium.launch({ channel: "chrome" });
const results = [];

try {
  for (const [name, route] of routes) {
    for (const width of widths) {
      const page = await browser.newPage({
        viewport: { width, height: 900 },
        deviceScaleFactor: 1,
        reducedMotion: "reduce"
      });
      const pageErrors = [];
      page.on("pageerror", (error) => pageErrors.push(error.message));
      await page.goto(new URL(route, baseUrl).toString(), { waitUntil: "domcontentloaded" });
      await page.locator("main").waitFor({ state: "visible" });
      await page.evaluate(() => document.fonts.ready);
      await page.waitForTimeout(180);
      const metrics = await page.evaluate(() => {
        const main = document.querySelector("main");
        const controls = [...(main?.querySelectorAll("a[href], button") ?? [])];
        const undersizedTargets = controls.flatMap((element) => {
          const box = element.getBoundingClientRect();
          if (box.width >= 24 && box.height >= 24) return [];
          return [{
            label: (element.getAttribute("aria-label") || element.textContent || "").trim().replace(/\s+/g, " ").slice(0, 80),
            width: Math.round(box.width),
            height: Math.round(box.height)
          }];
        });
        return {
          viewport: window.innerWidth,
          documentWidth: document.documentElement.scrollWidth,
          horizontalOverflow: document.documentElement.scrollWidth > window.innerWidth,
          undersizedTargets,
          heading: main?.querySelector("h1")?.textContent?.trim() ?? null
        };
      });
      const file = `${name}-${width}.png`;
      await page.screenshot({ path: join(outputDir, file), fullPage: true, animations: "disabled" });
      results.push({ route, file, width, ...metrics, pageErrors });
      await page.close();
    }
  }

  const navPage = await browser.newPage({ viewport: { width: 390, height: 844 }, reducedMotion: "reduce" });
  await navPage.goto(new URL("/", baseUrl).toString(), { waitUntil: "domcontentloaded" });
  await navPage.getByRole("button", { name: /mais/i }).click();
  await navPage.screenshot({ path: join(outputDir, "mais-390.png"), fullPage: true, animations: "disabled" });
  await navPage.close();

  await writeFile(join(outputDir, "inspection.json"), `${JSON.stringify({ phase, baseUrl, widths, routes, results }, null, 2)}\n`);
  const overflows = results.filter((result) => result.horizontalOverflow);
  const errors = results.filter((result) => result.pageErrors.length > 0);
  process.stdout.write(`${phase}: ${results.length} telas; ${overflows.length} larguras com overflow; ${errors.length} erros de página.\n`);
  process.stdout.write(`Evidências: ${outputDir}\n`);
} finally {
  await browser.close();
}
