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
    for (const width of [1440, 768, 542, 390]) {
      const height = width === 542 ? 853 : 1000;
      const page = await browser.newPage({ viewport: { width, height }, reducedMotion: "reduce" });
      const errors = [];
      const requests = [];
      page.on("pageerror", (error) => errors.push(error.message));
      page.on("request", request => requests.push(request.url()));
      await page.goto(`${base}#episode-1`, { waitUntil: "networkidle" });

      assert.equal(await page.getByRole("heading", { name: "Can the throughput leader still miss the decode floor?" }).count(), 1);
      assert.equal(await page.getByText("Recorded · exploratory · capacity not established", { exact: true }).count(), 1);
      const chooser = page.getByRole("button", { name: /Choose episode/i });
      assert.equal(await chooser.count(), 1);
      assert.equal(await page.getByText("What", { exact: true }).count(), 1);
      assert.equal(await page.getByText("Why", { exact: true }).count(), 1);
      assert.equal(await page.getByText("How", { exact: true }).count(), 1);
      assert.equal(await page.locator('nav [aria-current="page"]').count(), 2);
      assert.equal(await page.getByRole("navigation", { name: "Episode scroller" }).count(), 1);
      assert.equal(await page.getByRole("navigation", { name: "Episode scroller" }).getByRole("link", { name: /All episode summaries/ }).getAttribute("href"), "#episodes");
      assert.equal(await page.locator("nav details").filter({ hasText: "Lab tools" }).count(), 1);
      assert.equal(await page.getByRole("heading", { name: "Enough to understand the result." }).count(), 1);
      assert.equal(await page.locator(".basic-metric-ledger article").count(), 4);
      assert.equal(await page.locator(".basic-metric-ledger article").nth(0).locator(".metric-outcome.better").count(), 1);
      assert.equal(await page.locator(".basic-metric-ledger article").nth(1).locator(".metric-outcome.better").count(), 1);
      assert.match(await page.locator(".basic-metric-ledger article").nth(0).innerText(), /27\.5% · better/i);
      assert.match(await page.locator(".basic-metric-ledger article").nth(1).innerText(), /26\.8% · better/i);
      assert.equal(await page.locator(".linked-instrument").count(), 0);
      if (width === 542) {
        const responsiveLayout = await page.evaluate(() => {
          const rail = document.querySelector(".instrument-rail").getBoundingClientRect();
          const story = document.querySelector(".instrument-story").getBoundingClientRect();
          const brief = document.querySelector(".episode-basic-readout").getBoundingClientRect();
          return { railRight: rail.right, storyLeft: story.left, briefTop: brief.top, viewportHeight: window.innerHeight };
        });
        assert(responsiveLayout.railRight <= responsiveLayout.storyLeft, "the episode navigator must remain a left rail in the in-app browser pane");
        assert(responsiveLayout.briefTop < responsiveLayout.viewportHeight, "the four-signal brief must begin inside the first viewport");
      }
      assert.equal(new URL(page.url()).hash, "#episode-1?load=16&mode=deployments");
      await page.getByRole("button", { name: /Open evidence lab/ }).click();
      assert.equal(new URL(page.url()).hash, "#episode-1?load=16&mode=deployments&depth=evidence");
      assert.equal(await page.getByRole("group", { name: "Comparison mode" }).getByRole("button", { name: /Compare deployments/ }).getAttribute("aria-pressed"), "true");
      assert.equal(await page.getByRole("group", { name: "Compare measured load" }).getByRole("button").count(), 3);
      assert.equal(await page.getByRole("slider", { name: "Tested load" }).getAttribute("aria-valuetext"), "16 simulated users, measured level 2 of 3");
      assert.match(await page.getByLabel("Comparison summary").innerText(), /SGLang versus vLLM at 16 users/i);
      assert.match(await page.getByLabel("Comparison summary").innerText(), /27\.5% more output and 26\.8% lower median TTFT/i);
      assert.match(await page.getByLabel("Runtime comparison answer").innerText(), /27\.5% more output and 26\.8% lower median TTFT/i);
      assert.match(await page.locator(".instrument-readouts").innerText(), /665 \/ 666 completion-valid requests/);
      await page.getByRole("button", { name: "Pin current point" }).click();
      await page.getByRole("button", { name: /12 users/ }).click();
      assert.equal(await page.getByRole("button", { name: "Release pin" }).isEnabled(), true);
      await page.getByRole("button", { name: "Release pin" }).click();
      assert.equal(await page.getByRole("button", { name: "Pin current point" }).isEnabled(), true);
      await page.getByRole("button", { name: /24 users/ }).click();
      assert.equal(new URL(page.url()).hash, "#episode-1?load=24&mode=deployments&depth=evidence");
      await page.getByRole("button", { name: /Compare loads/ }).click();
      assert.equal(new URL(page.url()).hash, "#episode-1?load=24&mode=loads&depth=evidence");
      assert.match(await page.getByLabel("Comparison summary").innerText(), /Compared with 16 users/i);
      assert.match(await page.getByLabel("Runtime comparison answer").innerText(), /Each deployment is compared/i);
      assert.equal(await page.locator(".instrument-data-table").count(), 1);
      assert.equal(await page.locator(".instrument-metric-explanation").count() >= 2, true);
      await page.getByRole("button", { name: "Explain Visible TTFT p50" }).click();
      assert.match(await page.getByLabel("Metric explanation").innerText(), /Median client-visible time to first token/i);
      assert.match(await page.getByLabel("Metric explanation").innerText(), /Lower is better/i);
      assert.match(await page.getByLabel("Decode p10 threshold").innerText(), /90% of valid requests decoded at least this fast/i);
      assert.match(await page.getByLabel("Decode p10 threshold").innerText(), /threshold missed/i);
      const publicText = (await page.locator("body").innerText()).toLowerCase();
      for (const forbidden of ["0.31.0", "0.5.21", "run_id", "service_instance", "/users/", "configuration matrix", "qwen3.8", "fp8 weights", "kv cache"]) {
        assert.equal(publicText.includes(forbidden), false, `public Episode 01 text leaked ${forbidden}`);
      }
      assert.equal(await page.locator('[aria-label="Comparison summary"][aria-live="polite"]').count(), 1);
      assert.equal(await page.locator(".selection-ruler").first().evaluate(node => getComputedStyle(node).transitionDuration), "0s");
      await chooser.click();
      assert.equal(await chooser.getAttribute("aria-expanded"), "true");
      await page.keyboard.press("Escape");
      assert.equal(await chooser.getAttribute("aria-expanded"), "false");
      assert.equal(await chooser.evaluate(node => node === document.activeElement), true);
      await page.getByRole("button", { name: /Back to the episode brief/ }).click();
      assert.equal(new URL(page.url()).hash, "#episode-1?load=24&mode=loads");
      assert.equal(await page.locator(".linked-instrument").count(), 0);
      assert.equal(await page.locator(".episode-basic-readout").count(), 1);
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
