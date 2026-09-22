import type { PublishedCell } from "./studyPresentation";

type ChartCell = PublishedCell & {
  concurrency?: number;
  input_tokens_min?: number;
  input_tokens_max?: number;
};

type Workload = {
  profile: string;
  inputTokens: number;
  concurrency: number;
  tier: "Baseline" | "Stress";
  cells: ChartCell[];
};

const runtimeOrder = ["SGLang", "vLLM"];
const runtimeColors: Record<string, string> = {
  SGLang: "#ff7043",
  vLLM: "#45d6ae",
};

const compact = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const precise = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 });

function finite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function parseProfile(cell: ChartCell) {
  const match = /^(\d+)tok-c(\d+)$/.exec(cell.profile);
  return {
    inputTokens: cell.input_tokens_min ?? (match ? Number(match[1]) : 0),
    concurrency: cell.concurrency ?? (match ? Number(match[2]) : 0),
  };
}

function workloads(cells: PublishedCell[]): Workload[] {
  const groups = new Map<string, ChartCell[]>();
  for (const cell of cells as ChartCell[]) {
    groups.set(cell.profile, [...(groups.get(cell.profile) ?? []), cell]);
  }
  const grouped = [...groups.entries()].map(([profile, groupedCells]) => {
    const parsed = parseProfile(groupedCells[0]);
    return { profile, ...parsed, cells: groupedCells };
  }).sort((left, right) => (
    left.inputTokens - right.inputTokens || left.concurrency - right.concurrency
  ));

  const minimumConcurrency = new Map<number, number>();
  for (const item of grouped) {
    minimumConcurrency.set(
      item.inputTokens,
      Math.min(minimumConcurrency.get(item.inputTokens) ?? Infinity, item.concurrency),
    );
  }
  return grouped.map((item) => ({
    ...item,
    tier: item.concurrency === minimumConcurrency.get(item.inputTokens) ? "Baseline" : "Stress",
  }));
}

function orderedCells(workload: Workload) {
  return [...workload.cells].sort((left, right) => (
    runtimeOrder.indexOf(left.runtime) - runtimeOrder.indexOf(right.runtime)
  ));
}

function RuntimeLegend() {
  return (
    <div className="chart-legend" aria-label="Runtime legend">
      {runtimeOrder.map((runtime) => (
        <span key={runtime}><i style={{ background: runtimeColors[runtime] }} />{runtime}</span>
      ))}
      <span className="legend-note"><b>B</b> baseline</span>
      <span className="legend-note"><b>S</b> stress</span>
    </div>
  );
}

function axisTicks(maximum: number, steps = 5) {
  const rough = maximum / steps;
  const magnitude = 10 ** Math.floor(Math.log10(rough));
  const normalized = rough / magnitude;
  const nice = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
  const interval = nice * magnitude;
  const top = Math.ceil(maximum / interval) * interval;
  return Array.from({ length: Math.round(top / interval) + 1 }, (_, index) => index * interval);
}

function WorkloadTick({ item, x, y }: { item: Workload; x: number; y: number }) {
  return (
    <text className="chart-tick workload-tick" x={x} y={y} textAnchor="middle">
      <tspan x={x}>{compact.format(item.inputTokens)} tok · c{item.concurrency}</tspan>
      <tspan className="workload-tier" x={x} dy="15">{item.tier === "Baseline" ? "B" : "S"}</tspan>
    </text>
  );
}

