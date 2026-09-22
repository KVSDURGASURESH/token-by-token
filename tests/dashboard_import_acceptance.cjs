const { chromium } = require("../dashboard/node_modules/playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const url = process.argv[2];
if (!url) throw new Error("usage: node tests/dashboard_import_acceptance.cjs <dashboard-url>");
const screenshotDir = process.env.DASHBOARD_SCREENSHOT_DIR;
const metric = (p50, p95 = p50, p99 = p95) => ({ available: true, p50, p95, p99 });
const unavailable = { available: false, p50: null, p95: null, p99: null };
const fixture = {
  schema_version: 1, classification: "synthetic browser-test fixture",
  model: "fixture/model", model_revision: "fixture-revision", gpu: "fixture GPU", precision: "BF16",
  cells: [1, 2, 3].map((rep) => ({
    cell_id: `fixture-${rep}`, runtime: "vllm", profile: "128tok-c4", repetition: rep,
    successful_requests: 10, failed_requests: rep === 2 ? 1 : 0, successful_output_tokens: 320,
    output_tokens_per_second: rep === 3 ? null : rep * 100,
    client_ttft_ms: rep === 3 ? unavailable : metric(rep * 1000, rep * 1500, rep * 2000),
    client_tpot_ms: metric(12), client_e2e_ms: metric(1500),
  })),
};
const telemetry = {
  schema_version: 1, classification: "runtime_native_telemetry_summary", runtime: "vllm",
  sample_count: 4, window_seconds: 3,
  native_window: { prefill_seconds_per_request: 0.25, decode_seconds_per_request: null },
  metric_samples: { kv_cache_usage: { sample_count: 4, min: 0.1, mean: 0.3, p95: 0.5, max: 0.6 } },
};
const file = (name, value) => ({ name, mimeType: "application/json", buffer: Buffer.from(typeof value === "string" ? value : JSON.stringify(value)) });

(async () => {
  const browser = await chromium.launch({ headless: true,
    executablePath: process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" });
  const checks = [];
  try {
    for (const width of [1440, 390]) {
      const page = await browser.newPage({ viewport: { width, height: 900 } });
      const errors = [], requests = [];
      page.on("pageerror", (error) => errors.push(error.message));
      page.on("request", (request) => requests.push(request.url()));
      await page.goto(`${url.replace(/#.*$/, "")}#local-results`, { waitUntil: "networkidle" });
      assert.equal(await page.title(), "Local results — INFERENCE LAB");
      await page.locator("#result-file").setInputFiles(file("fixture.json", fixture));
      await page.locator(".reader-point").first().waitFor();
      const rows = page.locator('[aria-label="Imported benchmark rows"] tbody tr');
      assert.equal(await rows.count(), 3);
      assert.deepEqual(await rows.locator("td:nth-child(2)").allTextContents(), ["1", "2", "3"]);
      assert.equal(await rows.nth(1).locator("td:nth-child(3)").textContent(), "10 / 11");
      assert.equal(await page.locator(".reader-point").count(), 2);
      const circles = await page.locator(".reader-point circle").evaluateAll((nodes) => nodes.map((node) => ({ x: +node.getAttribute("cx"), y: +node.getAttribute("cy") })));
      assert(circles[1].x > circles[0].x && circles[1].y < circles[0].y, "Axes must map larger TTFT right and larger rate up.");
      assert.equal(await rows.nth(2).getByText("Unavailable", { exact: false }).count() > 0, true);
      assert.equal(await page.getByText("936", { exact: true }).count(), 0);
      await page.locator("#runtime-file").setInputFiles(file("telemetry.json", telemetry));
      await page.getByRole("heading", { name: "vllm runtime window" }).waitFor();
      assert.deepEqual(await page.locator(".reader-phases strong").allTextContents(), ["0.25 s", "Unavailable"]);
      assert.equal(await page.locator('[aria-label="Imported runtime telemetry"] tbody tr').count(), 1);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth), false);
      if (screenshotDir) {
        fs.mkdirSync(screenshotDir, { recursive: true });
        await page.screenshot({ path: path.join(screenshotDir, `local-results-${width}.png`), fullPage: true });
      }
      await page.locator("#runtime-file").setInputFiles(file("wrong-runtime.json", { ...telemetry, runtime: "sglang" }));
      await page.getByRole("alert").waitFor();
      assert.match(await page.getByRole("alert").textContent(), /does not appear/);
      assert.equal(await page.locator(".reader-phases").count(), 0);
      for (const bad of ["{broken", { ...fixture, cells: [{ ...fixture.cells[0], output_tokens_per_second: "100" }] },
        JSON.stringify(fixture).replace('"output_tokens_per_second":100', '"output_tokens_per_second":1e400')]) {
        await page.locator("#result-file").setInputFiles(file("invalid.json", bad));
        await page.getByRole("alert").waitFor();
        assert.equal(await page.locator(".reader-point").count(), 0);
      }
      await page.getByRole("link", { name: "Episode 0 study" }).click();
      await page.getByText("936", { exact: true }).first().waitFor();
      assert.equal(await page.title(), "Qwen2.5-32B-Instruct runtime study — Exploratory noncanonical");
      assert.deepEqual(errors, []);
      assert(requests.every((request) => new URL(request).origin === new URL(url).origin));
      checks.push({ width, separate_repetitions: true, measured_axes: true, missing_values: true,
        runtime_mismatch_rejected: true, malformed_metrics_rejected: true, no_uploads: true, no_overflow: true });
      await page.close();
    }
  } finally { await browser.close(); }
  console.log(JSON.stringify({ ok: true, checks }, null, 2));
})().catch((error) => { console.error(error); process.exitCode = 1; });
