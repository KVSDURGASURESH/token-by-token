import { useState } from "react";

const stages = ["instruction", "generation", "tool call", "tool gap", "tool result", "accumulated context", "next generation", "human gap"];

export function SessionReplay() {
  const [stage, setStage] = useState(0);
  return <div className="session-replay">
    <div className="replay-control">
      <label htmlFor="replay-stage">Scrub the replay <strong>{String(stage + 1).padStart(2, "0")} / {String(stages.length).padStart(2, "0")}</strong></label>
      <input id="replay-stage" type="range" min="0" max={stages.length - 1} step="1" value={stage} onChange={(event) => setStage(Number(event.target.value))} aria-valuetext={stages[stage]} />
    </div>
    <div className="replay-sessions" aria-live="polite">
      {["Session A", "Session B"].map((session, sessionIndex) => <section key={session}><header><span>{session}</span><strong>{sessionIndex === 0 ? stages[stage] : stages[(stage + 3) % stages.length]}</strong></header><div>{stages.map((item, index) => <i key={item} className={index <= (sessionIndex === 0 ? stage : (stage + 3) % stages.length) ? "complete" : ""} />)}</div></section>)}
    </div>
    <ol className="replay-transcript" aria-label="Replay stages">{stages.map((item, index) => <li key={item} aria-current={index === stage ? "step" : undefined}><span>{String(index + 1).padStart(2, "0")}</span>{item}</li>)}</ol>
    <p>Two session slots per user move independently. Tool execution and human think time create quiet gaps; accumulated context returns on the next generation.</p>
  </div>;
}
