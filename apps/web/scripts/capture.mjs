import { chromium } from 'playwright';
import { spawn } from 'child_process';
import { setTimeout as sleep } from 'timers/promises';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const webDir = path.resolve(__dirname, '..');
const outDir = path.resolve(webDir, '..', '..', 'docs', 'screenshots');
const depoisDir = path.join(outDir, 'depois');
fs.mkdirSync(outDir, { recursive: true });
fs.mkdirSync(depoisDir, { recursive: true });
const baseURL = 'http://localhost:3000';

async function waitForServer(url, timeout = 30000) {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    try {
      const res = await fetch(url);
      if (res.ok) return true;
    } catch {}
    await sleep(500);
  }
  throw new Error('Server not ready ' + url);
}

async function save(page, name, opts = { fullPage: true }) {
  const file = path.join(outDir, name);
  await page.screenshot({ path: file, ...opts });
  fs.copyFileSync(file, path.join(depoisDir, name));
  console.log('  saved', name);
}

async function run() {
  let server = null;
  let reused = false;
  try {
    await waitForServer(baseURL, 2000);
    reused = true;
    console.log('Reusing existing server at', baseURL);
  } catch {
    console.log('Starting next start from', webDir);
    server = spawn(path.join(webDir, 'node_modules/.bin/next'), ['start', '--port', '3000'], {
      cwd: webDir,
      stdio: 'inherit',
      env: { ...process.env, PORT: '3000' }
    });
    await sleep(3000);
    await waitForServer(baseURL, 30000);
  }
  console.log('Server ready');

  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const viewports = [
    { name: 'desktop', width: 1280, height: 800 },
    { name: 'mobile', width: 390, height: 844 }
  ];
  const pages = [
    { path: '/', name: '01-agora' },
    { path: '/conversa', name: '02-conversa' },
    { path: '/inbox', name: '03-inbox' },
    { path: '/dominios', name: '04-dominios' },
    { path: '/aprovacoes', name: '05-aprovacoes' },
    { path: '/fontes', name: '06-fontes' }
  ];

  for (const vp of viewports) {
    const context = await browser.newContext({ viewport: { width: vp.width, height: vp.height }, deviceScaleFactor: 2 });
    const page = await context.newPage();
    for (const p of pages) {
      console.log(`Capturing ${vp.name} ${p.name}`);
      await page.goto(baseURL + p.path, { waitUntil: 'networkidle' });
      await page.waitForTimeout(400);
      await save(page, `${p.name}-${vp.name}.png`, { fullPage: true });
      if (vp.name === 'mobile') {
        await save(page, `${p.name}-${vp.name}-viewport.png`, { fullPage: false });
      }
    }
    await page.goto(baseURL + '/nao-existe-404', { waitUntil: 'networkidle' });
    await page.waitForTimeout(400);
    await save(page, `07-erro-404-${vp.name}.png`, { fullPage: true });
    await context.close();
  }

  const context2 = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 2 });
  const page2 = await context2.newPage();
  await page2.goto(baseURL + '/', { waitUntil: 'networkidle' });
  await page2.getByRole('button', { name: /Por que isso importa/i }).first().click();
  await page2.waitForTimeout(400);
  await save(page2, '08-drawer-proveniencia-desktop.png', { fullPage: false });
  await page2.goto(baseURL + '/aprovacoes', { waitUntil: 'networkidle' });
  await page2.waitForTimeout(400);
  await save(page2, '09-aprovacao-pendente-desktop.png', { fullPage: true });
  await context2.close();

  const context3 = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
  const page3 = await context3.newPage();
  await page3.goto(baseURL + '/aprovacoes', { waitUntil: 'networkidle' });
  await page3.waitForTimeout(400);
  await save(page3, '09-aprovacao-pendente-mobile.png', { fullPage: true });
  await save(page3, '09-aprovacao-pendente-mobile-viewport.png', { fullPage: false });
  await context3.close();

  await browser.close();
  if (server && !reused) server.kill('SIGTERM');
  console.log('Done');
}

run().catch((e) => {
  console.error(e);
  process.exit(1);
});
