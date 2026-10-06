const { chromium } = require("../dashboard/node_modules/playwright");
const assert = require("node:assert/strict");

const url = process.argv[2];
if (!url) throw new Error("usage: node tests/dashboard_theme_acceptance.cjs <dashboard-url>");
const base = url.replace(/#.*$/, "");
const routes = ["episodes", "episode-0", "episode-1", "session-study", "methodology"];

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" });
  try {
    const systemContext = await browser.newContext({ colorScheme: "light" });
    const systemPage = await systemContext.newPage();
    await systemPage.goto(`${base}#episodes`, { waitUntil: "networkidle" });
    assert.equal(await systemPage.evaluate(() => document.documentElement.dataset.theme), "light");
    assert.equal(await systemPage.evaluate(() => localStorage.getItem("token-by-token-theme")), null);
    await systemContext.close();

    for (const width of [1440, 390]) {
      const context = await browser.newContext({ viewport: { width, height: 1000 }, colorScheme: "dark", reducedMotion: "reduce" });
      const page = await context.newPage();
      await page.goto(`${base}#episodes`, { waitUntil: "networkidle" });
      const group = page.getByRole("group", { name: "Color theme" });
      assert.equal(await group.getByRole("button").count(), 2);
      assert.equal(await group.locator('button[aria-pressed="true"]').count(), 1);
      const box = await group.boundingBox();
      assert(box && box.x + box.width > width - 46 && box.y < 40, "theme switch must remain at the top right");

      await group.getByRole("button", { name: "Light" }).click();
      assert.equal(await page.evaluate(() => document.documentElement.dataset.theme), "light");
      assert.equal(await page.evaluate(() => localStorage.getItem("token-by-token-theme")), "light");
      await page.reload({ waitUntil: "networkidle" });
      assert.equal(await page.evaluate(() => document.documentElement.dataset.theme), "light");

      for (const theme of ["light", "dark"]) {
        await page.getByRole("group", { name: "Color theme" }).getByRole("button", { name: theme === "light" ? "Light" : "Dark" }).click();
        for (const route of routes) {
          await page.goto(`${base}#${route}`, { waitUntil: "networkidle" });
          assert.equal(await page.evaluate(() => document.documentElement.dataset.theme), theme);
          assert.equal(await page.getByRole("group", { name: "Color theme" }).locator('button[aria-pressed="true"]').count(), 1);
          assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth), false, `${route} overflowed at ${width}px in ${theme}`);
          const colors = await page.evaluate(() => ({ background: getComputedStyle(document.body).backgroundColor, ink: getComputedStyle(document.body).color }));
          assert.notEqual(colors.background, colors.ink);
        }
      }
      await context.close();
      console.log(`Theme behavior passed at ${width}px across all public routes.`);
    }
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
