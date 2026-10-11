const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const read = (file) => fs.readFileSync(path.join(root, file), "utf8");

for (const file of [
  "dashboard/src/MethodologyPage.tsx",
  "dashboard/src/methodology/RequestAnatomy.tsx",
  "dashboard/src/methodology/SessionReplay.tsx",
  "dashboard/src/methodology/EvidenceViews.tsx",
]) assert(fs.existsSync(path.join(root, file)), `${file} must exist`);

const app = read("dashboard/src/App.tsx");
assert.match(app, /#methodology|methodology/);
assert.match(app, /<MethodologyPage/);

const page = read("dashboard/src/MethodologyPage.tsx");
assert.match(page, /50%/);
assert.match(page, /30%/);
assert.match(page, /20%/);
assert.match(page, /coherence/i);
assert.match(page, /smoke/i);
assert.match(page, /warm-up/i);
assert.match(page, /measured window/i);
assert.match(page, /completion validity/i);
assert.match(page, /not established/i);

const anatomy = read("dashboard/src/methodology/RequestAnatomy.tsx");
for (const layer of ["System instructions", "Tool definitions", "Conversation history", "Tool calls / results", "Current instruction", "Expected output"]) assert.match(anatomy, new RegExp(layer, "i"));

const replay = read("dashboard/src/methodology/SessionReplay.tsx");
assert.match(replay, /type="range"/);
for (const stage of ["instruction", "generation", "tool call", "tool gap", "tool result", "accumulated context", "next generation", "human gap"]) assert.match(replay, new RegExp(stage, "i"));

const evidence = read("dashboard/src/methodology/EvidenceViews.tsx");
for (const lane of ["Client-visible", "Engine-native", "GPU telemetry", "static approved aggregates"]) assert.match(evidence, new RegExp(lane, "i"));

console.log("Methodology contract passed.");
