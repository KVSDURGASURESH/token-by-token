const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const episodes = JSON.parse(fs.readFileSync(path.join(root, "dashboard/src/data/episodes.json"), "utf8"));
const episode1 = episodes.episodes.find((entry) => entry.id === "episode-1");

assert.equal(episode1.title, "Measure what matters");
assert.equal(episode1.status, "available");
assert.match(episode1.evidence, /recorded exploratory H200 runtime comparison/i);
assert.equal(episode1.dashboardView, "episode1-instrument");

const dataPath = path.join(root, "dashboard/src/data/episode-1-instrument.json");
assert(fs.existsSync(dataPath), "normalized Episode 01 evidence must exist");
const study = JSON.parse(fs.readFileSync(dataPath, "utf8"));

assert.equal(study.source.agentbench_commit, "6d1908d");
assert.equal(study.model, "Qwen/Qwen3.8-27B-FP8");
assert.equal(study.hardware, "1× NVIDIA H200 141 GB");
assert.equal(study.capacity_qualified, false);
assert.equal(study.provenance_verified, false);
assert.deepEqual(study.levels, [12, 16, 24]);
assert.deepEqual(study.arms.map((arm) => arm.id), ["vllm", "sglang"]);

for (const arm of study.arms) {
  assert.deepEqual(arm.points.map((point) => point.users), study.levels);
  assert(arm.points.every((point) => point.valid_sample_count > 0));
  assert(arm.points.every((point) => point.error_rate <= 0.01));
}

const vllm12 = study.arms.find((arm) => arm.id === "vllm").points[0];
const sglang12 = study.arms.find((arm) => arm.id === "sglang").points[0];
assert.equal(vllm12.output_tps, 374.7588238735019);
assert.equal(sglang12.output_tps, 497.3699412736081);
assert.equal(vllm12.tpot_p50_ms, 36.749324468085106);
assert.equal(sglang12.tpot_p50_ms, 20.63596386725664);

const evidenceSource = fs.readFileSync(path.join(root, "dashboard/src/instrument/evidence.ts"), "utf8");
assert.match(evidenceSource, /previousMeasuredLoad/);
assert.match(evidenceSource, /compareReadings/);
assert.match(evidenceSource, /visible TTFT/);
assert.match(evidenceSource, /adaptEpisode1Study/);
assert.doesNotMatch(evidenceSource, /label:\s*["']Server queue[^"']*TTFT/i);

console.log("Inference Instrument evidence contract passed.");
