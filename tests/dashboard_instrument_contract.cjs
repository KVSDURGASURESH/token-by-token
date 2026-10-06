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

const dataPath = path.join(root, "dashboard/src/data/episode-1-public.v1.json");
assert(fs.existsSync(dataPath), "normalized Episode 01 evidence must exist");
const study = JSON.parse(fs.readFileSync(dataPath, "utf8"));

assert.equal(study.schema_version, "public-inference-evidence.v1");
assert.equal(study.study.model_family, "Qwen3.8 27B");
assert.equal(study.study.hardware, "NVIDIA H200");
assert.equal(study.methodology.capacity_state, "not_established");
assert.equal(study.methodology.decode_threshold_tps, 20);
assert.equal(study.methodology.ttft_gated, false);
assert.deepEqual(study.levels, [12, 16, 24]);
assert.deepEqual(study.arms.map((arm) => arm.engine), ["vLLM", "SGLang"]);

for (const arm of study.arms) {
  assert.deepEqual(arm.points.map((point) => point.users), study.levels);
  assert(arm.points.every((point) => point.valid_requests > 0));
  assert(arm.points.every((point) => point.readings.error_rate_pct.value <= 1));
}

const vllm12 = study.arms.find((arm) => arm.engine === "vLLM").points[0];
const sglang12 = study.arms.find((arm) => arm.engine === "SGLang").points[0];
assert.equal(vllm12.readings.output_tps.value, 374.7588238735019);
assert.equal(sglang12.readings.output_tps.value, 497.36994127360805);
assert.equal(vllm12.readings.tpot_p50_ms.value, 36.749324468085106);
assert.equal(sglang12.readings.tpot_p50_ms.value, 20.63596386725664);
assert.equal(study.synchronized_series.length > 0, true);

const evidenceSource = fs.readFileSync(path.join(root, "dashboard/src/instrument/evidence.ts"), "utf8");
assert.match(evidenceSource, /previousMeasuredLoad/);
assert.match(evidenceSource, /compareReadings/);
assert.match(evidenceSource, /visible TTFT/);
assert.match(evidenceSource, /adaptEpisode1Study/);
assert.match(evidenceSource, /episode-1-public\.v1\.json/);
assert.doesNotMatch(evidenceSource, /\.configuration\b/);
assert.doesNotMatch(evidenceSource, /label:\s*["']Server queue[^"']*TTFT/i);

console.log("Inference Instrument evidence contract passed.");
