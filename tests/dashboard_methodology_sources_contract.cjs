const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const page = fs.readFileSync(path.join(root, 'dashboard/src/PublicSite.tsx'), 'utf8');
const sources = JSON.parse(fs.readFileSync(path.join(root, 'dashboard/src/data/site-v2/methodology-sources.json'), 'utf8'));

assert.equal(sources.length, 9, 'the reviewed AgentBench source inventory stays complete');
for (const source of sources) {
  for (const field of ['group', 'name', 'contributor', 'url', 'license', 'revision', 'use', 'handling', 'status']) {
    assert.equal(typeof source[field], 'string', `${source.name || 'source'} must declare ${field}`);
    assert(source[field].trim(), `${source.name || 'source'} ${field} must not be empty`);
  }
  assert.match(source.url, /^https:\/\//, `${source.name} uses a canonical HTTPS source`);
}

for (const name of ['Nebius', 'Novita', 'WildChat', 'Trace Commons', 'Thoughtworks', 'SWE-bench Pro', 'Kilo Code', 'tau-bench', 'llama-benchy']) {
  assert(sources.some(source => source.name.includes(name)), `${name} is credited`);
}

assert.match(page, /How the <span data-methodology-accent>lab<\/span> measures/);
assert.match(page, /Freeze the contract/);
assert.match(page, /Check the endpoint/);
assert.match(page, /Separate warm-up/);
assert.match(page, /Validate, then report/);
assert.match(page, /AgentBench is a private Mirastack Labs benchmarking harness/);
assert.match(page, /Neither public record claims that the bundled open-dataset mixture/);
assert.match(page, /Attribution is not permission/);
assert.doesNotMatch(page, /AgentBench is (?:an )?open.source/i);

console.log('Methodology source and attribution contract passed.');
