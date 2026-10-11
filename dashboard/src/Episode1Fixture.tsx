import fixture from "../../fixtures/episode1/public-aggregate.fixture.json";
import plan from "../../fixtures/episode1/episode1-planning.json";

type Summary = (typeof fixture.summaries)[number];
type MetricName = "ttft_ms" | "e2e_ms" | "requests" | "output_tokens" | "request_goodput" | "token_goodput";

const runtimeLabel = (runtime: string) => runtime.startsWith("vllm") ? "vLLM" : "SGLang";
const cellLabel = (cell: string) => ({
  "fixed-short": "512 in / 128 out · C1",
  "fixed-medium": "2,048 in / 128 out · C4",
  "natural-quality": "Natural stop · C1",
}[cell] ?? cell);

function metric(summary: Summary, name: MetricName) {
  if (name === "ttft_ms" || name === "e2e_ms") {
    const item = summary.latency[name];
    return { available: item.available, value: item.p50, reason: item.unavailable_reason };
  }
  const item = summary.throughput[name];
  return { available: item.available, value: item.value, reason: item.unavailable_reason };
}

function MetricChart({ name, title, unit }: { name: MetricName; title: string; unit: string }) {
  const values = fixture.summaries.map(item => metric(item, name)).filter(item => item.available && item.value !== null);
  const maximum = Math.max(...values.map(item => item.value ?? 0), 1);
  return (
    <figure className="episode1-chart">
      <figcaption><strong>{title}</strong><span>Per block and workload; synthetic contract values</span></figcaption>
      <div className="episode1-bars">
        {fixture.summaries.map(item => {
          const measured = metric(item, name);
          const value = measured.value;
          return <div className="episode1-bar-row" key={`${name}-${item.block_id}-${item.cell_id}`}>
            <span>{item.block_id.replace("block-", "B")} · {item.cell_id.replace("fixed-", "")}</span>
            <div aria-hidden="true">{measured.available && value !== null ? <i style={{ width: `${value === 0 ? 0 : Math.max(2, value / maximum * 100)}%` }} /> : null}</div>
            {measured.available && value !== null
              ? <strong>{value.toFixed(name.endsWith("_ms") ? 0 : 1)} {unit}</strong>
              : <strong className="metric-unavailable" title={measured.reason ?? "unavailable"}>— unavailable</strong>}
          </div>;
        })}
      </div>
    </figure>
  );
}

