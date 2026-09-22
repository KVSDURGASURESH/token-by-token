import { useEffect, useState } from "react";

type JsonObject = Record<string, unknown>;
type Row = {
  runtime: string; profile: string; repetition: number | null; cellId: string;
  successful: number; failed: number; outputTokens: number | null;
  throughput: number | null; ttft: number | null; tpot: number | null; e2e: number | null;
  ttftP95: number | null; ttftP99: number | null;
};
type Result = { model: string; revision: string; gpu: string; precision: string; classification: string; rows: Row[] };
type MetricSamples = { name: string; count: number; min: number; mean: number; p95: number; max: number };
type Telemetry = { runtime: string; count: number; seconds: number; prefill: number | null; decode: number | null; metrics: MetricSamples[] };

const format = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });
const show = (value: number | null) => value === null ? "Unavailable" : format.format(value);
const palette = ["#45d6ae", "#ff7043", "#8ba9ff", "#f3bb45"];

function object(value: unknown): JsonObject {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Expected a JSON object.");
  return value as JsonObject;
}
function text(value: unknown): string {
  if (typeof value !== "string" || !value.trim() || value.length > 500) throw new Error("Missing or invalid result identity.");
  return value;
}
function number(value: unknown, nullable = false): number | null {
  if (nullable && (value === null || value === undefined)) return null;
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) throw new Error("Metrics must be finite, nonnegative numbers.");
  return value;
}
function count(value: unknown): number {
  const result = number(value) as number;
  if (!Number.isSafeInteger(result)) throw new Error("Counts must be whole numbers.");
  return result;
}
function percentile(cell: JsonObject, name: string, p: "p50" | "p95" | "p99" = "p50"): number | null {
  const metric = object(cell[name]);
  if (metric.available === false) return null;
  if (metric.available !== true) throw new Error("Each latency metric must declare availability.");
  return number(metric[p]);
}

export function parseReaderResult(value: unknown): Result {
  const data = object(value);
  if (data.schema_version !== 1 || !Array.isArray(data.cells) || !data.cells.length || data.cells.length > 1000) {
    throw new Error("Choose a schema-version 1 normalized result with 1–1,000 cells.");
  }
  return {
    model: text(data.model), revision: text(data.model_revision), gpu: text(data.gpu),
    precision: text(data.precision), classification: text(data.classification),
    rows: data.cells.map((entry, index) => {
      const cell = object(entry);
      return {
        runtime: text(cell.runtime), profile: text(cell.profile),
        cellId: typeof cell.cell_id === "string" ? cell.cell_id : `row-${index + 1}`,
        repetition: cell.repetition == null ? null : count(cell.repetition),
        successful: count(cell.successful_requests), failed: count(cell.failed_requests),
        outputTokens: number(cell.successful_output_tokens, true),
        throughput: number(cell.output_tokens_per_second, true),
        ttft: percentile(cell, "client_ttft_ms"), tpot: percentile(cell, "client_tpot_ms"),
        e2e: percentile(cell, "client_e2e_ms"),
        ttftP95: percentile(cell, "client_ttft_ms", "p95"),
        ttftP99: percentile(cell, "client_ttft_ms", "p99"),
      };
    }),
  };
}

function parseTelemetry(value: unknown): Telemetry {
  const data = object(value);
  if (data.schema_version !== 1 || data.classification !== "runtime_native_telemetry_summary") {
    throw new Error("Choose the output from summarize_runtime_metrics.py.");
  }
  const native = object(data.native_window);
  const metrics = object(data.metric_samples);
  if (Object.keys(metrics).length > 100) throw new Error("Too many telemetry metrics.");
  return {
    runtime: text(data.runtime), count: count(data.sample_count), seconds: number(data.window_seconds) as number,
    prefill: number(native.prefill_seconds_per_request, true), decode: number(native.decode_seconds_per_request, true),
    metrics: Object.entries(metrics).map(([name, value]) => {
      const metric = object(value);
      return { name: text(name), count: count(metric.sample_count), min: number(metric.min) as number,
        mean: number(metric.mean) as number, p95: number(metric.p95) as number, max: number(metric.max) as number };
    }),
  };
}

async function readFile(file: File): Promise<unknown> {
  if (file.size > 10 * 1024 * 1024) throw new Error("Choose a summary smaller than 10 MB; keep raw request records outside this viewer.");
  try { return JSON.parse(await file.text()); }
  catch { throw new Error("This file is not valid JSON."); }
}