export function ThroughputChart({ cells }: { cells: PublishedCell[] }) {
  const grouped = workloads(cells);
  const values = cells.map((cell) => cell.output_tokens_per_second).filter(finite);
  const ticks = axisTicks(Math.max(...values, 1));
  const max = ticks.at(-1) ?? 1;
  const width = 760;
  const height = 420;
  const plot = { left: 72, right: 22, top: 24, bottom: 78 };
  const plotWidth = width - plot.left - plot.right;
  const plotHeight = height - plot.top - plot.bottom;
  const groupWidth = plotWidth / grouped.length;
  const barWidth = Math.min(30, groupWidth * 0.28);
  const y = (metric: number) => plot.top + plotHeight - metric / max * plotHeight;

  return (
    <figure className="scientific-figure throughput-figure">
      <figcaption>
        <div><strong>Delivered output rate</strong><span>Aggregate output tokens ÷ measured wall time</span></div>
        <RuntimeLegend />
      </figcaption>
      <div className="chart-scroll">
        <svg className="scientific-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-labelledby="throughput-title throughput-desc">
          <title id="throughput-title">Delivered output rate by categorical workload and runtime</title>
          <desc id="throughput-desc">Grouped bars compare SGLang and vLLM for six workload profiles. The vertical axis is output tokens per second. Input length and concurrency are shown together for every category.</desc>
          {ticks.map((tick) => {
            const tickY = y(tick);
            return <g key={tick}>
              <line className="chart-grid" x1={plot.left} x2={width - plot.right} y1={tickY} y2={tickY} />
              <text className="chart-tick" x={plot.left - 12} y={tickY + 4} textAnchor="end">{compact.format(tick)}</text>
            </g>;
          })}
          <line className="chart-axis" x1={plot.left} x2={plot.left} y1={plot.top} y2={height - plot.bottom} />
          <line className="chart-axis" x1={plot.left} x2={width - plot.right} y1={height - plot.bottom} y2={height - plot.bottom} />
          <text className="chart-axis-label" transform={`translate(18 ${plot.top + plotHeight / 2}) rotate(-90)`} textAnchor="middle">Output tokens / second</text>
          {grouped.map((item, groupIndex) => {
            const center = plot.left + groupWidth * (groupIndex + 0.5);
            return <g key={item.profile}>
              {orderedCells(item).map((cell, runtimeIndex) => {
                if (!finite(cell.output_tokens_per_second)) return null;
                const metric = cell.output_tokens_per_second;
                const barX = center + (runtimeIndex - 1) * barWidth;
                return <g key={cell.runtime}>
                  <rect
                    className="chart-bar"
                    x={barX}
                    y={y(metric)}
                    width={barWidth - 4}
                    height={height - plot.bottom - y(metric)}
                    fill={runtimeColors[cell.runtime] ?? "#c5ccca"}
                  />
                  <title>{cell.runtime}, {compact.format(item.inputTokens)} input tokens, concurrency {item.concurrency}: {precise.format(metric)} output tokens per second</title>
                </g>;
              })}
              <WorkloadTick item={item} x={center} y={height - plot.bottom + 22} />
            </g>;
          })}
        </svg>
      </div>
      <p className="chart-footnote">Workloads are discrete input-length/concurrency pairs. Baseline and stress also used different maximum output-token settings.</p>
    </figure>
  );
}

export function TtftChart({ cells }: { cells: PublishedCell[] }) {
  const grouped = workloads(cells);
  const width = 760;
  const height = 420;
  const plot = { left: 72, right: 22, top: 24, bottom: 78 };
  const plotWidth = width - plot.left - plot.right;
  const plotHeight = height - plot.top - plot.bottom;
  const groupWidth = plotWidth / grouped.length;
  const ticks = [10, 100, 1_000, 10_000, 100_000];
  const minimum = ticks[0];
  const maximum = ticks.at(-1) ?? 100_000;
  const y = (metric: number) => {
    const normalized = (Math.log10(metric) - Math.log10(minimum)) / (Math.log10(maximum) - Math.log10(minimum));
    return plot.top + plotHeight - normalized * plotHeight;
  };

  return (
    <figure className="scientific-figure ttft-figure">
      <figcaption>
        <div><strong>Median time to first token</strong><span>Log scale preserves the full 37 ms–88 s range</span></div>
        <RuntimeLegend />
      </figcaption>
      <div className="chart-scroll">
        <svg className="scientific-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-labelledby="ttft-title ttft-desc">
          <title id="ttft-title">Median time to first token by categorical workload and runtime</title>
          <desc id="ttft-desc">Points compare median client-measured time to first token for SGLang and vLLM across six workload profiles. The vertical axis is logarithmic in milliseconds.</desc>
          {ticks.map((tick) => {
            const tickY = y(tick);
            const label = tick >= 1_000 ? `${tick / 1_000} s` : `${tick} ms`;
            return <g key={tick}>
              <line className="chart-grid" x1={plot.left} x2={width - plot.right} y1={tickY} y2={tickY} />
              <text className="chart-tick" x={plot.left - 12} y={tickY + 4} textAnchor="end">{label}</text>
            </g>;
          })}
          <line className="chart-axis" x1={plot.left} x2={plot.left} y1={plot.top} y2={height - plot.bottom} />
          <line className="chart-axis" x1={plot.left} x2={width - plot.right} y1={height - plot.bottom} y2={height - plot.bottom} />
          <text className="chart-axis-label" transform={`translate(18 ${plot.top + plotHeight / 2}) rotate(-90)`} textAnchor="middle">Median TTFT (log scale)</text>
          {grouped.map((item, groupIndex) => {
            const center = plot.left + groupWidth * (groupIndex + 0.5);
            return <g key={item.profile}>
              {orderedCells(item).map((cell, runtimeIndex) => {
                const metric = cell.client_ttft_ms.available ? cell.client_ttft_ms.p50 : null;
                if (!finite(metric) || metric <= 0) return null;
                const pointX = center + (runtimeIndex === 0 ? -11 : 11);
                return <g key={cell.runtime}>
                  <line className="point-stem" x1={pointX} x2={pointX} y1={y(metric)} y2={height - plot.bottom} />
                  <circle cx={pointX} cy={y(metric)} r="6" fill={runtimeColors[cell.runtime] ?? "#c5ccca"} />
                  <title>{cell.runtime}, {compact.format(item.inputTokens)} input tokens, concurrency {item.concurrency}: {precise.format(metric)} ms median TTFT</title>
                </g>;
              })}
              <WorkloadTick item={item} x={center} y={height - plot.bottom + 22} />
            </g>;
          })}
        </svg>
      </div>
      <p className="chart-footnote">The log axis is explicitly labeled. Points are categorical comparisons; no trend line or isolated concurrency effect is claimed.</p>
    </figure>
  );
}

