import { chromium } from '../../../dashboard/node_modules/playwright/index.mjs';
import { pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(import.meta.dirname);
const browser = await chromium.launch({
  headless: true,
  executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
});
const page = await browser.newPage({ viewport: { width: 1080, height: 1350 }, deviceScaleFactor: 1 });
await page.goto(pathToFileURL(path.join(root, 'storyboard.html')).href);
await page.evaluate(async () => document.fonts.ready);

for (let scene = 0; scene < 7; scene += 1) {
  await page.evaluate((index) => {
    for (const el of document.querySelectorAll('.scene')) {
      el.classList.toggle('active', el.dataset.scene === String(index));
    }
  }, scene);
  await page.screenshot({ path: path.join(root, `scene-${scene}.png`) });
}

await browser.close();
