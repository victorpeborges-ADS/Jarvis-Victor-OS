import { test, expect } from "@playwright/test";
import { spawnSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

const passphrase = process.env.JARVIS_E2E_PASSPHRASE;
const databasePath = process.env.JARVIS_E2E_DATABASE_PATH;
const apiOrigin = process.env.JARVIS_E2E_API_ORIGIN ?? "http://127.0.0.1:8000";
const apiDir = resolve(process.cwd(), "../api");

function scopeForProject(project: string) {
  return project === "mobile"
    ? { domain: "dom_synthetic_b", calendar: "sim_calendar_b" }
    : { domain: "dom_synthetic_a", calendar: "sim_calendar_a" };
}

function prepareState(status: "stale" | "error", databaseCalendar: string) {
  if (!databasePath) throw new Error("Playwright deve usar banco sintético temporário explícito.");
  const result = spawnSync("uv", [
    "run", "--locked", "python", "e2e_mark_calendar_state.py", databasePath, databaseCalendar, status
  ], { cwd: apiDir, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
  if (result.status !== 0) throw new Error(`Falha ao preparar estado sintético ${status}: ${result.stderr}`);
}

async function enter(page: import("@playwright/test").Page) {
  if (!passphrase || passphrase.length < 12) throw new Error("Frase sintética de E2E ausente.");
  await page.goto("/integrado");
  await expect(page.getByTestId("local-passphrase")).toBeVisible();
  await page.getByTestId("local-passphrase").fill(passphrase);
  await page.getByTestId("local-login-submit").click();
  await expect(page.getByRole("heading", { name: "Concessões locais" })).toBeVisible();
}

async function grantAndClassify(page: import("@playwright/test").Page, domainId: string, calendarId: string) {
  const suffix = domainId.slice(-1).toUpperCase();
  await page.getByTestId("grant-domain").selectOption(domainId);
  await page.getByTestId("grant-create").click();
  await expect(page.getByTestId("grant-card").filter({ hasText: `Escopo sintético ${suffix}` })).toBeVisible();

  // The card itself is selected by its explicit stable calendar identifier.
  const calendarCard = page.locator(`[data-testid="calendar-card"][data-calendar-id="${calendarId}"]`);
  await expect(calendarCard).toBeVisible();
  await page.getByTestId(`calendar-domain-${calendarId}`).selectOption(domainId);
  const browserPut = page.waitForResponse((response) =>
    response.url().includes("/classification") && response.request().method() === "PUT"
  );
  await calendarCard.getByRole("button", { name: `Classificar ${calendarId}` }).click();
  const classificationResponse = await browserPut;
  // A cross-origin PUT with X-CSRF-Token can only reach this response after
  // Chromium accepts its CORS OPTIONS preflight.
  expect(classificationResponse.status()).toBe(200);
  await expect(calendarCard.getByText("Não sincronizado")).toBeVisible();
  return calendarCard;
}

test("API local no navegador: PUT/CORS, sync, proveniência, estados, modos e revogação", async ({ page }, testInfo) => {
  const { domain: domainForProject, calendar: calendarForProject } = scopeForProject(testInfo.project.name);
  let csrfToken: string | null = null;
  let activeGrantId: string | null = null;
  page.on("response", async (response) => {
    try {
      const body = await response.json() as Record<string, unknown>;
      if (response.url().endsWith("/real/session") && response.request().method() === "POST" && response.status() === 201) {
        csrfToken = typeof body.csrf_token === "string" ? body.csrf_token : null;
      }
      if (response.url().endsWith("/real/grants") && response.request().method() === "POST" && response.status() === 201) {
        activeGrantId = typeof body.id === "string" ? body.id : null;
      }
    } catch { /* empty responses have no JSON body */ }
  });
  await page.goto("/integrado");
  await expect(page.getByRole("heading", { name: /Agora · integração sintética/ })).toBeVisible();
  await expect(page.getByTestId("google-not-connected")).toBeVisible();

  const uniqueInvalidPhrase = `bad-e2e-${Date.now()}-never-reflect`;
  await page.getByTestId("local-passphrase").fill(uniqueInvalidPhrase);
  await page.getByTestId("local-login-submit").click();
  await expect(page.locator("p[role='alert']").first()).toBeVisible();
  await expect(page.getByText(uniqueInvalidPhrase, { exact: false })).toHaveCount(0);

  await page.getByTestId("local-passphrase").fill(passphrase ?? "");
  await page.getByTestId("local-login-submit").click();
  await expect(page.getByRole("heading", { name: "Concessões locais" })).toBeVisible();
  await expect(page.getByTestId("calendar-card")).toHaveCount(8);
  await expect(page.getByText(/^connected$/)).toHaveCount(0);

  if (domainForProject === "dom_synthetic_b") {
    await page.getByTestId("domain-filter").selectOption(domainForProject);
  }
  const calendarCard = await grantAndClassify(page, domainForProject, calendarForProject);
  await calendarCard.getByRole("button", { name: `Sincronizar ${calendarForProject}` }).click();
  await expect(calendarCard.getByText("Simulação atualizada")).toBeVisible();
  const syntheticTitle = `Compromisso sintético ${domainForProject.slice(-1).toUpperCase()}-1`;
  await expect(page.getByTestId("integrated-events").getByText(syntheticTitle)).toBeVisible();
  await page.getByText("Proveniência e verificação").first().click();
  await expect(page.getByText(/Calendar inteiramente simulado/).first()).toBeVisible();
  await expect(page.getByText(/Referência externa sintética/).first()).toBeVisible();
  await expect(page.getByText("revisão humana explícita").first()).toBeVisible();
  await expect(page.getByText("Memória local isolada · conteúdo sintético").first()).toBeVisible();
  await expect(page.getByText("Dataset: real", { exact: false })).toHaveCount(0);

  const apiCookie = (await page.context().cookies(apiOrigin)).find((cookie) => cookie.name === "jarvis_session");
  expect(apiCookie?.httpOnly).toBe(true);
  expect(apiCookie?.sameSite).toBe("Lax");
  expect(apiCookie?.secure).toBe(false); // loopback HTTP local
  expect(await page.evaluate(() => localStorage.length)).toBe(0);

  const screenshots = process.env.JARVIS_E2E_SCREENSHOT_DIR ?? resolve(process.cwd(), "../../docs/screenshots");
  mkdirSync(screenshots, { recursive: true });
  await page.getByTestId("local-event-card").first().evaluate((card) => {
    document.documentElement.style.scrollBehavior = "auto";
    const top = card.getBoundingClientRect().top + window.scrollY - 80;
    window.scrollTo(0, Math.max(0, top));
  });
  await page.getByTestId("local-event-card").first().screenshot({
    path: resolve(screenshots, `gate2-e-integrado-${testInfo.project.name}.png`)
  });

  await page.getByRole("link", { name: "Mudar para modo DEMO" }).click();
  await expect(page.getByText(/DEMO ·/).first()).toBeVisible();
  await expect(page.getByText(syntheticTitle, { exact: true })).toHaveCount(0);
  await expect(page.getByText("Daily MedSyn — revisão sprint").first()).toBeVisible();
  await page.goto("/");
  await expect(page.getByText(/DEMO ·/).first()).toBeVisible();
  await expect(page.locator("main > div.animate-fadeIn")).toHaveCSS("opacity", "1");
  await page.screenshot({ path: resolve(screenshots, `gate2-e-demo-${testInfo.project.name}.png`) });

  await page.getByRole("link", { name: "Abrir integração sintética com API local" }).click();
  await expect(page.getByRole("heading", { name: "Concessões locais" })).toBeVisible();
  if (domainForProject !== "dom_synthetic_a") {
    await expect(page.getByText(syntheticTitle, { exact: true })).toHaveCount(0);
    await page.getByTestId("domain-filter").selectOption(domainForProject);
  }
  await expect(page.getByTestId("integrated-events").getByText(syntheticTitle)).toBeVisible();

  prepareState("stale", calendarForProject);
  await page.getByRole("button", { name: "Atualizar estados" }).click();
  await expect(page.getByText(/Dados desatualizados/).first()).toBeVisible();
  await expect(page.getByText(/a ausência de itens não confirma uma agenda vazia/i)).toBeVisible();

  prepareState("error", calendarForProject);
  await page.getByRole("button", { name: "Atualizar estados" }).click();
  await expect(page.getByText("Erro na sincronização").first()).toBeVisible();
  await expect(page.getByText(/Código técnico oculto/).first()).toBeVisible();

  let releaseResponse!: () => void;
  let apiSyncFinished!: () => void;
  const responseGate = new Promise<void>((resolveGate) => { releaseResponse = resolveGate; });
  const syncFinished = new Promise<void>((resolveGate) => { apiSyncFinished = resolveGate; });
  await page.route("**/real/calendar-sim/sync", async (route) => {
    const response = await route.fetch();
    apiSyncFinished();
    await responseGate;
    try { await route.fulfill({ response }); } catch { /* browser request was invalidated after revocation */ }
  });
  const pendingSync = calendarCard.getByRole("button", { name: `Sincronizar ${calendarForProject}` }).click().catch(() => undefined);
  await syncFinished;
  const revoke = page.getByRole("button", { name: `Revogar Escopo sintético ${domainForProject.slice(-1).toUpperCase()}` });
  await revoke.click();
  await expect(page.getByTestId("integrated-events").getByText(syntheticTitle)).toHaveCount(0);
  await page.getByTestId("grant-domain").selectOption(domainForProject);
  await expect(page.getByTestId("grant-create")).toBeEnabled();
  releaseResponse();
  await pendingSync;
  await page.unroute("**/real/calendar-sim/sync");
  const deniedAfterRevocation = await page.evaluate(async ({ domainId, apiOrigin }) => {
    const response = await fetch(`${apiOrigin}/real/events?domain_id=${domainId}`, { credentials: "include" });
    return response.status;
  }, { domainId: domainForProject, apiOrigin });
  expect(deniedAfterRevocation).toBe(403);
  await expect(page.getByTestId("integrated-events").getByText(syntheticTitle)).toHaveCount(0);

  // Real API revocation out-of-band leaves the client grant view stale on
  // purpose; the following protected read must return 403 and clear UI data.
  await page.getByTestId("grant-domain").selectOption(domainForProject);
  await page.getByTestId("grant-create").click();
  await expect(page.getByTestId("grant-card")).toBeVisible();
  expect(csrfToken).toBeTruthy();
  expect(activeGrantId).toBeTruthy();
  const revokeStatus = await page.evaluate(async ({ grantId, csrf, apiOrigin }) => {
    const response = await fetch(`${apiOrigin}/real/grants/${grantId}/revoke`, {
      method: "POST", credentials: "include",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
      body: "{}"
    });
    return response.status;
  }, { grantId: activeGrantId!, csrf: csrfToken!, apiOrigin });
  expect(revokeStatus).toBe(200);
  await page.getByRole("button", { name: "Atualizar eventos autorizados" }).click();
  await expect(page.getByTestId("local-passphrase")).toBeVisible();
  await expect(page.getByText(syntheticTitle, { exact: true })).toHaveCount(0);
});

test("sessão no navegador: restauração após reload, logout e cookie expirado", async ({ page, context }) => {
  await enter(page);
  const bootstrap = page.waitForResponse((response) =>
    response.url().endsWith("/real/session") && response.request().method() === "GET" && response.status() === 200
  );
  await page.reload();
  await bootstrap;
  await expect(page.getByRole("heading", { name: "Concessões locais" })).toBeVisible();

  const cookie = (await context.cookies(apiOrigin)).find((item) => item.name === "jarvis_session");
  expect(cookie).toBeTruthy();
  await context.addCookies([{
    name: "jarvis_session", value: cookie!.value, domain: new URL(apiOrigin).hostname, path: "/",
    expires: Math.floor(Date.now() / 1000) - 1, httpOnly: true, secure: false, sameSite: "Lax"
  }]);
  await page.reload();
  await expect(page.getByTestId("local-passphrase")).toBeVisible();
  await expect(page.getByTestId("calendar-card")).toHaveCount(0);

  await page.getByTestId("local-passphrase").fill(passphrase ?? "");
  await page.getByTestId("local-login-submit").click();
  await expect(page.getByRole("button", { name: "Encerrar sessão" })).toBeVisible();
  await page.getByRole("button", { name: "Encerrar sessão" }).click();
  await expect(page.getByTestId("local-passphrase")).toBeVisible();
  expect((await context.cookies(apiOrigin)).some((item) => item.name === "jarvis_session")).toBe(false);
});
