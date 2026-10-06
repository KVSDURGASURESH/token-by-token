const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const dataPath = path.join(root, "dashboard/src/data/session-capacity-study.json");
assert(fs.existsSync(dataPath), "sanitized session-study data must exist");

const study = JSON.parse(fs.readFileSync(dataPath, "utf8"));

assert.equal(study.study_id, "session-capacity-2026-10-05");
assert.equal(study.capacity_qualified, false);
assert.equal(study.context_limit_tokens, 131072);
assert.equal(study.actual_prompt_max_tokens, 6691);
assert.deepEqual(study.levels, [2, 4, 8, 16, 32, 64, 100]);
assert.equal(study.deployments.length, 2);

for (const deployment of study.deployments) {
  assert.equal(deployment.sweep.length, 7);
  assert.deepEqual(deployment.sweep.map((row) => row.users), study.levels);
  assert(deployment.sweep.every((row) => row.measured >= row.valid));
}

const rtx = study.deployments.find((entry) => entry.id === "rtx-pro-6000");
const h200 = study.deployments.find((entry) => entry.id === "h200");
assert(rtx && h200);
assert.equal(rtx.soak.output_tps, 245.7181547412);
assert.equal(h200.soak.output_tps, 379.9426568493);
assert.equal(rtx.soak.visible_ttft_p95_s, 8.216985583);
assert.equal(h200.soak.visible_ttft_p95_s, 2.828482458);
assert.equal(h200.sweep.find((row) => row.users === 16).output_tps, 359.8099363824);
assert.equal(h200.sweep.find((row) => row.users === 64).visible_ttft_p50_s, 22.234826458);

console.log("Session-capacity dashboard data contract passed.");
