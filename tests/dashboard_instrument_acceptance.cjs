const { chromium } = require("../dashboard/node_modules/playwright");
const assert = require("node:assert/strict");

const url = process.argv[2];
if (!url) throw new Error("usage: node tests/dashboard_instrument_acceptance.cjs <dashboard-url>");
const base = url.replace(/#.*$/, "");

(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  });
  try {
    for (const width of [1440, 768, 390]) {
      const page = await browser.newPage({ viewport: { width, height: 1000 }, reducedMotion: "reduce" });
      const errors = [];
      const requests = [];
      page.on("pageerror", (error) => errors.push(error.message));
      page.on("request", request => requests.push(request.url()));
      await page.goto(`${base}#episode-1`, { waitUntil: "networkidle" });

      assert.equal(await page.getByRole("heading", { name: "Which runtime configuration serves this H200 workload better?" }).count(), 1);
      assert.equal(await page.getByText("Recorded · exploratory · capacity not established", { exact: true }).count(), 1);
      const chooser = page.getByRole("button", { name: /Choose episode/i });
      assert.equal(await chooser.count(), 1);
      assert.equal(await page.getByText("What", { exact: true }).count(), 1);
      assert.equal(await page.getByText("Why", { exact: true }).count(), 1);
      assert.equal(await page.getByText("How", { exact: true }).count(), 1);
      assert.equal(await page.locator('nav [aria-current="page"]').count(), 1);
      assert.equal(await page.locator("nav details").filter({ hasText: "Lab tools" }).count(), 1);
      await page.getByRole("button", { name: /Linked evidence/ }).click();
      assert.equal(new URL(page.url()).hash, "#episode-1");
      assert.equal(await page.getByRole("group", { name: "Compare measured load" }).getByRole("button").count(), 3);
      assert.equal(await page.getByRole("slider", { name: "Tested load" }).getAttribute("aria-valuetext"), "16 simulated users, measured level 2 of 3");
      assert.match(await page.getByLabel("Comparison summary").innerText(), /Compared with 12 users/i);
      assert.match(await page.getByLabel("Comparison summary").innerText(), /vLLM 0\.31\.0: \+0\.5% output, \+19\.9% visible TTFT/);
      await page.getByRole("button", { name: /24 users/ }).click();
      assert.match(await page.getByLabel("Comparison summary").innerText(), /Compared with 16 users/i);
      assert.equal(await page.locator(".instrument-data-table").count(), 1);
      assert.equal(await page.locator(".instrument-metric-explanation").count() >= 2, true);
      assert.equal(await page.locator('[aria-live="polite"]').count(), 1);
      assert.equal(await page.locator(".selection-ruler").first().evaluate(node => getComputedStyle(node).transitionDuration), "0s");
      await chooser.click();
      assert.equal(await chooser.getAttribute("aria-expanded"), "true");
      await page.keyboard.press("Escape");
      assert.equal(await chooser.getAttribute("aria-expanded"), "false");
      assert.equal(await chooser.evaluate(node => node === document.activeElement), true);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth), false);
      assert.deepEqual(errors, []);
      assert(requests.every(request => new URL(request).origin === new URL(base).origin));
      await page.close();
      console.log(`Episode instrument passed at ${width}px: evidence, interaction, reduced motion, no overflow.`);
    }
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
