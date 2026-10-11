import { useState } from "react";
import { METRICS, compareReadings, type EvidenceArm, type EvidenceStudy, type MetricDefinition } from "./evidence";
import type { ComparisonMode } from "../Episode1Instrument";

const ids = ["output_tps", "ttft_p50_ms", "ttft_p95_ms", "tpot_p50_ms", "decode_p10_tps", "error_rate_pct", "running_requests_mean", "waiting_requests_mean", "gpu_utilization_pct", "gpu_memory_gib", "gpu_power_w", "cache_context"];
const fmt = (value: number | null, unit = "") => value === null ? "—" : `${new Intl.NumberFormat("en-US", { maximumFractionDigits: value < 10 ? 2 : 1 }).format(value)}${unit === "%" ? "%" : ` ${unit}`}`;
const signed = (value: number | null) => value === null ? "—" : `${value >= 0 ? "+" : ""}${value.toFixed(1)}%`;
const pointFor = (study: EvidenceStudy, armId: string, load: number | null) => load === null ? null : study.arms.find(arm => arm.id === armId)?.points.find(point => point.load === load) ?? null;

function status(metric: MetricDefinition, delta: number | null) {
  if (delta === null) return "No comparison";
  if (metric.direction === "contextual") return "◇ Contextual change";
  if (metric.tolerancePercent !== null && Math.abs(delta) <= metric.tolerancePercent) return `≈ Changed <${metric.tolerancePercent}% (display band)`;
  const improvement = metric.direction === "higher" ? delta > 0 : delta < 0;
  return improvement ? "✓ Improved" : "↓ Regressed";
}

function outcome(metric: MetricDefinition, delta: number | null) {
  if (delta === null || metric.direction === "contextual") return "neutral";
  if (metric.tolerancePercent !== null && Math.abs(delta) <= metric.tolerancePercent) return "neutral";
  return (metric.direction === "higher" ? delta > 0 : delta < 0) ? "better" : "worse";
}

const directionLabel = (metric: MetricDefinition) => metric.direction === "higher" ? "Higher is better" : metric.direction === "lower" ? "Lower is better" : "Context only";

function PlotMarker({ marker, x, y, radius, className }: { marker: EvidenceArm["marker"]; x: number; y: number; radius: number; className: string }) {
  if (marker === "diamond") return <polygon points={`${x},${y - radius} ${x + radius},${y} ${x},${y + radius} ${x - radius},${y}`} className={className} />;
  if (marker === "square") return <rect x={x - radius} y={y - radius} width={radius * 2} height={radius * 2} className={className} />;
  return <circle cx={x} cy={y} r={radius} className={className} />;
}

function DecodeThreshold({ study, selected }: { study: EvidenceStudy; selected: number }) {
  if (study.decodeThreshold === null) return null;
  return <section className="decode-threshold" aria-label="Decode p10 threshold">
    <header><span>EXPERIENCE FLOOR / {selected} USERS</span><h2>Can 90% of valid requests stay above the line?</h2><p><strong>p10</strong> means 90% of valid requests decoded at least this fast. The declared threshold is {fmt(study.decodeThreshold, "tok/s")}.</p></header>
    <div>{study.arms.map((arm) => {
      const value = pointFor(study, arm.id, selected)?.readings.decode_p10_tps.value ?? null;
      const met = value !== null && value >= study.decodeThreshold!;
      const width = value === null ? 0 : Math.min(100, value / (study.decodeThreshold! * 2) * 100);
      return <article key={arm.id} className={`arm-${arm.id} ${met ? "threshold-met" : "threshold-missed"}`}><div><i /><h3>{arm.label}</h3><strong>{fmt(value, "tok/s")}</strong></div><div className="threshold-track" aria-label={`${arm.label}: ${met ? "threshold met" : "threshold missed"}`}><span style={{ width: `${width}%` }} /><b style={{ left: "50%" }} /></div><p>{met ? "✓ Threshold met" : "↓ Threshold missed"}</p></article>;
    })}</div>
  </section>;
}