export function Episode1Fixture() {
  const natural = fixture.summaries.filter(item => item.cell_id === "natural-quality");
  const fixtureFailureShape = natural.every(item => item.counts.schema_valid === 23 && item.counts.semantic_correct === 22 && item.counts.nontruncated === 23);
  const telemetryStates = fixture.telemetry.reduce<Record<string, { available: number; unavailable: number; reasons: Set<string> }>>((states, item) => {
    const state = states[item.metric] ?? { available: 0, unavailable: 0, reasons: new Set<string>() };
    if (item.available) state.available += 1;
    else {
      state.unavailable += 1;
      if (item.unavailable_reason) state.reasons.add(item.unavailable_reason);
    }
    states[item.metric] = state;
    return states;
  }, {});
  return (
    <article className="episode1-fixture">
      <header className="episode1-hero">
        <p className="lab-eyebrow">Token by Token / Inference Lab / Episode 01</p>
        <h1>Measure What Matters</h1>
        <p className="episode1-deck">The measurement contract comes before the runtime comparison.</p>
        <div className="fixture-warning" role="note">
          <strong>LOCAL FIXTURE — NOT PROVIDER MEASUREMENT</strong>
          <span>No GPU · no provider spend · synthetic contract timings · not approval evidence</span>
        </div>
      </header>

      <section className="episode1-facts" aria-label="Episode 1 planned protocol">
        <div><span>Candidate</span><strong>1 × H100 80GB</strong><small>Provider unverified</small></div>
        <div><span>Work</span><strong>{plan.totals.measured_requests} measured</strong><small>{plan.totals.warmups} declared warmups</small></div>
        <div><span>Design</span><strong>3 paired blocks</strong><small>Fresh runtime process per arm</small></div>
        <div><span>Status</span><strong>Not execution-ready</strong><small>No approval phrase</small></div>
      </section>

      <section className="episode1-section" aria-labelledby="fixture-schedule-title">
        <div className="lab-section-heading"><h2 id="fixture-schedule-title">The 18 declared cells</h2><p>Each card is one block/workload summary. Failures stay in the denominator.</p></div>
        <div className="episode1-cell-grid">
          {fixture.summaries.map(item => <article key={`${item.block_id}-${item.cell_id}`}>
            <p>{item.pair_id} · {item.block_id}</p>
            <h3>{runtimeLabel(item.runtime)}</h3>
            <strong>{cellLabel(item.cell_id)}</strong>
            <dl>
              <div><dt>Scheduled</dt><dd>{item.counts.scheduled}</dd></div>
              <div><dt>Transport success</dt><dd>{item.counts.transport_success}</dd></div>
              <div><dt>Unsent</dt><dd>{item.counts.unsent}</dd></div>
              <div><dt>Stop</dt><dd>{item.mode === "fixed_output" ? `${item.stop_reasons.length} length` : `${item.stop_reasons.eos} EOS`}</dd></div>
            </dl>
          </article>)}
        </div>
      </section>

      <section className="episode1-section" aria-labelledby="fixture-measures-title">
        <div className="lab-section-heading"><h2 id="fixture-measures-title">Separate measurements, never one score</h2><p>p50 is shown here for fixture readability. p99 is intentionally absent from this small design.</p></div>
        <div className="episode1-chart-grid">
          <MetricChart name="ttft_ms" title="Time to first token · p50" unit="ms" />
          <MetricChart name="e2e_ms" title="End-to-end latency · p50" unit="ms" />
          <MetricChart name="requests" title="Request throughput" unit="req/s" />
          <MetricChart name="output_tokens" title="Output-token throughput" unit="tok/s" />
          <MetricChart name="request_goodput" title="Qualified request goodput" unit="req/s" />
          <MetricChart name="token_goodput" title="Qualified token goodput" unit="tok/s" />
        </div>
      </section>

      <section className="episode1-section" aria-labelledby="fixture-work-title">
        <div className="lab-section-heading"><h2 id="fixture-work-title">Delivered work and stop outcomes</h2><p>Exact output-token totals and every scheduled stop outcome remain visible beside failures.</p></div>
        <div className="episode1-cell-grid compact">
          {fixture.summaries.map(item => <article key={`work-${item.block_id}-${item.cell_id}`}>
            <p>{item.block_id} · {cellLabel(item.cell_id)}</p>
            <h3>{item.counts.successful_output_tokens ?? "—"} tokens</h3>
            <dl>
              <div><dt>Success / scheduled</dt><dd>{item.counts.transport_success} / {item.counts.scheduled}</dd></div>
              <div><dt>Qualified</dt><dd>{item.counts.slo_qualified ?? "unavailable"}</dd></div>
              <div><dt>Length / EOS</dt><dd>{item.stop_reasons.length} / {item.stop_reasons.eos}</dd></div>
              <div><dt>Failed / timeout / unsent</dt><dd>{item.counts.failed + item.counts.http_failed + item.counts.sse_failed} / {item.counts.timeout} / {item.counts.unsent}</dd></div>
            </dl>
          </article>)}
        </div>
      </section>

      <section className="episode1-section" aria-labelledby="fixture-quality-title">
        <div className="lab-section-heading"><h2 id="fixture-quality-title">Natural-stop quality contract</h2><p>The authored gate for a real block is 24/24 schema-valid and at least 23/24 semantically correct.</p></div>
        <div className="episode1-table-wrap" tabIndex={0}>
          <table className="episode1-table">
            <thead><tr><th>Block</th><th>Runtime</th><th>Scheduled</th><th>Schema valid</th><th>Semantic correct</th><th>Nontruncated</th><th>Fixture gate</th></tr></thead>
            <tbody>{natural.map(item => <tr key={item.block_id}><th>{item.block_id}</th><td>{runtimeLabel(item.runtime)}</td><td>{item.counts.scheduled}</td><td>{item.counts.schema_valid}</td><td>{item.counts.semantic_correct}</td><td>{item.counts.nontruncated}</td><td className="warning">Does not pass</td></tr>)}</tbody>
          </table>
        </div>
        <p className="episode1-quality-note">Expected fixture failure shape: <strong>{fixtureFailureShape ? "confirmed" : "unexpected fixture contents"}</strong>. This is not the quality gate. One request per cell is unsent, and one transported output is semantically incorrect. A real run must report both facts rather than hiding them.</p>
      </section>

      <section className="episode1-section" aria-labelledby="fixture-telemetry-title">
        <div className="lab-section-heading"><h2 id="fixture-telemetry-title">Telemetry availability</h2><p>Unsupported or absent evidence stays a labeled gap; it is never plotted as zero.</p></div>
        <div className="episode1-telemetry-grid">
          {Object.entries(telemetryStates).map(([metricName, state]) => <article key={metricName}>
            <h3>{metricName.replaceAll("_", " ")}</h3>
            <strong>{state.available} available · {state.unavailable} unavailable</strong>
            <p>{[...state.reasons].join("; ") || "No unavailable reason recorded"}</p>
          </article>)}
        </div>
      </section>

      <section className="methodology" aria-labelledby="fixture-boundary-title">
        <h2 id="fixture-boundary-title">Evidence boundary</h2>
        <ul>{fixture.limitations.map(limit => <li key={limit}>{limit}</li>)}<li>Protocol <code>{fixture.protocol_sha256.slice(0, 12)}…</code>; full hash is retained in the fixture.</li></ul>
      </section>
    </article>
  );
}
