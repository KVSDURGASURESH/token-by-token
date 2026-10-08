const { chromium } = require("../dashboard/node_modules/playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");

const root = path.resolve(process.argv[2] || "");
if (!process.argv[2] || !fs.existsSync(path.join(root, "index.html"))) throw new Error("usage: node tests/dashboard_offline_acceptance.cjs dashboard/dist");

const contentType = (file) => file.endsWith(".html") ? "text/html" : file.endsWith(".js") ? "text/javascript" : file.endsWith(".css") ? "text/css" : file.endsWith(".svg") ? "image/svg+xml" : file.endsWith(".woff2") ? "font/woff2" : "application/octet-stream";
const server = http.createServer((request, response) => {
  const pathname = new URL(request.url, "http://127.0.0.1").pathname;
  const candidate = pathname === "/" ? path.join(root, "index.html") : path.join(root, pathname);
  const resolved = path.resolve(candidate);
  const file = resolved.startsWith(root + path.sep) && fs.existsSync(resolved) && fs.statSync(resolved).isFile() ? resolved : path.join(root, "index.html");
  response.writeHead(200, { "Content-Type": contentType(file), "Cache-Control": "no-store" });
  fs.createReadStream(file).pipe(response);
});

(async () => {
  await new Promise((resolve, reject) => server.listen(0, "127.0.0.1", error => error ? reject(error) : resolve()));
  const address = server.address();
  const base = `http://127.0.0.1:${address.port}/`;
  const localChrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
  const executablePath = process.env.CHROME_PATH || (fs.existsSync(localChrome) ? localChrome : undefined);
  const browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 }, reducedMotion: "reduce" });
    const blocked = [];
    const failed = [];
    await page.route("**/*", route => {
      const target = new URL(route.request().url());
      if (target.origin !== new URL(base).origin) { blocked.push(target.origin); return route.abort("blockedbyclient"); }
      return route.continue();
    });
    page.on("requestfailed", request => failed.push(request.url()));
    const routes = [
      ["episodes", "Every token is a measurement"],
      ["episode-0", "Warm-up"],
      ["episode-1", "Measure what matters"],
      ["field-notes", "Session capacity"],
      ["methodology", "How the lab measures"],
    ];
    for (const [hash, expected] of routes) {
      await page.goto(`${base}#${hash}`, { waitUntil: "networkidle" });
      assert.match(await page.locator("body").innerText(), new RegExp(expected, "i"), `${hash} did not render expected content`);
      assert.equal(await page.getByRole("group", { name: "Color theme" }).count(), 1);
    }
    assert.deepEqual(blocked, []);
    assert.deepEqual(failed, []);
    console.log("Offline dashboard passed: all public hashes rendered from static local assets only.");
  } finally {
    await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { console.error(error); server.close(); process.exitCode = 1; });
