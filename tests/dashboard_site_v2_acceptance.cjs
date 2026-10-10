const { chromium } = require('../dashboard/node_modules/playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const episode1Projection = require('../dashboard/src/data/site-v2/episode-1.json');
const episode0Telemetry = require('../dashboard/src/data/site-v2/episode-0-telemetry.json');
const catalog = require('../dashboard/src/data/site-v2/catalog.json');
const roadmapContext = require('../dashboard/src/data/site-v2/roadmap-context.json');
const roadmapEvidence = require('../dashboard/src/data/site-v2/roadmap-evidence.json');

const roadmap = fs.readFileSync(require.resolve('../docs/roadmap.md'), 'utf8');
const roadmapSections = Object.fromEntries([...roadmap.matchAll(/^### (\d+)\. ([^\n]+)\n\n([^\n]+)/gm)].map(match => [Number(match[1]), match[3].replaceAll('**', '')]));
const roadmapEvidenceSections = Object.fromEntries([...roadmap.matchAll(/^### (\d+)\.[\s\S]*?^\*\*Evidence:\*\* ([^\n]+)/gm)].map(match => [Number(match[1]), match[2].replaceAll('**', '')]));
for (const episode of catalog.episodes.filter(episode => episode.status === 'planned')) {
  assert.equal(roadmapContext[episode.id], roadmapSections[episode.number], `${episode.id} landing context must match its roadmap section`);
  assert.equal(roadmapEvidence[episode.id], roadmapEvidenceSections[episode.number], `${episode.id} landing evidence must match its roadmap section`);
  assert.match(episode.roadmapAnchor, new RegExp(`^${episode.number}-`), `${episode.id} must use GitHub's numbered roadmap anchor`);
}

assert.equal(episode1Projection.schema_version, 'token-by-token.public-site-projection.v1');
assert.deepEqual(
  episode1Projection.metric_definitions.find(metric => metric.id === 'gpu_memory_gib'),
  { id: 'gpu_memory_gib', explanation: 'Maximum sampled device memory use in the measured window.' },
  'the public projection defines GPU memory as the maximum sampled value'
);
assert.deepEqual(episode1Projection.arms.map(arm => {
  const point = arm.points.find(point => point.users === 16);
  return [arm.engine, point.valid_requests, point.total_requests, point.level_valid];
}), [['vLLM',665,666,true],['SGLang',889,889,true]]);
assert.deepEqual(episode0Telemetry.workloads.find(workload => workload.id === '2048-c24').engines,
  { vLLM: { kv_cache_peak: 0.9988, waiting_requests_peak: 14.5, prefill_duration_seconds: 1.1217, decode_duration_seconds: 4.5523 }, SGLang: { kv_cache_peak: 0.99, waiting_requests_peak: 17, prefill_duration_seconds: null, decode_duration_seconds: null } });

const base = process.argv[2];
if (!base) throw new Error('usage: node tests/dashboard_site_v2_acceptance.cjs <url>');

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    await page.goto(`${base}#episodes`);
    assert.equal(await page.locator('[data-screen-label="Landing"] h1').textContent(), 'Every token is a measurement.');
    assert.equal(await page.locator('[data-screen-label="Landing"] [data-landing-token-accent]').innerText(), 'TOKEN');
    assert.equal(await page.locator('[data-screen-label="Landing"] [data-landing-token-accent]').evaluate(el => getComputedStyle(el).color), 'rgb(0, 124, 134)', 'TOKEN alone uses the cyan signature color');
    assert.equal(await page.locator('[data-token]').count(), 10);
    assert.equal(await page.locator('.tbt-rail-chapters button').count(), 2, 'landing has only Recorded and Planned subchapters');
    assert.equal(await page.getByText('Field notes', { exact: true }).count(), 0, 'Field Notes is removed from public navigation');
    const episodeTwoRow = page.locator('[data-episode-index-row="episode-2"]');
    assert.equal(await episodeTwoRow.getByRole('button', { name: /Show context for Episode 02/ }).getAttribute('aria-expanded'), 'false');
    assert.equal(await page.locator('.tbt-index-open').count(), 0, 'episode rows expose only the context disclosure until expanded');
    await episodeTwoRow.getByRole('button', { name: /Show context for Episode 02/ }).click();
    assert.equal(await episodeTwoRow.getByRole('button', { name: /Hide context for Episode 02/ }).getAttribute('aria-expanded'), 'true');
    assert.match(await episodeTwoRow.innerText(), /The experiment map.*Randomize or counterbalance execution order.*Evidence:.*selected images and kernels/is, 'planned disclosure uses the matching roadmap section and evidence contract');
    assert.match(await episodeTwoRow.getByRole('link', { name: /Read the experiment roadmap/ }).getAttribute('href'), /docs\/roadmap\.md#2-equal-work-runtime-baseline$/);
    assert.equal(await episodeTwoRow.locator('.tbt-index-context > p:not(.tbt-eyebrow)').evaluateAll(elements => elements.every(el => Number(getComputedStyle(el).fontWeight) <= 300)), true, 'roadmap context and evidence use the approved lighter reading weight');
    assert.equal(await episodeTwoRow.locator('.tbt-index-context').evaluate(el => parseFloat(getComputedStyle(el).rowGap) >= 12), true, 'experiment text, Evidence, and roadmap link have readable vertical separation');
    const episodeZeroRow = page.locator('[data-episode-index-row="episode-0"]');
    await episodeZeroRow.getByRole('button', { name: /Show context for Episode 00/ }).click();
    assert.equal(await episodeZeroRow.getByRole('link', { name: /Open the recorded study/ }).getAttribute('href'), '#episode-0', 'recorded disclosures contain the study link');
    const landingSummaries = page.locator('.tbt-index-summary');
    assert.equal(await landingSummaries.evaluateAll(nodes => new Set(nodes.map(node => getComputedStyle(node).maxWidth)).size), 1, 'episode taglines share one readable line length');
    assert.equal(await page.locator('.tbt-deck').evaluate(el => getComputedStyle(el).fontWeight), '300', 'typography option A gives supporting copy a lighter reading weight');
    assert.equal(await page.locator('.tbt-externals a[aria-label^="Source on GitHub"] svg').count(), 1);
    await page.getByRole('button', { name: /Lab tools/ }).click();
    assert.equal(await page.locator('#lab-tools [data-local-tool]').count(), 0, 'public Lab Tools no longer lists internal operator rows');
    assert.match(await page.locator('#lab-tools').innerText(), /Benchmarking harness powered by AgentBench from Mirastack Labs/i);
    assert.equal(await page.locator('#lab-tools [data-mirastack-labs]').evaluate(el => getComputedStyle(el).color), 'rgb(0, 124, 134)', 'Mirastack Labs uses the cyan signature color');
    assert.match(await page.locator('#lab-tools').innerText(), /hello@mirastacklabs\.ai/i);
    assert.equal(await page.locator('.tbt-site-nav a[href="#methodology"] + #lab-tools-btn').count(), 1, 'Lab Tools is immediately beside Methodology');
    assert.equal(await page.locator('.tbt-site-nav #lab-tools-btn + [data-home-link]').count(), 1, 'Home follows Lab Tools');
    const mark = await (await page.request.get(`${base}token-by-token.svg`)).text();
    assert.doesNotMatch(mark, /c2pa|Anthropic|manifest/i, 'production mark excludes prototype provenance metadata');
    await page.goto(`${base}#field-notes`);
    assert.equal(await page.locator('[data-screen-label="Landing"]').count(), 1, 'retired Field Notes links resolve to the episode catalog');
    await page.goto(`${base}#episode-1?load=16`);
    assert.equal(await page.locator('.tbt-brand').innerText(), 'TOKEN BY TOKEN', 'site wordmark removes the inference-lab suffix');
    assert.equal(await page.locator('.tbt-brand [data-brand-part="by"]').evaluate(el => getComputedStyle(el).color), 'rgb(178, 47, 24)', 'Option B renders BY in the red signal color');
    assert.match(await page.locator('.tbt-study-header .tbt-eyebrow').innerText(), /^Episode 01: Measure what matters · Recorded study$/i);
    assert.match(await page.locator('#page-title').innerText(), /Can the throughput leader still miss the decode floor/i, 'recorded studies default to the evidence-backed analysis headline');
    assert.equal(await page.locator('#page-title').evaluate(el => getComputedStyle(el).textTransform), 'uppercase', 'analysis headline is uppercase');
    assert.equal(await page.locator('#page-title [data-headline-accent]').evaluate(el => getComputedStyle(el).color), 'rgb(0, 124, 134)', 'analytical phrase uses the cyan signature color');
    assert.doesNotMatch(await page.locator('body').innerText(), /Capacity (?:was )?not established/i, 'reader-facing copy explains the measurement boundary instead of using an ambiguous capacity label');
    assert.match(await page.locator('.tbt-study-header').innerText(), /Tested loads only.*maximum sustainable rate not measured/i);
    assert.equal(await page.locator('.tbt-hero-evidence').count(), 0, 'the hero does not duplicate the measured Brief result');
    assert.equal(await page.locator('.tbt-rail-episodes a[href="#episode-13"] [data-episode-title]').innerText(), 'SYSTEM 1 and LLMs on labeled decision tasks', 'public episode label uses SYSTEM 1');
    assert.equal(await page.locator('.tbt-rail-episodes a[href="#episode-13"] small').innerText(), 'PLANNED', 'planned rail status stays visible and neutral');
    assert.equal(await page.locator('.tbt-rail-episodes a[href="#episode-13"] small').evaluate(el => getComputedStyle(el).color), 'rgb(90, 105, 102)');
    const recordedNumberFont = await page.locator('.tbt-rail-episodes a[href="#episode-0"] b').evaluate(el => getComputedStyle(el).fontFamily);
    const plannedNumberFont = await page.locator('.tbt-rail-episodes a[href="#episode-2"] b').evaluate(el => getComputedStyle(el).fontFamily);
    const chapterNumberFont = await page.locator('.tbt-rail-chapters button:first-child b').evaluate(el => getComputedStyle(el).fontFamily);
    assert.equal(plannedNumberFont, recordedNumberFont, 'planned and recorded episode numbers use one typeface');
    assert.equal(chapterNumberFont, recordedNumberFont, 'chapter numbers use the episode-number typeface');
    await page.getByRole('link', { name: 'Skip to content' }).focus();
    await page.keyboard.press('Enter');
    assert.equal(await page.locator('main').evaluate(el => el === document.activeElement), true);
    assert.match(page.url(), /load=16/, 'skip link preserves route');
    assert.equal(await page.locator('.tbt-rail-chapters button:first-child b').evaluate(el => getComputedStyle(el).color), 'rgb(0, 124, 134)');
    await page.goto(`${base}#methodology`);
    assert.equal(await page.locator('.tbt-rail-chapters button:first-child b').evaluate(el => getComputedStyle(el).color), 'rgb(90, 105, 102)');
    await page.goto(`${base}#episode-1?load=16`);
    assert.equal(await page.locator('#ch-brief .tbt-finding .state-better').count() >= 1, true);
    assert.equal(await page.locator('#ch-brief .tbt-finding .state-better').first().evaluate(el => getComputedStyle(el).color), 'rgb(0, 109, 69)');
    assert.equal(await page.locator('#ch-brief .tbt-brief-heading').evaluate(el => getComputedStyle(el).fontSize), '11px');
    assert.equal(await page.locator('#ch-brief table tbody tr').count(), 4);
    assert.equal(await page.locator('#ch-brief .tbt-caveat li').count() >= 3, true);
    assert.equal(await page.locator('[data-experiment-contract]').count(), 1, 'Episode 01 publishes a bounded experiment contract');
    assert.equal(await page.locator('[data-config-state="enabled"]').count(), 4);
    assert.equal(await page.locator('[data-config-state="withheld"]').count(), 2);
    assert.match(await page.locator('[data-experiment-contract]').innerText(), /One H200 per arm.*Matched model family.*Runtime optimization flags.*withheld/is);
    assert.doesNotMatch(await page.locator('[data-experiment-contract]').innerText(), /Qwen|max_concurrent|prefix_caching|kv_cache_dtype/i, 'the public contract does not compile serving settings into the site');
    const configColors = await page.locator('[data-experiment-contract]').evaluate(root => {
      const css = (selector) => getComputedStyle(root.querySelector(selector));
      return {
        ink: getComputedStyle(document.querySelector('[data-tbt]')).color,
        enabledLabel: css('[data-config-state="enabled"] b').color,
        enabledIcon: css('[data-config-state="enabled"] i').color,
        inheritedLabel: css('[data-config-state="withheld"] b').color,
        inheritedDetail: css('[data-config-state="withheld"] small').color,
      };
    });
    assert.equal(configColors.enabledLabel, configColors.ink, 'configuration labels remain neutral');
    assert.equal(configColors.inheritedLabel, configColors.ink, 'inherited labels remain neutral');
    assert.notEqual(configColors.enabledIcon, configColors.ink, 'only the enabled status mark carries evidence color');
    assert.notEqual(configColors.inheritedDetail, configColors.ink, 'only inherited detail carries the amber state color');
    assert.equal(await page.locator('.tbt-config-grid').evaluate(el => Number.parseFloat(getComputedStyle(el).paddingBottom) >= 18), true, 'the experiment-contract divider leaves breathing room below its option details');
    const contractBox = await page.locator('[data-experiment-contract]').boundingBox();
    const labToggleBox = await page.locator('#lab-toggle').boundingBox();
    assert(contractBox && labToggleBox && labToggleBox.y >= contractBox.y + contractBox.height, 'Evidence Lab control follows the experiment contract');
    const unfoldSize = await page.locator('.tbt-unfold').evaluate(el => ({ height: el.getBoundingClientRect().height, font: Number.parseFloat(getComputedStyle(el).fontSize) }));
    assert(unfoldSize.height <= 38 && unfoldSize.font <= 11, 'configuration control stays visually subordinate');
    const labToggleSize = await page.locator('#lab-toggle').evaluate(el => ({ height: el.getBoundingClientRect().height, font: Number.parseFloat(getComputedStyle(el).fontSize) }));
    assert(labToggleSize.height <= 38 && labToggleSize.font <= 11, 'Evidence Lab control stays visually subordinate');
    assert.deepEqual(
      await page.locator('.tbt-unfold, #lab-toggle').evaluateAll(elements => elements.map(el => ({ width: el.getBoundingClientRect().width, height: el.getBoundingClientRect().height }))),
      [{ width: 184, height: 34 }, { width: 184, height: 34 }],
      'recorded JSON and Evidence Lab actions use one stable control size'
    );
    await page.getByRole('button', { name: /Unfold recorded JSON/i }).click();
    assert.equal(await page.locator('[data-configuration-note]').count(), 1);
    assert.match(await page.locator('.tbt-unfold').innerText(), /Fold configuration note/i);
    await page.waitForTimeout(850);
    assert.equal(await page.locator('.tbt-paper-stage').evaluate(el => el.getBoundingClientRect().height >= 580), true, 'configuration paper unfolds with the approved transition');
    assert.equal(await page.locator('.tbt-paper').evaluate(el => el.scrollHeight <= el.clientHeight + 1), true, 'the unfolded paper never clips the JSON or privacy boundary');
    assert.match(await page.locator('[data-configuration-note]').innerText(), /"user_levels".*"measurement_seconds".*"decode_p10_floor_tps"/is);
    assert.doesNotMatch(await page.locator('[data-configuration-note]').innerText(), /Qwen|max_concurrent|prefix_caching|kv_cache_dtype/i);
    assert.match(await page.locator('[data-configuration-note]').innerText(), /public measurement contract.*not a runnable serving profile/is);
    assert.equal(await page.locator('[data-run-cost]').count(), 1, 'Episode 01 explains the bounded cost model');
    const runCostText = await page.locator('[data-run-cost]').innerText();
    assert.match(runCostText, /\$3\.21.*42 GPU-minutes/is);
    assert.match(runCostText, /\$4\.59\s*\/\s*h.*not the provider invoice/is);
    assert.equal(await page.locator('[data-cost-provider]').innerText(), 'RUNPOD');
    assert.equal(await page.locator('[data-cost-provider]').evaluate(el => getComputedStyle(el).color), 'rgb(0, 124, 134)', 'the recorded cost provider uses the cyan identity accent');
    await page.goto(`${base}#episode-2`);
    assert.equal(await page.locator('.tbt-planned-state').innerText(), 'PLANNED');
    assert.equal(await page.locator('.tbt-planned-state').evaluate(el => getComputedStyle(el).color), 'rgb(90, 105, 102)', 'planned state stays neutral in the navigation system');
    assert.equal(await page.locator('[data-planned-watermark]').innerText(), 'PLANNED');
    assert.equal(await page.locator('.tbt-planned-outline').count(), 1, 'planned pages use one concise experiment outline');
    assert.equal(await page.locator('.tbt-study > .tbt-chapter').count(), 0, 'planned pages do not render empty evidence chapters');
    await page.getByRole('link', { name: /Read the experiment roadmap/ }).click();
    assert.match(page.url(), /#episodes\?open=episode-2$/, 'planned roadmap link returns to the matching landing-page section');
    const returnedEpisodeTwo = page.locator('[data-episode-index-row="episode-2"]');
    assert.equal(await returnedEpisodeTwo.getAttribute('data-expanded'), 'true', 'matching landing-page section opens automatically');
    assert.match(await returnedEpisodeTwo.innerText(), /Equal-work runtime baseline.*Evidence:.*selected images and kernels/is, 'returned section exposes the complete matching roadmap content');
    await page.locator('.tbt-rail-episodes a[href="#episode-1"]').click();
    await page.locator('#page-title').waitFor();
    assert.equal(await page.evaluate(() => scrollY <= 1), true, 'switching episodes resets the reader to the new introduction');
    await page.goto(`${base}#episode-1?load=16&theme=dark&text=200&head=question`);
    assert.equal(await page.locator('[data-tbt]').getAttribute('data-theme'), 'dark');
    assert.equal(await page.evaluate(() => getComputedStyle(document.documentElement).fontSize), '32px');
    assert.match(await page.locator('h1').textContent(), /Can the throughput leader still miss the decode floor/);
    await page.goto(`${base}#episode-1?load=16`);
    assert.doesNotMatch(await page.locator('#ch-brief').innerText(), /Unavailable/, 'recorded Episode 01 point must show values');
    assert.match(await page.locator('#ch-brief .tbt-finding').innerText(), /At 16 users, SGLang recorded/i);
    assert.match(await page.locator('#ch-brief .tbt-finding').innerText(), /output.*median TTFT/i);
    await page.evaluate(() => { window.__analyticsEvents = []; window.umami = { track: (name, data) => window.__analyticsEvents.push({ name, data }) }; });
    await page.getByRole('button', { name: /Open evidence lab/ }).click();
    const labBox = await page.locator('#lab').boundingBox();
    const costBox = await page.locator('[data-run-cost]').boundingBox();
    assert(labBox && costBox && costBox.y >= labBox.y + labBox.height, 'cost basis follows the complete Evidence Lab');
    assert.equal(await page.evaluate(() => window.__analyticsEvents.some(event => event.name === 'evidence-lab-toggle' && event.data.state === 'open')), true, 'evidence expansion records an anonymous interaction event');
    await page.locator('#ch-boundaries').scrollIntoViewIfNeeded();
    await page.waitForFunction(() => document.querySelector('.tbt-rail-chapters button:nth-child(4)')?.getAttribute('aria-current') === 'location');
    assert.equal(await page.locator('.tbt-rail-chapters button:nth-child(4)').innerText(), '04\nBoundaries', 'scroll spy follows the visible chapter');
    await page.locator('#ch-brief').scrollIntoViewIfNeeded();
    await page.waitForFunction(() => document.querySelector('.tbt-rail-chapters button:first-child')?.getAttribute('aria-current') === 'location');
    assert.equal(await page.locator('#ch-method [data-protocol-row]').count(), 6);
    assert.equal(await page.locator('#ch-boundaries [data-boundary-block]').count(), 4);
    assert.equal(await page.locator('#ch-source [data-source-row]').count(), 4);
    assert.match(await page.locator('#ch-source').innerText(), /offline evidence client.*real benchmark submission is not released/i);
    assert.equal(await page.locator('#ch-method [data-request-anatomy]').count(), 1);
    await page.locator('#ch-method [data-request-anatomy]').getByRole('button', { name: 'TPOT' }).click();
    assert.match(await page.locator('#ch-method [data-request-anatomy]').innerText(), /decode duration divided/i);
    assert.match(await page.locator('#ch-evidence h2').innerText(), /03 Evidence.*Engines at 16 users/is);
    assert.equal(await page.locator('#ch-evidence svg[data-plot]').count() >= 4, true, 'evidence uses recorded plots');
    assert.equal(await page.locator('#ch-evidence [data-evidence-group]').count() >= 2, true, 'evidence has metric groups');
    assert.equal(await page.locator('#ch-evidence [data-identity-legend]').count(), 1);
    assert.equal(await page.locator('#ch-evidence [data-observed-signals]').count(), 1, 'notable recorded signals are surfaced');
    assert.match(await page.locator('#ch-evidence [data-observed-signals]').innerText(), /Tail latency.*TTFT p95.*Waiting requests.*context only/is, 'notable recorded signals remain evidence-scoped');
    await page.getByRole('group', { name: 'Baseline engine' }).getByRole('button', { name: 'SGLang' }).click();
    assert.match(await page.locator('#ch-evidence [data-observed-signals]').innerText(), /TTFT p95.*75\.9% worse/is, 'the highlighted tail signal follows the active baseline direction');
    await page.getByRole('group', { name: 'Baseline engine' }).getByRole('button', { name: 'vLLM' }).click();
    const directional = page.locator('#ch-evidence [data-evidence-group]').filter({ hasText: 'Directional comparisons' }).first();
    assert.equal(await directional.getByRole('tablist', { name: 'Directional metrics' }).count(), 1, 'directional metrics use a stable selector rail');
    assert.equal(await directional.getByRole('tab').count(), 4);
    assert.equal(await directional.getByRole('tab', { selected: true }).getAttribute('data-metric-tab'), 'output_tps', 'output is selected by default');
    assert.equal(await directional.getByRole('tabpanel').count(), 1, 'only one directional metric is rendered at a time');
    const selectedBand = directional.locator('svg[data-plot] rect').first();
    assert.equal(await selectedBand.count(), 1, 'selected workload has a chart band');
    assert.notEqual(await selectedBand.evaluate(el => getComputedStyle(el).stroke), 'none', 'selected workload band has a visible boundary');
    assert.equal(await page.locator('#ch-evidence [data-plot-value]').count() >= 4, true, 'plots show exact selected operands');
    assert.equal(await page.locator('#ch-evidence [data-metric] .state-better, #ch-evidence [data-metric] .state-worse, #ch-evidence [data-metric] .state-band').count() >= 1, true, 'delta has semantic state');
    assert.equal(await page.locator('[data-metric="error_rate_pct"] [data-reference="Declared 1% limit"]').count(), 1);
    assert.equal(await page.locator('[data-metric="error_rate_pct"] [data-reference="Declared 1% limit"]').evaluate(el => Number(el.getAttribute('y1')) < 88), true, 'threshold contributes to plot scale');
    assert.equal(await page.locator('[data-metric="decode_p10_tps"] [data-reference="Declared 20 tok/s floor"]').count(), 1);
    assert.match(await page.locator('#ch-evidence .tbt-validity').innerText(), /vLLM · 665\/666 valid requests.*SGLang · 889\/889 valid requests/s);
    const dataLink = page.locator('#ch-source a[download]');
    assert.equal(await dataLink.count(), 1, 'Source exposes its sanitized static JSON');
    const directionalHeight = await directional.evaluate(el => el.getBoundingClientRect().height);
    await directional.getByRole('tab', { name: /TTFT p50/ }).click();
    assert.match(await directional.getByRole('tabpanel').getAttribute('aria-label'), /TTFT p50/);
    assert.equal(Math.abs((await directional.evaluate(el => el.getBoundingClientRect().height)) - directionalHeight) <= 2, true, 'switching metrics does not reflow the section');
    await directional.getByRole('tab', { name: /Output throughput/ }).click();
    assert.match(page.url(), /metric=output_tps/);
    assert.equal(await page.getByRole('region', { name: 'Explanation: Output throughput' }).count(), 1);
    assert.match(await page.getByRole('region', { name: 'Explanation: Output throughput' }).innerText(), /Directional comparison.*Higher is better/s);
    const thresholdCardWhileDirectionalIsOpen = page.locator('#ch-evidence [data-metric="error_rate_pct"]');
    assert.equal(await thresholdCardWhileDirectionalIsOpen.evaluate(el => getComputedStyle(el).opacity), '1', 'threshold controls stay visibly available while a directional explanation is open');
    assert.equal(await thresholdCardWhileDirectionalIsOpen.getByRole('button', { name: /Open explanation/ }).isEnabled(), true, 'threshold explanation remains actionable');
    await page.keyboard.press('Escape');
    assert.doesNotMatch(page.url(), /metric=/);
    assert.equal(await page.locator('#ch-evidence [data-metric-tab="output_tps"]').evaluate(el => el === document.activeElement), true);
    await page.locator('#ch-evidence [data-metric="error_rate_pct"]').getByRole('button', { name: /Open explanation/ }).click();
    assert.match(await page.getByRole('region', { name: 'Explanation: Error rate' }).innerText(), /Declared threshold for each engine.*1% validity limit/s);
    assert.equal(await page.locator('#ch-evidence').getAttribute('data-explanation-open'), 'error_rate_pct', 'open explanation identifies the focused metric');
    assert.equal(await page.locator('#ch-evidence [data-metric="error_rate_pct"]').evaluate(el => Number(getComputedStyle(el).opacity)), 1, 'selected chart stays fully visible');
    await page.waitForFunction(() => Number(getComputedStyle(document.querySelector('#ch-evidence [data-metric-workbench] .tbt-metric-panel')).opacity) < 0.6);
    assert.equal(await page.locator('#ch-evidence [data-metric-workbench]').evaluate(el => getComputedStyle(el).opacity), '1', 'the directional selector remains visibly available');
    assert.equal(await page.locator('#ch-evidence [data-metric-workbench] .tbt-metric-panel').evaluate(el => Number(getComputedStyle(el).opacity) < 0.6), true, 'the unrelated directional chart content dims while an explanation is open');
    const vizNote = page.getByRole('region', { name: 'Explanation: Error rate' }).locator('[data-viz-note]');
    assert.match(await vizNote.innerText(), /Grafana dashboard.*top navigation/i);
    assert.equal(await vizNote.evaluate(el => getComputedStyle(el).fontStyle), 'italic');
    assert.equal(await directional.locator('h3 small').evaluate(el => Number(getComputedStyle(el).fontWeight) <= 300), true, 'evidence helper copy uses a lighter weight');
    await page.keyboard.press('Escape');
    await page.locator('#ch-evidence [data-metric="waiting_requests_mean"]').getByRole('button', { name: /Open explanation/ }).click();
    assert.match(await page.getByRole('region', { name: 'Explanation: Waiting requests' }).innerText(), /Context only — not ranked.*no better direction/s);
    await page.keyboard.press('Escape');
    await page.getByRole('button', { name: 'Loads within each engine' }).click();
    assert.match(page.url(), /mode=loads/);
    assert.doesNotMatch(page.url(), /base=/, 'mode switch clears old baseline');
    await page.getByRole('group', { name: 'Comparison' }).getByRole('button', { name: 'Loads within each engine' }).focus();
    await page.keyboard.press('ArrowLeft');
    assert.match(page.url(), /mode=engines/);
    await page.waitForFunction(() => document.activeElement?.getAttribute('data-seg') === 'mode' && document.activeElement?.getAttribute('data-val') === 'engines');
    await page.getByRole('button', { name: 'Loads within each engine' }).click();
    const referenceLoad = page.getByRole('group', { name: 'Reference load' });
    assert.equal(await referenceLoad.getByRole('button').count(), 3, 'all recorded loads remain visible in the reference control');
    assert.equal(await referenceLoad.locator('[data-val="16"]').isDisabled(), true, 'the selected load remains visible but cannot reference itself');
    assert.match(await referenceLoad.locator('[data-val="16"]').innerText(), /16.*selected/is, 'the disabled reference explains why it is unavailable');
    await page.goto(`${base}#episode-1?load=24&mode=loads&base=24&depth=lab`);
    assert.match(await page.locator('#ch-evidence h2').innerText(), /Loads compared with 12 users/i, 'a self-reference deep link falls back to another recorded load');
    assert.equal(await page.getByRole('group', { name: 'Reference load' }).locator('[data-val="24"]').isDisabled(), true, '24 users remains visible and disabled when selected');
    assert.match(await page.locator('#ch-evidence .tbt-compare-controls').innerText(), /Selected load: 24 users.*Reference load: 12 users/is);
    for (const chapter of ['brief', 'method', 'evidence', 'boundaries', 'source']) {
      assert.equal(await page.locator(`#ch-${chapter}`).count(), 1, `missing ${chapter}`);
    }
    assert.equal(await page.locator('[data-track] [data-seg="load"]').count(), 3);
    await page.locator('[data-seg="load"][data-val="16"]').click();
    assert.match(page.url(), /load=16/);
    assert.match(await page.locator('[data-tbt] [role="status"]').first().textContent(), /16 users selected.*output/i);
    const portraitPage = await browser.newPage({ viewport: { width: 810, height: 1180 } });
    await portraitPage.goto(`${base}#episode-1?load=16&depth=lab&metric=error_rate_pct`);
    await portraitPage.waitForSelector('#ch-evidence[data-explanation-open="error_rate_pct"]');
    assert.equal(await portraitPage.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth), false, 'portrait evidence view has no horizontal page overflow');
    const portraitBoxes = await portraitPage.locator('#ch-evidence .tbt-plot-card, #ch-evidence .tbt-explanation-row > div').evaluateAll(els => els.map(el => ({ left: el.getBoundingClientRect().left, right: el.getBoundingClientRect().right, viewport: innerWidth })));
    assert.equal(portraitBoxes.every(box => box.left >= -1 && box.right <= box.viewport + 1), true, 'portrait evidence charts and explanation stay inside the viewport');
    await portraitPage.close();
    const compactPage = await browser.newPage({ viewport: { width: 1024, height: 900 } });
    await compactPage.goto(`${base}#episode-1?load=16&depth=lab&metric=output_tps`);
    const compactPlot = await compactPage.locator('#ch-evidence [data-selected-metric="output_tps"]').boundingBox();
    const compactExplanation = await compactPage.getByRole('region', { name: 'Explanation: Output throughput' }).boundingBox();
    assert(compactPlot && compactExplanation && compactExplanation.y >= compactPlot.y + compactPlot.height - 1, 'compact desktop evidence stacks explanations instead of clipping the right column');
    await compactPage.close();
    for (const width of [1181, 1200]) {
      const boundaryPage = await browser.newPage({ viewport: { width, height: 900 } });
      await boundaryPage.goto(`${base}#episode-1?load=16&depth=lab&metric=output_tps`);
      const layout = await boundaryPage.locator('#ch-evidence [data-metric-workbench]').evaluate(workbench => {
        const panel = workbench.querySelector('.tbt-metric-panel');
        const plot = workbench.querySelector('.tbt-selected-plot');
        const explanation = workbench.querySelector('.tbt-explanation-row');
        return {
          panelOverflow: getComputedStyle(panel).overflow,
          explanationOverflow: getComputedStyle(explanation).overflow,
          explanationTop: explanation.getBoundingClientRect().top,
          plotBottom: plot.getBoundingClientRect().bottom,
        };
      });
      assert.equal(layout.panelOverflow, 'visible', `evidence panel must not clip content at ${width}px`);
      assert.equal(layout.explanationOverflow, 'visible', `evidence explanation must not become an internal scroller at ${width}px`);
      assert(layout.explanationTop >= layout.plotBottom - 1, `evidence explanation must stack below the plot at ${width}px`);
      await boundaryPage.close();
    }
    const dragPage = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    await dragPage.goto(`${base}#episode-1?load=16`);
    const track = await dragPage.locator('[data-track]').boundingBox();
    assert(track);
    await dragPage.mouse.move(track.x + track.width * .3, track.y + 15);
    await dragPage.mouse.down();
    await dragPage.mouse.move(track.x + track.width * .875, track.y + 15, { steps: 4 });
    await dragPage.mouse.up();
    assert.match(dragPage.url(), /load=24/);
    await dragPage.goBack();
    assert.match(dragPage.url(), /load=16/, 'one drag must create one navigable history entry');
    await dragPage.close();
    const wheelPage = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    await wheelPage.goto(`${base}#episode-1?load=16`);
    assert.match(await wheelPage.locator('.tbt-selector-note').innerText(), /Scroll over the rail.*next recorded load/i, 'the measured-load rail advertises normal wheel interaction');
    const wheelResult = await wheelPage.locator('[data-track]').evaluate(track => {
      const event = new WheelEvent('wheel', { deltaY: 220, bubbles: true, cancelable: true });
      const dispatched = track.dispatchEvent(event);
      return { defaultPrevented: event.defaultPrevented, dispatched };
    });
    assert.deepEqual(wheelResult, { defaultPrevented: true, dispatched: false }, 'the measured-load rail cancels wheel scrolling before snapping');
    await wheelPage.waitForURL(/load=24/);
    assert.equal(await wheelPage.locator('[data-seg="load"][aria-pressed="true"]').getAttribute('data-val'), '24', 'normal wheel scrolling snaps the measured-load selector to the next recorded point');
    await wheelPage.waitForTimeout(200);
    await wheelPage.locator('[data-track]').evaluate(track => track.dispatchEvent(new WheelEvent('wheel', { deltaY: -220, bubbles: true, cancelable: true })));
    await wheelPage.waitForURL(/load=16/);
    await wheelPage.close();
    await page.goto(`${base}#episode-0`);
    assert.match(await page.locator('#page-title').innerText(), /Can 48\.9% more throughput come with 19\.8% higher median TPOT/i);
    assert.equal(await page.locator('.tbt-hero-evidence').count(), 0, 'Episode 00 keeps its result in the Brief only');
    assert.equal(await page.locator('[data-strip] [data-seg="wl"]').count(), 6);
    assert.equal(await page.locator('[data-seg="wl"][aria-pressed="true"]').getAttribute('data-val'), '2048-c24');
    assert.match(await page.locator('[data-workload-guide]').innerText(), /4 of 6 workloads.*Scroll or drag.*use arrows.*Select a workload/is);
    const workloadCue = page.locator('[data-workload-cue]');
    assert.match(await workloadCue.innerText(), /scroll or drag.*select a workload/i);
    const cueStyle = await workloadCue.evaluate(element => ({ background: getComputedStyle(element).backgroundColor, color: getComputedStyle(element).color }));
    assert.equal(cueStyle.background, 'rgba(0, 0, 0, 0)', 'workload guidance does not use a competing color block');
    assert.equal(await workloadCue.locator('em').evaluate(element => getComputedStyle(element).fontStyle), 'italic', 'interaction instruction is visually secondary');
    assert.notEqual(await workloadCue.locator('b').evaluate(element => getComputedStyle(element).color), cueStyle.background, 'workload count remains legible');
    assert.equal(await workloadCue.locator('[data-cue-pointer]').count(), 1, 'workload interaction cue points at the selectable cards');
    assert.equal(await page.getByRole('progressbar', { name: 'Selected workload' }).getAttribute('aria-valuenow'), '4');
    await page.getByRole('button', { name: /Open evidence lab/ }).click();
    await page.waitForFunction(() => document.activeElement?.id === 'h-method');
    const activeMetric = page.getByRole('tab', { selected: true });
    assert.match(await activeMetric.innerText(), /showing/i, 'the active evidence metric is explicitly marked');
    assert.equal(await activeMetric.locator('[data-active-wedge]').count(), 1, 'the active evidence metric has a solid directional marker');
    const firstPlotPoint = page.locator('#ch-evidence [data-plot-point]').first();
    assert.equal(await firstPlotPoint.getAttribute('tabindex'), '0', 'plot points are keyboard focusable');
    assert.match(await firstPlotPoint.getAttribute('aria-label'), /vLLM.*Delivered output rate.*tok\/s/i);
    assert.equal(await firstPlotPoint.evaluate(element => element.closest('button') === null), true, 'focusable plot points are never nested inside buttons');
    await firstPlotPoint.focus();
    const focusedTooltip = page.locator('#ch-evidence [data-plot-tooltip][data-visible="true"]');
    await focusedTooltip.waitFor();
    assert.match(await focusedTooltip.textContent(), /vLLM.*Delivered output rate.*tok\/s/i, 'focused plot point exposes exact x/y details');
    assert.equal(await focusedTooltip.evaluate(el => el.closest('svg') === null), true, 'plot detail is rendered outside the SVG instead of covering the graph');
    const tooltipColors = await focusedTooltip.evaluate(el => ({ color: getComputedStyle(el).color, background: getComputedStyle(el).backgroundColor }));
    assert.deepEqual(tooltipColors, { color: 'rgb(23, 47, 45)', background: 'rgb(251, 250, 245)' }, 'light tooltip uses dark text on a light surface');
    const telemetry = page.locator('#ch-evidence [data-workload-telemetry]');
    assert.match(await telemetry.innerText(), /Waiting requests peak\s+14\.5 req\s+17\.0 req/);
    assert.match(await telemetry.innerText(), /Prefill duration \(native\)\s+1\.12 s\s+∅ Not exposed/);
    assert.match(await telemetry.innerText(), /Decode duration \(native\)\s+4\.55 s\s+∅ Not exposed/);
    assert.equal(await page.locator('#ch-source [data-source-row]').count(), 5);
    assert.match(await page.locator('#ch-source').innerText(), /rounded from retained public runtime and GPU records/i);
    assert.equal(await page.locator('#ch-source a[download="episode-0-public-telemetry.json"]').count(), 1);
    await page.evaluate(() => scrollTo(0, document.documentElement.scrollHeight));
    await page.waitForFunction(() => document.querySelector('.tbt-rail-chapters button:nth-child(5)')?.getAttribute('aria-current') === 'location');
    const deliveredWork = page.locator('#ch-evidence [data-metric="work_per_request"]');
    assert.match(await deliveredWork.innerText(), /Open explanation\s*\+/i, 'expandable metric advertises its explanation');
    const deliveredWorkToggle = deliveredWork.getByRole('button', { name: /Open explanation/ });
    assert.equal(await deliveredWorkToggle.getAttribute('aria-controls'), 'ex-work_per_request');
    await deliveredWorkToggle.click();
    assert.match(await deliveredWork.innerText(), /Close explanation\s*[−-]/i, 'expanded metric advertises how to close its explanation');
    assert.match(await page.getByRole('region', { name: 'Explanation: Delivered output per request' }).innerText(), /Delivered work equality gate.*Equal delivered output/s);
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => document.activeElement?.getAttribute('data-metric-toggle') === 'work_per_request');
    await page.goto(`${base}#episode-0`);
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
    await page.goto(`${base}#episode-1?ch=evidence`);
    await page.locator('#ch-evidence').waitFor();
    assert.match(page.url(), /depth=lab/);
    await page.waitForFunction(() => document.activeElement?.id === 'h-evidence');
    await page.goto(`${base}#episode-1?depth=lab&ch=evidence`);
    await page.waitForFunction(() => document.activeElement?.id === 'h-evidence');
    await page.goto(`${base}#episodes`);
    await page.goBack();
    await page.waitForFunction(() => document.activeElement?.id === 'h-evidence');
    await page.reload();
    await page.waitForFunction(() => document.activeElement?.id === 'h-evidence');
    await page.goto(`${base}#episode-1?load=16&depth=lab&mode=loads&base=12&ch=evidence`);
    assert.match(await page.locator('[data-selected-metric="output_tps"] .tbt-plot-states').innerText(), /vLLM.*Within.*SGLang.*3\.4% worse/is);
    assert.equal(await page.locator('[data-selected-metric="output_tps"] [data-reference="Selected baseline load"]').evaluate(el => el.getAttribute('x1') === el.getAttribute('x2') && el.getAttribute('y1') !== el.getAttribute('y2')), true);
    assert.match(await page.locator('[data-selected-metric="output_tps"] [data-reference="Selected baseline load"]').getAttribute('aria-label'), /12 users.*both engines/);
    assert.match(await page.locator('#ch-evidence .tbt-operands').innerText(), /vLLM at 16 users versus vLLM at 12 users.*SGLang at 16 users versus SGLang at 12 users/s);
    await page.getByRole('button', { name: /Exact measurement ledger/ }).click();
    assert.match(await page.locator('.tbt-wide-ledger').innerText(), /vLLM.*Within.*SGLang.*3\.4% worse/is);
    await page.goto(`${base}#episode-1?mode=bad&base=bad&ch=bad&metric=bad&depth=lab`);
    await page.getByText('Link adjusted').waitFor();
    assert.match(await page.locator('[role="status"]').allInnerTexts().then(x => x.join(' ')), /Link adjusted/);
    assert.doesNotMatch(page.url(), /mode=bad|base=bad|ch=bad|metric=bad/);
    await page.goto(`${base}#episode-1?depth=bogus`);
    await page.getByText('Link adjusted').waitFor();
    assert.match(await page.locator('.tbt-notice').innerText(), /depth is not available/i);
    assert.doesNotMatch(page.url(), /depth=bogus/);
    for (const route of ['episode-0','episode-1']) {
      await page.goto(`${base}#${route}?depth=lab&ch=evidence&metric=${route === 'episode-0' ? 'output_tokens_per_second' : 'output_tps'}`);
      await page.locator('#lab-toggle').click();
      assert.equal(await page.locator('#lab').count(), 0, `${route} lab stays collapsed`);
      assert.doesNotMatch(page.url(), /ch=|metric=/, `${route} clears hidden chapter and metric`);
      assert.equal(await page.locator('#lab-toggle').evaluate(el => el === document.activeElement), true);
      await page.goBack();
      await page.locator('#ch-evidence').waitFor();
      assert.match(page.url(), /ch=evidence/, `${route} Back restores chapter`);
      await page.goForward();
      assert.equal(await page.locator('#lab').count(), 0, `${route} Forward restores collapsed state`);
    }
    await page.goto(`${base}#episodes?ch=recorded`);
    await page.waitForFunction(() => document.activeElement?.id === 'h-recorded');
    await page.goto(`${base}#methodology?ch=states`);
    await page.waitForFunction(() => document.activeElement?.id === 'h-states');
    assert.match(await page.locator('#ch-definitions').innerText(), /Episode 01 alone.*20 tok\/s.*Episode 01 declares.*1%/s);
    assert.doesNotMatch(await page.locator('.tbt-methodology').innerText(), /Field Note/i);
    assert.match(await page.locator('#ch-states').innerText(), /Threshold met.*Threshold missed.*Invalid/s);
    assert.equal(await page.locator('#ch-evidence [data-metric][aria-expanded="true"]').count(), 0);
    await page.goto(`${base}#episode-0`);
    const pager = page.getByRole('navigation', { name: 'Episode pager' });
    assert.equal(await pager.locator('a').count(), 2);
    assert.match(await pager.locator('a').first().innerText(), /SERIES\s+ALL EPISODES/i);
    assert.match(await pager.locator('a').nth(1).innerText(), /NEXT · EPISODE 01(?: →)?\s+MEASURE WHAT MATTERS/i);
    const pagerTitleFont = await pager.locator('a').nth(1).locator('strong').evaluate(el => getComputedStyle(el).fontFamily);
    assert.equal(pagerTitleFont, recordedNumberFont, 'pager episode titles use the episode display typeface');
    assert.equal(await pager.locator('strong').first().evaluate(el => Number.parseFloat(getComputedStyle(el).fontSize) <= 16), true, 'pager titles stay subordinate to page copy');
    await page.goto(`${base}#episode-1`);
    assert.match(await page.getByRole('navigation', { name: 'Episode pager' }).locator('a').nth(1).innerText(), /NEXT · EPISODE 02(?: →)?\s+EQUAL-WORK RUNTIME BASELINE/i);
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
        for (const route of ['episodes','episode-0','episode-1','episode-2','methodology']) {
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
        if (width === 390) {
          for (const chapter of ['method','evidence','boundaries','source']) {
            await page.goto(`${base}#episode-1?depth=lab&ch=${chapter}&text=200`);
            await page.waitForFunction(ch => document.activeElement?.id === `h-${ch}`, chapter);
            const placement = await page.evaluate(ch => ({ heading: document.getElementById(`h-${ch}`).getBoundingClientRect().top, selector: document.querySelector('.tbt-selector').getBoundingClientRect().bottom }), chapter);
            assert(placement.heading >= placement.selector + 8, `${chapter} heading is obscured at 390px 200%: ${JSON.stringify(placement)}`);
          }
          for (const route of ['episode-0','episode-1']) {
            await page.goto(`${base}#${route}?depth=lab&ch=method&text=200`);
            await page.locator('#ch-evidence [data-metric]').first().click();
            for (const selector of ['.tbt-method-cards > div','.tbt-protocol > div','.tbt-boundary-grid > div','.tbt-explanation-row > div','.tbt-field-explanation']) {
              const boxes = await page.locator(selector).evaluateAll(els => els.map(el => ({ right: el.getBoundingClientRect().right, viewport: innerWidth })));
              assert(boxes.every(box => box.right <= box.viewport + 1), `${route} ${selector} clips at 390px 200%`);
            }
          }
        }
        await page.close();
      }
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
