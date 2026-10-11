import { useEffect, useState } from "react";

type LaunchResult = { plan_sha256?: string; status?: string; error?: string; [key: string]: unknown };
type LaunchStatus = {
  configured: boolean;
  launch_enabled: boolean;
  phase: string;
  supported_episodes: number[];
  episode?: number;
  plan_sha256?: string;
  maximum_spend_usd?: string;
  approval_phrase?: string;
  last_result?: LaunchResult | null;
};
type Capabilities = { session: string };

const readiness = [
  ["01", "Measurement contract", "Executable", "Repository-owned RunPod lifecycle, workload, capture and verified cleanup"],
  ["02", "Reproducible inference", "Adapter required", "No canonical reproducibility workload adapter"],
  ["03–09", "Serving experiments", "Adapters required", "Endpoint prompt packs are rehearsal probes, not canonical cache/scheduler/quantization/speculation/topology experiments"],
  ["10", "Platform playbooks", "Architecture decision", "Choose existing Slurm/Kubernetes cluster integration or an authorized temporary RunPod cluster"],
  ["11", "Model internals", "Adapter required", "TensorLab instrumentation and workload contract are not implemented"],
  ["12", "LoRA / QLoRA", "Adapter required", "Training, checkpoint and quality-capture contract is not implemented"],
  ["13", "Jev runtime", "Architecture decision", "Select the real Jev API and version before implementing its adapter"],
  ["14", "Packaging", "Adapter required", "Build/release validation workload is not implemented"],
  ["15", "Saturation", "Adapter required", "Canonical load-generation and recovery workload is not implemented"],
  ["16", "Release gates and recovery", "Adapter required", "Capstone release-gate, rollback and recovery workload is not implemented"],
];

export function CanonicalLaunch() {
  const [caps, setCaps] = useState<Capabilities | null>(null);
  const [status, setStatus] = useState<LaunchStatus | null>(null);
  const [approval, setApproval] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const refresh = async () => {
    const next = await fetch("/api/canonical-status", { cache: "no-store" });
    if (!next.ok) throw new Error(`Canonical status returned ${next.status}`);
    setStatus(await next.json());
  };
  useEffect(() => {
    Promise.all([
      fetch("/api/capabilities", { cache: "no-store" }).then(response => response.json()),
      fetch("/api/canonical-status", { cache: "no-store" }).then(response => response.json()),
    ]).then(([nextCaps, nextStatus]) => { setCaps(nextCaps); setStatus(nextStatus); })
      .catch(error => setMessage(error instanceof Error ? error.message : "Local bridge unavailable"));
  }, []);
  useEffect(() => {
    if (status?.phase !== "running") return;
    const timer = window.setInterval(() => refresh().catch(() => undefined), 2000);
    return () => window.clearInterval(timer);
  }, [status?.phase]);

  async function post(path: string, body: object) {
    if (!caps) return;
    setBusy(true); setMessage("");
    try {
      const response = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json", "X-Episode1-Session": caps.session }, body: JSON.stringify(body) });
      const value = await response.json();
      if (!response.ok) throw new Error(value.error ?? `Bridge returned ${response.status}`);
      setMessage(path.endsWith("preflight") ? "Preflight passed without creating a provider resource." : "Canonical run accepted. Cleanup must be provider-verified before completion.");
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Canonical operation failed");
    } finally { setBusy(false); }
  }

  const exact = Boolean(status?.approval_phrase && approval === status.approval_phrase);
  return <article className="canonical-launch">
    <header className="runner-hero"><div><p className="lab-eyebrow">CANONICAL EXECUTION / FAIL CLOSED</p><h1>Launch only what was approved.</h1><p>The dashboard invokes the repository-owned Episode 1 production runner. The server—not the browser—selects every input path, and the runner revalidates the immutable plan, source, build, authorization receipt and evidence closure before provider creation.</p></div><div className="diagnostic-stamp"><strong>{status?.configured ? "EPISODE 01" : "NOT CONFIGURED"}</strong><span>{status?.phase ?? "Loading"}</span></div></header>
    {message && <div className="quick-alert" role="status"><strong>{message}</strong></div>}
    <section className="canonical-card">
      <div><span>Bound plan</span><code>{status?.plan_sha256 ?? "Start the bridge with --canonical-launch-bundle"}</code></div>
      <div><span>Maximum charge</span><strong>{status?.maximum_spend_usd ? `$${status.maximum_spend_usd} USD` : "Unavailable"}</strong></div>
      <div><span>Paid launch switch</span><strong>{status?.launch_enabled ? "Enabled by operator" : "Disabled"}</strong></div>
      <div className="canonical-actions"><button disabled={!status?.configured || busy || status?.phase === "running"} onClick={() => post("/api/canonical-preflight", {})}>Run read-only preflight</button><button className="start" disabled={!status?.configured || !status?.launch_enabled || !exact || busy || status?.phase === "running"} onClick={() => post("/api/canonical-launch", { approval_phrase: approval })}>Launch approved plan</button></div>
      <label>Exact digest-bound spend approval phrase<textarea rows={3} spellCheck={false} value={approval} onChange={event => setApproval(event.target.value)} placeholder={status?.approval_phrase ?? "Available only after a launch bundle is configured"}/></label>
      <p className="canonical-warning">Typing the phrase is an accidental-click guard, not a substitute for the retained authorization record. The production runner independently verifies that record and rejects stale, mismatched or incomplete approval before any resource is created.</p>
      {status?.last_result && <pre>{JSON.stringify(status.last_result, null, 2)}</pre>}
    </section>
    <section className="readiness-table"><header><span>CANONICAL ADAPTER READINESS</span><h2>Executable is a stricter word than configurable.</h2><p>Runtime GPU, model, image digest and maximum price belong in the bound plan. Rows below identify missing software or unresolved architecture—not values an operator can fill in later.</p></header><div role="table">{readiness.map(row => <div role="row" key={row[0]}><b role="cell">{row[0]}</b><strong role="cell">{row[1]}</strong><span role="cell">{row[2]}</span><p role="cell">{row[3]}</p></div>)}</div></section>
  </article>;
}
