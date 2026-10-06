import episode1Data from "../data/episode-1-instrument.json";
import sessionData from "../data/session-capacity-study.json";

export type EvidenceState = "recorded" | "draft" | "import-pending" | "planned";
export type MetricDirection = "higher" | "lower" | "contextual";
export type MetricReading = { available: boolean; value: number | null; unit: string; reason: string | null };
export type EvidencePoint = { load: number; label: string; readings: Record<string, MetricReading>; sampleCount: number; validCount: number };
export type EvidenceArm = { id: string; label: string; marker: "circle" | "diamond" | "square"; lineStyle: "solid" | "dashed" | "dotted"; configuration: string[]; points: EvidencePoint[] };
export type EvidenceStudy = { id: string; kind: "episode" | "field-note"; number: number | null; title: string; question: string; state: EvidenceState; statusLabel: string; what: string; why: string; how: string; model: string; hardware: string; provenance: string; loads: number[]; arms: EvidenceArm[]; limitations: string[] };
export type MetricDefinition = { id: string; label: string; shortLabel: string; explanation: string; unit: string; direction: MetricDirection; tolerancePercent: number | null };
export type ComparisonResult = { available: boolean; absolute: number | null; relativePercent: number | null; reason: string | null };

export const METRICS: Record<string, MetricDefinition> = {
  output_tps: { id: "output_tps", label: "Output throughput", shortLabel: "Throughput", explanation: "Successful output tokens divided by the declared measurement duration.", unit: "tok/s", direction: "higher", tolerancePercent: 2 },
  ttft_p50: { id: "ttft_p50", label: "Visible TTFT p50", shortLabel: "TTFT p50", explanation: "Median time from client request start to the first visible content event.", unit: "ms", direction: "lower", tolerancePercent: 2 },
  ttft_p95: { id: "ttft_p95", label: "Visible TTFT p95", shortLabel: "TTFT p95", explanation: "95th-percentile time from client request start to the first visible content event.", unit: "ms", direction: "lower", tolerancePercent: 2 },
  tpot_p50: { id: "tpot_p50", label: "TPOT p50", shortLabel: "TPOT p50", explanation: "Median per-request first-to-last content span divided by exact output tokens minus one.", unit: "ms/token", direction: "lower", tolerancePercent: 2 },
  tpot_p95: { id: "tpot_p95", label: "TPOT p95", shortLabel: "TPOT p95", explanation: "95th-percentile time per output token where that percentile is available.", unit: "ms/token", direction: "lower", tolerancePercent: 2 },
  invalid_rate: { id: "invalid_rate", label: "Failed / invalid requests", shortLabel: "Invalid", explanation: "Requests that did not meet the recorded completion-validity contract.", unit: "%", direction: "lower", tolerancePercent: 0.1 },
  queue_depth: { id: "queue_depth", label: "Runtime queue depth", shortLabel: "Queued", explanation: "Mean requests waiting for admission according to the runtime-native gauge.", unit: "requests", direction: "contextual", tolerancePercent: null },
  queue_wait: { id: "queue_wait", label: "Runtime queue wait", shortLabel: "Queue wait", explanation: "Time spent in the server queue where a comparable native duration is directly available.", unit: "ms", direction: "lower", tolerancePercent: null },
  kv_occupancy: { id: "kv_occupancy", label: "KV-cache occupancy", shortLabel: "KV cache", explanation: "Runtime-reported KV-cache use; source units remain visible because runtime definitions differ.", unit: "source unit", direction: "contextual", tolerancePercent: null },
  gpu_utilization: { id: "gpu_utilization", label: "GPU utilization", shortLabel: "GPU util.", explanation: "Mean sampled device utilization during the aligned five-minute measurement window.", unit: "%", direction: "contextual", tolerancePercent: null },
  gpu_memory: { id: "gpu_memory", label: "GPU memory used", shortLabel: "GPU memory", explanation: "Mean reported device memory consumption during the aligned measurement window.", unit: "GiB", direction: "contextual", tolerancePercent: null },
  gpu_power: { id: "gpu_power", label: "GPU board power", shortLabel: "Power", explanation: "Mean sampled board power during the aligned measurement window.", unit: "W", direction: "contextual", tolerancePercent: null }
};

const reading = (value: number | null | undefined, unit: string, reason: string | null = null): MetricReading => ({ available: value !== null && value !== undefined, value: value ?? null, unit, reason: value === null || value === undefined ? reason ?? "Not recorded for this arm and load." : null });

export function previousMeasuredLoad(loads: number[], selected: number): number | null {
  const ordered = [...loads].sort((a, b) => a - b);
  const index = ordered.indexOf(selected);
  return index > 0 ? ordered[index - 1] : null;
}

export function compareReadings(current: MetricReading, baseline: MetricReading): ComparisonResult {
  if (!current.available || current.value === null) return { available: false, absolute: null, relativePercent: null, reason: current.reason ?? "Current reading unavailable." };
  if (!baseline.available || baseline.value === null) return { available: false, absolute: null, relativePercent: null, reason: baseline.reason ?? "Baseline reading unavailable." };
  const absolute = current.value - baseline.value;
  return { available: true, absolute, relativePercent: baseline.value === 0 ? null : absolute / baseline.value * 100, reason: baseline.value === 0 ? "Relative change unavailable for a zero baseline." : null };
}

