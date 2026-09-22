type RuntimeName = "SGLang" | "vLLM";

type TelemetryCell = {
  runtime: RuntimeName;
  profile: string;
  inputTokens: number;
  concurrency: number;
  tier: "Baseline" | "Stress";
  repetitions: number;
  kvPeak: number;
  waitingPeak: number;
  prefillSeconds?: number;
  decodeSeconds?: number;
};

type GpuPeak = {
  runtime: RuntimeName;
  run: "Baseline" | "Stress";
  samples: number;
  utilizationPercent: number;
  memoryMib: number;
  powerWatts: number;
  temperatureCelsius: number;
};

const runtimeOrder: RuntimeName[] = ["SGLang", "vLLM"];
const runtimeColors: Record<RuntimeName, string> = {
  SGLang: "#ff7043",
  vLLM: "#45d6ae",
};
const phaseColors = { Prefill: "#f3bb45", Decode: "#8ba9ff" };

// Exact sanitized aggregates from public/telemetry-summary.csv.
const telemetry: TelemetryCell[] = [
  { runtime: "vLLM", profile: "128tok-c1", inputTokens: 128, concurrency: 1, tier: "Baseline", repetitions: 3, kvPeak: 0.007444168734491274, waitingPeak: 0, prefillSeconds: 0.03801939942824997, decodeSeconds: 1.5392463786625548 },
  { runtime: "vLLM", profile: "128tok-c16", inputTokens: 128, concurrency: 16, tier: "Stress", repetitions: 2, kvPeak: 0.13058312655086846, waitingPeak: 0, prefillSeconds: 0.08930222005437827, decodeSeconds: 3.221376715489896 },
  { runtime: "vLLM", profile: "2048tok-c4", inputTokens: 2_048, concurrency: 4, tier: "Baseline", repetitions: 3, kvPeak: 0.3238213399503722, waitingPeak: 0, prefillSeconds: 0.49705169501248747, decodeSeconds: 1.734369233920006 },
  { runtime: "vLLM", profile: "2048tok-c24", inputTokens: 2_048, concurrency: 24, tier: "Stress", repetitions: 2, kvPeak: 0.9987593052109182, waitingPeak: 14.5, prefillSeconds: 1.1217399096025877, decodeSeconds: 4.552280826691357 },
  { runtime: "vLLM", profile: "8192tok-c8", inputTokens: 8_192, concurrency: 8, tier: "Baseline", repetitions: 3, kvPeak: 0.956575682382134, waitingPeak: 5, prefillSeconds: 1.2194402618074998, decodeSeconds: 2.524467064688603 },
  { runtime: "vLLM", profile: "8192tok-c32", inputTokens: 8_192, concurrency: 32, tier: "Stress", repetitions: 2, kvPeak: 0.9646401985111663, waitingPeak: 29, prefillSeconds: 0.9625173531461596, decodeSeconds: 4.127860516474198 },
  { runtime: "SGLang", profile: "128tok-c1", inputTokens: 128, concurrency: 1, tier: "Baseline", repetitions: 3, kvPeak: 0.01, waitingPeak: 0 },
  { runtime: "SGLang", profile: "128tok-c16", inputTokens: 128, concurrency: 16, tier: "Stress", repetitions: 2, kvPeak: 0.2, waitingPeak: 0 },
  { runtime: "SGLang", profile: "2048tok-c4", inputTokens: 2_048, concurrency: 4, tier: "Baseline", repetitions: 3, kvPeak: 0.49, waitingPeak: 0 },
  { runtime: "SGLang", profile: "2048tok-c24", inputTokens: 2_048, concurrency: 24, tier: "Stress", repetitions: 2, kvPeak: 0.99, waitingPeak: 17 },
  { runtime: "SGLang", profile: "8192tok-c8", inputTokens: 8_192, concurrency: 8, tier: "Baseline", repetitions: 3, kvPeak: 0.98, waitingPeak: 6 },
  { runtime: "SGLang", profile: "8192tok-c32", inputTokens: 8_192, concurrency: 32, tier: "Stress", repetitions: 2, kvPeak: 0.99, waitingPeak: 30 },
];

