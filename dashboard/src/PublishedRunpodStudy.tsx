import { useEffect } from "react";
import studyJson from "./data/latest.json";
import { ScientificCharts } from "./ScientificCharts";
import { TelemetryCharts } from "./TelemetryCharts";
import {
  disclosureGroups,
  evidenceLines,
  goodputPresentation,
  methodologyLimitations,
  setDocumentTitle,
  studyIdentity,
  studyTotals,
  type Distribution,
  type Goodput,
  type PublishedStudy,
} from "./studyPresentation";

const study = studyJson as PublishedStudy;
const integer = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const decimal = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 });

function value(number: number | null | undefined, unit = "") {
  return typeof number === "number" && Number.isFinite(number)
    ? `${decimal.format(number)}${unit}`
    : "Unavailable";
}

function metricValues(metric: Distribution) {
  if (!metric.available) return <span className="unavailable">Unavailable</span>;
  return (
    <span className="percentiles">
      <span><b>p50</b> {value(metric.p50)}</span>
      <span><b>p95</b> {value(metric.p95)}</span>
      <span><b>p99</b> {value(metric.p99)}</span>
      <span className="unit">ms</span>
    </span>
  );
}

function evidenceClass(line: string) {
  return line.startsWith("Warning:") || line.startsWith("Unavailable:")
    ? "evidence warning"
    : "evidence";
}

function MetricCell({ metric }: { metric: Distribution }) {
  return (
    <td>
      {metricValues(metric)}
      <span className="evidence-stack">
        {evidenceLines(metric).map((line) => <small className={evidenceClass(line)} key={line}>{line}</small>)}
      </span>
    </td>
  );
}

function GoodputCell({ goodput }: { goodput: Goodput }) {
  const presentation = goodputPresentation(goodput);
  return (
    <td>
      {presentation.available
        ? <strong>{value(presentation.tokensPerSecond, " tok/s")}</strong>
        : <strong className="unavailable">Goodput unavailable</strong>}
      <span className="evidence-stack">
        {presentation.lines.map((line) => <small className={evidenceClass(line)} key={line}>{line}</small>)}
      </span>
    </td>
  );
}

export function PublishedRunpodStudy() {
  const identity = studyIdentity(study);
  const totals = studyTotals(study);
  const disclosures = disclosureGroups(study.study_facts);
  const limitations = methodologyLimitations(study);

  useEffect(() => {
    setDocumentTitle(document, study);
  }, []);

  return (
    <article className="published-study">
      <header className="study-identity">
        <div>
          <span className="series-kicker">INFERENCE LAB <b>Episode 0: Warm-up</b></span>
          <span className="status">{identity.classification} artifact</span>
          <h1>{identity.title}</h1>
          <p>{study.model} / {study.precision} / {study.gpu}</p>
        </div>
        <code title={study.model_revision}>revision {study.model_revision.slice(0, 12)}…</code>
      </header>

      <section className="metric-strip" aria-label="Study totals">
        <div><span>Runtime engines</span><strong>{totals.engineCount}</strong></div>
        <div><span>Matrix cells</span><strong>{totals.cellCount}</strong></div>
        <div><span>Attempted requests</span><strong>{String(totals.attempted)}</strong></div>
        <div><span>Failures</span><strong className={totals.failures === 0 ? "safe" : "warning-text"}>{integer.format(totals.failures)}</strong></div>
        <div><span>Peak output throughput</span><strong>{value(totals.peakThroughput, " tok/s")}</strong></div>
        <div><span>Goodput evidence</span><strong>{totals.availableGoodputCells > 0 ? `${totals.availableGoodputCells}/${totals.cellCount} cells` : "Unavailable"}</strong></div>
      </section>

      {disclosures.length > 0 && <section className="disclosures" aria-labelledby="disclosures-title">
        <div className="section-label">
          <h2 id="disclosures-title">Study disclosures</h2>
          <p>Each fact remains in the category assigned by the normalized artifact.</p>
        </div>
        <div className="disclosure-groups">
          {disclosures.map((group) => (
            <section key={group.key}>
              <h3>{group.label}</h3>
              <ul>{group.facts.map((fact) => <li key={fact}>{fact}</li>)}</ul>
            </section>
          ))}
        </div>
      </section>}

      <section className="evidence-board" aria-labelledby="board-title">
        <div className="section-label">
          <h2 id="board-title">Measured performance</h2>
          <p>Six categorical workloads pair both runtimes. Input length and concurrency change together across profiles, so the charts do not represent a controlled concurrency sweep.</p>
        </div>
        <ScientificCharts cells={study.cells} />
      </section>

      <section className="telemetry-board" aria-labelledby="telemetry-title">
        <div className="section-label">
          <h2 id="telemetry-title">Runtime and device telemetry</h2>
          <p>Sanitized aggregate summaries show native phase timing where exposed, KV and queue pressure, and device peaks. Missing runtime metrics remain visibly unavailable.</p>
        </div>
        <TelemetryCharts />
      </section>

      <section className="results" aria-labelledby="results-title">
        <div className="section-label">
          <h2 id="results-title">Exact comparison table</h2>
          <p>Scroll horizontally inside the table to inspect the complete evidence envelope.</p>
        </div>
        <div className="published-study-table" tabIndex={0} aria-label="Scrollable benchmark results">
          <table>
            <caption>Complete normalized client-side streaming results. Request totals and metric evidence are reported per row; unavailable evidence is never inferred.</caption>
            <thead>
              <tr>
                <th>Runtime / profile</th>
                <th>TTFT p50 / p95 / p99</th>
                <th>TPOT p50 / p95 / p99</th>
                <th>ITL p50 / p95 / p99</th>
                <th>E2E p50 / p95 / p99</th>
                <th>Output throughput</th>
                <th>Goodput</th>
                <th>Requests</th>
              </tr>
            </thead>
            <tbody>
              {study.cells.map((cell) => (
                <tr key={`${cell.runtime}-${cell.profile}`}>
                  <th scope="row"><strong>{cell.runtime}</strong><small>{cell.profile}</small></th>
                  <MetricCell metric={cell.client_ttft_ms} />
                  <MetricCell metric={cell.client_tpot_ms} />
                  <MetricCell metric={cell.client_itl_ms} />
                  <MetricCell metric={cell.client_e2e_ms} />
                  <td><strong>{value(cell.output_tokens_per_second, " tok/s")}</strong></td>
                  <GoodputCell goodput={cell.goodput} />
                  <td><strong>{cell.successful_requests}/{cell.successful_requests + cell.failed_requests}</strong><small className="evidence">successful / attempted</small></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <footer className="methodology">
        <h2>How to read this study</h2>
        <ul>{limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}</ul>
      </footer>
    </article>
  );
}
