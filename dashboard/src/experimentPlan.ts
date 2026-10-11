import templatesData from "./data/experiment-templates.v1.json";

export type Hypothesis = "slow_first_token" | "slow_decode" | "throughput_collapse" | "high_cost";
export type Track = "serving" | "model" | "training" | "decision" | "topology" | "platform" | "release";
export type Engine = "vllm" | "sglang";
export type ExperimentTemplate = { id: string; version: number; episode: number; previousEpisode: number; track: Track; label: string; hypothesis: Hypothesis; suggestedControls: string[]; note: string };

export type ExperimentPlan = {
  schema_version: "inference-lab.experiment-plan.v1";
  planning_only: true;
  execution_ready: false;
  execution_authorized: false;
  identity: { episode: number; track: Track; template_id: string; template_version: number; label: string };
  hypothesis: Hypothesis;
  model: { model_id: string; revision: string; tokenizer_id: string; tokenizer_revision: string; template_id: string };
  runtime_lanes: Array<{ engine: Engine; selected: boolean; requested_version: string | null; image_digest: string | null }>;
  hardware: { gpu_type: string; gpu_memory_gb: number | null; gpu_count: number; node_count: number };
  optimizations: {
    prefix_caching: "off" | "requested"; cache_policy: "cold" | "warm" | "mixed";
    chunked_prefill: "off" | "requested"; chunk_token_budget: number | null;
    attention_backend: "auto" | "flashattention2" | "flashattention3" | "triton";
    weight_precision: "bf16" | "fp16" | "fp8" | "int8" | "int4";
    weight_artifact: string; kv_precision: "auto" | "fp16" | "fp8";
    speculative_method: "none" | "draft_model"; draft_model_id: string;
    structured_output: "none" | "json_schema" | "grammar";
  };
  workload: {
    input_tokens: number; output_tokens: number; output_contract: "natural_stop" | "fixed_output";
    load_mode: "concurrency" | "arrival_rate"; concurrency: number | null; arrival_rate_rps: number | null;
    warmup_requests: number; requests: number; repetitions: number; timeout_seconds: number;
    cache_state: "cold" | "warm" | "mixed";
  };
  quality: { dataset: string; dataset_version: string; metric: string; threshold: number; require_schema_validity: boolean; require_semantic_correctness: boolean };
  slos: { ttft_ms: number; tpot_ms: number; end_to_end_ms: number; max_error_rate: number };
  cost: { desired_budget_usd: string; hourly_rate_usd: string | null; rate_source: string; rate_date: string | null; planned_duration_hours: string };
};

export type PlanEnvelope = { kind: "inference-lab.planning-config"; digest_algorithm: "sha256"; planning_config_digest: string; config: ExperimentPlan };
export const templates = templatesData.templates as ExperimentTemplate[];

export function planForTemplate(templateId: string): ExperimentPlan {
  const template = templates.find(item => item.id === templateId) ?? templates[0];
  const serving = !["model", "training", "decision", "platform"].includes(template.track);
  return {
    schema_version: "inference-lab.experiment-plan.v1", planning_only: true, execution_ready: false, execution_authorized: false,
    identity: { episode: template.episode, track: template.track, template_id: template.id, template_version: template.version, label: template.label },
    hypothesis: template.hypothesis,
    model: { model_id: "unknown", revision: "unknown", tokenizer_id: "unknown", tokenizer_revision: "unknown", template_id: "unknown" },
    runtime_lanes: [
      { engine: "vllm", selected: serving, requested_version: null, image_digest: null },
      { engine: "sglang", selected: serving, requested_version: null, image_digest: null }
    ],
    hardware: { gpu_type: "unselected", gpu_memory_gb: null, gpu_count: 1, node_count: 1 },
    optimizations: {
      prefix_caching: template.suggestedControls.includes("prefix_caching") ? "requested" : "off", cache_policy: "cold",
      chunked_prefill: template.suggestedControls.includes("chunked_prefill") ? "requested" : "off", chunk_token_budget: null,
      attention_backend: "auto", weight_precision: "bf16", weight_artifact: "unknown", kv_precision: "auto",
      speculative_method: "none", draft_model_id: "", structured_output: "none"
    },
    workload: { input_tokens: 2048, output_tokens: 128, output_contract: "natural_stop", load_mode: "concurrency", concurrency: 1, arrival_rate_rps: null, warmup_requests: 8, requests: 128, repetitions: 3, timeout_seconds: 300, cache_state: "cold" },
    quality: { dataset: "unknown", dataset_version: "unknown", metric: "task_acceptance", threshold: 0.9, require_schema_validity: true, require_semantic_correctness: true },
    slos: { ttft_ms: 1000, tpot_ms: 50, end_to_end_ms: 15000, max_error_rate: 0.01 },
    cost: { desired_budget_usd: "5.00", hourly_rate_usd: null, rate_source: "unavailable", rate_date: null, planned_duration_hours: "1.00" }
  };
}

