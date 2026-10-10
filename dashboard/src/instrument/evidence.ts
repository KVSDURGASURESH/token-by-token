import episode1Data from "../data/episode-1-public.v1.json";
import sessionData from "../data/session-capacity-study.json";

export type EvidenceState = "recorded" | "draft" | "import-pending" | "planned";
export type MetricDirection = "higher" | "lower" | "contextual";
export type MetricReading = { available: boolean; value: number | null; unit: string; reason: string | null; evidenceState?: string };
export type EvidencePoint = { load: number; label: string; readings: Record<string, MetricReading>; sampleCount: number; validCount: number };
export type EvidenceArm = { id: string; label: string; marker: "circle" | "diamond" | "square"; lineStyle: "solid" | "dashed" | "dotted"; points: EvidencePoint[] };
export type EvidenceStudy = { id: string; kind: "episode" | "field-note"; number: number | null; title: string; question: string; state: EvidenceState; statusLabel: string; what: string; why: string; how: string; model: string; hardware: string; provenance: string; loads: number[]; arms: EvidenceArm[]; limitations: string[]; decodeThreshold: number | null; capacityState: string };
export type MetricDefinition = { id: string; label: string; shortLabel: string; explanation: string; unit: string; direction: MetricDirection; tolerancePercent: number | null };
export type ComparisonResult = { available: boolean; absolute: number | null; relativePercent: number | null; reason: string | null };

