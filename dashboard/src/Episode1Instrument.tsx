import { useEffect, useMemo, useState } from "react";
import { EpisodeShell } from "./instrument/EpisodeShell";
import { LoadSweeper } from "./instrument/LoadSweeper";
import { LinkedMetricInstrument } from "./instrument/LinkedMetricInstrument";
import { METRICS, adaptEpisode1Study, compareReadings, previousMeasuredLoad, type EvidenceStudy } from "./instrument/evidence";

export type ComparisonMode = "deployments" | "loads";
type ExperienceDepth = "brief" | "evidence";

const briefMetrics = ["output_tps", "ttft_p50_ms", "tpot_p50_ms", "decode_p10_tps"];
const briefFormat = (value: number | null, unit: string) => value === null ? "—" : `${new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(value)} ${unit}`;

function EpisodeBrief({ study, selected, onSelect, onOpenEvidence }: { study: EvidenceStudy; selected: number; onSelect(load: number): void; onOpenEvidence(): void }) {
  const first = study.arms[0]?.points.find(point => point.load === selected);
  const second = study.arms[1]?.points.find(point => point.load === selected);
  return <section className="episode-basic-readout" id="brief-results">
    <header><div><span>BASIC VIEW / FOUR SIGNALS</span><h2>Enough to understand the result.</h2></div><div className="basic-load-control" role="group" aria-label="Basic measured load">{study.loads.map(load => <button key={load} type="button" aria-pressed={load === selected} onClick={() => onSelect(load)}>{load}<small>users</small></button>)}</div></header>
    <div className="basic-metric-ledger">{briefMetrics.map(id => {
      const metric = METRICS[id]; const firstReading = first?.readings[id]; const secondReading = second?.readings[id];
      const delta = firstReading && secondReading ? compareReadings(secondReading, firstReading).relativePercent : null;
      const neutral = delta === null || (metric.tolerancePercent !== null && Math.abs(delta) <= metric.tolerancePercent);
      const better = !neutral && (metric.direction === "higher" ? Number(delta) > 0 : Number(delta) < 0);
      const verdict = neutral ? "neutral" : better ? "better" : "worse";
      return <article key={id}><div><span>{metric.shortLabel}</span><small>{metric.direction === "higher" ? "Higher is better" : "Lower is better"}</small></div><dl><div><dt>{study.arms[0].label}</dt><dd>{briefFormat(firstReading?.value ?? null, metric.unit)}</dd></div><div><dt>{study.arms[1].label}</dt><dd>{briefFormat(secondReading?.value ?? null, metric.unit)}</dd></div></dl><strong className={`metric-outcome ${verdict}`}><i aria-hidden="true">{neutral ? "≈" : better ? "✓" : "✕"}</i>{delta === null ? "Unavailable" : `${Math.abs(delta).toFixed(1)}% · ${neutral ? "effectively unchanged" : better ? "better" : "worse"}`}</strong></article>;
    })}</div>
    <footer><div><strong>Want the mechanism and exact evidence?</strong><p>Open the evidence lab for all linked plots, metric definitions, threshold checks, validity counts, and the exact measurement table.</p></div><button type="button" onClick={onOpenEvidence}>Open evidence lab <span aria-hidden="true">→</span></button></footer>
  </section>;
}

function LeadFinding({ study, selected }: { study: EvidenceStudy; selected: number }) {
  const first = study.arms[0]?.points.find(point => point.load === selected);
  const second = study.arms[1]?.points.find(point => point.load === selected);
  const output = first && second ? compareReadings(second.readings.output_tps, first.readings.output_tps).relativePercent : null;
  const ttft = first && second ? compareReadings(second.readings.ttft_p50_ms, first.readings.ttft_p50_ms).relativePercent : null;
  if (output === null || ttft === null) return <strong>Direct comparison unavailable at this measured point.</strong>;
  const outputBetter = output > 0;
  const ttftBetter = ttft < 0;
  return <strong>
    {study.arms[1].label} recorded <span className={`metric-outcome ${outputBetter ? "better" : "worse"}`}><i aria-hidden="true">{outputBetter ? "↑" : "↓"}</i>{Math.abs(output).toFixed(1)}% {outputBetter ? "more" : "less"} output</span> and <span className={`metric-outcome ${ttftBetter ? "better" : "worse"}`}><i aria-hidden="true">{ttftBetter ? "↓" : "↑"}</i>{Math.abs(ttft).toFixed(1)}% {ttftBetter ? "lower" : "higher"} median TTFT</span> than {study.arms[0].label}.
  </strong>;
}

