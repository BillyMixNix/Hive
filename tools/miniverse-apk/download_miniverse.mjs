import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const OUT = path.resolve('winlator-app/app/src/main/assets/miniverse.zip');
const URL = 'https://ponywolf.itch.io/miniverse/purchase';
fs.mkdirSync(path.dirname(OUT), { recursive: true });
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ acceptDownloads: true });
const page = await context.newPage();
try {
  console.log('Opening official Ponywolf Miniverse download page...');
  await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 120000 });
  await page.waitForSelector('a.direct_download_btn', { timeout: 60000 });
  const direct = page.locator('a.direct_download_btn').first();
  await Promise.all([page.waitForLoadState('domcontentloaded').catch(() => {}), direct.click()]);
  await page.waitForTimeout(2500);
  const selectors = ['a.download_btn','a.button.download_btn','a[href*="/download/"]','a[href*="upload_id"]'];
  let link = null;
  for (const selector of selectors) {
    const loc = page.locator(selector);
    if (await loc.count()) { link = loc.first(); console.log(`Found ${selector}`); break; }
  }
  if (!link) {
    console.error((await page.content()).slice(0, 30000));
    throw new Error('Could not find Miniverse download button');
  }
  const href = await link.getAttribute('href');
  if (href) {
    const absolute = new URL(href, page.url()).toString();
    const response = await context.request.get(absolute, { timeout: 180000 });
    if (!response.ok()) throw new Error(`Download HTTP ${response.status()}`);
    fs.writeFileSync(OUT, await response.body());
  } else {
    const dlPromise = page.waitForEvent('download', { timeout: 180000 });
    await link.click();
    const dl = await dlPromise;
    await dl.saveAs(OUT);
  }
  const size = fs.statSync(OUT).size;
  console.log(`Saved ${OUT} (${size} bytes)`);
  if (size < 50_000_000) throw new Error(`Downloaded file is unexpectedly small (${size} bytes)`);
} finally {
  await browser.close();
}