function MiniPlot({ study, metricId, selected, baseline, active, onSelect }: { study: EvidenceStudy; metricId: string; selected: number; baseline: number | null; active: boolean; onSelect(metricId: string): void }) {
  const metric = METRICS[metricId];
  const values = study.arms.flatMap(arm => arm.points.map(point => point.readings[metricId]?.value).filter((v): v is number => v !== null && v !== undefined));
  if (!values.length) return null;
  const max = Math.max(...values) || 1;
  const min = Math.min(...values, 0);
  const range = max - min || 1;
  const minLoad = Math.min(...study.loads); const loadRange = Math.max(...study.loads) - minLoad || 1;
  const x = (load: number) => 48 + ((load - minLoad) / loadRange) * 518;
  const y = (value: number) => 154 - ((value - min) / range) * 118;
  return <figure className={`instrument-plot ${active ? "active" : ""}`} role="button" tabIndex={0} aria-pressed={active} aria-label={`Explain ${metric.label}`} onClick={() => onSelect(metricId)} onKeyDown={event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onSelect(metricId); } }}>
    <figcaption><strong>{metric.label}</strong><span className="instrument-metric-explanation">{metric.explanation}</span></figcaption>
    <svg viewBox="0 0 600 190" role="img" aria-label={`${metric.label} across measured loads`}>
      {[36, 95, 154].map(line => <line key={line} x1="48" x2="566" y1={line} y2={line} className="instrument-gridline" />)}
      <text x="43" y="39" textAnchor="end">{new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(max)}</text>
      <text x="43" y="157" textAnchor="end">{new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(min)}</text>
      <text x="48" y="18">{metric.unit}</text>
      {study.loads.map(load => <g key={load}><line x1={x(load)} x2={x(load)} y1="30" y2="160" className={load === selected ? "selection-ruler" : load === baseline ? "baseline-ruler" : "load-ruler"} /><text x={x(load)} y="181" textAnchor="middle">{load}</text></g>)}
      {study.arms.map(arm => {
        const available = arm.points.filter(point => point.readings[metricId]?.available);
        const path = available.map((point, i) => `${i ? "L" : "M"}${x(point.load)},${y(point.readings[metricId].value as number)}`).join(" ");
        return <g key={arm.id} className={`arm-${arm.id}`}><path d={path} className={`instrument-series-line ${arm.lineStyle}`} />{available.map(point => <g key={point.load}><PlotMarker marker={arm.marker} x={x(point.load)} y={y(point.readings[metricId].value as number)} radius={point.load === selected ? 7 : 4} className={point.load === baseline ? "baseline-point" : "metric-point"} />{point.load === selected && <text x={x(point.load)} y={Math.max(30, y(point.readings[metricId].value as number) - 12)} textAnchor="middle" className="selected-value">{fmt(point.readings[metricId].value, point.readings[metricId].unit)}</text>}<title>{arm.label}, {point.load} users: {fmt(point.readings[metricId].value, point.readings[metricId].unit)}</title></g>)}</g>;
      })}
    </svg>
    <div className="instrument-legend">{study.arms.map(arm => <span key={arm.id} className={`arm-${arm.id}`} data-marker={arm.marker}><i />{arm.label} · {arm.marker}</span>)}<small>recorded users → numeric scale</small></div>
  </figure>;
}

function MetricExplanation({ study, metricId, selected }: { study: EvidenceStudy; metricId: string; selected: number }) {
  const metric = METRICS[metricId];
  const source = metricId.startsWith("gpu_") ? "Aligned GPU sample" : metricId.includes("requests") || metricId === "cache_context" ? "Engine-native gauge" : "Client-visible or derived result";
  const caveat = metric.direction === "contextual" ? "Context only. Use this signal to explain a pattern, not to declare a winner." : `A ${metric.tolerancePercent ?? 0}%${metric.tolerancePercent === null ? "" : " display band"} is descriptive, not a confidence interval.`;
  return <aside className="metric-explanation-panel" aria-live="polite" aria-label="Metric explanation">
    <header><span>METRIC EXPLANATION / {source}</span><h3>{metric.label}</h3><p>{metric.unit} · {directionLabel(metric)}</p></header>
    <div><p>{metric.explanation}</p><strong>{caveat}</strong></div>
    <table><caption>Recorded values; selected load highlighted</caption><thead><tr><th>Users</th>{study.arms.map(arm => <th key={arm.id}>{arm.label} · {arm.marker}</th>)}</tr></thead><tbody>{study.loads.map(load => <tr key={load} className={load === selected ? "selected" : undefined}><th>{load}</th>{study.arms.map(arm => <td key={arm.id}>{fmt(pointFor(study, arm.id, load)?.readings[metricId]?.value ?? null, metric.unit)}</td>)}</tr>)}</tbody></table>
  </aside>;
}

