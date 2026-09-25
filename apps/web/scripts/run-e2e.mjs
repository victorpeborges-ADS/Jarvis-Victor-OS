import { spawn, spawnSync } from "node:child_process";
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
  const port = Number(url.port);
  if (url.protocol !== "http:" || !["127.0.0.1", "localhost", "[::1]"].includes(host) || url.port !== expectedPort || !Number.isInteger(port) || port < 1 || port > 65535 || url.username || url.password || url.pathname !== "/" || url.search || url.hash) {
    throw new Error(`${label} deve usar loopback HTTP na porta ${expectedPort}.`);
  }
  return url.origin;
}

function bindHostFor(origin) {
  const hostname = new URL(origin).hostname.toLowerCase();
  return hostname === "localhost" ? "127.0.0.1" : hostname.replace(/^\[|\]$/g, "");
}

const checkedWebOrigin = requireLocalOrigin(webOrigin, "3000", "Origem web E2E");
const apiHost = new URL(checkedWebOrigin).hostname;
const apiOrigin = requireLocalOrigin(process.env.JARVIS_E2E_API_ORIGIN ?? `http://${apiHost}:8000`, "8000", "Origem da API E2E");
if (new URL(apiOrigin).hostname !== apiHost) {
  throw new Error("A página e a API E2E devem usar o mesmo hostname loopback para o cookie SameSite=Lax.");
}
const webUrl = new URL(checkedWebOrigin);
const apiUrl = new URL(apiOrigin);
if (webUrl.port === apiUrl.port) throw new Error("As portas web e API E2E devem ser diferentes.");
const webPort = Number(webUrl.port);
const apiPort = Number(apiUrl.port);
const webBindHost = bindHostFor(checkedWebOrigin);
const apiBindHost = bindHostFor(apiOrigin);
const apiEnv = {
  ...Object.fromEntries(Object.entries(process.env).filter(([key]) => !/^JARVIS_/i.test(key) && !/(?:^|_)(?:token|secret|password|passphrase|credential|cookie|authorization|private_key|api_key|access_key)(?:_|$)/i.test(key))),
  JARVIS_BIND_HOST: apiBindHost,
  JARVIS_BIND_PORT: String(apiPort),
  JARVIS_LOCAL_PASSPHRASE: passphrase
};

function ensurePortAvailable(port, host, label) {
  return new Promise((resolvePromise, reject) => {
    const server = net.createServer();
    server.once("error", () => reject(new Error(`Porta ${label} ${port} já está ocupada; escolha outra porta loopback para o E2E.`)));
    server.listen(port, host, () => server.close(resolvePromise));
  });
}

async function waitForApi(child) {
  const deadline = Date.now() + 60_000;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) throw new Error(`API sintética encerrou antes de ficar pronta (exit ${child.exitCode}).`);
    try {
      const response = await fetch(`${apiOrigin}/health`, { signal: AbortSignal.timeout(1000) });
      if (response.ok) return;
    } catch { /* wait for the local runner */ }
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 250));
  }
  throw new Error("Tempo esgotado ao iniciar a API sintética em loopback.");
}

async function waitForWeb(child, getOutput) {
  const deadline = Date.now() + 60_000;
  while (Date.now() < deadline) {
    const output = getOutput();
    if (child.exitCode !== null) throw new Error(`Next sintético encerrou antes de ficar pronto (exit ${child.exitCode}): ${output.slice(-2000)}`);
    if (output.includes("Ready in")) return;
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 100));
  }
  throw new Error(`Tempo esgotado ao iniciar Next em loopback: ${getOutput().slice(-2000)}`);
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
let web;
let playwright;
let tempDir;
let exitCode = 1;
try {
  await ensurePortAvailable(apiPort, apiBindHost, "API");
  await ensurePortAvailable(webPort, webBindHost, "web");

  const webEnv = {
    ...Object.fromEntries(Object.entries(apiEnv).filter(([key]) => !/^JARVIS_/i.test(key))),
    NEXT_PUBLIC_JARVIS_API_URL: apiOrigin
  };
  const build = spawnSync("npm", ["run", "build"], { cwd: webDir, env: webEnv, stdio: "inherit", timeout: 300_000 });
  if (build.error || build.status !== 0) throw new Error(`Build web sintético falhou${build.error ? `: ${build.error.message}` : ` (exit ${build.status})`}.`);

  tempDir = mkdtempSync(resolve(tmpdir(), "jarvis-gate-e2e-"));
  const databasePath = resolve(tempDir, "memory.sqlite3");
  Object.assign(apiEnv, {
    JARVIS_DATABASE_PATH: databasePath,
    JARVIS_E2E_DATABASE_PATH: databasePath,
    JARVIS_E2E_PASSPHRASE: passphrase
  });

  api = spawn("uv", ["run", "--locked", "--project", apiDir, "python", "serve.py"], {
    cwd: apiDir,
    env: apiEnv,
    detached: true,
    stdio: "ignore"
  });
  await waitForApi(api);

  let webOutput = "";
  web = spawn(process.execPath, [
    resolve(webDir, "node_modules/next/dist/bin/next"), "start",
    "--hostname", webBindHost, "--port", String(webPort)
  ], {
    cwd: webDir,
    env: webEnv,
    detached: true,
    stdio: ["ignore", "pipe", "pipe"]
  });
  const collectWebOutput = (chunk) => {
    const value = chunk.toString();
    webOutput = `${webOutput}${value}`.slice(-8000);
    process.stdout.write(value);
  };
  web.stdout.on("data", collectWebOutput);
  web.stderr.on("data", collectWebOutput);
  await waitForWeb(web, () => webOutput);

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
    detached: true,
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
  await stopProcess(web);
  await stopProcess(api);
  try { if (tempDir) rmSync(tempDir, { recursive: true }); }
  catch (error) { if (error?.code !== "ENOENT") throw error; }
}
process.exitCode = exitCode;
