import { useMemo, useState } from "react";
import { EpisodeShell } from "./instrument/EpisodeShell";
import { LoadSweeper } from "./instrument/LoadSweeper";
import { LinkedMetricInstrument } from "./instrument/LinkedMetricInstrument";
import { adaptEpisode1Study, previousMeasuredLoad } from "./instrument/evidence";

export function Episode1Instrument() {
  const study = useMemo(adaptEpisode1Study, []);
  const [selected, setSelected] = useState(16);
  const [pinned, setPinned] = useState<number | null>(null);
  const baseline = pinned ?? previousMeasuredLoad(study.loads, selected);
  return <EpisodeShell study={study} chapters={[{ id: "overview", label: "The question" }, { id: "method", label: "The experiment" }, { id: "results", label: "Linked evidence" }, { id: "evidence-boundary", label: "Evidence boundary" }, { id: "boundaries", label: "Conclusions" }] }>
    <section className="instrument-opening" id="method">
      <p className="opening-index">01 / THE EXPERIMENT</p>
      <div><h2>One GPU. Two inference engines. Three matched pressure points.</h2><p>A recorded deployment comparison: the same model family, one H200, a conversation-and-tool-use workload, two active sessions per user, two minutes of warm-up and five minutes of measurement.</p></div>
      <aside><strong>12 → 16 → 24</strong><span>users</span><small>24 → 32 → 48 active streams</small></aside>
    </section>
    <LoadSweeper loads={study.loads} selected={selected} baseline={baseline} pinned={pinned !== null} onSelect={setSelected} onPin={(load) => setPinned(load)} />
    <LinkedMetricInstrument study={study} selected={selected} baseline={baseline} />
    <section className="evidence-boundary-panel" id="evidence-boundary"><header><span>EVIDENCE BOUNDARY / DO NOT SKIP</span><h2>A deployment comparison, not an engine-only verdict.</h2><p>The public bundle contains measured outcomes and aligned chart signals—not serving recipes or internal deployment details.</p></header><div><article><h3>What is matched</h3><p>Model family, precision, hardware, measured loads, session ratio, warm-up and measurement protocol.</p></article><article><h3>What remains deployment-specific</h3><p>Runtime-native queue and cache definitions. Compare queue trends within an engine; cache signals are intentionally unavailable for ranking.</p></article><article><h3>The declared gate</h3><p>Decode p10 must remain at or above 20 tok/s. TTFT is reported for user-experience analysis but is not a capacity gate.</p></article><article><h3>Result boundary</h3><p><strong>Recorded deployment comparison.</strong> Capacity not established.</p></article></div></section>
    <section className="evidence-boundaries" id="boundaries"><header><span>READ THIS BEFORE SHARING</span><h2>What the evidence does—and does not—say.</h2></header><div><section><h3>Observed</h3><ul><li>SGLang leads at 12 and 16 users on output throughput, TTFT and TPOT.</li><li>At 24 users the output advantage reverses while visible latency nearly converges.</li><li>Both engines clear the decode floor at 12 users and miss it at 16 and 24.</li><li>Both deployments keep the H200 highly utilized while waiting pressure rises.</li></ul></section><section><h3>Not established</h3><ul>{study.limitations.map(item => <li key={item}>{item}</li>)}</ul></section></div><footer><strong>Source:</strong> {study.provenance}. Selection changes the view only; it never reruns the benchmark.</footer></section>
  </EpisodeShell>;
}