export function Episode1Instrument() {
  const study = useMemo(adaptEpisode1Study, []);
  const initialState = useMemo(() => {
    const query = new URLSearchParams(window.location.hash.split("?")[1] ?? "");
    const load = Number(query.get("load"));
    const baseline = Number(query.get("baseline"));
    return {
      selected: study.loads.includes(load) ? load : 16,
      pinned: study.loads.includes(baseline) ? baseline : null,
      mode: query.get("mode") === "loads" ? "loads" as ComparisonMode : "deployments" as ComparisonMode,
      depth: query.get("depth") === "evidence" ? "evidence" as ExperienceDepth : "brief" as ExperienceDepth,
    };
  }, [study.loads]);
  const [selected, setSelected] = useState(initialState.selected);
  const [pinned, setPinned] = useState<number | null>(initialState.pinned);
  const [mode, setMode] = useState<ComparisonMode>(initialState.mode);
  const [depth, setDepth] = useState<ExperienceDepth>(initialState.depth);
  const baseline = pinned ?? previousMeasuredLoad(study.loads, selected);
  useEffect(() => {
    const query = new URLSearchParams({ load: String(selected), mode });
    if (pinned !== null) query.set("baseline", String(pinned));
    window.history.replaceState(null, "", `#episode-1?load=${query.get("load")}&mode=${query.get("mode")}${depth === "evidence" ? "&depth=evidence" : ""}${pinned === null ? "" : `&baseline=${pinned}`}`);
  }, [depth, mode, pinned, selected]);
  const chapters = depth === "brief" ? [{ id: "overview", label: "The question" }, { id: "brief-results", label: "Four signals" }] : [{ id: "overview", label: "The question" }, { id: "method", label: "The experiment" }, { id: "results", label: "Linked evidence" }, { id: "evidence-boundary", label: "Evidence boundary" }, { id: "boundaries", label: "Conclusions" }];
  return <EpisodeShell study={study} chapters={chapters}>
    <section className="instrument-lead" aria-label="Episode 01 lead finding">
      <div><span>RECORDED OBSERVATION / {selected} USERS</span><LeadFinding study={study} selected={selected} /><p>Matched load, one H200. Deployment comparison only; capacity and statistical significance were not established.</p></div>
      {depth === "evidence" ? <div className="comparison-mode" role="group" aria-label="Comparison mode">
        <button type="button" aria-pressed={mode === "deployments"} onClick={() => setMode("deployments")}><span>01</span>Compare deployments<small>at this load</small></button>
        <button type="button" aria-pressed={mode === "loads"} onClick={() => setMode("loads")}><span>02</span>Compare loads<small>within each deployment</small></button>
      </div> : <div className="brief-state"><span>BRIEF</span><strong>1 finding</strong><small>4 essential signals</small></div>}
    </section>
    {depth === "brief" ? <EpisodeBrief study={study} selected={selected} onSelect={setSelected} onOpenEvidence={() => setDepth("evidence")} /> : <>
    <button className="depth-return" type="button" onClick={() => setDepth("brief")}>← Back to the episode brief</button>
    <section className="instrument-opening" id="method">
      <p className="opening-index">01 / THE EXPERIMENT</p>
      <div><h2>One GPU. Two inference engines. Three matched pressure points.</h2><p>A recorded deployment comparison: the same model family, one H200, a conversation-and-tool-use workload, two active sessions per user, two minutes of warm-up and five minutes of measurement.</p></div>
      <aside><strong>12 → 16 → 24</strong><span>simulated users</span><small>24 → 32 → 48 session slots</small></aside>
    </section>
    <LoadSweeper loads={study.loads} selected={selected} baseline={baseline} pinned={pinned !== null} onSelect={setSelected} onPin={(load) => setPinned(load)} />
    <LinkedMetricInstrument study={study} selected={selected} baseline={baseline} mode={mode} />
    <section className="evidence-boundary-panel" id="evidence-boundary"><header><span>EVIDENCE BOUNDARY / DO NOT SKIP</span><h2>A deployment comparison, not an engine-only verdict.</h2><p>The public bundle contains measured outcomes and aligned chart signals—not serving recipes or internal deployment details.</p></header><div><article><h3>What is matched</h3><p>Model family, precision, hardware, measured loads, session ratio, warm-up and measurement protocol.</p></article><article><h3>What remains deployment-specific</h3><p>Runtime-native queue and cache definitions. Compare queue trends within an engine; cache signals are intentionally unavailable for ranking.</p></article><article><h3>The declared gate</h3><p>Decode p10 must remain at or above 20 tok/s. TTFT is reported for user-experience analysis but is not a capacity gate.</p></article><article><h3>Result boundary</h3><p><strong>Recorded deployment comparison.</strong> Tested loads only; maximum sustainable request rate was not measured.</p></article></div></section>
    <section className="evidence-boundaries" id="boundaries"><header><span>READ THIS BEFORE SHARING</span><h2>What the evidence does—and does not—say.</h2></header><div><section><h3>Observed</h3><ul><li>SGLang leads at 12 and 16 users on output throughput, TTFT and TPOT.</li><li>At 24 users the output advantage reverses while visible latency nearly converges.</li><li>Both engines clear the decode floor at 12 users and miss it at 16 and 24.</li><li>Both deployments keep the H200 highly utilized while waiting pressure rises.</li></ul></section><section><h3>Not established</h3><ul>{study.limitations.map(item => <li key={item}>{item}</li>)}</ul></section></div><footer><strong>Source:</strong> {study.provenance}. Selection changes the view only; it never reruns the benchmark.</footer></section>
    </>}
  </EpisodeShell>;
}