function ResultsPlot({ rows }: { rows: Row[] }) {
  const points = rows.map((row, index) => ({ ...row, index }))
    .filter((row) => row.ttft !== null && row.throughput !== null);
  const runtimes = [...new Set(rows.map((row) => row.runtime))];
  const top = (value: number) => {
    if (value === 0) return 1;
    const step = 10 ** Math.floor(Math.log10(value));
    return Math.ceil(value * 1.08 / step) * step;
  };
  const maxX = top(Math.max(0, ...points.map((row) => row.ttft! / 1000)));
  const maxY = top(Math.max(0, ...points.map((row) => row.throughput!)));
  const x = (value: number) => 95 + value / maxX * 700;
  const y = (value: number) => 370 - value / maxY * 320;
  return <figure className="scientific-figure reader-plot">
    <figcaption><div><strong>Delivered rate versus first-token wait</strong>
      <span>Each dot is one supplied row. Repetitions stay separate; overlapping dots remain at their measured coordinates.</span></div></figcaption>
    <div className="chart-legend">{runtimes.map((runtime, index) => <span key={runtime}>
      <i style={{ background: palette[index % palette.length] }} />{runtime}</span>)}</div>
    <div className="chart-scroll">
      <svg viewBox="0 0 850 455" className="reader-scatter" role="img" aria-label="Imported results: x-axis TTFT p50 in seconds; y-axis delivered output tokens per second">
        {[0, 1, 2, 3, 4].map((tick) => <g key={tick}>
          <line x1="95" x2="795" y1={y(maxY * tick / 4)} y2={y(maxY * tick / 4)} stroke="var(--line)" />
          <line y1="50" y2="370" x1={x(maxX * tick / 4)} x2={x(maxX * tick / 4)} stroke="var(--line)" />
          <text x="82" y={y(maxY * tick / 4) + 5} textAnchor="end">{show(maxY * tick / 4)}</text>
          <text y="395" x={x(maxX * tick / 4)} textAnchor="middle">{show(maxX * tick / 4)}</text>
        </g>)}
        <text x="445" y="432" textAnchor="middle">Client TTFT p50 (seconds) →</text>
        <text transform="translate(24 210) rotate(-90)" textAnchor="middle">Delivered output rate (tokens/s) →</text>
        {points.map((row) => <g key={row.index} className="reader-point" tabIndex={0}>
          <title>{`Row ${row.index + 1}: ${row.runtime} · ${row.profile} · repetition ${row.repetition ?? "unrecorded"}; TTFT ${show(row.ttft! / 1000)} s, throughput ${show(row.throughput)} tok/s`}</title>
          <circle cx={x(row.ttft! / 1000)} cy={y(row.throughput!)} r="6" fill={palette[runtimes.indexOf(row.runtime) % palette.length]} stroke="var(--paper)" strokeWidth="1.5" />
          <text x={x(row.ttft! / 1000) + 9} y={y(row.throughput!) - 8}>{row.index + 1}</text>
        </g>)}
      </svg>
    </div>
    <p className="reader-note">{points.length} of {rows.length} rows plotted. Dot numbers match the table. Unavailable metrics are omitted. These points do not establish an equal-work comparison or a controlled sweep.</p>
  </figure>;
}

