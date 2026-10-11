import { EvidenceViews } from "./methodology/EvidenceViews";
import { RequestAnatomy } from "./methodology/RequestAnatomy";
import { SessionReplay } from "./methodology/SessionReplay";

const chapters = [
  ["method-question", "Why realism"],
  ["method-population", "Population"],
  ["method-request", "Request anatomy"],
  ["method-replay", "Two-session replay"],
  ["method-protocol", "Protocol gates"],
  ["method-evidence", "Aligned evidence"],
  ["method-meaning", "What it means"],
] as const;

const scrollTo = (id: string) => {
  const target = document.getElementById(id);
  if (!target) return;
  target.tabIndex = -1;
  target.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
  target.focus({ preventScroll: true });
};

export function MethodologyPage() {
  return <div className="method-page">
    <aside className="method-rail"><p>METHODOLOGY / 01</p><nav aria-label="Methodology chapters">{chapters.map(([id, label], index) => <button key={id} type="button" onClick={() => scrollTo(id)}><span>{String(index + 1).padStart(2, "0")}</span>{label}</button>)}</nav></aside>
    <article className="method-story">
      <header className="method-hero" id="method-question"><p>HOW THE STUDY BECOMES EVIDENCE</p><h1>Benchmark the session, not the toy prompt.</h1><div><p>A fast single-turn completion can hide the pressure created by long context, tool use, human pauses and two simultaneous sessions. This method keeps those behaviors in the workload, then separates what was observed from what was never established.</p><strong>realistic traffic<br />measured boundaries<br />static publication</strong></div></header>

      <section className="method-section population-section" id="method-population"><header><span>01 / POPULATION</span><h2>Three traffic shapes. One declared mix.</h2><p>The study replays a fixed, seeded population assembled from open, de-identified request corpora. Personal fields and unsafe material are excluded upstream; the public site carries no request content.</p></header><div className="population-strata"><article><strong>50%</strong><h3>Repository-scale agent work</h3><p>Multi-turn coding trajectories with realistic system context, tools and returned observations.</p></article><article><strong>30%</strong><h3>Interactive coding sessions</h3><p>Long-lived assistant sessions whose tool gaps and human pauses shape offered load.</p></article><article><strong>20%</strong><h3>General conversation</h3><p>Tool-free, multi-turn chat keeps the population from collapsing into one workload archetype.</p></article></div></section>

      <section className="method-section" id="method-request"><header><span>02 / REQUEST ANATOMY</span><h2>A request is accumulated state.</h2><p>Reveal each layer to see why prompt length and cache behavior evolve during a session. Bands show structure, never source content.</p></header><RequestAnatomy /></section>

      <section className="method-section" id="method-replay"><header><span>03 / TWO-SESSION REPLAY</span><h2>Concurrency is people × open sessions.</h2><p>Each simulated user holds two independent session slots. The replay preserves output length and pacing so a tool gap does not masquerade as server latency.</p></header><SessionReplay /></section>

      <section className="method-section" id="method-protocol"><header><span>04 / PROTOCOL GATES</span><h2>Fail early. Measure only the declared window.</h2><p>A result advances only when its prerequisite is satisfied or explicitly recorded as unavailable.</p></header><ol className="protocol-line"><li><b>Coherence</b><span>Recall, long context and structured tool-use probes.</span></li><li><b>Smoke</b><span>One-user end-to-end health and telemetry visibility.</span></li><li><b>Warm-up</b><span>Two minutes absorb cold session starts.</span></li><li><b>Measured window</b><span>Five minutes at one declared user level.</span></li><li><b>Completion validity</b><span>Reject a level above 1% failed requests.</span></li><li><b>Threshold</b><span>Decode p10 must stay at or above 20 tok/s.</span></li><li><b>Report</b><span>Publish observations; capacity remains not established unless every gate qualifies.</span></li></ol></section>

      <section className="method-section" id="method-evidence"><header><span>05 / ALIGNED EVIDENCE</span><h2>Client, engine and GPU tell different parts of the story.</h2><p>Alignment supports explanation. It does not make unlike runtime-native metrics directly comparable.</p></header><EvidenceViews /></section>

      <section className="method-section" id="method-meaning"><header><span>06 / INTERPRETATION</span><h2>Definitions before conclusions.</h2><p>The labels below are deliberately narrow; the page does not stretch one metric into a claim it cannot support.</p></header><dl className="definition-ledger"><div><dt>TTFT</dt><dd>Client request start to first visible token. It includes more than server queue time.</dd></div><div><dt>TPOT</dt><dd>Per-request time between output tokens after the first. It is not whole-server output throughput.</dd></div><div><dt>Decode tok/s</dt><dd>Per-request generation speed. p10 means 90% of valid requests were at least this fast.</dd></div><div><dt>Output throughput</dt><dd>Successful output tokens per measured second across the deployment.</dd></div><div><dt>Completion validity</dt><dd>The response satisfied the recorded completion contract. It does not establish task correctness.</dd></div><div><dt>Contextual telemetry</dt><dd>Queue, cache and GPU signals explain behavior; incompatible native definitions are not ranked.</dd></div></dl><div className="method-boundary"><section><h3>Observed</h3><p>Recorded values at 12, 16 and 24 users, aligned across client, engine and GPU windows.</p></section><section><h3>Not established</h3><p>Universal engine superiority, task-solving quality, statistical significance, or capacity beyond the declared gate.</p></section></div></section>
    </article>
  </div>;
}