const keys: Record<string, string[]> = {
  root: ["schema_version","planning_only","execution_ready","execution_authorized","identity","hypothesis","model","runtime_lanes","hardware","optimizations","workload","quality","slos","cost"],
  identity: ["episode","track","template_id","template_version","label"], model: ["model_id","revision","tokenizer_id","tokenizer_revision","template_id"],
  lane: ["engine","selected","requested_version","image_digest"], hardware: ["gpu_type","gpu_memory_gb","gpu_count","node_count"],
  optimizations: ["prefix_caching","cache_policy","chunked_prefill","chunk_token_budget","attention_backend","weight_precision","weight_artifact","kv_precision","speculative_method","draft_model_id","structured_output"],
  workload: ["input_tokens","output_tokens","output_contract","load_mode","concurrency","arrival_rate_rps","warmup_requests","requests","repetitions","timeout_seconds","cache_state"],
  quality: ["dataset","dataset_version","metric","threshold","require_schema_validity","require_semantic_correctness"],
  slos: ["ttft_ms","tpot_ms","end_to_end_ms","max_error_rate"], cost: ["desired_budget_usd","hourly_rate_usd","rate_source","rate_date","planned_duration_hours"]
};
const decimal = /^(0|[1-9]\d*)(\.\d{1,2})?$/;
const exactKeys = (value: unknown, expected: string[]) => !!value && typeof value === "object" && !Array.isArray(value) && Object.keys(value).length === expected.length && Object.keys(value).every(key => expected.includes(key));
const finiteInt = (value: unknown, min: number, max: number) => typeof value === "number" && Number.isFinite(value) && Number.isInteger(value) && value >= min && value <= max;
const finiteNum = (value: unknown, min: number, max: number) => typeof value === "number" && Number.isFinite(value) && value >= min && value <= max;