export function ReaderResults() {
  const [result, setResult] = useState<Result | null>(null);
  const [filename, setFilename] = useState("");
  const [error, setError] = useState("");
  const [telemetry, setTelemetry] = useState<Telemetry | null>(null);
  const [telemetryError, setTelemetryError] = useState("");
  useEffect(() => { document.title = "Local results — INFERENCE LAB"; }, []);

  return <article className="published-study reader-results">
    <header className="study-identity"><div><span className="series-kicker">INFERENCE LAB / YOUR MEASUREMENTS</span>
      <h1>Open your experiment</h1><p>Inspect normalized results in your browser. Files stay on this device.</p></div></header>
    <section className="reader-import" aria-label="Import local results">
      <label htmlFor="result-file">Normalized benchmark JSON</label>
      <input id="result-file" type="file" accept=".json,application/json" onChange={async (event) => {
        const file = event.target.files?.[0]; if (!file) return;
        setError(""); setResult(null); setTelemetry(null); setTelemetryError("");
        try { setResult(parseReaderResult(await readFile(file))); setFilename(file.name); }
        catch (failure) { setError(failure instanceof Error ? failure.message : "Unable to read result."); }
      }} />
      <p>Use the JSON produced by <code>normalize_live_benchmark_results.py</code>. Each input repetition remains a separate row; this viewer does not pool percentiles.</p>
      {error && <p role="alert" className="warning-text">{error}</p>}
    </section>
    {result && <>
      <section className="reader-context"><span className="status">{result.classification}</span>
        <h2>{result.model}</h2><p>{result.gpu} · {result.precision} · {result.rows.length} rows · {filename}</p>
        <p className="reader-note">Model revision: {result.revision}. Imported evidence is user-supplied; opening it does not verify provider provenance or experimental validity.</p></section>
      <ResultsPlot rows={result.rows} />
      <section className="results"><div className="section-label"><h2>Every repetition, visible</h2>
        <p>Read latency beside delivered work. No historical values are added to imported results.</p></div>
        <div className="published-study-table" tabIndex={0} aria-label="Imported benchmark rows"><table>
          <thead><tr><th>Row / runtime / workload</th><th>Repetition</th><th>Successful / attempted</th><th>Mean output tokens</th><th>TTFT p50 / p95 / p99 (ms)</th><th>TPOT p50 (ms)</th><th>E2E p50 (ms)</th><th>Output rate (tok/s)</th></tr></thead>
          <tbody>{result.rows.map((row, index) => <tr key={`${row.cellId}-${index}`}>
            <th scope="row">{index + 1}. {row.runtime}<small>{row.profile}</small></th>
            <td>{row.repetition ?? "Unrecorded"}</td><td>{row.successful} / {row.successful + row.failed}</td>
            <td>{show(row.outputTokens !== null && row.successful > 0 ? row.outputTokens / row.successful : null)}</td>
            <td>{show(row.ttft)} / {show(row.ttftP95)} / {show(row.ttftP99)}</td>
            <td>{show(row.tpot)}</td><td>{show(row.e2e)}</td><td>{show(row.throughput)}</td>
          </tr>)}</tbody>
        </table></div>
      </section>
      <section className="reader-import"><label htmlFor="runtime-file">Optional runtime telemetry summary</label>
        <input id="runtime-file" type="file" accept=".json,application/json" onChange={async (event) => {
          const file = event.target.files?.[0]; if (!file) return;
          setTelemetryError(""); setTelemetry(null);
          try {
            const imported = parseTelemetry(await readFile(file));
            if (!result.rows.some((row) => row.runtime.toLowerCase() === imported.runtime.toLowerCase())) throw new Error("Telemetry runtime does not appear in the imported benchmark.");
            setTelemetry(imported);
          } catch (failure) { setTelemetryError(failure instanceof Error ? failure.message : "Unable to read telemetry."); }
        }} />
        <p>Choose output from <code>summarize_runtime_metrics.py</code>. Confirm it belongs to the same run. Full-window telemetry is shown separately from benchmark cells.</p>
        {telemetryError && <p role="alert" className="warning-text">{telemetryError}</p>}
      </section>
      {telemetry && <section className="results"><div className="section-label"><h2>{telemetry.runtime} runtime window</h2>
        <p>{telemetry.count} samples over {show(telemetry.seconds)} seconds. Phase means use histogram deltas; sample percentiles below describe scrapes, not request latency.</p></div>
        <div className="reader-phases"><p><span>Prefill per request</span><strong>{show(telemetry.prefill)}{telemetry.prefill === null ? "" : " s"}</strong></p>
          <p><span>Decode per request</span><strong>{show(telemetry.decode)}{telemetry.decode === null ? "" : " s"}</strong></p></div>
        <div className="published-study-table" tabIndex={0} aria-label="Imported runtime telemetry"><table>
          <thead><tr><th>Native metric</th><th>Samples</th><th>Min</th><th>Sample mean</th><th>Sample p95</th><th>Max</th></tr></thead>
          <tbody>{telemetry.metrics.map((metric) => <tr key={metric.name}><th scope="row">{metric.name}</th><td>{metric.count}</td>
            <td>{show(metric.min)}</td><td>{show(metric.mean)}</td><td>{show(metric.p95)}</td><td>{show(metric.max)}</td></tr>)}</tbody>
        </table></div><p className="reader-note">Metric names retain native units: *_seconds values use seconds; *_total, *_count and request gauges are counts; KV usage is a runtime-specific fraction. Cumulative counter samples are not per-request durations.</p>
      </section>}
    </>}
  </article>;
}
