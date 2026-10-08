const { chromium } = require('../dashboard/node_modules/playwright');
const assert = require('node:assert/strict');

const base = process.argv[2];
if (!base) throw new Error('usage: node tests/dashboard_site_v2_acceptance.cjs <url>');

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    await page.goto(`${base}#episodes`);
    assert.equal(await page.locator('[data-screen-label="Landing"] h1').textContent(), 'Every token is a measurement.');
    assert.equal(await page.locator('[data-token]').count(), 10);
    assert.equal(await page.locator('.tbt-rail-chapters button').count(), 3, 'landing has Recorded, Field notes, Planned subchapters');
    assert.equal(await page.locator('.tbt-externals a[aria-label^="Source on GitHub"] svg').count(), 1);
    await page.getByRole('button', { name: /Lab tools/ }).click();
    assert.equal(await page.locator('#lab-tools [data-local-tool]').count(), 5);
    const mark = await (await page.request.get(`${base}token-by-token.svg`)).text();
    assert.doesNotMatch(mark, /c2pa|Anthropic|manifest/i, 'production mark excludes prototype provenance metadata');
    await page.goto(`${base}#episode-1?load=16`);
    assert.equal(await page.locator('.tbt-rail-chapters button:first-child b').evaluate(el => getComputedStyle(el).color), 'rgb(0, 124, 134)');
    await page.goto(`${base}#methodology`);
    assert.equal(await page.locator('.tbt-rail-chapters button:first-child b').evaluate(el => getComputedStyle(el).color), 'rgb(90, 105, 102)');
    await page.goto(`${base}#episode-1?load=16`);
    assert.equal(await page.locator('#ch-brief .tbt-finding .state-better').count() >= 1, true);
    assert.equal(await page.locator('#ch-brief .tbt-finding .state-better').first().evaluate(el => getComputedStyle(el).color), 'rgb(0, 109, 69)');
    assert.equal(await page.locator('#ch-brief .tbt-brief-heading').evaluate(el => getComputedStyle(el).fontSize), '11px');
    assert.equal(await page.locator('#ch-brief table tbody tr').count(), 4);
    assert.equal(await page.locator('#ch-brief .tbt-caveat li').count() >= 3, true);
    await page.goto(`${base}#episode-1?load=16&theme=dark&text=200&head=question`);
    assert.equal(await page.locator('[data-tbt]').getAttribute('data-theme'), 'dark');
    assert.equal(await page.evaluate(() => getComputedStyle(document.documentElement).fontSize), '32px');
    assert.match(await page.locator('h1').textContent(), /What breaks first/);
    await page.goto(`${base}#episode-1?load=16`);
    assert.doesNotMatch(await page.locator('#ch-brief').innerText(), /Unavailable/, 'recorded Episode 01 point must show values');
    assert.match(await page.locator('#ch-brief .tbt-finding').innerText(), /At 16 users, SGLang recorded/i);
    assert.match(await page.locator('#ch-brief .tbt-finding').innerText(), /output.*median TTFT/i);
    await page.getByRole('button', { name: /Open evidence lab/ }).click();
    assert.equal(await page.locator('#ch-method [data-protocol-row]').count(), 6);
    assert.equal(await page.locator('#ch-boundaries [data-boundary-block]').count(), 4);
    assert.equal(await page.locator('#ch-source [data-source-row]').count(), 4);
    assert.match(await page.locator('#ch-source').innerText(), /proposed, not released/i);
    assert.equal(await page.locator('#ch-method [data-request-anatomy]').count(), 1);
    await page.locator('#ch-method [data-request-anatomy]').getByRole('button', { name: 'TPOT' }).click();
    assert.match(await page.locator('#ch-method [data-request-anatomy]').innerText(), /decode duration divided/i);
    assert.match(await page.locator('#ch-evidence h2').innerText(), /03 Evidence.*Engines at 16 users/is);
    assert.equal(await page.locator('#ch-evidence svg[data-plot]').count() >= 4, true, 'evidence uses recorded plots');
    assert.equal(await page.locator('#ch-evidence [data-evidence-group]').count() >= 2, true, 'evidence has metric groups');
    assert.equal(await page.locator('#ch-evidence [data-identity-legend]').count(), 1);
    assert.equal(await page.locator('#ch-evidence [data-metric] [data-plot-value]').count() >= 4, true, 'plots show exact selected operands');
    assert.equal(await page.locator('#ch-evidence [data-metric] .state-better, #ch-evidence [data-metric] .state-worse, #ch-evidence [data-metric] .state-band').count() >= 1, true, 'delta has semantic state');
    const dataLink = page.locator('#ch-source a[download]');
    assert.equal(await dataLink.count(), 1, 'Source exposes its sanitized static JSON');
    await page.locator('#ch-evidence [data-metric="output_tps"]').click();
    assert.match(page.url(), /metric=output_tps/);
    assert.equal(await page.getByRole('region', { name: 'Explanation: Output throughput' }).count(), 1);
    await page.keyboard.press('Escape');
    assert.doesNotMatch(page.url(), /metric=/);
    assert.equal(await page.locator('#ch-evidence [data-metric="output_tps"]').evaluate(el => el === document.activeElement), true);
    await page.getByRole('button', { name: 'Loads within each engine' }).click();
    assert.match(page.url(), /mode=loads/);
    assert.equal(await page.getByRole('group', { name: 'Baseline load' }).getByRole('button').count(), 3);
    for (const chapter of ['brief', 'method', 'evidence', 'boundaries', 'source']) {
      assert.equal(await page.locator(`#ch-${chapter}`).count(), 1, `missing ${chapter}`);
    }
    assert.equal(await page.locator('[data-track] [data-seg="load"]').count(), 3);
    await page.locator('[data-seg="load"][data-val="24"]').click();
    assert.match(page.url(), /load=24/);
    assert.match(await page.locator('[data-tbt] [role="status"]').first().textContent(), /24 users selected.*output/i);
    const dragPage = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    await dragPage.goto(`${base}#episode-1?load=16`);
    const track = await dragPage.locator('[data-track]').boundingBox();
    assert(track);
    await dragPage.mouse.move(track.x + track.width * .45, track.y + 15);
    await dragPage.mouse.down();
    await dragPage.mouse.move(track.x + track.width * .875, track.y + 15, { steps: 4 });
    await dragPage.mouse.up();
    assert.match(dragPage.url(), /load=24/);
    await dragPage.goBack();
    assert.match(dragPage.url(), /load=16/, 'one drag must create one navigable history entry');
    await dragPage.close();
    await page.goto(`${base}#episode-0`);
    assert.equal(await page.locator('[data-strip] [data-seg="wl"]').count(), 6);
    assert.equal(await page.locator('[data-seg="wl"][aria-pressed="true"]').getAttribute('data-val'), '2048-c24');
    await page.locator('[data-seg="wl"][data-val="128-c1"]').click();
    assert.equal(await page.getByRole('button', { name: 'Previous workload' }).isDisabled(), true);
    await page.locator('[data-seg="wl"][data-val="8192-c8"]').click();
    assert.match(await page.locator('#ch-brief .tbt-finding').innerText(), /unequal work.*throughput and latency are not compared/i);
    assert.equal(await page.locator('#ch-brief .tbt-finding .state-band').count(), 1);
    assert.equal(await page.locator('#ch-brief .tbt-finding .state-band').evaluate(el => getComputedStyle(el).color), 'rgb(138, 91, 0)');
    await page.getByRole('button', { name: /Open evidence lab/ }).click();
    assert.equal(await page.locator('#ch-method [data-protocol-row]').count(), 6);
    assert.equal(await page.locator('#ch-method [data-request-anatomy]').count(), 0);
    assert.match(await page.locator('#ch-evidence h2').innerText(), /8,192-token input · 8 concurrent/is);
    assert.equal(await page.locator('#ch-evidence [data-evidence-group]').count() >= 2, true);
    assert.equal(await page.getByText('Workload-level telemetry').count(), 1);
    assert.equal(await page.locator('[data-run-telemetry]').count(), 2);
    assert.match(await page.locator('[data-run-telemetry]').first().innerText(), /power.*samples/is);
    await page.goto(`${base}#field-notes`);
    assert.equal(await page.locator('[data-screen-label="Selector"]').count(), 0, 'field note has no page selector');
    await page.getByRole('button', { name: /Open evidence lab/ }).click();
    assert.equal(await page.locator('#ch-evidence [data-seg="users"]').count(), 7);
    await page.locator('#ch-evidence [data-seg="users"][data-val="32"]').click();
    assert.match(page.url(), /users=32/);
    assert.match(await page.locator('#ch-evidence [data-metric="error_rate"]').innerText(), /16\.91%/);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' });
  try {
    for (const width of [1440, 768, 542, 390, 320]) {
      for (const theme of ['light', 'dark']) {
        const page = await browser.newPage({ viewport: { width, height: 900 }, colorScheme: theme, reducedMotion: 'reduce' });
        const external = [];
        await page.route('**/*', route => { if (new URL(route.request().url()).origin !== new URL(base).origin) { external.push(route.request().url()); route.abort(); } else route.continue(); });
        for (const route of ['episodes','episode-0','episode-1','episode-2','field-notes','methodology']) {
          await page.goto(`${base}#${route}`);
          const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
          assert.equal(overflow, false, `${route} overflows at ${width}px ${theme}`);
          assert.equal(await page.locator('h1').count(), 1, `${route} h1 count`);
        }
        await page.goto(`${base}#episode-1`);
        const navColor = await page.locator('.tbt-rail-chapters button:first-child b').evaluate(el => getComputedStyle(el).color).catch(() => null);
        if (width >= 981) assert.equal(navColor, theme === 'light' ? 'rgb(0, 124, 134)' : 'rgb(121, 216, 223)');
        const favorable = await page.locator('#ch-brief .tbt-finding .state-better').first().evaluate(el => getComputedStyle(el).color);
        assert.equal(favorable, theme === 'light' ? 'rgb(0, 109, 69)' : 'rgb(75, 220, 175)');
        await page.goto(`${base}#episode-0?wl=2048-c24`);
        const unfavorable = await page.locator('#ch-brief .tbt-finding .state-worse').first().evaluate(el => getComputedStyle(el).color);
        assert.equal(unfavorable, theme === 'light' ? 'rgb(178, 47, 24)' : 'rgb(255, 122, 77)');
        assert.deepEqual(external, [], 'public site requested an external asset');
        await page.goto(`${base}#episode-1?load=16`);
        await page.locator('[data-seg="load"][data-val="16"]').focus();
        await page.keyboard.press('ArrowRight');
        assert.match(page.url(), /load=24/);
        await page.keyboard.press('Home');
        assert.match(page.url(), /load=12/);
        await page.goto(`${base}#episode-0?wl=128-c1`);
        await page.getByRole('button', { name: 'Next workload' }).click();
        assert.match(page.url(), /wl=128-c16/);
        await page.evaluate(() => { document.documentElement.style.fontSize = '200%'; });
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth), false, `200% text overflows at ${width}px ${theme}`);
        await page.close();
      }
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
