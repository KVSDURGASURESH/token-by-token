type LoadSweeperProps = { loads: number[]; selected: number; baseline: number | null; pinned: boolean; onSelect(load: number): void; onPin(load: number | null): void };

export function LoadSweeper({ loads, selected, baseline, pinned, onSelect, onPin }: LoadSweeperProps) {
  const index = Math.max(0, loads.indexOf(selected));
  return <section className="instrument-sweeper" aria-label="Load sweeper">
    <header><div><span>CONTROL / MEASURED LOAD</span><h2>Move through the evidence</h2></div><p>Only recorded points are selectable. The instrument does not interpolate or generate new measurements.</p></header>
    <div className="sweeper-buttons" role="group" aria-label="Compare measured load">
      {loads.map((load, pointIndex) => <button key={load} type="button" aria-pressed={load === selected} onClick={() => onSelect(load)}><span>{String(pointIndex + 1).padStart(2, "0")}</span><b>{load}</b><small>users</small></button>)}
    </div>
    <label className="sweeper-range">Tested load
      <input type="range" min={0} max={loads.length - 1} step={1} value={index} aria-label="Tested load" aria-valuetext={`${selected} simulated users, measured level ${index + 1} of ${loads.length}`} onChange={event => onSelect(loads[Number(event.target.value)])} />
    </label>
    <div className="sweeper-pin">
      <span>Comparison basis</span>
      <strong>{baseline === null ? "No earlier measured point" : pinned ? `${baseline} users · pinned` : `${baseline} users · previous`}</strong>
      <button type="button" onClick={() => onPin(pinned ? null : selected)}>{pinned ? "Release pin" : "Pin current point"}</button>
    </div>
  </section>;
}