// Exact sanitized peak summaries from public/gpu-summary.json.
const gpuPeaks: GpuPeak[] = [
  { runtime: "vLLM", run: "Baseline", samples: 313, utilizationPercent: 100, memoryMib: 74_139, powerWatts: 704.67, temperatureCelsius: 63 },
  { runtime: "SGLang", run: "Baseline", samples: 358, utilizationPercent: 100, memoryMib: 70_632, powerWatts: 696.46, temperatureCelsius: 59 },
  { runtime: "vLLM", run: "Stress", samples: 372, utilizationPercent: 100, memoryMib: 74_139, powerWatts: 703.22, temperatureCelsius: 70 },
  { runtime: "SGLang", run: "Stress", samples: 544, utilizationPercent: 100, memoryMib: 71_178, powerWatts: 706.04, temperatureCelsius: 67 },
];

const integer = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const decimal = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 });

function workloads() {
  const unique = new Map<string, TelemetryCell>();
  for (const cell of telemetry) unique.set(cell.profile, cell);
  return [...unique.values()].sort((left, right) => (
    left.inputTokens - right.inputTokens || left.concurrency - right.concurrency
  ));
}

function cellsFor(profile: string) {
  return telemetry
    .filter((cell) => cell.profile === profile)
    .sort((left, right) => runtimeOrder.indexOf(left.runtime) - runtimeOrder.indexOf(right.runtime));
}

function RuntimeLegend() {
  return <div className="chart-legend" aria-label="Runtime legend">
    {runtimeOrder.map((runtime) => <span key={runtime}><i style={{ background: runtimeColors[runtime] }} />{runtime}</span>)}
    <span className="legend-note"><b>B</b> baseline</span>
    <span className="legend-note"><b>S</b> stress</span>
  </div>;
}

function WorkloadTick({ item, x, y }: { item: TelemetryCell; x: number; y: number }) {
  return <text className="chart-tick workload-tick" x={x} y={y} textAnchor="middle">
    <tspan x={x}>{integer.format(item.inputTokens)} tok · c{item.concurrency}</tspan>
    <tspan className="workload-tier" x={x} dy="15">{item.tier === "Baseline" ? "B" : "S"}</tspan>
  </text>;
}