export function LinkedMetricInstrument({ study, selected, baseline, mode }: { study: EvidenceStudy; selected: number; baseline: number | null; mode: ComparisonMode }) {
  const [explainedMetric, setExplainedMetric] = useState("output_tps");
  const summaryBits = study.arms.map(arm => {
    const current = pointFor(study, arm.id, selected);
    const base = pointFor(study, arm.id, baseline);
    if (!current || !base) return `${arm.label}: no previous comparison`;
    const output = compareReadings(current.readings.output_tps, base.readings.output_tps);
    const ttft = compareReadings(current.readings.ttft_p50_ms, base.readings.ttft_p50_ms);
    return `${arm.label}: ${signed(output.relativePercent)} output, ${signed(ttft.relativePercent)} visible TTFT`;
  });
  const firstArm = pointFor(study, study.arms[0]?.id, selected);
  const secondArm = pointFor(study, study.arms[1]?.id, selected);
  const outputAcrossArms = firstArm && secondArm ? compareReadings(secondArm.readings.output_tps, firstArm.readings.output_tps) : null;
  const ttftAcrossArms = firstArm && secondArm ? compareReadings(secondArm.readings.ttft_p50_ms, firstArm.readings.ttft_p50_ms) : null;
  const crossArmAnswer = outputAcrossArms?.available && ttftAcrossArms?.available
    ? `${study.arms[1].label} recorded ${Math.abs(outputAcrossArms.relativePercent ?? 0).toFixed(1)}% ${Number(outputAcrossArms.relativePercent) >= 0 ? "more" : "less"} output and ${Math.abs(ttftAcrossArms.relativePercent ?? 0).toFixed(1)}% ${Number(ttftAcrossArms.relativePercent) <= 0 ? "lower" : "higher"} median TTFT than ${study.arms[0].label}.`
    : "A direct arm comparison is unavailable at this load.";
  return <section className="linked-instrument" id="results">
    <div className="runtime-answer" aria-label="Runtime comparison answer"><span>DIRECT ANSWER / {selected} USERS / {mode === "deployments" ? "DEPLOYMENTS" : "LOAD CHANGE"}</span><strong>{mode === "deployments" ? crossArmAnswer : baseline === null ? "Choose a later point or pin a measured baseline to compare loads." : summaryBits.join(" · ")}</strong><p>{mode === "deployments" ? "Recorded deployment comparison only: runtime configurations differ, capacity was not established, and statistical uncertainty was not estimated." : `Each deployment is compared with its own recorded ${baseline ?? "earlier"}-user point. No values are interpolated.`}</p></div>
    <div className="comparison-summary" aria-label="Comparison summary" aria-live="polite">
      <span>OBSERVATION / {selected} USERS</span>
      <h2>{mode === "deployments" ? `${study.arms[1].label} versus ${study.arms[0].label} at ${selected} users` : baseline === null ? "First measured point; no previous comparison." : `Compared with ${baseline} users`}</h2>
      <p>{mode === "deployments" ? crossArmAnswer : summaryBits.join(" · ")}</p>
      <small>Changes under 2% use a descriptive display band; this is not a confidence interval or significance test.</small>
    </div>
    <DecodeThreshold study={study} selected={selected} />
    <div className="instrument-primary-plots"><MiniPlot study={study} metricId="output_tps" selected={selected} baseline={mode === "loads" ? baseline : null} active={explainedMetric === "output_tps"} onSelect={setExplainedMetric} /><MiniPlot study={study} metricId="ttft_p50_ms" selected={selected} baseline={mode === "loads" ? baseline : null} active={explainedMetric === "ttft_p50_ms"} onSelect={setExplainedMetric} /></div>
    <div className="instrument-secondary-plots"><MiniPlot study={study} metricId="tpot_p50_ms" selected={selected} baseline={mode === "loads" ? baseline : null} active={explainedMetric === "tpot_p50_ms"} onSelect={setExplainedMetric} /><MiniPlot study={study} metricId="waiting_requests_mean" selected={selected} baseline={mode === "loads" ? baseline : null} active={explainedMetric === "waiting_requests_mean"} onSelect={setExplainedMetric} /><MiniPlot study={study} metricId="gpu_power_w" selected={selected} baseline={mode === "loads" ? baseline : null} active={explainedMetric === "gpu_power_w"} onSelect={setExplainedMetric} /></div>
    <MetricExplanation study={study} metricId={explainedMetric} selected={selected} />
    <div className="instrument-readouts">
      {study.arms.map((arm, armIndex) => {
        const current = pointFor(study, arm.id, selected);
        const comparisonArm = study.arms[armIndex === 0 ? 1 : 0];
        const comparisonPoint = mode === "deployments" ? pointFor(study, comparisonArm?.id, selected) : pointFor(study, arm.id, baseline);
        return <section key={arm.id} className={`arm-${arm.id}`}><header><i /><h3>{arm.label}</h3><span>{current?.validCount ?? 0} / {current?.sampleCount ?? 0} completion-valid requests</span></header><p className="validity-note">Completion validity checks the recorded response contract; it does not establish task correctness.</p><div>{ids.slice(0, 7).map(id => {
          const reading = current?.readings[id]; const result = reading && comparisonPoint ? compareReadings(reading, comparisonPoint.readings[id]) : null;
          const resultOutcome = outcome(METRICS[id], result?.relativePercent ?? null);
          const comparisonLabel = mode === "deployments" ? `${comparisonArm?.label} at ${selected} users` : `${baseline ?? "—"} users`;
          return <dl key={id}><dt>{METRICS[id].shortLabel}<em>{directionLabel(METRICS[id])}</em></dt><dd>{reading ? fmt(reading.value, reading.unit) : "—"}</dd><small className={`metric-outcome ${result?.available ? resultOutcome : "neutral"}`}>{result?.available ? `${resultOutcome === "better" ? "↑" : resultOutcome === "worse" ? "↓" : "≈"} ${signed(result.relativePercent)} · ${status(METRICS[id], result.relativePercent)} vs ${comparisonLabel}` : reading?.reason ?? "No comparison basis"}</small></dl>;
        })}</div></section>;
      })}
    </div>
    <details className="instrument-data" id="evidence"><summary>Open exact measurement table</summary><div><table className="instrument-data-table"><caption>Exact selected-load readings and comparison deltas</caption><thead><tr><th>Arm</th><th>Metric</th><th>Load</th><th>Value</th><th>Basis</th><th>Absolute Δ</th><th>Relative Δ</th><th>Status / reason</th></tr></thead><tbody>{study.arms.flatMap(arm => ids.map(id => {
      const armIndex = study.arms.findIndex(candidate => candidate.id === arm.id); const comparisonArm = study.arms[armIndex === 0 ? 1 : 0];
      const current = pointFor(study, arm.id, selected)?.readings[id]; const comparisonPoint = mode === "deployments" ? pointFor(study, comparisonArm?.id, selected) : pointFor(study, arm.id, baseline); const basis = mode === "deployments" ? `${comparisonArm?.label} at ${selected}` : baseline ?? "—"; const result = current && comparisonPoint ? compareReadings(current, comparisonPoint.readings[id]) : null;
      return <tr key={`${arm.id}-${id}`}><th>{arm.label}</th><td>{METRICS[id].label}</td><td>{selected}</td><td>{current ? fmt(current.value, current.unit) : "—"}</td><td>{basis}</td><td>{result?.absolute === null || !result ? "—" : fmt(result.absolute, current?.unit)}</td><td>{result?.available ? signed(result.relativePercent) : "—"}</td><td>{current?.available ? status(METRICS[id], result?.relativePercent ?? null) : current?.reason}</td></tr>;
    }))}</tbody></table></div></details>
  </section>;
}
