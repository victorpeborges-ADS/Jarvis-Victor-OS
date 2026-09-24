import { spawn } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import net from "node:net";
import { tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const webDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const apiDir = resolve(webDir, "../api");
const passphrase = "synthetic-e2e-only-passphrase-2026";
const webOrigin = process.env.JARVIS_E2E_WEB_ORIGIN ?? "http://127.0.0.1:3000";

function requireLocalOrigin(value, expectedPort, label) {
  let url;
  try { url = new URL(value); }
  catch { throw new Error(`${label} deve ser uma origem loopback explícita.`); }
  const host = url.hostname.toLowerCase();
  if (url.protocol !== "http:" || !["127.0.0.1", "localhost", "[::1]"].includes(host) || url.port !== expectedPort || url.username || url.password || url.pathname !== "/" || url.search || url.hash) {
    throw new Error(`${label} deve usar loopback HTTP na porta ${expectedPort}.`);
  }
  return url.origin;
}

const checkedWebOrigin = requireLocalOrigin(webOrigin, "3000", "Origem web E2E");
const apiHost = new URL(checkedWebOrigin).hostname;
const apiOrigin = requireLocalOrigin(
  process.env.JARVIS_E2E_API_ORIGIN ?? `http://${apiHost}:8000`,
  "8000",
  "Origem da API E2E"
);
if (new URL(apiOrigin).hostname !== apiHost) {
  throw new Error("A página e a API E2E devem usar o mesmo hostname loopback para o cookie SameSite=Lax.");
}
const tempDir = mkdtempSync(resolve(tmpdir(), "jarvis-gate-e2e-"));
const databasePath = resolve(tempDir, "memory.sqlite3");
const apiEnv = {
  ...process.env,
  JARVIS_BIND_HOST: "127.0.0.1",
  JARVIS_BIND_PORT: "8000",
  JARVIS_DATABASE_PATH: databasePath,
  JARVIS_LOCAL_PASSPHRASE: passphrase,
  JARVIS_E2E_DATABASE_PATH: databasePath,
  JARVIS_E2E_PASSPHRASE: passphrase
};

function ensurePortAvailable(port) {
  return new Promise((resolvePromise, reject) => {
    const server = net.createServer();
    server.once("error", () => reject(new Error(`Porta ${port} já está ocupada; não reutilize servidores externos no E2E.`)));
    server.listen(port, "127.0.0.1", () => server.close(resolvePromise));
  });
}

async function waitForApi(child) {
  const deadline = Date.now() + 60_000;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) throw new Error(`API sintética encerrou antes de ficar pronta (exit ${child.exitCode}).`);
    try {
      const response = await fetch("http://127.0.0.1:8000/health", { signal: AbortSignal.timeout(1000) });
      if (response.ok) return;
    } catch { /* wait for the local runner */ }
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 250));
  }
  throw new Error("Tempo esgotado ao iniciar a API sintética em loopback.");
}

function stopProcess(child) {
  if (!child || child.exitCode !== null) return Promise.resolve();
  return new Promise((resolvePromise) => {
    const timer = setTimeout(() => {
      try { process.kill(-child.pid, "SIGKILL"); } catch { /* process already stopped */ }
      resolvePromise();
    }, 5000);
    child.once("exit", () => { clearTimeout(timer); resolvePromise(); });
    try { process.kill(-child.pid, "SIGTERM"); } catch { clearTimeout(timer); resolvePromise(); }
  });
}

let api;
let playwright;
let exitCode = 1;
try {
  await ensurePortAvailable(8000);
  api = spawn("uv", ["run", "--locked", "--project", apiDir, "python", "serve.py"], {
    cwd: apiDir,
    env: apiEnv,
    detached: true,
    stdio: "ignore"
  });
  await waitForApi(api);

  const playwrightEnv = {
    ...apiEnv,
    JARVIS_E2E_WEB_ORIGIN: checkedWebOrigin,
    JARVIS_E2E_API_ORIGIN: apiOrigin,
    JARVIS_E2E_DATABASE_PATH: databasePath,
    JARVIS_E2E_PASSPHRASE: passphrase
  };
  playwright = spawn(process.execPath, [resolve(webDir, "node_modules/@playwright/test/cli.js"), "test", ...process.argv.slice(2)], {
    cwd: webDir,
    env: playwrightEnv,
    stdio: "inherit"
  });
  exitCode = await new Promise((resolvePromise, reject) => {
    playwright.once("error", reject);
    playwright.once("exit", (code, signal) => resolvePromise(code ?? (signal ? 1 : 0)));
  });
} catch (error) {
  process.stderr.write(`${error instanceof Error ? error.message : "E2E local failed"}\n`);
} finally {
  await stopProcess(playwright);
  await stopProcess(api);
  try { rmSync(tempDir, { recursive: true }); }
  catch (error) { if (error?.code !== "ENOENT") throw error; }
}
process.exitCode = exitCode;