function RuntimePhaseDurations() {
  const grouped = workloads();
  const vllm = telemetry.filter((cell) => cell.runtime === "vLLM");
  const width = 980;
  const height = 430;
  const plot = { left: 86, right: 28, top: 28, bottom: 78 };
  const plotWidth = width - plot.left - plot.right;
  const plotHeight = height - plot.top - plot.bottom;
  const groupWidth = plotWidth / grouped.length;
  const ticks = [0.01, 0.1, 1, 10];
  const y = (metric: number) => plot.top + plotHeight - (Math.log10(metric) + 2) / 3 * plotHeight;

  return <figure className="scientific-figure telemetry-figure phase-figure">
    <figcaption>
      <div><strong>Native request phase durations</strong><span>vLLM histogram summaries; SGLang did not expose matching durations</span></div>
      <div className="chart-legend phase-legend" aria-label="Phase legend">
        {Object.entries(phaseColors).map(([phase, color]) => <span key={phase}><i style={{ background: color }} />{phase}</span>)}
      </div>
    </figcaption>
    <div className="availability-note"><b>Coverage</b> vLLM 6/6 cells · SGLang unavailable</div>
    <div className="chart-scroll">
      <svg className="scientific-chart telemetry-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-labelledby="phase-title phase-desc">
        <title id="phase-title">vLLM native prefill and decode duration summaries by workload</title>
        <desc id="phase-desc">Categorical dot plot of the median of per-repetition mean vLLM prefill and decode seconds per request for six workloads. SGLang did not expose matching duration metrics.</desc>
        {ticks.map((tick) => <g key={tick}>
          <line className="chart-grid" x1={plot.left} x2={width - plot.right} y1={y(tick)} y2={y(tick)} />
          <text className="chart-tick" x={plot.left - 12} y={y(tick) + 4} textAnchor="end">{tick < 1 ? `${tick * 1_000} ms` : `${tick} s`}</text>
        </g>)}
        <line className="chart-axis" x1={plot.left} x2={plot.left} y1={plot.top} y2={height - plot.bottom} />
        <line className="chart-axis" x1={plot.left} x2={width - plot.right} y1={height - plot.bottom} y2={height - plot.bottom} />
        <text className="chart-axis-label" transform={`translate(18 ${plot.top + plotHeight / 2}) rotate(-90)`} textAnchor="middle">Seconds / request (log scale)</text>
        {grouped.map((item, index) => {
          const cell = vllm.find((candidate) => candidate.profile === item.profile);
          const center = plot.left + groupWidth * (index + 0.5);
          if (!cell || cell.prefillSeconds === undefined || cell.decodeSeconds === undefined) return null;
          return <g key={item.profile}>
            <line className="phase-connector" x1={center - 10} x2={center + 10} y1={y(cell.prefillSeconds)} y2={y(cell.decodeSeconds)} />
            <circle cx={center - 10} cy={y(cell.prefillSeconds)} r="7" fill={phaseColors.Prefill}><title>{item.profile}: {cell.prefillSeconds.toFixed(3)} s/request prefill, median of {cell.repetitions} per-repetition means</title></circle>
            <circle cx={center + 10} cy={y(cell.decodeSeconds)} r="7" fill={phaseColors.Decode}><title>{item.profile}: {cell.decodeSeconds.toFixed(3)} s/request decode, median of {cell.repetitions} per-repetition means</title></circle>
            <WorkloadTick item={item} x={center} y={height - plot.bottom + 22} />
          </g>;
        })}
      </svg>
    </div>
    <p className="chart-footnote"><b>Source:</b> sanitized <code>telemetry-summary.csv</code>. Each point is the median of per-repetition mean duration; these runtime-native durations are not inferred from client TTFT or TPOT.</p>
  </figure>;
}

function KvPeakChart() {
  const grouped = workloads();
  const width = 760;
  const height = 420;
  const plot = { left: 76, right: 22, top: 24, bottom: 78 };
  const plotWidth = width - plot.left - plot.right;
  const plotHeight = height - plot.top - plot.bottom;
  const groupWidth = plotWidth / grouped.length;
  const ticks = [0, 25, 50, 75, 100];
  const y = (metric: number) => plot.top + plotHeight - metric / 100 * plotHeight;

  return <figure className="scientific-figure telemetry-figure kv-figure">
    <figcaption><div><strong>Native KV-cache usage peaks</strong><span>Median peak within each workload’s repetitions</span></div><RuntimeLegend /></figcaption>
    <div className="chart-scroll">
      <svg className="scientific-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-labelledby="kv-title kv-desc">
        <title id="kv-title">Median peak native KV-cache usage by workload and runtime</title>
        <desc id="kv-desc">Categorical points compare the median of repetition-level peak KV-cache usage for SGLang and vLLM across six workloads.</desc>
        {ticks.map((tick) => <g key={tick}>
          <line className="chart-grid" x1={plot.left} x2={width - plot.right} y1={y(tick)} y2={y(tick)} />
          <text className="chart-tick" x={plot.left - 12} y={y(tick) + 4} textAnchor="end">{tick}%</text>
        </g>)}
        <line className="chart-axis" x1={plot.left} x2={plot.left} y1={plot.top} y2={height - plot.bottom} />
        <line className="chart-axis" x1={plot.left} x2={width - plot.right} y1={height - plot.bottom} y2={height - plot.bottom} />
        <text className="chart-axis-label" transform={`translate(18 ${plot.top + plotHeight / 2}) rotate(-90)`} textAnchor="middle">Median of repetition peaks (%)</text>
        {grouped.map((item, index) => {
          const center = plot.left + groupWidth * (index + 0.5);
          return <g key={item.profile}>
            {cellsFor(item.profile).map((cell, runtimeIndex) => {
              const pointX = center + (runtimeIndex === 0 ? -11 : 11);
              const percent = cell.kvPeak * 100;
              return <g key={cell.runtime}>
                <line className="point-stem" x1={pointX} x2={pointX} y1={y(percent)} y2={height - plot.bottom} />
                <circle cx={pointX} cy={y(percent)} r="6" fill={runtimeColors[cell.runtime]}><title>{cell.runtime}, {item.profile}: {decimal.format(percent)}% median peak KV-cache usage; {cell.repetitions} repetitions</title></circle>
              </g>;
            })}
            <WorkloadTick item={item} x={center} y={height - plot.bottom + 22} />
          </g>;
        })}
      </svg>
    </div>
    <p className="chart-footnote"><b>Source:</b> sanitized <code>telemetry-summary.csv</code>. Each point is a median of repetition-level peaks, not a trace; runtime denominators are not proven equivalent.</p>
  </figure>;
}

