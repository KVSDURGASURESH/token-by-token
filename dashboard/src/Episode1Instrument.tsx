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
  return <EpisodeShell study={study} chapters={[{ id: "overview", label: "The question" }, { id: "method", label: "The experiment" }, { id: "results", label: "Linked evidence" }, { id: "configuration", label: "Configuration" }, { id: "boundaries", label: "Boundaries" }] }>
    <section className="instrument-opening" id="method">
      <p className="opening-index">01 / THE EXPERIMENT</p>
      <div><h2>One GPU. Two real deployments. Three matched pressure points.</h2><p>This is not a generic runtime shootout. It is a recorded comparison of the exact configurations below: Qwen3.8-27B-FP8, one H200, a real agent/chat replay corpus, two active sessions per user, two minutes of warm-up and five minutes of measurement.</p></div>
      <aside><strong>12 → 16 → 24</strong><span>users</span><small>24 → 32 → 48 active streams</small></aside>
    </section>
    <LoadSweeper loads={study.loads} selected={selected} baseline={baseline} pinned={pinned !== null} onSelect={setSelected} onPin={(load) => setPinned(load)} />
    <LinkedMetricInstrument study={study} selected={selected} baseline={baseline} />
    <section className="configuration-matrix" id="configuration"><header><span>CONFIGURATION / DO NOT SKIP</span><h2>The runtimes were not configured identically.</h2><p>That makes this a deployment comparison, not an engine-only verdict.</p></header><div>{study.arms.map(arm => <article key={arm.id} className={`arm-${arm.id}`}><h3><i />{arm.label}</h3><ul>{arm.configuration.map(item => <li key={item}>{item}</li>)}</ul></article>)}</div></section>
    <section className="evidence-boundaries" id="boundaries"><header><span>READ THIS BEFORE SHARING</span><h2>What the evidence does—and does not—say.</h2></header><div><section><h3>Observed</h3><ul><li>SGLang leads at 12 and 16 users on output throughput, TTFT and TPOT.</li><li>At 24 users the output advantage reverses while visible latency nearly converges.</li><li>Both deployments keep the H200 highly utilized; their queue and KV signals are runtime-native, not interchangeable.</li></ul></section><section><h3>Not established</h3><ul>{study.limitations.map(item => <li key={item}>{item}</li>)}</ul></section></div><footer><strong>Source:</strong> {study.provenance}. Selection changes the view only; it never reruns the benchmark.</footer></section>
  </EpisodeShell>;
}
