const { chromium } = require("../dashboard/node_modules/playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const url = process.argv[2];
if (!url) throw new Error("usage: node tests/dashboard_series_acceptance.cjs <dashboard-url>");
const base = url.replace(/#.*$/, "");

(async () => {
  const browser = await chromium.launch({ headless: true,
    executablePath: process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" });
  try {
    for (const width of [1440, 390]) {
      const page = await browser.newPage({ viewport: { width, height: 900 } });
      const errors = [], requests = [];
      page.on("pageerror", error => errors.push(error.message));
      page.on("request", request => requests.push(request.url()));
      await page.goto(base, { waitUntil: "networkidle" });
      assert.equal(await page.title(), "Token by Token — Inference Lab");
      assert.equal(await page.getByRole("heading", { name: "Table of contents" }).count(), 1);
      assert.equal(await page.getByText("936", { exact: true }).count(), 0);
      assert(await page.locator(".lab-logo").evaluate(img => img.complete && img.naturalWidth > 0));
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      if (process.env.DASHBOARD_SCREENSHOT_DIR) {
        fs.mkdirSync(process.env.DASHBOARD_SCREENSHOT_DIR, { recursive: true });
        await page.screenshot({ path: path.join(process.env.DASHBOARD_SCREENSHOT_DIR, `series-${width}.png`), fullPage: true });
      }
      await page.getByRole("link", { name: "Explore results", exact: true }).click();
      await page.getByText("936", { exact: true }).first().waitFor();
      assert.equal(new URL(page.url()).hash, "#episode-0");
      assert(await page.locator(".published-study-table").isVisible());
      await page.getByRole("link", { name: "All episodes", exact: true }).click();
      await page.getByRole("heading", { name: "Table of contents" }).waitFor();
      await page.goBack();
      await page.getByText("936", { exact: true }).first().waitFor();
      await page.goto(`${base}#recorded-study`, { waitUntil: "networkidle" });
      await page.getByText("936", { exact: true }).first().waitFor();
      assert.deepEqual(errors, []);
      assert(requests.every(request => new URL(request).origin === new URL(base).origin));
      await page.close();
      console.log(`Series navigation passed at ${width}px: index, logo, study, return, browser back, legacy link, local-only requests.`);
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
