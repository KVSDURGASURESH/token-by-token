import { useState } from "react";

const layers = [
  { name: "System instructions", share: 18, note: "Stable behavior, safety and environment context carried into the turn." },
  { name: "Tool definitions", share: 14, note: "Structured capabilities and argument shapes available to the model." },
  { name: "Conversation history", share: 42, note: "Earlier messages, decisions and accumulated working context." },
  { name: "Tool calls / results", share: 15, note: "Prior actions and returned observations, including realistic payload sizes." },
  { name: "Current instruction", share: 6, note: "The next user intent that advances the recorded session." },
  { name: "Expected output", share: 5, note: "A recorded output-length target, not a copied completion." },
] as const;

export function RequestAnatomy() {
  const [active, setActive] = useState(0);
  return <div className="request-anatomy">
    <div className="request-layer-controls" role="group" aria-label="Request anatomy layers">
      {layers.map((layer, index) => <button key={layer.name} type="button" aria-pressed={active === index} onClick={() => setActive(index)}><span>{String(index + 1).padStart(2, "0")}</span>{layer.name}</button>)}
    </div>
    <figure aria-labelledby="request-anatomy-caption">
      <figcaption id="request-anatomy-caption"><strong>{layers[active].name}</strong><span>{layers[active].note}</span></figcaption>
      <div className="token-shape" aria-label="Anonymized token-shape bands">
        {layers.map((layer, index) => <i key={layer.name} className={active === index ? "active" : ""} style={{ flexGrow: layer.share }} title={`${layer.name}: illustrative relative shape`} />)}
      </div>
      <p>Illustrative shape only. No prompts, completions, tool schemas or payload excerpts are published.</p>
    </figure>
  </div>;
}
