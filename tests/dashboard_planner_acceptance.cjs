const { chromium } = require("../dashboard/node_modules/playwright");

(async () => {
  const browser = await chromium.launch({ headless: true,
    executablePath: process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" });
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const requests = [];
  page.on("request", request => requests.push(request.url()));
  await page.goto("http://127.0.0.1:5173/#experiment-planner?episode=3");
  await page.waitForSelector(".planner-summary code:not(:has-text('Computing'))");
  if (await page.locator("text=No GPU will be created").count() !== 1) throw new Error("Missing permanent safety label");
  if (await page.locator("button", { hasText: /Run|Launch|Execute/ }).count()) throw new Error("Planner exposes execution action");
  const before = await page.locator(".planner-summary code").textContent();
  await page.getByLabel("Requests").fill("129");
  await page.waitForTimeout(100);
  const after = await page.locator(".planner-summary code").textContent();
  if (before === after) throw new Error("Digest did not change after an edit");
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
  if (overflow) throw new Error("Planner overflows at 390px");
  if (requests.some(url => /runpod|\/api\/run|\/api\/quick-test/.test(url))) throw new Error("Planner generated provider or execution traffic");
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.reload();
  if (await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)) throw new Error("Planner overflows at 1440px");
  await browser.close();
  console.log("dashboard planner acceptance passed");
})().catch(error => { console.error(error); process.exit(1); });