export function validatePlan(value: unknown): string[] {
  const e: string[] = [];
  if (!exactKeys(value, keys.root)) return ["Plan has missing or unknown top-level fields."];
  const p = value as ExperimentPlan;
  if (p.schema_version !== "inference-lab.experiment-plan.v1") e.push("Unsupported schema version.");
  if (p.planning_only !== true || p.execution_ready !== false || p.execution_authorized !== false) e.push("Safety constants were changed.");
  for (const section of ["identity","model","hardware","optimizations","workload","quality","slos","cost"] as const) if (!exactKeys(p[section], keys[section])) e.push(`${section} has missing or unknown fields.`);
  if (!Array.isArray(p.runtime_lanes) || p.runtime_lanes.length !== 2 || p.runtime_lanes.some(l => !exactKeys(l, keys.lane))) e.push("Runtime lanes must contain exactly the closed vLLM and SGLang records.");
  if (e.length) return e;
  const requiredStrings: Array<[unknown, string]> = [
    [p.identity.label,"Draft label"],[p.model.model_id,"Model identity"],[p.model.revision,"Model revision"],
    [p.model.tokenizer_id,"Tokenizer identity"],[p.model.tokenizer_revision,"Tokenizer revision"],[p.model.template_id,"Prompt template identity"],
    [p.hardware.gpu_type,"GPU type"],[p.optimizations.weight_artifact,"Weight artifact"],[p.optimizations.draft_model_id,"Draft model identity"],
    [p.quality.dataset,"Quality dataset"],[p.quality.dataset_version,"Dataset version"],[p.quality.metric,"Quality metric"],
    [p.cost.rate_source,"Rate source"]
  ];
  for (const [field, label] of requiredStrings) if (typeof field !== "string" || (label !== "Draft model identity" && !field.trim())) e.push(`${label} must be a nonempty string.`);
  if (typeof p.quality.require_schema_validity !== "boolean" || typeof p.quality.require_semantic_correctness !== "boolean") e.push("Quality requirements must be booleans.");
  if (p.cost.rate_date !== null && (typeof p.cost.rate_date !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(p.cost.rate_date))) e.push("Rate date must be null or an ISO date.");
  if (!templates.some(t => t.id === p.identity?.template_id && t.episode === p.identity?.episode && t.version === p.identity?.template_version && t.track === p.identity?.track)) e.push("Episode and template identity are inconsistent.");
  const enumChecks: Array<[unknown, readonly string[], string]> = [
    [p.hypothesis,["slow_first_token","slow_decode","throughput_collapse","high_cost"],"Hypothesis"],
    [p.optimizations?.prefix_caching,["off","requested"],"Prefix caching"],[p.optimizations?.cache_policy,["cold","warm","mixed"],"Cache policy"],
    [p.optimizations?.chunked_prefill,["off","requested"],"Chunked prefill"],[p.optimizations?.attention_backend,["auto","flashattention2","flashattention3","triton"],"Attention backend"],
    [p.optimizations?.weight_precision,["bf16","fp16","fp8","int8","int4"],"Weight precision"],[p.optimizations?.kv_precision,["auto","fp16","fp8"],"KV precision"],
    [p.optimizations?.speculative_method,["none","draft_model"],"Speculative method"],[p.optimizations?.structured_output,["none","json_schema","grammar"],"Structured output"],
    [p.workload?.load_mode,["concurrency","arrival_rate"],"Load mode"],[p.workload?.output_contract,["natural_stop","fixed_output"],"Output contract"],[p.workload?.cache_state,["cold","warm","mixed"],"Workload cache state"]
  ];
  for (const [value, allowed, label] of enumChecks) if (typeof value !== "string" || !allowed.includes(value)) e.push(`${label} is unsupported.`);
  const laneEngines = p.runtime_lanes?.map(l => l.engine) ?? [];
  if (new Set(laneEngines).size !== 2 || !laneEngines.includes("vllm") || !laneEngines.includes("sglang")) e.push("Runtime lanes must be unique vLLM and SGLang lanes.");
  if (p.runtime_lanes?.some(l => typeof l.selected !== "boolean" || (l.requested_version !== null && typeof l.requested_version !== "string") || (l.image_digest !== null && typeof l.image_digest !== "string"))) e.push("Runtime lane values are malformed.");
  if (["model","training","decision","platform"].includes(p.identity?.track) && p.runtime_lanes?.some(l => l.selected)) e.push("Serving lanes are not applicable to this companion/platform template.");
  const forbiddenText = /(?:https?:\/\/|\b(?:api[_-]?key|token|password|secret)\b|(?:^|\s)(?:bash|sh|curl|wget)\s)/i;
  const stringValues = JSON.stringify(p);
  if (forbiddenText.test(stringValues)) e.push("Endpoint URLs, credentials and shell commands are not accepted.");
  const integerChecks: Array<[unknown,number,number,string]> = [[p.hardware?.gpu_count,1,64,"GPU count"],[p.hardware?.node_count,1,64,"Node count"],[p.workload?.input_tokens,1,1048576,"Input tokens"],[p.workload?.output_tokens,1,1048576,"Output tokens"],[p.workload?.warmup_requests,0,100000,"Warm-up requests"],[p.workload?.requests,1,1000000,"Requests"],[p.workload?.repetitions,1,100,"Repetitions"],[p.workload?.timeout_seconds,1,86400,"Timeout"]];
  for (const [v,min,max,label] of integerChecks) if (!finiteInt(v,min,max)) e.push(`${label} is outside its allowed range.`);
  if (p.hardware?.gpu_memory_gb !== null && !finiteNum(p.hardware?.gpu_memory_gb,1,1000)) e.push("GPU memory is outside its allowed range.");
  for (const [v,min,max,label] of [[p.quality?.threshold,0,1,"Quality threshold"],[p.slos?.ttft_ms,0.01,3600000,"TTFT SLO"],[p.slos?.tpot_ms,0.01,3600000,"TPOT SLO"],[p.slos?.end_to_end_ms,0.01,3600000,"End-to-end SLO"],[p.slos?.max_error_rate,0,1,"Error-rate SLO"]] as Array<[unknown,number,number,string]>) if (!finiteNum(v,min,max)) e.push(`${label} is outside its allowed range.`);
  if (p.workload?.load_mode === "concurrency" && (!finiteInt(p.workload.concurrency,1,100000) || p.workload.arrival_rate_rps !== null)) e.push("Concurrency mode requires concurrency and no arrival rate.");
  if (p.workload?.load_mode === "arrival_rate" && (!finiteNum(p.workload.arrival_rate_rps,0.001,100000) || p.workload.concurrency !== null)) e.push("Arrival-rate mode requires an arrival rate and no concurrency.");
  if (p.optimizations?.chunked_prefill === "off" && p.optimizations.chunk_token_budget !== null) e.push("Chunk token budget requires requested chunked prefill.");
  if (p.optimizations?.speculative_method === "draft_model" && (typeof p.optimizations.draft_model_id !== "string" || !p.optimizations.draft_model_id.trim())) e.push("Draft-model speculation requires a draft model identity.");
  for (const [value,label] of [[p.cost?.desired_budget_usd,"Desired budget"],[p.cost?.planned_duration_hours,"Planned duration"],[p.cost?.hourly_rate_usd,"Hourly rate"]] as Array<[string|null,string]>) if (value !== null && !decimal.test(value)) e.push(`${label} must be a nonnegative decimal string with at most two fractional digits.`);
  return e;
}