export const METRICS: Record<string, MetricDefinition> = {
  output_tps: { id: "output_tps", label: "Output throughput", shortLabel: "Throughput", explanation: "Successful output tokens divided by the declared measurement duration.", unit: "tok/s", direction: "higher", tolerancePercent: 2 },
  ttft_p50_ms: { id: "ttft_p50_ms", label: "Visible TTFT p50", shortLabel: "TTFT p50", explanation: "Median client-visible time to first token.", unit: "ms", direction: "lower", tolerancePercent: 2 },
  ttft_p95_ms: { id: "ttft_p95_ms", label: "Visible TTFT p95", shortLabel: "TTFT p95", explanation: "95th-percentile client-visible time to first token.", unit: "ms", direction: "lower", tolerancePercent: 2 },
  tpot_p50_ms: { id: "tpot_p50_ms", label: "TPOT p50", shortLabel: "TPOT p50", explanation: "Median time per output token after the first token.", unit: "ms/token", direction: "lower", tolerancePercent: 2 },
  decode_p10_tps: { id: "decode_p10_tps", label: "Decode speed p10", shortLabel: "Decode p10", explanation: "90% of valid requests decoded at least this fast.", unit: "tok/s", direction: "higher", tolerancePercent: null },
  error_rate_pct: { id: "error_rate_pct", label: "Failed / invalid requests", shortLabel: "Invalid", explanation: "Requests that did not meet the recorded completion-validity contract.", unit: "%", direction: "lower", tolerancePercent: 0.1 },
  running_requests_mean: { id: "running_requests_mean", label: "Running requests", shortLabel: "Running", explanation: "Mean runtime-native running-request gauge in the measured window.", unit: "requests", direction: "contextual", tolerancePercent: null },
  waiting_requests_mean: { id: "waiting_requests_mean", label: "Waiting requests", shortLabel: "Waiting", explanation: "Mean runtime-native waiting-request gauge; compare the trend, not the engine-native definition.", unit: "requests", direction: "contextual", tolerancePercent: null },
  cache_context: { id: "cache_context", label: "Cache context", shortLabel: "Cache", explanation: "Unavailable for cross-engine ranking because the native definitions differ.", unit: "%", direction: "contextual", tolerancePercent: null },
  gpu_utilization_pct: { id: "gpu_utilization_pct", label: "GPU utilization", shortLabel: "GPU util.", explanation: "Mean sampled device utilization during the aligned five-minute measurement window.", unit: "%", direction: "contextual", tolerancePercent: null },
  gpu_memory_gib: { id: "gpu_memory_gib", label: "Maximum sampled GPU memory", shortLabel: "GPU memory", explanation: "Maximum sampled device memory use in the measured window.", unit: "GiB", direction: "contextual", tolerancePercent: null },
  gpu_power_w: { id: "gpu_power_w", label: "GPU board power", shortLabel: "Power", explanation: "Mean sampled board power during the aligned measurement window.", unit: "W", direction: "contextual", tolerancePercent: null }
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
    id: "episode-1",
    kind: "episode",
    number: 1,
    title: "Episode 01 — The throughput lead changes with load",
    question: "Can the throughput leader still miss the decode floor?",
    state: "recorded",
    statusLabel: "Recorded · exploratory · capacity not established",
    what: "Compare vLLM and SGLang on one H200 at three matched, recorded user levels.",
    why: "Find the point where output, TTFT, TPOT and queue pressure stop telling the same story.",
    how: `Replay a conversation-and-tool-use workload for ${episode1Data.methodology.measurement_seconds / 60} measured minutes after warm-up, with ${episode1Data.methodology.sessions_per_user} active sessions per user.`,
    model: "Matched model · serving details withheld",
    hardware: `${episode1Data.study.hardware_count}× ${episode1Data.study.hardware}`,
    provenance: episode1Data.study.provenance,
    loads: episode1Data.levels,
    limitations: episode1Data.limitations,
    decodeThreshold: episode1Data.methodology.decode_threshold_tps,
    capacityState: episode1Data.methodology.capacity_state,
    arms: episode1Data.arms.map((arm) => ({
      id: arm.engine.toLowerCase(),
      label: arm.engine,
      marker: arm.marker as EvidenceArm["marker"],
      lineStyle: arm.line_style as EvidenceArm["lineStyle"],
      points: arm.points.map((point) => ({
        load: point.users,
        label: `${point.users} users · ${point.active_sessions} active sessions`,
        sampleCount: point.total_requests,
        validCount: point.valid_requests,
        readings: Object.fromEntries(Object.entries(point.readings).map(([id, value]) => [id, { ...value, evidenceState: value.evidence_state }]))
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
    decodeThreshold: null,
    capacityState: "not_established",
    arms: sessionData.deployments.map((arm, armIndex) => ({
      id: arm.id,
      label: arm.label,
      marker: (armIndex === 0 ? "square" : "diamond") as EvidenceArm["marker"],
      lineStyle: (armIndex === 0 ? "dashed" : "solid") as EvidenceArm["lineStyle"],
      points: arm.sweep.map((point) => ({
        load: point.users,
        label: `${point.users} simulated users`,
        sampleCount: point.measured,
        validCount: point.valid,
        readings: {
          output_tps: reading(point.output_tps, "tok/s"),
          ttft_p50_ms: reading(point.visible_ttft_p50_s * 1000, "ms"),
          ttft_p95_ms: reading(point.visible_ttft_p95_s * 1000, "ms"),
          tpot_p50_ms: reading(null, "ms/token", "TPOT was not included in the supplied field-note aggregate."),
          decode_p10_tps: reading(null, "tok/s", "Decode p10 was not included in the supplied field-note aggregate."),
          error_rate_pct: reading(point.error_rate * 100, "%"),
          running_requests_mean: reading(null, "requests", "Runtime-native running requests were not included in the supplied field-note aggregate."),
          waiting_requests_mean: reading(null, "requests", "Runtime-native waiting requests were not included in the supplied field-note aggregate."),
          cache_context: reading(null, "%", "Cache telemetry was not included in the supplied field-note aggregate."),
          gpu_utilization_pct: reading(null, "%", "GPU telemetry was not included in the supplied field-note aggregate."),
          gpu_memory_gib: reading(null, "GiB", "GPU telemetry was not included in the supplied field-note aggregate."),
          gpu_power_w: reading(null, "W", "GPU telemetry was not included in the supplied field-note aggregate.")
        }
      }))
    }))
  };
}
