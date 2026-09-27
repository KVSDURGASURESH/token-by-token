import { useEffect, useMemo, useRef, useState } from "react";

type Profile = { id: string; label: string; runtime_id: string; model: string; supported_optional_fields: string[]; context_length: number | null };
type Config = {
  schema_version: "episode1.quick-test.v1"; mode: "single" | "compare";
  prompt: { system: string; user: string };
  lanes: { id: string; profile_id: string; label: string }[];
  sampling: { maximum_output_tokens: number; temperature: number; top_p: number; top_k?: number; seed?: number; stop?: string };
  request_timeout_seconds: number; repetitions: number; concurrency: number;
};
type LaneView = { text: string; state: string; ttft: number | null; e2e: number | null; tokens: number | null; rate: number | null; error: string };
type Capabilities = { schema_version: string; session: string; profiles: Profile[]; limits: { repetitions: number; concurrency: number } };

const blankLane = (): LaneView => ({ text: "", state: "ready", ttft: null, e2e: null, tokens: null, rate: null, error: "" });
const shortPrompt = "Explain why time to first token and generation speed measure different parts of an inference request.";
const mediumPrompt = "You are reviewing an inference-system comparison. Explain, in a concise technical note, why time to first token, end-to-end latency, output token count, generation rate, failures, and effective runtime configuration must be reported separately. Include one example of a misleading conclusion caused by collapsing them into a single score.";

function defaultConfig(profiles: Profile[]): Config {
  const first = profiles[0]?.id ?? "demo-fast";
  const second = profiles[1]?.id ?? first;
  return { schema_version: "episode1.quick-test.v1", mode: "compare", prompt: { system: "Answer precisely and do not invent measurements.", user: shortPrompt },
    lanes: [{ id: "lane-1", profile_id: first, label: "Lane A" }, { id: "lane-2", profile_id: second, label: "Lane B" }],
    sampling: { maximum_output_tokens: 128, temperature: 0, top_p: 1 }, request_timeout_seconds: 120, repetitions: 1, concurrency: 1 };
}

function download(name: string, value: unknown) {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2) + "\n"], { type: "application/json" }));
  link.download = name; link.click(); URL.revokeObjectURL(link.href);
}

const show = (value: number | null, unit: string) => value === null ? "Unavailable" : `${value.toFixed(1)} ${unit}`;

