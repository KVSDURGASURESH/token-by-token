import { METRICS, compareReadings, type EvidenceStudy, type MetricDefinition } from "./evidence";

const ids = ["output_tps", "ttft_p50", "ttft_p95", "tpot_p50", "queue_depth", "gpu_utilization", "gpu_memory", "gpu_power", "kv_occupancy"];
const fmt = (value: number | null, unit = "") => value === null ? "—" : `${new Intl.NumberFormat("en-US", { maximumFractionDigits: value < 10 ? 2 : 1 }).format(value)}${unit === "%" ? "%" : ` ${unit}`}`;
const signed = (value: number | null) => value === null ? "—" : `${value >= 0 ? "+" : ""}${value.toFixed(1)}%`;
const pointFor = (study: EvidenceStudy, armId: string, load: number | null) => load === null ? null : study.arms.find(arm => arm.id === armId)?.points.find(point => point.load === load) ?? null;

function status(metric: MetricDefinition, delta: number | null) {
  if (delta === null) return "No comparison";
  if (metric.direction === "contextual") return "◇ Contextual change";
  if (metric.tolerancePercent !== null && Math.abs(delta) <= metric.tolerancePercent) return "≈ Within tolerance";
  const improvement = metric.direction === "higher" ? delta > 0 : delta < 0;
  return improvement ? "✓ Improved" : "↓ Regressed";
}

function MiniPlot({ study, metricId, selected, baseline }: { study: EvidenceStudy; metricId: string; selected: number; baseline: number | null }) {
  const metric = METRICS[metricId];
  const values = study.arms.flatMap(arm => arm.points.map(point => point.readings[metricId]?.value).filter((v): v is number => v !== null && v !== undefined));
  if (!values.length) return null;
  const max = Math.max(...values) || 1;
  const min = Math.min(...values, 0);
  const range = max - min || 1;
  const x = (load: number) => 34 + (study.loads.indexOf(load) / Math.max(1, study.loads.length - 1)) * 532;
  const y = (value: number) => 154 - ((value - min) / range) * 118;
  return <figure className="instrument-plot">
    <figcaption><strong>{metric.label}</strong><span className="instrument-metric-explanation">{metric.explanation}</span></figcaption>
    <svg viewBox="0 0 600 190" role="img" aria-label={`${metric.label} across measured loads`}>
      {[36, 95, 154].map(line => <line key={line} x1="34" x2="566" y1={line} y2={line} className="instrument-gridline" />)}
      {study.loads.map(load => <g key={load}><line x1={x(load)} x2={x(load)} y1="30" y2="160" className={load === selected ? "selection-ruler" : load === baseline ? "baseline-ruler" : "load-ruler"} /><text x={x(load)} y="181" textAnchor="middle">{load}</text></g>)}
      {study.arms.map(arm => {
        const available = arm.points.filter(point => point.readings[metricId]?.available);
        const path = available.map((point, i) => `${i ? "L" : "M"}${x(point.load)},${y(point.readings[metricId].value as number)}`).join(" ");
        return <g key={arm.id} className={`arm-${arm.id}`}><path d={path} className={`instrument-series-line ${arm.lineStyle}`} />{available.map(point => <g key={point.load}><circle cx={x(point.load)} cy={y(point.readings[metricId].value as number)} r={point.load === selected ? 7 : 4} className={point.load === baseline ? "baseline-point" : "metric-point"} /><title>{arm.label}, {point.load} users: {fmt(point.readings[metricId].value, point.readings[metricId].unit)}</title></g>)}</g>;
      })}
    </svg>
    <div className="instrument-legend">{study.arms.map(arm => <span key={arm.id} className={`arm-${arm.id}`}><i />{arm.label}</span>)}<small>simulated users →</small></div>
  </figure>;
}

export function LinkedMetricInstrument({ study, selected, baseline }: { study: EvidenceStudy; selected: number; baseline: number | null }) {
  const summaryBits = study.arms.map(arm => {
    const current = pointFor(study, arm.id, selected);
    const base = pointFor(study, arm.id, baseline);
    if (!current || !base) return `${arm.label}: no previous comparison`;
    const output = compareReadings(current.readings.output_tps, base.readings.output_tps);
    const ttft = compareReadings(current.readings.ttft_p50, base.readings.ttft_p50);
    return `${arm.label}: ${signed(output.relativePercent)} output, ${signed(ttft.relativePercent)} visible TTFT`;
  });
  return <section className="linked-instrument" id="results">
    <div className="comparison-summary" aria-label="Comparison summary" aria-live="polite">
      <span>OBSERVATION / {selected} USERS</span>
      <h2>{baseline === null ? "First measured point; no previous comparison." : `Compared with ${baseline} users`}</h2>
      <p>{summaryBits.join(" · ")}</p>
    </div>
    <div className="instrument-primary-plots"><MiniPlot study={study} metricId="output_tps" selected={selected} baseline={baseline} /><MiniPlot study={study} metricId="ttft_p50" selected={selected} baseline={baseline} /></div>
    <div className="instrument-secondary-plots"><MiniPlot study={study} metricId="tpot_p50" selected={selected} baseline={baseline} /><MiniPlot study={study} metricId="queue_depth" selected={selected} baseline={baseline} /><MiniPlot study={study} metricId="gpu_power" selected={selected} baseline={baseline} /></div>
    <div className="instrument-readouts">
      {study.arms.map(arm => {
        const current = pointFor(study, arm.id, selected);
        const base = pointFor(study, arm.id, baseline);
        return <section key={arm.id} className={`arm-${arm.id}`}><header><i /><h3>{arm.label}</h3><span>{current?.validCount ?? 0} valid samples</span></header><div>{ids.slice(0, 6).map(id => {
          const reading = current?.readings[id]; const result = reading && base ? compareReadings(reading, base.readings[id]) : null;
          return <dl key={id}><dt>{METRICS[id].shortLabel}</dt><dd>{reading ? fmt(reading.value, reading.unit) : "—"}</dd><small>{result?.available ? `${signed(result.relativePercent)} · ${status(METRICS[id], result.relativePercent)}` : reading?.reason ?? "No earlier basis"}</small></dl>;
        })}</div></section>;
      })}
    </div>
    <details className="instrument-data" id="evidence"><summary>Open exact measurement table</summary><div><table className="instrument-data-table"><caption>Exact selected-load readings and comparison deltas</caption><thead><tr><th>Arm</th><th>Metric</th><th>Load</th><th>Value</th><th>Basis</th><th>Absolute Δ</th><th>Relative Δ</th><th>Status / reason</th></tr></thead><tbody>{study.arms.flatMap(arm => ids.map(id => {
      const current = pointFor(study, arm.id, selected)?.readings[id]; const base = pointFor(study, arm.id, baseline)?.readings[id]; const result = current && base ? compareReadings(current, base) : null;
      return <tr key={`${arm.id}-${id}`}><th>{arm.label}</th><td>{METRICS[id].label}</td><td>{selected}</td><td>{current ? fmt(current.value, current.unit) : "—"}</td><td>{baseline ?? "—"}</td><td>{result?.absolute === null || !result ? "—" : fmt(result.absolute, current?.unit)}</td><td>{result?.available ? signed(result.relativePercent) : "—"}</td><td>{current?.available ? status(METRICS[id], result?.relativePercent ?? null) : current?.reason}</td></tr>;
    }))}</tbody></table></div></details>
  </section>;
}