export function adaptEpisode1Study(): EvidenceStudy {
  return {
    id: episode1Data.study_id,
    kind: "episode",
    number: 1,
    title: episode1Data.title,
    question: "Which runtime configuration serves this H200 workload better?",
    state: "recorded",
    statusLabel: "Recorded · exploratory · capacity not established",
    what: "Compare corrected SGLang and vLLM deployments on one H200 at the same three recorded user levels.",
    why: "See where output, visible TTFT, TPOT and resource use move together—and where a throughput-only answer fails.",
    how: "Replay the same agent/chat workload for five measured minutes after warm-up, with two active sessions per simulated user.",
    model: episode1Data.model,
    hardware: episode1Data.hardware,
    provenance: `AgentBench ${episode1Data.source.agentbench_commit} · aggregated VictoriaMetrics exports · server provenance unverified`,
    loads: episode1Data.levels,
    limitations: episode1Data.limitations,
    arms: episode1Data.arms.map((arm) => ({
      id: arm.id,
      label: arm.label,
      marker: arm.marker as EvidenceArm["marker"],
      lineStyle: arm.line_style as EvidenceArm["lineStyle"],
      configuration: arm.configuration,
      points: arm.points.map((point) => ({
        load: point.users,
        label: `${point.users} users · ${point.active_streams} active streams`,
        sampleCount: point.sample_count,
        validCount: point.valid_sample_count,
        readings: {
          output_tps: reading(point.output_tps, "tok/s"),
          ttft_p50: reading(point.ttft_p50_ms, "ms"),
          ttft_p95: reading(point.ttft_p95_ms, "ms"),
          tpot_p50: reading(point.tpot_p50_ms, "ms/token"),
          tpot_p95: reading(null, "ms/token", "TPOT p95 was not published in the source report."),
          invalid_rate: reading(point.error_rate * 100, "%"),
          queue_depth: reading(point.telemetry.queued_requests_mean, "requests"),
          queue_wait: reading(null, "ms", "Runtime queue-duration histograms were exported but not normalized for a cross-runtime comparison."),
          kv_occupancy: arm.id === "vllm" ? reading("kv_cache_usage_ratio_mean" in point.telemetry ? point.telemetry.kv_cache_usage_ratio_mean * 100 : null, "%") : reading("kv_cache_memory_usage_gib" in point.telemetry ? point.telemetry.kv_cache_memory_usage_gib : null, "GiB"),
          gpu_utilization: reading(point.telemetry.gpu_utilization_mean_pct, "%"),
          gpu_memory: reading(point.telemetry.gpu_memory_used_gib, "GiB"),
          gpu_power: reading(point.telemetry.gpu_power_mean_w, "W")
        }
      }))
    }))
  };
}

export function adaptSessionStudy(): EvidenceStudy {
  return {
    id: sessionData.study_id,
    kind: "field-note",
    number: null,
    title: "When more users mean more waiting",
    question: "What changes when more users arrive?",
    state: "recorded",
    statusLabel: "Recorded field note · exploratory · capacity not established",
    what: "Compare two recorded vLLM deployments as synthetic conversational load increases.",
    why: "Expose when aggregate output hides a worsening user-visible wait.",
    how: "Replay the same synthetic multi-turn sessions at seven discrete user levels; do not interpolate between them.",
    model: sessionData.model,
    hardware: "RTX PRO 6000 and H200 deployment comparison",
    provenance: "Sanitized session-capacity handoff · unverified provenance fields",
    loads: sessionData.levels,
    limitations: ["Tools were not executed and task correctness was not scored.", "Client-visible TTFT is not server queue duration.", "The deployments differ in hardware and software details."],
    arms: sessionData.deployments.map((arm, armIndex) => ({
      id: arm.id,
      label: arm.label,
      marker: (armIndex === 0 ? "square" : "diamond") as EvidenceArm["marker"],
      lineStyle: (armIndex === 0 ? "dashed" : "solid") as EvidenceArm["lineStyle"],
      configuration: [],
      points: arm.sweep.map((point) => ({
        load: point.users,
        label: `${point.users} simulated users`,
        sampleCount: point.measured,
        validCount: point.valid,
        readings: {
          output_tps: reading(point.output_tps, "tok/s"),
          ttft_p50: reading(point.visible_ttft_p50_s * 1000, "ms"),
          ttft_p95: reading(point.visible_ttft_p95_s * 1000, "ms"),
          tpot_p50: reading(null, "ms/token", "TPOT was not included in the supplied field-note aggregate."),
          tpot_p95: reading(null, "ms/token", "TPOT was not included in the supplied field-note aggregate."),
          invalid_rate: reading(point.error_rate * 100, "%"),
          queue_depth: reading(null, "requests", "Runtime-native queue depth was not included in the supplied field-note aggregate."),
          queue_wait: reading(null, "ms", "Server queue duration was not included in the supplied field-note aggregate."),
          kv_occupancy: reading(null, "source unit", "KV-cache telemetry was not included in the supplied field-note aggregate."),
          gpu_utilization: reading(null, "%", "GPU telemetry was not included in the supplied field-note aggregate."),
          gpu_memory: reading(null, "GiB", "GPU telemetry was not included in the supplied field-note aggregate."),
          gpu_power: reading(null, "W", "GPU telemetry was not included in the supplied field-note aggregate.")
        }
      }))
    }))
  };
}
