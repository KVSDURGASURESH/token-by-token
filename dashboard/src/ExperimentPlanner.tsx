import { useEffect, useMemo, useState } from "react";
import catalog from "./data/episodes.json";
import capabilitiesData from "./data/capabilities.v1.json";
import { importEnvelope, makeEnvelope, planForTemplate, planningDigest, templates, validatePlan, type ExperimentPlan } from "./experimentPlan";

const hypothesisLabels = {
  slow_first_token: "Slow first token",
  slow_decode: "Slow subsequent tokens",
  throughput_collapse: "Throughput collapse under load",
  high_cost: "High cost per useful token"
} as const;
type PlannerEpisode = (typeof catalog.episodes)[number] & { roadmapAnchor?: string };
const plannerEpisodes = catalog.episodes as PlannerEpisode[];
const initialEpisode = () => {
  const params = new URLSearchParams(window.location.hash.split("?")[1] ?? "");
  const episode = Number(params.get("episode"));
  return Number.isInteger(episode) && episode >= 1 && episode <= 16 ? episode : 1;
};
const suggestedByHypothesis: Record<ExperimentPlan["hypothesis"], string[]> = {
  slow_first_token: ["prefix_caching", "chunked_prefill", "attention_backend"],
  slow_decode: ["weight_quantization", "kv_quantization", "speculative_decoding"],
  throughput_collapse: ["continuous_batching", "paged_kv", "replicas"],
  high_cost: ["weight_quantization", "smaller_model", "distillation", "prefix_caching"]
};