export function RateLatencyScatter({ cells }: { cells: PublishedCell[] }) {
  const grouped = workloads(cells);
  const points = grouped.flatMap((item) => orderedCells(item).flatMap((cell) => {
    const rate = cell.output_tokens_per_second;
    const ttft = cell.client_ttft_ms.available ? cell.client_ttft_ms.p50 : null;
    return finite(rate) && finite(ttft) && ttft > 0 ? [{ item, cell, rate, ttft }] : [];
  }));
  const width = 980;
  const height = 470;
  const plot = { left: 78, right: 30, top: 24, bottom: 66 };
  const plotWidth = width - plot.left - plot.right;
  const plotHeight = height - plot.top - plot.bottom;
  const xTicks = axisTicks(Math.max(...points.map((point) => point.rate), 1));
  const xMaximum = xTicks.at(-1) ?? 1;
  const yTicks = [10, 100, 1_000, 10_000, 100_000];
  const x = (metric: number) => plot.left + metric / xMaximum * plotWidth;
  const y = (metric: number) => plot.top + plotHeight - (Math.log10(metric) - 1) / 4 * plotHeight;

  return (
    <figure className="scientific-figure scatter-figure">
      <figcaption>
        <div><strong>Rate versus median TTFT</strong><span>Upper-right is higher rate with slower first token</span></div>
        <RuntimeLegend />
      </figcaption>
      <div className="chart-scroll">
        <svg className="scientific-chart scatter-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-labelledby="scatter-title scatter-desc">
          <title id="scatter-title">Delivered output rate versus median time to first token</title>
          <desc id="scatter-desc">Scatter plot of aggregate output tokens per second against median client time to first token. Each point is labeled with input token count and concurrency.</desc>
          {xTicks.map((tick) => <g key={tick}>
            <line className="chart-grid" x1={x(tick)} x2={x(tick)} y1={plot.top} y2={height - plot.bottom} />
            <text className="chart-tick" x={x(tick)} y={height - plot.bottom + 22} textAnchor="middle">{compact.format(tick)}</text>
          </g>)}
          {yTicks.map((tick) => <g key={tick}>
            <line className="chart-grid" x1={plot.left} x2={width - plot.right} y1={y(tick)} y2={y(tick)} />
            <text className="chart-tick" x={plot.left - 12} y={y(tick) + 4} textAnchor="end">{tick >= 1_000 ? `${tick / 1_000} s` : `${tick} ms`}</text>
          </g>)}
          <line className="chart-axis" x1={plot.left} x2={plot.left} y1={plot.top} y2={height - plot.bottom} />
          <line className="chart-axis" x1={plot.left} x2={width - plot.right} y1={height - plot.bottom} y2={height - plot.bottom} />
          <text className="chart-axis-label" x={plot.left + plotWidth / 2} y={height - 12} textAnchor="middle">Output tokens / second</text>
          <text className="chart-axis-label" transform={`translate(18 ${plot.top + plotHeight / 2}) rotate(-90)`} textAnchor="middle">Median TTFT (log scale)</text>
          {points.map(({ item, cell, rate, ttft }) => {
            const pointX = x(rate);
            const pointY = y(ttft);
            const anchor = pointX > width - 160 ? "end" : "start";
            const isSglang = cell.runtime === "SGLang";
            const labelX = pointX + (anchor === "end" ? -14 : 14);
            const labelY = pointY + (isSglang ? -13 : 19);
            const runtimeLabel = isSglang ? "SGLang" : cell.runtime;
            return <g className="scatter-point" key={`${cell.runtime}-${cell.profile}`}>
              <line
                className="scatter-leader"
                x1={pointX + (anchor === "end" ? -5 : 5)}
                y1={pointY + (isSglang ? -5 : 5)}
                x2={labelX + (anchor === "end" ? 4 : -4)}
                y2={labelY + (isSglang ? 3 : -4)}
              />
              <circle cx={pointX} cy={pointY} r="7" fill={runtimeColors[cell.runtime] ?? "#c5ccca"} />
              <text className="scatter-label" x={labelX} y={labelY} textAnchor={anchor}>{compact.format(item.inputTokens)} / c{item.concurrency} · {runtimeLabel}</text>
              <title>{cell.runtime}, {item.tier.toLowerCase()}, {compact.format(item.inputTokens)} input tokens at concurrency {item.concurrency}: {precise.format(rate)} output tokens per second, {precise.format(ttft)} ms median TTFT</title>
            </g>;
          })}
        </svg>
      </div>
      <p className="chart-footnote">Labels read “input tokens / concurrency.” Every point is a distinct workload; movement across points combines changes in both variables.</p>
    </figure>
  );
}

