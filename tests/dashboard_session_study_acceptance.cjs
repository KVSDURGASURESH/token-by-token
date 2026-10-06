const { chromium } = require("../dashboard/node_modules/playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const url = process.argv[2];
if (!url) throw new Error("usage: node tests/dashboard_session_study_acceptance.cjs <dashboard-url>");
const base = url.replace(/#.*$/, "");
const screenshotDir = process.env.DASHBOARD_SCREENSHOT_DIR;

(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  });
  try {
    for (const width of [1440, 768, 390]) {
      const page = await browser.newPage({ viewport: { width, height: 900 }, colorScheme: "dark" });
      const errors = [];
      const requests = [];
      page.on("pageerror", (error) => errors.push(error.message));
      page.on("request", (request) => requests.push(request.url()));

      await page.goto(`${base}#session-study`, { waitUntil: "networkidle" });
      assert.equal(await page.title(), "Session capacity field note — INFERENCE LAB");
      assert.equal(await page.getByRole("heading", { name: /Three percent more output/i }).count(), 1);
      assert.equal(await page.getByText("Capacity not established", { exact: true }).count(), 1);
      assert.equal(await page.locator(".session-plot").count(), 3);
      assert.match(await page.getByLabel("Deployment comparison boundary").innerText(), /Serving profiles, launch flags and internal optimization recipes/i);
      assert.equal(await page.locator('[aria-label="Previous study comparison table"] tbody tr').count() > 4, true);
      assert.match(await page.locator(".tension-lanes").innerText(), /359\.81.*371\.32/s);
      assert.match(await page.locator(".tension-lanes").innerText(), /1\.17.*22\.23/s);
      const palette = await page.evaluate(() => {
        const main = document.querySelector("main");
        const legend = [...document.querySelectorAll(".session-legend i")];
        return {
          page: main ? getComputedStyle(main).backgroundColor : "",
          ink: main ? getComputedStyle(main).color : "",
          comparison: legend.slice(0, 2).map((node) => getComputedStyle(node).backgroundColor),
        };
      });
      assert.equal(palette.page, "rgb(8, 10, 11)");
      assert.equal(palette.ink, "rgb(242, 245, 239)");
      assert.deepEqual(palette.comparison, ["rgb(255, 112, 67)", "rgb(69, 214, 174)"]);
      const loadControl = page.getByRole("group", { name: "Compare measured load" });
      assert.equal(await loadControl.getByRole("button").count(), 7);
      assert.equal(await loadControl.getByRole("button", { name: "16 users" }).getAttribute("aria-pressed"), "true");
      await loadControl.getByRole("button", { name: "32 users" }).click();
      const selectedComparison = page.locator('[aria-label="Selected sweep comparison"]');
      assert.match(await selectedComparison.innerText(), /H200.*258\.45.*8\.88.*45\.18.*16\.91%.*521 \/ 627/s);
      assert.match(await selectedComparison.innerText(), /RTX PRO 6000.*228\.46.*17\.88.*20\.46.*0\.39%.*511 \/ 513/s);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth), false);
      assert.deepEqual(errors, []);
      assert(requests.every((request) => new URL(request).origin === new URL(base).origin));

      if (screenshotDir) {
        fs.mkdirSync(screenshotDir, { recursive: true });
        await page.screenshot({ path: path.join(screenshotDir, `session-study-${width}.png`), fullPage: true });
      }
      await page.close();
      console.log(`Session study passed at ${width}px: evidence, tables, charts, no overflow, local-only requests.`);
    }
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