function canonical(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  return `{${Object.entries(value as Record<string, unknown>).sort(([a],[b]) => a.localeCompare(b)).map(([k,v]) => `${JSON.stringify(k)}:${canonical(v)}`).join(",")}}`;
}

export async function planningDigest(plan: ExperimentPlan): Promise<string> {
  const bytes = new TextEncoder().encode(canonical(plan));
  const hash = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(hash), byte => byte.toString(16).padStart(2, "0")).join("");
}

export async function makeEnvelope(plan: ExperimentPlan): Promise<PlanEnvelope> {
  return { kind: "inference-lab.planning-config", digest_algorithm: "sha256", planning_config_digest: await planningDigest(plan), config: plan };
}

export async function importEnvelope(text: string): Promise<PlanEnvelope> {
  const parsed: unknown = JSON.parse(text);
  if (!exactKeys(parsed, ["kind","digest_algorithm","planning_config_digest","config"])) throw new Error("Import envelope has missing or unknown fields.");
  const envelope = parsed as PlanEnvelope;
  if (envelope.kind !== "inference-lab.planning-config" || envelope.digest_algorithm !== "sha256") throw new Error("Unsupported planning envelope.");
  const errors = validatePlan(envelope.config);
  if (errors.length) throw new Error(errors.join(" "));
  if (await planningDigest(envelope.config) !== envelope.planning_config_digest) throw new Error("Planning configuration digest does not match the imported content.");
  return envelope;
}