function WaitingPeakChart() {
  const grouped = workloads();
  const width = 760;
  const height = 420;
  const plot = { left: 76, right: 22, top: 24, bottom: 78 };
  const plotWidth = width - plot.left - plot.right;
  const plotHeight = height - plot.top - plot.bottom;
  const groupWidth = plotWidth / grouped.length;
  const ticks = [0, 10, 20, 30];
  const y = (metric: number) => plot.top + plotHeight - metric / 32 * plotHeight;

  return <figure className="scientific-figure telemetry-figure queue-figure">
    <figcaption><div><strong>Waiting-request peaks</strong><span>Median peak queue depth within each workload’s repetitions</span></div><RuntimeLegend /></figcaption>
    <div className="chart-scroll">
      <svg className="scientific-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-labelledby="queue-title queue-desc">
        <title id="queue-title">Median peak waiting requests by workload and runtime</title>
        <desc id="queue-desc">Categorical points compare the median of repetition-level peak waiting-request counts for SGLang and vLLM across six workloads.</desc>
        {ticks.map((tick) => <g key={tick}>
          <line className="chart-grid" x1={plot.left} x2={width - plot.right} y1={y(tick)} y2={y(tick)} />
          <text className="chart-tick" x={plot.left - 12} y={y(tick) + 4} textAnchor="end">{tick}</text>
        </g>)}
        <line className="chart-axis" x1={plot.left} x2={plot.left} y1={plot.top} y2={height - plot.bottom} />
        <line className="chart-axis" x1={plot.left} x2={width - plot.right} y1={height - plot.bottom} y2={height - plot.bottom} />
        <text className="chart-axis-label" transform={`translate(18 ${plot.top + plotHeight / 2}) rotate(-90)`} textAnchor="middle">Median peak waiting requests</text>
        {grouped.map((item, index) => {
          const center = plot.left + groupWidth * (index + 0.5);
          return <g key={item.profile}>
            {cellsFor(item.profile).map((cell, runtimeIndex) => {
              const pointX = center + (runtimeIndex === 0 ? -11 : 11);
              return <g key={cell.runtime}>
                <line className="point-stem" x1={pointX} x2={pointX} y1={y(cell.waitingPeak)} y2={height - plot.bottom} />
                <circle cx={pointX} cy={y(cell.waitingPeak)} r="6" fill={runtimeColors[cell.runtime]}><title>{cell.runtime}, {item.profile}: {decimal.format(cell.waitingPeak)} median peak waiting requests; {cell.repetitions} repetitions</title></circle>
              </g>;
            })}
            <WorkloadTick item={item} x={center} y={height - plot.bottom + 22} />
          </g>;
        })}
      </svg>
    </div>
    <p className="chart-footnote"><b>Source:</b> sanitized <code>telemetry-summary.csv</code>. Peaks need not coincide with KV or latency peaks; no causal claim is made.</p>
  </figure>;
}

