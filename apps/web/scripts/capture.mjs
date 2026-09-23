import { chromium } from 'playwright';
import { spawn } from 'child_process';
import { setTimeout as sleep } from 'timers/promises';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const webDir = path.resolve(__dirname, '..');
const outDir = path.resolve(webDir, '..', '..', 'docs', 'screenshots');
fs.mkdirSync(outDir, { recursive: true });
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

async function run() {
  console.log('Starting next start from', webDir);
  const server = spawn(path.join(webDir, 'node_modules/.bin/next'), ['start', '--port', '3000'], {
    cwd: webDir,
    stdio: 'inherit',
    env: { ...process.env, PORT: '3000' }
  });

  await sleep(3000);
  await waitForServer(baseURL, 30000);
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
      const url = baseURL + p.path;
      console.log(`Capturing ${vp.name} ${p.name} -> ${url}`);
      await page.goto(url, { waitUntil: 'networkidle' });
      await page.waitForTimeout(500);
      const file = path.join(outDir, `${p.name}-${vp.name}.png`);
      await page.screenshot({ path: file, fullPage: true });
      console.log('  saved', file);
    }
    // erro 404
    await page.goto(baseURL + '/nao-existe-404', { waitUntil: 'networkidle' });
    await page.waitForTimeout(500);
    await page.screenshot({ path: path.join(outDir, `07-erro-404-${vp.name}.png`), fullPage: true });
    await context.close();
  }

  // drawer proveniencia
  const context2 = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page2 = await context2.newPage();
  await page2.goto(baseURL + '/', { waitUntil: 'networkidle' });
  await page2.getByRole('button', { name: /Ver por que isso importa/i }).first().click();
  await page2.waitForTimeout(500);
  await page2.screenshot({ path: path.join(outDir, `08-drawer-proveniencia-desktop.png`), fullPage: false });
  // pending aprovacoes já em 05, mas capturar detalhe com aprovação pendente highlight
  await page2.goto(baseURL + '/aprovacoes', { waitUntil: 'networkidle' });
  await page2.waitForTimeout(500);
  await page2.screenshot({ path: path.join(outDir, `09-aprovacao-pendente-desktop.png`), fullPage: true });
  await context2.close();

  const context3 = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page3 = await context3.newPage();
  await page3.goto(baseURL + '/aprovacoes', { waitUntil: 'networkidle' });
  await page3.waitForTimeout(500);
  await page3.screenshot({ path: path.join(outDir, `09-aprovacao-pendente-mobile.png`), fullPage: true });
  await context3.close();

  await browser.close();
  server.kill('SIGTERM');
  console.log('Done');
}

run().catch(e => { console.error(e); process.exit(1); });