export function DeliveredWorkChart({ cells }: { cells: PublishedCell[] }) {
  const grouped = workloads(cells);
  const width = 980;
  const height = 430;
  const plot = { left: 78, right: 28, top: 28, bottom: 78 };
  const plotWidth = width - plot.left - plot.right;
  const plotHeight = height - plot.top - plot.bottom;
  const groupWidth = plotWidth / grouped.length;
  const barWidth = Math.min(34, groupWidth * 0.25);
  const ticks = [0, 32, 64, 96, 128];
  const y = (metric: number) => plot.top + plotHeight - metric / 140 * plotHeight;

  return (
    <figure className="scientific-figure work-figure">
      <figcaption>
        <div><strong>Mean delivered output versus request cap</strong><span>Delivered output tokens ÷ successful requests; cap shown per workload</span></div>
        <RuntimeLegend />
      </figcaption>
      <div className="chart-scroll">
        <svg className="scientific-chart scatter-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-labelledby="work-title work-desc">
          <title id="work-title">Mean delivered output tokens per successful request compared with the configured maximum</title>
          <desc id="work-desc">Grouped bars compare SGLang and vLLM mean delivered output tokens for six workloads. Horizontal cap markers show 64 tokens for baseline workloads and 128 tokens for stress workloads. The two long-context vLLM cells delivered less output work than their paired SGLang cells.</desc>
          {ticks.map((tick) => <g key={tick}>
            <line className="chart-grid" x1={plot.left} x2={width - plot.right} y1={y(tick)} y2={y(tick)} />
            <text className="chart-tick" x={plot.left - 12} y={y(tick) + 4} textAnchor="end">{tick}</text>
          </g>)}
          <line className="chart-axis" x1={plot.left} x2={plot.left} y1={plot.top} y2={height - plot.bottom} />
          <line className="chart-axis" x1={plot.left} x2={width - plot.right} y1={height - plot.bottom} y2={height - plot.bottom} />
          <text className="chart-axis-label" transform={`translate(18 ${plot.top + plotHeight / 2}) rotate(-90)`} textAnchor="middle">Mean delivered output tokens / request</text>
          {grouped.map((item, groupIndex) => {
            const center = plot.left + groupWidth * (groupIndex + 0.5);
            const cap = item.tier === "Baseline" ? 64 : 128;
            return <g key={item.profile}>
              <line className="output-cap" x1={center - groupWidth * 0.33} x2={center + groupWidth * 0.33} y1={y(cap)} y2={y(cap)} />
              {orderedCells(item).map((cell, runtimeIndex) => {
                const metric = cell.successful_requests > 0
                  ? cell.successful_output_tokens / cell.successful_requests
                  : null;
                if (!finite(metric)) return null;
                const barX = center + (runtimeIndex - 1) * barWidth;
                return <g key={cell.runtime}>
                  <rect className="chart-bar" x={barX} y={y(metric)} width={barWidth - 4} height={height - plot.bottom - y(metric)} fill={runtimeColors[cell.runtime] ?? "#c5ccca"} />
                  <text className="work-value" x={barX + (barWidth - 4) / 2} y={y(metric) - 8} textAnchor="middle">{precise.format(metric)}</text>
                  <title>{cell.runtime}, {item.profile}: {precise.format(metric)} mean delivered output tokens per successful request; configured maximum {cap}</title>
                </g>;
              })}
              <WorkloadTick item={item} x={center} y={height - plot.bottom + 22} />
            </g>;
          })}
        </svg>
      </div>
      <p className="chart-footnote"><b>Source:</b> normalized successful output-token totals and request counts. Gray markers are configured caps (64 baseline, 128 stress), not measured values; stop reasons and output-length distributions were not retained.</p>
    </figure>
  );
}

export function ScientificCharts({ cells }: { cells: PublishedCell[] }) {
  return <div className="scientific-chart-grid">
    <ThroughputChart cells={cells} />
    <TtftChart cells={cells} />
    <DeliveredWorkChart cells={cells} />
    <RateLatencyScatter cells={cells} />
  </div>;
}