export function QuickTest() {
  const [caps, setCaps] = useState<Capabilities | null>(null);
  const [config, setConfig] = useState<Config>(() => defaultConfig([]));
  const [lanes, setLanes] = useState<Record<string, LaneView>>({ "lane-1": blankLane(), "lane-2": blankLane() });
  const [runId, setRunId] = useState("");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const abort = useRef<AbortController | null>(null);

  useEffect(() => { fetch("/api/capabilities", { cache: "no-store" }).then(async response => {
    if (!response.ok) throw new Error(`Local bridge returned ${response.status}`);
    return response.json() as Promise<Capabilities>;
  }).then(value => { setCaps(value); setConfig(defaultConfig(value.profiles)); }).catch(failure => setError(failure instanceof Error ? failure.message : "Local bridge unavailable")); }, []);
  const activeLanes = config.mode === "single" ? config.lanes.slice(0, 1) : config.lanes.slice(0, 2);
  const profiles = useMemo(() => new Map(caps?.profiles.map(profile => [profile.id, profile]) ?? []), [caps]);

  const patchLane = (id: string, patch: Partial<LaneView>) => setLanes(current => ({ ...current, [id]: { ...(current[id] ?? blankLane()), ...patch } }));
  const changeLane = (index: number, patch: Partial<Config["lanes"][number]>) => setConfig(current => ({ ...current, lanes: current.lanes.map((lane, laneIndex) => laneIndex === index ? { ...lane, ...patch } : lane) }));
  const sampling = <K extends keyof Config["sampling"]>(key: K, value: Config["sampling"][K]) => setConfig(current => ({ ...current, sampling: { ...current.sampling, [key]: value } }));

  async function stop() {
    if (runId && caps) await fetch("/api/cancel", { method: "POST", headers: { "Content-Type": "application/json", "X-Episode1-Session": caps.session }, body: JSON.stringify({ run_id: runId }) }).catch(() => undefined);
    abort.current?.abort(); activeLanes.forEach(lane => patchLane(lane.id, { state: "cancelled" })); setRunning(false);
  }

  function consume(event: Record<string, any>) {
    if (event.type === "accepted") setRunId(event.run_id);
    else if (event.type === "state") patchLane(event.lane_id, { state: event.state });
    else if (event.type === "content") setLanes(current => ({ ...current, [event.lane_id]: { ...(current[event.lane_id] ?? blankLane()), state: "streaming", text: (current[event.lane_id]?.text ?? "") + event.text } }));
    else if (event.type === "attempt") patchLane(event.lane_id, { state: event.status, ttft: event.ttft_ms, e2e: event.e2e_ms, tokens: event.output_tokens, rate: event.generation_tokens_per_second, error: event.error ?? "" });
    else if (event.type === "complete") { setResult(event.result); setRunning(false); }
    else if (event.type === "fatal") { setError(event.error); setRunning(false); }
  }

  async function start() {
    if (!caps || running) return;
    setError(""); setResult(null); setRunId("");
    setLanes(Object.fromEntries(activeLanes.map(lane => [lane.id, { ...blankLane(), state: "preparing" }])));
    setRunning(true); const controller = new AbortController(); abort.current = controller;
    try {
      const response = await fetch("/api/run", { method: "POST", signal: controller.signal,
        headers: { "Content-Type": "application/json", "Accept": "text/event-stream", "X-Episode1-Session": caps.session },
        body: JSON.stringify({ ...config, lanes: activeLanes }) });
      if (!response.ok) { const body = await response.json(); throw new Error(body.error ?? `Bridge returned ${response.status}`); }
      const reader = response.body?.getReader(); if (!reader) throw new Error("Streaming response is unavailable");
      const decoder = new TextDecoder(); let buffer = "";
      while (true) {
        const { done, value } = await reader.read(); if (done) break;
        buffer += decoder.decode(value, { stream: true });
        while (buffer.includes("\n\n")) { const index = buffer.indexOf("\n\n"); const frame = buffer.slice(0, index); buffer = buffer.slice(index + 2);
          const line = frame.split("\n").find(item => item.startsWith("data: ")); if (line) consume(JSON.parse(line.slice(6))); }
      }
    } catch (failure) {
      if ((failure as Error).name !== "AbortError") setError(failure instanceof Error ? failure.message : "Run failed");
      setRunning(false);
    }
  }

  async function copyCli() {
    const command = `python scripts/episode1_playground.py ${config.mode === "single" ? "request" : "compare"} --config quick-test.json --bridge http://127.0.0.1:8765 --output quick-test-result.json`;
    await navigator.clipboard.writeText(command); setError("CLI command copied. Save this configuration as quick-test.json before running it.");
  }

  return <article className="quick-test">
    <header className="quick-hero"><div><p className="lab-eyebrow">EPISODE 01 / LIVE REQUEST CONSOLE</p><h1>Quick test</h1><p>Race two independently available endpoints—or inspect one—using the exact same prompt and runner-side clock.</p></div><div className="diagnostic-stamp"><strong>AD-HOC DIAGNOSTIC</strong><span>Never promotable benchmark evidence</span></div></header>
    {!caps && <div className="quick-alert" role="status"><strong>Bridge offline</strong><span>Start the documented local bridge to unlock demo and live endpoint profiles.</span></div>}
    {error && <div className="quick-alert" role="alert"><strong>{error}</strong></div>}

    <section className="quick-control" aria-label="Quick test configuration">
      <div className="mode-switch"><button className={config.mode === "single" ? "active" : ""} onClick={() => setConfig(value => ({ ...value, mode: "single" }))}>Single endpoint</button><button className={config.mode === "compare" ? "active" : ""} onClick={() => setConfig(value => ({ ...value, mode: "compare" }))}>Two-lane compare</button></div>
      <label className="wide">Prompt<textarea value={config.prompt.user} onChange={event => setConfig(value => ({ ...value, prompt: { ...value.prompt, user: event.target.value } }))} rows={5} maxLength={32768} /></label>
      <label className="wide">System instruction<textarea value={config.prompt.system} onChange={event => setConfig(value => ({ ...value, prompt: { ...value.prompt, system: event.target.value } }))} rows={2} maxLength={32768} /></label>
      <div className="preset-row"><span>Prompt preset</span><button onClick={() => setConfig(value => ({ ...value, prompt: { ...value.prompt, user: shortPrompt } }))}>Episode 1 short</button><button onClick={() => setConfig(value => ({ ...value, prompt: { ...value.prompt, user: mediumPrompt } }))}>Episode 1 medium</button><small>Input tokens: unavailable without a reviewed matching tokenizer.</small></div>
      <div className="lane-configs">{activeLanes.map((lane, index) => { const profile = profiles.get(lane.profile_id); return <fieldset key={lane.id}><legend>Lane {index + 1}</legend><label>Label<input value={lane.label} maxLength={80} onChange={event => changeLane(index, { label: event.target.value })} /></label><label>Endpoint profile<select value={lane.profile_id} onChange={event => changeLane(index, { profile_id: event.target.value })}>{caps?.profiles.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label><dl><div><dt>Runtime</dt><dd>{profile?.runtime_id ?? "—"}</dd></div><div><dt>Model</dt><dd>{profile?.model ?? "—"}</dd></div><div><dt>Context</dt><dd>{profile?.context_length ?? "unknown"}</dd></div></dl></fieldset>; })}</div>
      <details><summary>Advanced request controls</summary><div className="advanced-grid"><label>Maximum output tokens<input type="number" min="1" max="4096" value={config.sampling.maximum_output_tokens} onChange={event => sampling("maximum_output_tokens", Number(event.target.value))} /></label><label>Temperature<input type="number" min="0" max="2" step="0.1" value={config.sampling.temperature} onChange={event => sampling("temperature", Number(event.target.value))} /></label><label>Top p<input type="number" min="0" max="1" step="0.05" value={config.sampling.top_p} onChange={event => sampling("top_p", Number(event.target.value))} /></label><label>Top k<input type="number" value={config.sampling.top_k ?? ""} placeholder="unset" onChange={event => sampling("top_k", event.target.value === "" ? undefined : Number(event.target.value))} /></label><label>Seed<input type="number" min="0" value={config.sampling.seed ?? ""} placeholder="unset" onChange={event => sampling("seed", event.target.value === "" ? undefined : Number(event.target.value))} /></label><label>Stop sequence<input value={config.sampling.stop ?? ""} placeholder="unset" onChange={event => sampling("stop", event.target.value || undefined)} /></label><label>Timeout (seconds)<input type="number" min="1" max="600" value={config.request_timeout_seconds} onChange={event => setConfig(value => ({ ...value, request_timeout_seconds: Number(event.target.value) }))} /></label><label>Repetitions<input type="number" min="1" max="20" value={config.repetitions} onChange={event => setConfig(value => ({ ...value, repetitions: Number(event.target.value) }))} /></label><label>Concurrency<input type="number" min="1" max="4" value={config.concurrency} onChange={event => setConfig(value => ({ ...value, concurrency: Number(event.target.value) }))} /></label></div><p>Optional fields must be supported by every selected server profile; unsupported settings fail before dispatch.</p></details>
      <div className="quick-actions"><button className="start" disabled={!caps || running} onClick={start}>Start test</button><button className="stop" disabled={!running} onClick={stop}>Stop</button><button onClick={() => download("quick-test.json", { ...config, lanes: activeLanes })}>Save config</button><label className="file-button">Load config<input type="file" accept="application/json,.json" onChange={async event => { const file = event.target.files?.[0]; if (!file) return; try { const loaded = JSON.parse(await file.text()) as Config; if (loaded.schema_version !== "episode1.quick-test.v1") throw new Error("Unsupported config version"); setConfig(loaded); setError(""); } catch (failure) { setError(failure instanceof Error ? failure.message : "Invalid config"); } }} /></label><button onClick={copyCli}>Copy CLI command</button></div>
    </section>

    <section className={`race-grid ${activeLanes.length === 1 ? "single" : ""}`} aria-live="polite">{activeLanes.map(lane => { const view = lanes[lane.id] ?? blankLane(); const profile = profiles.get(lane.profile_id); return <article className="race-lane" key={lane.id}><header><div><span>{profile?.runtime_id ?? lane.profile_id}</span><h2>{lane.label}</h2></div><strong className={`lane-state ${view.state}`}>{view.state}</strong></header><div className="response"><p>{view.text || (view.state === "ready" ? "Ready for a request." : "Waiting for first content…")}</p>{view.error && <strong className="lane-error">{view.error}</strong>}</div><dl className="lane-metrics"><div><dt>TTFT</dt><dd>{show(view.ttft, "ms")}</dd></div><div><dt>Total</dt><dd>{show(view.e2e, "ms")}</dd></div><div><dt>Output</dt><dd>{view.tokens === null ? "Unavailable" : `${view.tokens} tokens`}</dd></div><div><dt>Generation</dt><dd>{show(view.rate, "tok/s")}</dd></div></dl></article>; })}</section>

    <section className="quick-method"><h2>What these numbers mean</h2><p><strong>TTFT</strong> starts at the runner’s actual send boundary and ends at its first nonempty content event. <strong>Total</strong> ends at the terminal stream event. <strong>Generation</strong> is (N−1) server-reported tokens divided by the first-to-last content span; it stays unavailable for one-token or one-chunk responses. This screen never declares a winner.</p>{result && <div className="export-row"><button onClick={() => download("quick-test-result.json", result)}>Export aggregate JSON</button><button onClick={() => download("quick-test-private.json", { result, config: { ...config, lanes: activeLanes }, responses: Object.fromEntries(activeLanes.map(lane => [lane.id, lanes[lane.id]?.text ?? ""])) })}>Export private JSON with text</button><small>Raw prompt and response text are included only in the explicitly private export.</small></div>}</section>
  </article>;
}
