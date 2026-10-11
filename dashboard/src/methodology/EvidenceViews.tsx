const lanes = [
  { name: "Client-visible", detail: "TTFT, TPOT, per-request decode speed, completion validity", pattern: [18, 42, 28, 65, 34, 72] },
  { name: "Engine-native", detail: "running work, waiting work and runtime-native context pressure", pattern: [12, 28, 54, 32, 78, 46] },
  { name: "GPU telemetry", detail: "utilization, memory and board power over the same window", pattern: [48, 62, 58, 74, 69, 82] },
] as const;

export function EvidenceViews() {
  return <figure className="evidence-views" aria-labelledby="evidence-views-caption">
    <figcaption id="evidence-views-caption"><strong>One time ruler. Three evidence views.</strong><span>Signals remain in their native definitions while their measurement windows stay aligned.</span></figcaption>
    <div className="evidence-time-ruler"><span>window start</span><i /><span>static approved aggregates</span></div>
    {lanes.map((lane) => <section key={lane.name}><header><strong>{lane.name}</strong><span>{lane.detail}</span></header><svg viewBox="0 0 600 82" role="img" aria-label={`${lane.name} illustrative aligned signal`}><line x1="0" y1="70" x2="600" y2="70" /><polyline points={lane.pattern.map((value, index) => `${index * 120},${78 - value * .75}`).join(" ")} /></svg></section>)}
    <p>Local metrics restoration and dashboard inspection happen once during evidence construction. The published page uses only this embedded static bundle and makes no metrics-server request.</p>
  </figure>;
}