export function ExperimentPlanner() {
  const firstTemplate = templates.find(item => item.episode === initialEpisode()) ?? templates[0];
  const [plan, setPlan] = useState<ExperimentPlan>(() => planForTemplate(firstTemplate.id));
  const [digest, setDigest] = useState("");
  const [notice, setNotice] = useState("");
  const errors = useMemo(() => validatePlan(plan), [plan]);
  const template = templates.find(item => item.id === plan.identity.template_id)!;
  const capabilityMap = new Map(capabilitiesData.capabilities.map(item => [item.feature, item]));
  const companion = ["model", "training", "decision", "platform"].includes(plan.identity.track);

  useEffect(() => { planningDigest(plan).then(setDigest); }, [plan]);
  const update = <K extends keyof ExperimentPlan>(key: K, value: ExperimentPlan[K]) => setPlan(previous => ({ ...previous, [key]: value }));
  const chooseEpisode = (episode: number) => {
    const next = templates.find(item => item.episode === episode);
    if (next) { setPlan(planForTemplate(next.id)); setNotice(""); }
  };
  const download = async () => {
    if (errors.length) return;
    const envelope = await makeEnvelope(plan);
    const blob = new Blob([JSON.stringify(envelope, null, 2) + "\n"], { type: "application/json" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob); link.download = `episode-${plan.identity.episode}-planning-config.json`; link.click();
    URL.revokeObjectURL(link.href); setNotice("Validated planning snapshot exported. It is not execution approval.");
  };
  const importFile = async (file?: File) => {
    if (!file) return;
    try { const envelope = await importEnvelope(await file.text()); setPlan(envelope.config); setNotice("Digest-verified planning snapshot imported as a new editable draft."); }
    catch (error) { setNotice(error instanceof Error ? `Import rejected: ${error.message}` : "Import rejected."); }
  };

  return <article className="planner">
    <header className="planner-hero">
      <div><p className="planner-kicker">Experiment design desk / configuration schema v1</p><h1>Plan the evidence before the GPU.</h1><p>Turn a symptom into a falsifiable, versioned experiment contract. Requested settings remain candidates until runtime and hardware preflight verifies them.</p></div>
      <div className="planner-safety"><strong>Planning only</strong><span>No GPU will be created</span><small>execution_ready: false<br />execution_authorized: false</small></div>
    </header>

    <div className="planner-layout"><form className="planner-form" onSubmit={event => event.preventDefault()}>
      <section className="planner-step"><header><span>01</span><div><h2>Episode &amp; template</h2><p>Every roadmap stage starts from a reusable planning contract.</p></div></header><div className="planner-fields two">
        <label>Episode<select value={plan.identity.episode} onChange={e => chooseEpisode(Number(e.target.value))}>{plannerEpisodes.filter(e => e.number > 0).map(e => <option key={e.id} value={e.number}>{String(e.number).padStart(2,"0")} — {e.title}</option>)}</select></label>
        <label>Template<select value={template.id} onChange={e => setPlan(planForTemplate(e.target.value))}>{templates.filter(t => t.episode === plan.identity.episode).map(t => <option key={t.id} value={t.id}>{t.label} · v{t.version}</option>)}</select></label>
        <label className="wide">Draft label<input value={plan.identity.label} maxLength={120} onChange={e => update("identity", {...plan.identity, label:e.target.value})} /></label>
      </div><p className="planner-note">{template.note} <a href={`${catalog.repository}/blob/main/docs/roadmap.md#${plannerEpisodes[plan.identity.episode].roadmapAnchor}`}>Read roadmap stage ↗</a></p></section>

      <section className="planner-step"><header><span>02</span><div><h2>What are you investigating?</h2><p>A hypothesis suggests controls; it does not diagnose the cause or promise improvement.</p></div></header><div className="hypothesis-grid">{Object.entries(hypothesisLabels).map(([value,label]) => <label key={value} className={plan.hypothesis===value ? "selected" : ""}><input type="radio" name="hypothesis" checked={plan.hypothesis===value} onChange={() => update("hypothesis", value as ExperimentPlan["hypothesis"])} /><strong>{label}</strong><small>{suggestedByHypothesis[value as ExperimentPlan["hypothesis"]].join(" · ")}</small></label>)}</div></section>

      <section className="planner-step"><header><span>03</span><div><h2>Model, lanes &amp; candidate hardware</h2><p>Unknown identities remain explicit. A GPU choice does not claim inventory or availability.</p></div></header><div className="planner-fields three">
        <label>Model identity<input value={plan.model.model_id} onChange={e => update("model", {...plan.model,model_id:e.target.value})} /></label><label>Model revision<input value={plan.model.revision} onChange={e => update("model", {...plan.model,revision:e.target.value})} /></label><label>Tokenizer identity<input value={plan.model.tokenizer_id} onChange={e => update("model", {...plan.model,tokenizer_id:e.target.value})} /></label>
        <label>Tokenizer revision<input value={plan.model.tokenizer_revision} onChange={e => update("model", {...plan.model,tokenizer_revision:e.target.value})} /></label><label>Prompt / chat template<input value={plan.model.template_id} onChange={e => update("model", {...plan.model,template_id:e.target.value})} /></label><label>Weight artifact<input value={plan.optimizations.weight_artifact} onChange={e => update("optimizations", {...plan.optimizations,weight_artifact:e.target.value})} /></label>
        <label>GPU type<select value={plan.hardware.gpu_type} onChange={e => update("hardware", {...plan.hardware,gpu_type:e.target.value})}><option value="unselected">Unselected</option><option>NVIDIA H100 80GB</option><option>NVIDIA A100 80GB</option><option>NVIDIA L40S 48GB</option><option>NVIDIA RTX 4090 24GB</option></select></label><label>GPU count<input type="number" min="1" max="64" value={plan.hardware.gpu_count} onChange={e => update("hardware", {...plan.hardware,gpu_count:Number(e.target.value)})}/></label><label>Nodes<input type="number" min="1" max="64" value={plan.hardware.node_count} onChange={e => update("hardware", {...plan.hardware,node_count:Number(e.target.value)})}/></label>
      </div><fieldset className="runtime-lanes" disabled={companion}><legend>{companion ? "Serving lanes — not applicable to this track" : "Requested serving lanes"}</legend>{plan.runtime_lanes.map((lane,index) => <div key={lane.engine}><label className="check"><input type="checkbox" checked={lane.selected} onChange={e => { const lanes=[...plan.runtime_lanes]; lanes[index]={...lane,selected:e.target.checked}; update("runtime_lanes",lanes); }}/>{lane.engine === "vllm" ? "vLLM" : "SGLang"}</label><label>Requested version<input placeholder="unknown" value={lane.requested_version ?? ""} onChange={e => {const lanes=[...plan.runtime_lanes];lanes[index]={...lane,requested_version:e.target.value||null};update("runtime_lanes",lanes)}} /></label><label>Image digest<input placeholder="unknown" value={lane.image_digest ?? ""} onChange={e => {const lanes=[...plan.runtime_lanes];lanes[index]={...lane,image_digest:e.target.value||null};update("runtime_lanes",lanes)}} /></label></div>)}</fieldset></section>

      <section className="planner-step"><header><span>04</span><div><h2>Optimization requests</h2><p>Engine/version support is unverified. Intrinsic scheduler features are informational.</p></div></header>{companion ? <div className="not-applicable">Serving controls are not applicable to this {plan.identity.track} template. Smaller-model and distillation choices require a new model/training artifact and quality contract.</div> : <div className="planner-fields three">
        <label>Prefix caching<select value={plan.optimizations.prefix_caching} onChange={e => update("optimizations", {...plan.optimizations,prefix_caching:e.target.value as "off"|"requested"})}><option value="off">Off baseline</option><option value="requested">Requested · preflight</option></select></label><label>Cache-state policy<select value={plan.optimizations.cache_policy} onChange={e => update("optimizations", {...plan.optimizations,cache_policy:e.target.value as ExperimentPlan["optimizations"]["cache_policy"]})}><option value="cold">Cold</option><option value="warm">Warm</option><option value="mixed">Mixed</option></select></label>
        <label>Chunked prefill<select value={plan.optimizations.chunked_prefill} onChange={e => update("optimizations", {...plan.optimizations,chunked_prefill:e.target.value as "off"|"requested",chunk_token_budget:e.target.value==="off"?null:plan.optimizations.chunk_token_budget})}><option value="off">Off baseline</option><option value="requested">Requested · preflight</option></select></label><label>Chunk token budget<input type="number" min="1" disabled={plan.optimizations.chunked_prefill==="off"} value={plan.optimizations.chunk_token_budget??""} onChange={e => update("optimizations", {...plan.optimizations,chunk_token_budget:e.target.value?Number(e.target.value):null})}/></label>
        <label>Attention backend<select value={plan.optimizations.attention_backend} onChange={e => update("optimizations", {...plan.optimizations,attention_backend:e.target.value as ExperimentPlan["optimizations"]["attention_backend"]})}><option value="auto">Auto · record dispatch</option><option value="flashattention2">FlashAttention 2</option><option value="flashattention3">FlashAttention 3</option><option value="triton">Triton attention</option></select></label><label>Weight precision<select value={plan.optimizations.weight_precision} onChange={e => update("optimizations", {...plan.optimizations,weight_precision:e.target.value as ExperimentPlan["optimizations"]["weight_precision"]})}>{["bf16","fp16","fp8","int8","int4"].map(v=><option key={v}>{v}</option>)}</select></label><label>KV precision<select value={plan.optimizations.kv_precision} onChange={e => update("optimizations", {...plan.optimizations,kv_precision:e.target.value as ExperimentPlan["optimizations"]["kv_precision"]})}><option value="auto">Auto</option><option value="fp16">FP16</option><option value="fp8">FP8 · preflight</option></select></label>
        <label>Speculative decoding<select value={plan.optimizations.speculative_method} onChange={e => update("optimizations", {...plan.optimizations,speculative_method:e.target.value as "none"|"draft_model"})}><option value="none">None</option><option value="draft_model">Draft model · preflight</option></select></label><label>Draft model identity<input disabled={plan.optimizations.speculative_method==="none"} value={plan.optimizations.draft_model_id} onChange={e=>update("optimizations",{...plan.optimizations,draft_model_id:e.target.value})}/></label><label>Structured output<select value={plan.optimizations.structured_output} onChange={e=>update("optimizations",{...plan.optimizations,structured_output:e.target.value as ExperimentPlan["optimizations"]["structured_output"]})}><option value="none">None</option><option value="json_schema">JSON schema</option><option value="grammar">Grammar</option></select></label>
      </div>}<div className="capability-strip">{suggestedByHypothesis[plan.hypothesis].map(feature => {const c=capabilityMap.get(feature); return <span key={feature} title={c?.constraint}>{feature.replaceAll("_"," ")} <b>{c?.state.replaceAll("_"," ") ?? "unverified"}</b></span>})}</div></section>

      <section className="planner-step"><header><span>05</span><div><h2>Work, quality, SLO &amp; cost contract</h2><p>Budget is desired, not enforced. Cost per million tokens needs measured throughput.</p></div></header><div className="planner-fields four">
        <label>Input tokens<input type="number" min="1" value={plan.workload.input_tokens} onChange={e=>update("workload",{...plan.workload,input_tokens:Number(e.target.value)})}/></label><label>Output tokens<input type="number" min="1" value={plan.workload.output_tokens} onChange={e=>update("workload",{...plan.workload,output_tokens:Number(e.target.value)})}/></label><label>Requests<input type="number" min="1" value={plan.workload.requests} onChange={e=>update("workload",{...plan.workload,requests:Number(e.target.value)})}/></label><label>Repetitions<input type="number" min="1" max="100" value={plan.workload.repetitions} onChange={e=>update("workload",{...plan.workload,repetitions:Number(e.target.value)})}/></label>
        <label>Load mode<select value={plan.workload.load_mode} onChange={e=>update("workload",{...plan.workload,load_mode:e.target.value as "concurrency"|"arrival_rate",concurrency:e.target.value==="concurrency"?1:null,arrival_rate_rps:e.target.value==="arrival_rate"?1:null})}><option value="concurrency">Concurrency</option><option value="arrival_rate">Arrival rate</option></select></label><label>{plan.workload.load_mode==="concurrency"?"Concurrency":"Arrival rate / sec"}<input type="number" min="0.001" step="0.001" value={plan.workload.concurrency??plan.workload.arrival_rate_rps??""} onChange={e=>update("workload",plan.workload.load_mode==="concurrency"?{...plan.workload,concurrency:Number(e.target.value)}:{...plan.workload,arrival_rate_rps:Number(e.target.value)})}/></label>
        <label>Quality dataset<input value={plan.quality.dataset} onChange={e=>update("quality",{...plan.quality,dataset:e.target.value})}/></label><label>Quality threshold<input type="number" min="0" max="1" step="0.01" value={plan.quality.threshold} onChange={e=>update("quality",{...plan.quality,threshold:Number(e.target.value)})}/></label>
        <label>TTFT SLO · ms<input type="number" min="0.01" value={plan.slos.ttft_ms} onChange={e=>update("slos",{...plan.slos,ttft_ms:Number(e.target.value)})}/></label><label>TPOT SLO · ms<input type="number" min="0.01" value={plan.slos.tpot_ms} onChange={e=>update("slos",{...plan.slos,tpot_ms:Number(e.target.value)})}/></label><label>End-to-end SLO · ms<input type="number" min="0.01" value={plan.slos.end_to_end_ms} onChange={e=>update("slos",{...plan.slos,end_to_end_ms:Number(e.target.value)})}/></label><label>Max error rate<input type="number" min="0" max="1" step="0.001" value={plan.slos.max_error_rate} onChange={e=>update("slos",{...plan.slos,max_error_rate:Number(e.target.value)})}/></label>
        <label>Desired budget · USD<input inputMode="decimal" value={plan.cost.desired_budget_usd} onChange={e=>update("cost",{...plan.cost,desired_budget_usd:e.target.value})}/></label><label>Hourly rate · USD<input inputMode="decimal" placeholder="Unavailable" value={plan.cost.hourly_rate_usd??""} onChange={e=>update("cost",{...plan.cost,hourly_rate_usd:e.target.value||null})}/></label><label>Rate source<input value={plan.cost.rate_source} onChange={e=>update("cost",{...plan.cost,rate_source:e.target.value})}/></label><label>Planned duration · hours<input inputMode="decimal" value={plan.cost.planned_duration_hours} onChange={e=>update("cost",{...plan.cost,planned_duration_hours:e.target.value})}/></label>
      </div></section>
    </form>

    <aside className="planner-summary" aria-live="polite"><p className="summary-label">Draft status</p><strong className={errors.length?"invalid":"valid"}>{errors.length?`${errors.length} issue${errors.length===1?"":"s"}`:"Valid planning config"}</strong>{errors.length?<ul>{errors.map(error=><li key={error}>{error}</li>)}</ul>:<p>Shape and semantic checks pass. Runtime compatibility is still unverified.</p>}<dl><div><dt>Evidence</dt><dd>Requested · not measured</dd></div><div><dt>Compatibility</dt><dd>Preflight required</dd></div><div><dt>Cost estimate</dt><dd>{plan.cost.hourly_rate_usd??"Unavailable"}</dd></div></dl><code title={digest}>{digest ? `${digest.slice(0,16)}…` : "Computing digest…"}</code><small>Planning configuration digest only — not paid-execution approval.</small><div className="planner-actions"><button type="button" disabled={errors.length>0} onClick={download}>Export validated snapshot</button><label className="import-button">Import snapshot<input type="file" accept="application/json,.json" onChange={e=>importFile(e.target.files?.[0])}/></label></div>{notice&&<p className="planner-notice">{notice}</p>}<a href={`${catalog.repository}/blob/main/docs/experiment-planner.md`}>Planner safety &amp; format ↗</a></aside>
    </div>
  </article>;
}
