import { useEffect, useState } from "react";
import studyData from "./data/session-capacity-study.json";

const study = studyData;
type Deployment = (typeof study.deployments)[number];
type SweepRow = Deployment["sweep"][number];

const one = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 });
const two = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const integer = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

function percent(value: number) {
  return `${two.format(value * 100)}%`;
}

type PlotProps = {
  title: string;
  description: string;
  metric: (row: SweepRow) => number;
  maximum: number;
  ticks: number[];
  formatTick: (value: number) => string;
  log?: boolean;
};

function SweepPlot({ title, description, metric, maximum, ticks, formatTick, log = false }: PlotProps) {
  const width = 720;
  const height = 330;
  const plot = { left: 62, right: 24, top: 28, bottom: 54 };
  const plotWidth = width - plot.left - plot.right;
  const plotHeight = height - plot.top - plot.bottom;
  const x = (index: number) => plot.left + index / (study.levels.length - 1) * plotWidth;
  const y = (value: number) => {
    if (!log) return plot.top + plotHeight - value / maximum * plotHeight;
    const floor = 0.5;
    const normalized = (Math.log10(Math.max(value, floor)) - Math.log10(floor)) /
      (Math.log10(maximum) - Math.log10(floor));
    return plot.top + plotHeight - normalized * plotHeight;
  };

  return (
    <figure className="session-plot">
      <figcaption><strong>{title}</strong><span>{description}</span></figcaption>
      <div className="session-chart-scroll">
        <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${title}. ${description}`}>
          {ticks.map((tick) => <g key={tick}>
            <line className="session-gridline" x1={plot.left} x2={width - plot.right} y1={y(tick)} y2={y(tick)} />
            <text className="session-tick" x={plot.left - 10} y={y(tick) + 4} textAnchor="end">{formatTick(tick)}</text>
          </g>)}
          <line className="session-axis" x1={plot.left} x2={plot.left} y1={plot.top} y2={height - plot.bottom} />
          <line className="session-axis" x1={plot.left} x2={width - plot.right} y1={height - plot.bottom} y2={height - plot.bottom} />
          {study.levels.map((level, index) => <g key={level}>
            <text className="session-tick" x={x(index)} y={height - 24} textAnchor="middle">{level}</text>
          </g>)}
          <text className="session-axis-label" x={plot.left + plotWidth / 2} y={height - 4} textAnchor="middle">Simulated users</text>
          {study.deployments.map((deployment) => {
            const points = deployment.sweep.map((row, index) => `${x(index)},${y(metric(row))}`).join(" ");
            return <g key={deployment.id}>
              <polyline points={points} fill="none" stroke={deployment.color} strokeWidth="3" />
              {deployment.sweep.map((row, index) => <circle
                key={row.users}
                cx={x(index)}
                cy={y(metric(row))}
                r={row.users === 16 || row.users === 64 ? 6 : 4}
                fill={deployment.color}
                stroke="#071018"
                strokeWidth="2"
              ><title>{deployment.label}, {row.users} users: {formatTick(metric(row))}; {row.valid}/{row.measured} valid</title></circle>)}
            </g>;
          })}
        </svg>
      </div>
      <div className="session-legend">
        {study.deployments.map((deployment) => <span key={deployment.id}><i style={{ background: deployment.color }} />{deployment.label}</span>)}
      </div>
    </figure>
  );
}

function SoakColumn({ deployment }: { deployment: Deployment }) {
  const soak = deployment.soak;
  return (
    <section className="soak-column" style={{ "--deployment-color": deployment.color } as React.CSSProperties}>
      <header><i /> <h3>{deployment.label}</h3></header>
      <dl>
        <div><dt>Aggregate output</dt><dd>{two.format(soak.output_tps)} <small>tok/s</small></dd></div>
        <div><dt>Visible TTFT p95</dt><dd>{two.format(soak.visible_ttft_p95_s)} <small>s</small></dd></div>
        <div><dt>Request decode p50</dt><dd>{two.format(soak.decode_tps_p50)} <small>tok/s</small></dd></div>
        <div><dt>Errors</dt><dd>{percent(soak.error_rate)}</dd></div>
        <div><dt>Valid / measured</dt><dd>{integer.format(soak.valid)} / {integer.format(soak.measured)}</dd></div>
        <div><dt>Visible timing coverage</dt><dd>{integer.format(soak.visible_ttft_samples)} / {integer.format(soak.valid)}</dd></div>
      </dl>
    </section>
  );
}

export function SessionCapacityStudy() {
  const [selectedUsers, setSelectedUsers] = useState(16);
  const h200 = study.deployments.find((deployment) => deployment.id === "h200")!;
  const at16 = h200.sweep.find((row) => row.users === 16)!;
  const at64 = h200.sweep.find((row) => row.users === 64)!;
  const outputGain = (at64.output_tps / at16.output_tps - 1) * 100;
  const waitMultiple = at64.visible_ttft_p50_s / at16.visible_ttft_p50_s;

  useEffect(() => {
    document.title = "Session capacity field note — INFERENCE LAB";
  }, []);

  return (
    <article className="session-study">
      <header className="session-hero">
        <div className="session-hero-copy">
          <p className="session-kicker">Token by Token · recorded field note</p>
          <h1><span>Three percent more output.</span><span>Nineteen times the wait.</span></h1>
          <p className="session-deck">A conversational-load study of two Qwen3.6-27B-FP8 deployments—and a reminder that the highest token rate can be the wrong operating point.</p>
        </div>
        <aside className="qualification-stamp" aria-label="Qualification status">
          <strong>Capacity not established</strong>
          <span>Every formal capacity verdict remains unqualified.</span>
        </aside>
      </header>

      <section className="tension-lanes" aria-label="Headline H200 sweep result">
        <div className="tension-lane output-lane">
          <span>Aggregate output</span>
          <strong>+{one.format(outputGain)}%</strong>
          <small>{two.format(at16.output_tps)} → {two.format(at64.output_tps)} tok/s</small>
        </div>
        <div className="tension-connector" aria-hidden="true"><i /><i /><i /><i /><i /></div>
        <div className="tension-lane wait-lane">
          <span>Median visible-text wait</span>
          <strong>{one.format(waitMultiple)}× as long</strong>
          <small>{two.format(at16.visible_ttft_p50_s)} → {two.format(at64.visible_ttft_p50_s)} seconds</small>
        </div>
        <p>One H200 sweep, 16 → 64 simulated users. Discrete tested levels; no fitted capacity curve.</p>
      </section>

      <section className="session-section matched-study" aria-labelledby="matched-title">
        <header className="session-section-heading">
          <h2 id="matched-title">The matched 16-user soaks</h2>
          <p>Fifteen measured minutes per deployment. Up to 32 client requests could be in flight; serving profiles and runtime controls remain withheld.</p>
        </header>
        <div className="soak-comparison">{study.deployments.map((deployment) => <SoakColumn deployment={deployment} key={deployment.id} />)}</div>
        <p className="metric-definition">Aggregate output is valid completion tokens divided by cohort duration including bounded drain. Visible TTFT measures the interval from client request start to the first text-content event; missing timings are excluded. Request decode rate is client-derived and may include reasoning or tool events; it is not direct GPU decode speed.</p>
      </section>

      <section className="session-section" aria-labelledby="sweep-title">
        <header className="session-section-heading">
          <h2 id="sweep-title">The sweep tells two stories</h2>
          <p>Throughput, visible waiting and failures must be read together. The H200 32-user failure spike remains visible rather than being averaged away.</p>
        </header>
        <fieldset className="load-selector" aria-label="Compare measured load">
          <legend>Compare measured load</legend>
          <div>{study.levels.map((level) => <button
            key={level}
            type="button"
            aria-pressed={selectedUsers === level}
            onClick={() => setSelectedUsers(level)}
          >{level} users</button>)}</div>
        </fieldset>
        <div className="selected-load" aria-label="Selected sweep comparison" aria-live="polite">
          <header><span>Selected sweep point</span><strong>{selectedUsers} simulated users · {selectedUsers * study.workload.slots_per_user} client slots</strong></header>
          <div className="selected-load-grid">{study.deployments.map((deployment) => {
            const row = deployment.sweep.find((item) => item.users === selectedUsers)!;
            return <section key={deployment.id} style={{ "--deployment-color": deployment.color } as React.CSSProperties}>
              <h3><i />{deployment.label}</h3>
              <dl>
                <div><dt>Aggregate output</dt><dd>{two.format(row.output_tps)} <small>tok/s</small></dd></div>
                <div><dt>Median visible wait</dt><dd>{two.format(row.visible_ttft_p50_s)} <small>s</small></dd></div>
                <div><dt>p95 visible wait</dt><dd>{two.format(row.visible_ttft_p95_s)} <small>s</small></dd></div>
                <div><dt>Invalid / failed</dt><dd>{percent(row.error_rate)}</dd></div>
                <div><dt>Valid / measured</dt><dd>{integer.format(row.valid)} / {integer.format(row.measured)}</dd></div>
              </dl>
            </section>;
          })}</div>
          <p>Sweep values only. Selectors move among measured levels; they do not interpolate or declare capacity.</p>
        </div>
        <div className="session-chart-grid" aria-label="Session capacity sweep charts">
          <SweepPlot title="Aggregate successful output" description="Valid completion tokens per cohort second" metric={(row) => row.output_tps} maximum={400} ticks={[0, 100, 200, 300, 400]} formatTick={(value) => `${value}`} />
          <SweepPlot title="Median visible-text wait" description="Log scale; missing visible-text events excluded" metric={(row) => row.visible_ttft_p50_s} maximum={128} ticks={[0.5, 1, 2, 8, 32, 128]} formatTick={(value) => `${value} s`} log />
          <SweepPlot title="Invalid or failed requests" description="Client-observed rate; no hardware root cause inferred" metric={(row) => row.error_rate * 100} maximum={30} ticks={[0, 10, 20, 30]} formatTick={(value) => `${value}%`} />
        </div>
      </section>

      <section className="session-section study-progression" aria-labelledby="previous-title">
        <header className="session-section-heading">
          <h2 id="previous-title">Previous study → current study</h2>
          <p>This is a methodology progression, not a cross-study speedup. Model, precision, hardware, runtime and traffic all changed.</p>
        </header>
        <div className="session-table-wrap" tabIndex={0} aria-label="Previous study comparison table">
          <table><thead><tr><th>Dimension</th><th>Episode 0 warm-up</th><th>Session field note</th></tr></thead>
            <tbody>{study.previous_study.map((row) => <tr key={row.dimension}><th scope="row">{row.dimension}</th><td>{row.previous}</td><td>{row.current}</td></tr>)}</tbody>
          </table>
        </div>
      </section>

      <section className="session-section" aria-labelledby="comparison-boundary-title">
        <header className="session-section-heading">
          <h2 id="comparison-boundary-title">Comparison boundary</h2>
          <p>The public field note names the engine and measured hardware only. Internal serving details are intentionally withheld and cannot support a pure hardware-only claim.</p>
        </header>
        <div className="boundary-columns" aria-label="Deployment comparison boundary"><section><h3>Public basis</h3><ul><li>Same model family and precision.</li><li>Same recorded session workload and measured user levels.</li><li>One RTX PRO 6000 deployment and one H200 deployment, both served by vLLM.</li></ul></section><section><h3>Withheld</h3><ul><li>Serving profiles, launch flags and internal optimization recipes.</li><li>Software build and package details.</li><li>Any claim that those undisclosed differences were controlled.</li></ul></section></div>
      </section>

      <section className="session-section evidence-boundary" aria-labelledby="boundary-title">
        <header className="session-section-heading">
          <h2 id="boundary-title">What the evidence permits</h2>
          <p>The dashboard keeps the conclusion narrower than the chart.</p>
        </header>
        <div className="boundary-columns">
          <section><h3>Observed</h3><ul>
            <li>At the matched soak, H200 delivered 379.94 tok/s versus 245.72 on RTX.</li>
            <li>H200 p95 visible response start was 2.83 s versus 8.22 s.</li>
            <li>At 64 H200 users, output was only 3.2% above the 16-user sweep point while median visible wait was about 19× as long.</li>
          </ul></section>
          <section><h3>Not established</h3><ul>
            <li>No “16 production users,” exact knee or universal GPU multiplier.</li>
            <li>Valid prompts peaked at 6,569 tokens in the soaks and 6,691 across the sweeps; results do not establish behavior beyond the observed prompt distribution.</li>
            <li>Serving profiles and cache controls are withheld, so the study does not attribute outcomes to a specific optimization.</li>
            <li>Tools were not executed and coding-task correctness was not scored.</li>
          </ul></section>
        </div>
      </section>

      <footer className="session-method">
        <p><strong>{study.workload.sessions} synthetic sessions · {study.workload.turns} turns · {study.workload.slots_per_user} slots/user</strong></p>
        <p>{study.workload.description}</p>
        <p>Recorded results with unverified provenance fields. Latest handoff did not include matched cost or cleanup evidence. The existing Episode 0 dashboard remains a separate historical dataset.</p>
      </footer>
    </article>
  );
}
