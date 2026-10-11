const { chromium } = require("../dashboard/node_modules/playwright");
const assert = require("node:assert/strict");

const url = process.argv[2];
if (!url) throw new Error("usage: node tests/dashboard_methodology_acceptance.cjs <dashboard-url>");
const base = url.replace(/#.*$/, "");

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" });
  try {
    for (const width of [1440, 768, 390]) {
      const page = await browser.newPage({ viewport: { width, height: 1000 }, reducedMotion: "reduce" });
      const errors = [];
      const requests = [];
      page.on("pageerror", error => errors.push(error.message));
      page.on("request", request => requests.push(request.url()));
      await page.goto(`${base}#methodology`, { waitUntil: "networkidle" });

      assert.equal(await page.getByRole("heading", { level: 1 }).count(), 1);
      assert.match(await page.getByRole("heading", { level: 1 }).innerText(), /benchmark the session/i);
      assert.equal(await page.getByRole("navigation", { name: "Methodology chapters" }).getByRole("button").count(), 7);
      assert.match(await page.locator(".population-strata").innerText(), /50%[\s\S]*30%[\s\S]*20%/);

      const layers = page.getByRole("group", { name: "Request anatomy layers" }).getByRole("button");
      assert.equal(await layers.count(), 6);
      await layers.nth(3).click();
      assert.equal(await layers.nth(3).getAttribute("aria-pressed"), "true");

      const slider = page.getByRole("slider", { name: "Scrub the replay" });
      await slider.focus();
      await page.keyboard.press("End");
      assert.equal(await slider.getAttribute("aria-valuetext"), "human gap");
      assert.equal(await page.locator('.replay-transcript li[aria-current="step"]').innerText().then(text => /human gap/i.test(text)), true);

      assert.equal(await page.locator(".evidence-views section").count(), 3);
      assert.match(await page.locator(".evidence-views").innerText(), /static approved aggregates/i);
      assert.match(await page.locator(".definition-ledger").innerText(), /TTFT[\s\S]*TPOT[\s\S]*Decode tok\/s/i);
      assert.match(await page.locator(".method-boundary").innerText(), /Observed[\s\S]*Not established/i);
      const publicText = (await page.locator("body").innerText()).toLowerCase();
      for (const forbidden of ["service_instance", "run_id", "/users/", "mirastacklabs", "agentbench"]) assert.equal(publicText.includes(forbidden), false);

      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth), false);
      assert.deepEqual(errors, []);
      assert(requests.every(request => new URL(request).origin === new URL(base).origin));
      await page.close();
      console.log(`Methodology passed at ${width}px: content, keyboard controls, offline requests, no overflow.`);
    }
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