function GpuPeakChart() {
  const width = 980;
  const height = 390;
  const plot = { left: 86, right: 28, top: 40, bottom: 70 };
  const plotWidth = width - plot.left - plot.right;
  const plotHeight = height - plot.top - plot.bottom;
  const runs: GpuPeak["run"][] = ["Baseline", "Stress"];
  const groupWidth = plotWidth / runs.length;
  const ticks = [0, 25, 50, 75, 100];
  const y = (metric: number) => plot.top + plotHeight - metric / 100 * plotHeight;

  return <figure className="scientific-figure telemetry-figure gpu-figure">
    <figcaption><div><strong>Peak GPU utilization</strong><span>Maximum of one-second device samples; all four run summaries reached 100%</span></div><RuntimeLegend /></figcaption>
    <div className="chart-scroll">
      <svg className="scientific-chart telemetry-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-labelledby="gpu-title gpu-desc">
        <title id="gpu-title">Peak GPU utilization by runtime and run</title>
        <desc id="gpu-desc">All SGLang and vLLM baseline and stress run summaries reached a peak GPU utilization of 100 percent in one-second device samples. This chart does not show sustained utilization.</desc>
        {ticks.map((tick) => <g key={tick}>
          <line className="chart-grid" x1={plot.left} x2={width - plot.right} y1={y(tick)} y2={y(tick)} />
          <text className="chart-tick" x={plot.left - 12} y={y(tick) + 4} textAnchor="end">{tick}%</text>
        </g>)}
        <line className="chart-axis" x1={plot.left} x2={plot.left} y1={plot.top} y2={height - plot.bottom} />
        <line className="chart-axis" x1={plot.left} x2={width - plot.right} y1={height - plot.bottom} y2={height - plot.bottom} />
        <text className="chart-axis-label" transform={`translate(18 ${plot.top + plotHeight / 2}) rotate(-90)`} textAnchor="middle">Peak GPU utilization (%)</text>
        {runs.map((run, runIndex) => {
          const center = plot.left + groupWidth * (runIndex + 0.5);
          return <g key={run}>
            {gpuPeaks.filter((entry) => entry.run === run).sort((left, right) => runtimeOrder.indexOf(left.runtime) - runtimeOrder.indexOf(right.runtime)).map((entry, runtimeIndex) => {
              const pointX = center + (runtimeIndex === 0 ? -30 : 30);
              return <g key={entry.runtime}>
                <line className="gpu-stem" x1={pointX} x2={pointX} y1={y(entry.utilizationPercent)} y2={height - plot.bottom} stroke={runtimeColors[entry.runtime]} />
                <circle cx={pointX} cy={y(entry.utilizationPercent)} r="8" fill={runtimeColors[entry.runtime]} />
                <text className="gpu-value" x={pointX} y={y(entry.utilizationPercent) - 14} textAnchor="middle">100%</text>
                <title>{entry.runtime} {run.toLowerCase()}: 100% peak GPU utilization across {entry.samples} one-second samples; {integer.format(entry.memoryMib)} MiB peak memory, {decimal.format(entry.powerWatts)} W peak power, {integer.format(entry.temperatureCelsius)} °C peak temperature</title>
              </g>;
            })}
            <text className="chart-tick gpu-run-label" x={center} y={height - plot.bottom + 24} textAnchor="middle">{run}</text>
          </g>;
        })}
      </svg>
    </div>
    <div className="gpu-peak-table" aria-label="Supporting GPU peak summaries">
      {gpuPeaks.map((entry) => <div key={`${entry.runtime}-${entry.run}`}>
        <b style={{ color: runtimeColors[entry.runtime] }}>{entry.runtime} · {entry.run}</b>
        <span>{integer.format(entry.memoryMib)} MiB</span>
        <span>{decimal.format(entry.powerWatts)} W</span>
        <span>{integer.format(entry.temperatureCelsius)} °C</span>
        <small>{integer.format(entry.samples)} samples</small>
      </div>)}
    </div>
    <p className="chart-footnote"><b>Source:</b> sanitized <code>gpu-summary.json</code>. Values are maxima of one-second samples, not medians or traces; they do not measure saturation duration or identify a bottleneck.</p>
  </figure>;
}

export function TelemetryCharts() {
  return <div className="telemetry-chart-grid">
    <RuntimePhaseDurations />
    <KvPeakChart />
    <WaitingPeakChart />
    <GpuPeakChart />
  </div>;
}
