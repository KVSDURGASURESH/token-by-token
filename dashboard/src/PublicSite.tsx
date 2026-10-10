import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import catalog from './data/site-v2/catalog.json';
import roadmapContext from './data/site-v2/roadmap-context.json';
import roadmapEvidence from './data/site-v2/roadmap-evidence.json';
import methodologySources from './data/site-v2/methodology-sources.json';
import episode0 from './data/site-v2/episode-0.json';
import episode1 from './data/site-v2/episode-1.json';
import episode0DataUrl from './data/site-v2/episode-0.json?url';
import episode1DataUrl from './data/site-v2/episode-1.json?url';
import episode0Telemetry from './data/site-v2/episode-0-telemetry.json';
import episode0TelemetryUrl from './data/site-v2/episode-0-telemetry.json?url';
import { applyTheme, getInitialTheme, type Theme } from './theme';
import { Analytics, trackAnalyticsEvent, useEngagementAnalytics } from './analytics';
import './public-site.css';

const CHAPTERS = ['brief', 'method', 'evidence', 'boundaries', 'source'] as const;
const GITHUB_URL = 'https://github.com/KVSDURGASURESH/token-by-token';
const GRAFANA_URL = import.meta.env.VITE_PUBLIC_GRAFANA_ENABLED === 'true' ? 'https://graph.endlesstokens.ai' : undefined;
const workloadIds = [...new Set(episode0.cells.map(cell => `${cell.input_tokens_min}-c${cell.concurrency}`))];
const measuredLoads = episode1.levels.map(Number);
const episodes = catalog.episodes;

type Route = { page: string; params: URLSearchParams; notices: string[] };
let normalizedNotice: { hash: string; messages: string[] } | null = null;
function readRoute(): Route {
  const [page, query] = location.hash.slice(1).split('?');
  const resolved = page === 'recorded-study' ? 'episode-0' : page === 'session-study' || page === 'field-notes' ? 'episodes' : page || 'episodes';
  const params = new URLSearchParams(query ?? '');
  const notices: string[] = [];
  const validMetric = resolved === 'episode-1' ? specs1.map(x => x.id) : resolved === 'episode-0' ? specs0.map(x => x.id) : [];
  const validChapter = resolved === 'methodology' ? ['process','definitions','states','identity','rules','protocols','sources'] : resolved === 'episodes' ? ['recorded','planned'] : [...CHAPTERS];
  for (const [key, allowed] of [['mode',['engines','loads']],['ch',validChapter],['metric',validMetric]] as [string,string[]][]) {
    if (params.has(key) && !allowed.includes(params.get(key)!)) { notices.push(`${key} is not available; showing the default.`); params.delete(key); }
  }
  if (params.has('depth') && !['brief','lab','ledger'].includes(params.get('depth')!)) { notices.push('depth is not available; showing the default.'); params.delete('depth'); }
  if (resolved !== 'episode-1') { params.delete('mode'); params.delete('base'); }
  const mode = params.get('mode') === 'loads' ? 'loads' : 'engines';
  const bases = mode === 'loads' ? measuredLoads.map(String) : ['vllm','sglang'];
  if (params.has('base') && !bases.includes(params.get('base')!)) { notices.push('baseline is not available; showing the default.'); params.delete('base'); }
  if (params.get('ch') && params.get('ch') !== 'brief' && (resolved === 'episode-0' || resolved === 'episode-1') && !['lab','ledger'].includes(params.get('depth') ?? '')) params.set('depth','lab');
  if (params.has('metric') && !['lab','ledger'].includes(params.get('depth') ?? '')) params.set('depth','lab');
  if (notices.length) normalizedNotice = { hash: url(resolved, params), messages: notices };
  else if (normalizedNotice?.hash === location.hash) notices.push(...normalizedNotice.messages);
  else normalizedNotice = null;
  return { page: resolved, params, notices };
}
function url(page: string, params: URLSearchParams) { const q = params.toString(); return `#${page}${q ? `?${q}` : ''}`; }
function format(value: number | null | undefined, unit: string, digits = 1) {
  if (value == null) return '—';
  return `${value.toLocaleString('en-US', { maximumFractionDigits: digits, minimumFractionDigits: digits })}${unit === '%' ? '%' : ` ${unit}`}`;
}
function decision(a: number | null | undefined, b: number | null | undefined, higher = true) {
  if (a == null || b == null || b === 0) return { symbol: '∅', text: 'No recorded comparison', kind: 'empty' };
  const delta = (a - b) / b * 100;
  if (Math.abs(delta) < 2) return { symbol: '≈', text: 'Within ±2% display band', kind: 'band' };
  const better = higher ? delta > 0 : delta < 0;
  return { symbol: better ? '✓' : '✕', text: `${Math.abs(delta).toFixed(1)}% ${better ? 'better' : 'worse'}`, kind: better ? 'better' : 'worse' };
}
function ChapterHeading({ number, title, id, heading }: { number: number; title: string; id: string; heading?: string }) {
  return <h2 id={`h-${id}`} tabIndex={-1} className="tbt-chapter-heading"><span className="tbt-chapter-label"><span aria-hidden="true" className="tbt-chapter-bar" />{String(number).padStart(2, '0')} {title}</span><span>{heading ?? title}</span></h2>;
}
function EpisodePager({ number }: { number: number }) {
  const previous = number > 0 ? episodes.find(episode => episode.number === number - 1) : null;
  const next = episodes.find(episode => episode.number === number + 1);
  return <nav className="tbt-pager" aria-label="Episode pager"><a className="previous" href={previous ? `#${previous.id}` : '#episodes'}><small>{previous ? `← Previous · Episode ${String(previous.number).padStart(2,'0')}` : '← Series'}</small><strong>{previous?.title ?? 'All episodes'}</strong></a>{next && <a className="next" href={`#${next.id}`}><small>Next · Episode {String(next.number).padStart(2,'0')} →</small><strong>{next.title}</strong></a>}</nav>;
}
function ExternalLinks() {
  return <div className="tbt-externals"><a href={GITHUB_URL} target="_blank" rel="noopener noreferrer" aria-label="Source on GitHub (opens in a new tab)"><svg aria-hidden="true" width="16" height="16" viewBox="0 0 16 16" fill="currentColor"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" /></svg>GitHub</a>{GRAFANA_URL && <a href={GRAFANA_URL} target="_blank" rel="noopener noreferrer" aria-label="Live Grafana dashboard, hosted separately (opens in a new tab)"><svg aria-hidden="true" width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4"><rect x="1.5" y="2" width="13" height="12" /><path d="M4 11V8.5M7 11V5.5M10 11V7M13 11V4" /></svg>Live dashboard <small aria-hidden="true">↗</small></a>}</div>;
}
function TokenStrip() {
  const tokens = ['Time', '·to', '·first', '·token', '·is', '·the', '·wait', '·a', '·user', '·feels.'];
  return <figure className="tbt-tokens"><div aria-hidden="true" className="tbt-token-row">{tokens.map((token, i) => <span data-token key={i}><b>{token}</b><small>t{String(i).padStart(2, '0')}</small></span>)}</div><figcaption><span><i className="first" />First token — TTFT</span><span><i className="later" />Every token after — TPOT</span></figcaption></figure>;
}
function EpisodeIndexRow({ episode, revealed = false }: { episode: (typeof episodes)[number]; revealed?: boolean }) {
  const [open, setOpen] = useState(revealed);
  const rowRef = useRef<HTMLDivElement>(null);
  const number = String(episode.number).padStart(2, '0');
  const contextId = `episode-context-${episode.id}`;
  useEffect(() => {
    if (!revealed) return;
    setOpen(true);
    requestAnimationFrame(() => rowRef.current?.scrollIntoView({ block: 'center' }));
  }, [revealed]);
  return <div ref={rowRef} className="tbt-index-row" data-episode-index-row={episode.id} data-expanded={open || undefined}>
    <div className="tbt-index-row-main">
      <b className="tbt-index-number">{number}</b>
      <span className="tbt-index-copy"><strong>{episode.title}</strong><small className="tbt-index-summary">{episode.summary}</small></span>
      <button type="button" className="tbt-index-disclosure" aria-expanded={open} aria-controls={contextId} aria-label={`${open ? 'Hide' : 'Show'} context for Episode ${number}`} onClick={() => setOpen(value => !value)}><span aria-hidden="true">{open ? '−' : '+'}</span></button>
    </div>
    {open && <div id={contextId} className="tbt-index-context">
      <p className="tbt-eyebrow">The experiment map</p>
      <p>{episode.status === 'planned' ? roadmapContext[episode.id as keyof typeof roadmapContext] : episode.summary}</p>
      {episode.status === 'planned' && <p className="tbt-index-evidence"><strong>Evidence:</strong> {roadmapEvidence[episode.id as keyof typeof roadmapEvidence]}</p>}
      {episode.status === 'available' ? <a href={`#${episode.id}`}>Open the recorded study →</a> : <a href={`${GITHUB_URL}/blob/main/docs/roadmap.md#${episode.roadmapAnchor}`} target="_blank" rel="noopener noreferrer">Read the experiment roadmap →</a>}
    </div>}
  </div>;
}
function Landing({ openEpisode }: { openEpisode?: string | null }) {
  const recorded = episodes.filter(e => e.status === 'available');
  const planned = episodes.filter(e => e.status === 'planned');
  return <article className="tbt-landing"><header data-screen-label="Landing" className="tbt-hero"><p className="tbt-eyebrow">Token by Token · an open inference lab</p><h1 id="page-title">Every <span data-landing-token-accent>token</span> is a measurement.</h1><p className="tbt-deck">We run open model-serving engines under recorded load and read the results one claim at a time — what a user waits for, what the hardware does, and where the evidence stops.</p><TokenStrip /><div className="tbt-cta"><a className="primary" href="#episode-0">Start with Episode 00 →</a><a className="secondary" href="#episode-1">Episode 01 · Measure what matters</a><a className="tertiary" href="#methodology">How the lab measures</a></div><p className="tbt-counts"><span>{recorded.length} recorded episodes</span><span>{planned.length} planned</span></p></header><section id="ch-recorded" className="tbt-index-group"><h2 id="h-recorded" tabIndex={-1}>01 Recorded</h2>{recorded.map(episode => <EpisodeIndexRow key={episode.id} episode={episode} revealed={openEpisode === episode.id} />)}</section><section id="ch-planned" className="tbt-index-group"><h2 id="h-planned" tabIndex={-1}>02 Planned</h2>{planned.map(episode => <EpisodeIndexRow key={episode.id} episode={episode} revealed={openEpisode === episode.id} />)}</section></article>;
}
function Selector({ episode, value, select }: { episode: 0 | 1; value: string; select(v: string, replace?: boolean): void }) {
  const stripRef = useRef<HTMLDivElement>(null);
  const trackRef = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);
  const lastWheelSnap = useRef(0);
  const [motion, setMotion] = useState(false);
  useLayoutEffect(() => { if (episode !== 0) return; const strip = stripRef.current; const card = strip?.querySelector<HTMLElement>(`[data-val="${value}"]`); if (strip && card) strip.scrollTo({ left: card.offsetLeft - (strip.clientWidth - card.offsetWidth) / 2, behavior: motion && !matchMedia('(prefers-reduced-motion: reduce)').matches ? 'smooth' : 'instant' }); setMotion(true); }, [episode, value]);
  const options = episode === 1 ? measuredLoads.map(String) : workloadIds;
  const index = options.indexOf(value);
  function move(next: number) { const bounded = Math.max(0, Math.min(options.length - 1, next)); select(options[bounded]); requestAnimationFrame(() => document.querySelector<HTMLElement>(`[data-seg="${episode === 1 ? 'load' : 'wl'}"][data-val="${options[bounded]}"]`)?.focus()); }
  function key(event: React.KeyboardEvent) { let next = index; if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next++; else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') next--; else if (event.key === 'Home') next = 0; else if (event.key === 'End') next = options.length - 1; else return; event.preventDefault(); move(next); }
  const point = (v: number) => `${(measuredLoads.indexOf(v) / Math.max(1, measuredLoads.length - 1)) * 100}%`;
  function snap(event: React.PointerEvent<HTMLDivElement>, replace: boolean, force = false) { const rect = event.currentTarget.getBoundingClientRect(); const ratio = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)); const nearest = measuredLoads[Math.round(ratio * (measuredLoads.length - 1))]; if (force || String(nearest) !== value) select(String(nearest), replace); }
  useEffect(() => {
    if (episode !== 1) return;
    const track = trackRef.current;
    if (!track) return;
    const handleWheel = (event: WheelEvent) => {
      const delta = Math.abs(event.deltaY) >= Math.abs(event.deltaX) ? event.deltaY : event.deltaX;
      if (Math.abs(delta) < 12) return;
      event.preventDefault();
      const now = performance.now();
      if (lastWheelSnap.current && now - lastWheelSnap.current < 180) return;
      lastWheelSnap.current = now;
      move(index + (delta > 0 ? 1 : -1));
    };
    track.addEventListener('wheel', handleWheel, { passive: false });
    return () => track.removeEventListener('wheel', handleWheel);
  }, [episode, index, select]);
  return <div data-screen-label="Selector" className="tbt-selector"><span id="sel-label" className="tbt-eyebrow">{episode === 1 ? 'Selected measured load' : 'Recorded workload'}</span>{episode === 1 ? <div role="group" aria-labelledby="sel-label" data-track ref={trackRef} onKeyDown={key} onPointerDown={event => { if ((event.target as HTMLElement).closest('button')) return; dragging.current = true; snap(event, false, true); event.currentTarget.setPointerCapture(event.pointerId); }} onPointerMove={event => { if (dragging.current) snap(event, true); }} onPointerUp={event => { dragging.current = false; if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId); }} onPointerCancel={() => { dragging.current = false; }} className="tbt-track"><div className="tbt-track-rail" /><div className="tbt-track-fill" style={{ left: point(measuredLoads[0]), width: point(Number(value)) }} />{measuredLoads.map(v => <button key={v} type="button" data-seg="load" data-val={v} aria-pressed={String(v) === value} tabIndex={String(v) === value ? 0 : -1} onClick={() => select(String(v))} style={{ left: point(v) }}><i /><b>{v}</b><small>Users</small></button>)}<div className="tbt-thumb" aria-hidden="true" style={{ left: point(Number(value)) }} /></div> : <div className="tbt-workload-shell"><div data-workload-guide className="tbt-workload-guide"><div data-workload-cue className="tbt-workload-cue"><span aria-hidden="true">↔</span><span><b>{index + 1} of {options.length} workloads</b><em>Scroll or drag · use arrows · select a workload</em></span><span data-cue-pointer aria-hidden="true">↓</span></div><div role="progressbar" aria-label="Selected workload" aria-valuemin={1} aria-valuemax={options.length} aria-valuenow={index + 1}><i style={{ width: `${(index + 1) / options.length * 100}%` }} /></div></div><div className={`tbt-workload-wrap ${index > 0 ? 'can-prev' : ''} ${index < options.length - 1 ? 'can-next' : ''}`}><button type="button" aria-label="Previous workload" disabled={index === 0} onClick={() => move(index - 1)}>←</button><div role="group" aria-labelledby="sel-label" aria-describedby="workload-note" data-strip ref={stripRef} onKeyDown={key} className="tbt-workload-strip">{workloadIds.map((id, i) => { const [input, concurrent] = id.split('-c').map(Number); const cells = episode0.cells.filter(c => c.input_tokens_min === input && c.concurrency === concurrent); const unequal = cells.length === 2 && Math.abs(cells[0].successful_output_tokens / cells[0].successful_requests - cells[1].successful_output_tokens / cells[1].successful_requests) > 1e-9; return <button type="button" key={id} data-seg="wl" data-val={id} aria-pressed={id === value} tabIndex={id === value ? 0 : -1} onClick={() => select(id)}><small>{i % 2 ? 'Stress' : 'Baseline'} · {i + 1} of 6</small><b>{input.toLocaleString()}-token input</b><small>{concurrent} concurrent request{concurrent === 1 ? '' : 's'}</small><small>{unequal ? '≠ unequal work — not compared' : '= equal work'}</small></button>; })}</div><button type="button" aria-label="Next workload" disabled={index === options.length - 1} onClick={() => move(index + 1)}>→</button></div></div>}<span id="workload-note" className="tbt-selector-note">{episode === 1 ? 'Scroll over the rail to move to the next recorded load. You can also drag, tap or use ← →; the dashed rail between points was never measured.' : 'Input length and concurrency change together. These are six separate workloads, not a sweep.'}</span></div>;
}
const specs1 = [
  { id: 'output_tps', title: 'Output throughput', unit: 'tok/s', higher: true },
  { id: 'ttft_p50_ms', title: 'TTFT p50', unit: 'ms', higher: false },
  { id: 'ttft_p95_ms', title: 'TTFT p95', unit: 'ms', higher: false },
  { id: 'tpot_p50_ms', title: 'TPOT p50', unit: 'ms/token', higher: false },
  { id: 'decode_p10_tps', title: 'Decode p10', unit: 'tok/s', higher: true },
  { id: 'error_rate_pct', title: 'Error rate', unit: '%', higher: false },
  { id: 'running_requests_mean', title: 'Running requests', unit: 'req', higher: false },
  { id: 'waiting_requests_mean', title: 'Waiting requests', unit: 'req', higher: false },
  { id: 'gpu_utilization_pct', title: 'GPU utilization', unit: '%', higher: false },
  { id: 'gpu_power_w', title: 'GPU board power', unit: 'W', higher: false },
  { id: 'gpu_memory_gib', title: 'Maximum sampled GPU memory', unit: 'GiB', higher: false },
];
const specs0 = [
  { id: 'output_tokens_per_second', title: 'Delivered output rate', unit: 'tok/s', higher: true },
  { id: 'client_ttft_ms', title: 'TTFT p50', unit: 'ms', higher: false },
  { id: 'client_tpot_ms', title: 'TPOT p50', unit: 'ms/token', higher: false },
  { id: 'client_e2e_ms', title: 'End-to-end p50', unit: 'ms', higher: false },
  { id: 'client_itl_ms', title: 'Client inter-chunk latency p50', unit: 'ms', higher: false },
  { id: 'work_per_request', title: 'Delivered output per request', unit: 'tok/req', higher: true },
];
function readings(episode: 0 | 1, value: string) {
  if (episode === 1) return episode1.arms.map(arm => ({ name: arm.engine, values: Object.fromEntries(Object.entries(arm.points.find(p => p.users === Number(value))?.readings ?? {}).map(([key, reading]) => [key, reading.value])) as Record<string, number | null> }));
  const [input, concurrency] = value.split('-c').map(Number);
  return ['vLLM', 'SGLang'].map(name => { const cell = episode0.cells.find(c => c.runtime === name && c.input_tokens_min === input && c.concurrency === concurrency); return { name, values: { output_tokens_per_second: cell?.output_tokens_per_second ?? null, client_ttft_ms: cell?.client_ttft_ms.p50 ?? null, client_tpot_ms: cell?.client_tpot_ms.p50 ?? null, client_e2e_ms: cell?.client_e2e_ms.p50 ?? null, client_itl_ms: cell?.client_itl_ms.p50 ?? null, work_per_request: cell ? cell.successful_output_tokens / cell.successful_requests : null } as Record<string, number | null> }; });
}
function PlotPoint({ x, y, shape, label, show, hide }: { x: number; y: number; shape: 'circle' | 'diamond'; label: string; show(label: string): void; hide(): void }) {
  return <g data-plot-point tabIndex={0} role="img" aria-label={label} onFocus={() => show(label)} onBlur={hide} onMouseEnter={() => show(label)} onMouseLeave={hide}>
    {shape === 'circle' ? <circle cx={x} cy={y} r="3" fill="var(--paper)" stroke="var(--ink)" strokeWidth="1.5" /> : <rect x={x - 3} y={y - 3} width="6" height="6" transform={`rotate(45 ${x} ${y})`} fill="var(--paper)" stroke="var(--muted)" strokeWidth="1.5" />}
  </g>;
}
function MetricPlot({ episode, metric, selected, mode, baseline }: { episode: 0 | 1; metric: string; selected: string; mode?: string; baseline?: string }) {
  const [activePoint, setActivePoint] = useState<string | null>(null);
  const xs = episode === 1 ? measuredLoads.map(String) : workloadIds;
  const series = xs.map(x => readings(episode, x));
  const threshold = metric === 'decode_p10_tps' ? 20 : metric === 'error_rate_pct' ? 1 : null;
  const selectedRows = readings(episode, selected);
  const referenceRows = episode === 1 && mode === 'engines' ? selectedRows.filter(row => row.name.toLowerCase() === (baseline === 'sglang' ? 'sglang' : 'vllm')) : [];
  const references = threshold == null ? referenceRows.map(row => ({ name: `${row.name} baseline`, value: row.values[metric] })).filter((row): row is { name: string; value: number } => row.value != null) : [{ name: `Declared ${metric === 'error_rate_pct' ? '1% limit' : '20 tok/s floor'}`, value: threshold }];
  const values = [...series.flatMap(pair => pair.map(row => row.values[metric])), ...references.map(row => row.value)].filter((v): v is number => v != null);
  const max = Math.max(1, ...values) * 1.15;
  const x = (i: number) => 18 + (i + .5) * 244 / xs.length;
  const y = (v: number) => 80 - v / max * 68;
  const path = (identity: number) => series.map((pair, i) => pair[identity].values[metric] == null ? '' : `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)} ${y(pair[identity].values[metric]!).toFixed(1)}`).join(' ');
  const spec = (episode === 1 ? specs1 : specs0).find(item => item.id === metric)!;
  return <><div data-plot-tooltip data-visible={Boolean(activePoint)} aria-live="polite" className="tbt-plot-tooltip">{activePoint ?? 'Focus or point to a marker for its exact recorded value.'}</div><svg data-plot viewBox="0 0 280 108" role="group" aria-label={`${spec.title} across recorded ${episode === 1 ? 'loads' : 'workloads'}`}><rect x={18 + xs.indexOf(selected) * 244 / xs.length} y="0" width={244 / xs.length} height="88" fill="var(--panel)" /><line x1="18" x2="262" y1="88" y2="88" stroke="var(--line-strong)" />{episode === 1 && mode === 'loads' && baseline && <line data-reference="Selected baseline load" x1={x(xs.indexOf(baseline))} x2={x(xs.indexOf(baseline))} y1="8" y2="88" stroke="var(--neutral)" strokeDasharray="3 3" aria-label={`${baseline} users: selected baseline load for both engines`} />}{references.map(reference => <line key={reference.name} data-reference={reference.name} x1="18" x2="262" y1={y(reference.value)} y2={y(reference.value)} stroke="var(--neutral)" strokeDasharray="3 3" aria-label={`${reference.name}: ${reference.value}`} />)}{episode === 1 && <><path d={path(0)} fill="none" stroke="var(--ink)" strokeWidth="1.5" /><path d={path(1)} fill="none" stroke="var(--muted)" strokeWidth="1.5" strokeDasharray="5 4" /></>}{series.flatMap((pair,i) => pair.map((row,k) => { const v = row.values[metric]; if (v == null) return null; const workload = episode === 1 ? `${xs[i]} users` : `${Number(xs[i].split('-c')[0]).toLocaleString()}-token input · ${xs[i].split('-c')[1]} concurrent requests`; const label = `${row.name} · ${workload} · ${spec.title}: ${format(v, spec.unit)}`; return <PlotPoint key={`${i}-${k}`} x={x(i) + (episode === 0 ? k === 0 ? -4 : 4 : 0)} y={y(v)} shape={k === 0 ? 'circle' : 'diamond'} label={label} show={setActivePoint} hide={() => setActivePoint(null)} />; }))}{xs.map((val,i) => <text key={val} x={x(i)} y="99" textAnchor="middle" fill="var(--muted)" fontSize="8">{episode === 1 ? val : <><tspan x={x(i)}>{Number(val.split('-c')[0]).toLocaleString()}</tspan><tspan x={x(i)} dy="8">c{val.split('-c')[1]}</tspan></>}</text>)}</svg></>;
}
function comparisonOptions(mode: 'engines' | 'loads', selected: string) { return mode === 'loads' ? measuredLoads.map(String).filter(load => load !== selected) : ['vllm', 'sglang']; }
function comparisonBaseline(mode: 'engines' | 'loads', selected: string, requested: string | null) { const options = comparisonOptions(mode, selected); return requested && options.includes(requested) ? requested : options[0]; }
function EvidenceControls({ route, selected, setParam }: { route: Route; selected: string; setParam(key: string, value: string, replace?: boolean): void }) {
  const mode = route.params.get('mode') === 'loads' ? 'loads' : 'engines';
  const baseOptions = comparisonOptions(mode, selected);
  const visibleBaseOptions = mode === 'loads' ? measuredLoads.map(String) : baseOptions;
  const requested = route.params.get('base');
  const baseline = comparisonBaseline(mode, selected, requested);
  function key(event: React.KeyboardEvent<HTMLDivElement>, options: string[], current: string, pick: (v: string) => void, segment: string) {
    const i = options.indexOf(current);
    const j = event.key === 'Home' ? 0 : event.key === 'End' ? options.length - 1 : event.key === 'ArrowRight' || event.key === 'ArrowDown' ? Math.min(options.length - 1, i + 1) : event.key === 'ArrowLeft' || event.key === 'ArrowUp' ? Math.max(0, i - 1) : -1;
    if (j < 0) return;
    event.preventDefault(); pick(options[j]); requestAnimationFrame(() => document.querySelector<HTMLElement>(`[data-seg="${segment}"][data-val="${options[j]}"]`)?.focus());
  }
  return <div className="tbt-compare-controls"><div><span id="mode-label" className="tbt-eyebrow">Comparison</span><div role="group" aria-labelledby="mode-label" onKeyDown={event => key(event, ['engines', 'loads'], mode, v => setParam('mode', v), 'mode')}>{[['engines','Engines at this load'],['loads','Loads within each engine']].map(([v,label]) => <button key={v} type="button" data-seg="mode" data-val={v} aria-pressed={mode === v} tabIndex={mode === v ? 0 : -1} onClick={() => setParam('mode', v)}>{label}</button>)}</div></div><div><span id="base-label" className="tbt-eyebrow">{mode === 'loads' ? 'Reference load' : 'Baseline engine'}</span><div role="group" aria-labelledby="base-label" onKeyDown={event => key(event, baseOptions, baseline, v => setParam('base', v), 'base')}>{visibleBaseOptions.map(v => { const isSelectedLoad = mode === 'loads' && v === selected; return <button key={v} type="button" data-seg="base" data-val={v} disabled={isSelectedLoad} aria-disabled={isSelectedLoad || undefined} aria-pressed={!isSelectedLoad && baseline === v} tabIndex={!isSelectedLoad && baseline === v ? 0 : -1} onClick={() => setParam('base', v)}>{v === 'vllm' ? 'vLLM' : v === 'sglang' ? 'SGLang' : <>{v}{isSelectedLoad && <small>Selected</small>}</>}</button>; })}</div></div><p>Operands: {mode === 'loads' ? `Selected load: ${selected} users. Reference load: ${baseline} users. Each engine is compared with itself across those two recorded loads.` : `${baseline === 'vllm' ? 'SGLang' : 'vLLM'} is the subject and ${baseline === 'vllm' ? 'vLLM' : 'SGLang'} is the baseline, both at ${selected} users.`}</p></div>;
}
type MetricSpec = { id: string; title: string; unit: string; higher: boolean };
const evidenceNotes: Record<string, string> = {
  output_tokens_per_second: 'Rate rises with concurrency, but delivered output per request must match before ranking.',
  client_ttft_ms: 'Input length and concurrency change together, so first-token time cannot be attributed to either alone.',
  client_tpot_ms: 'Per-token time describes the visible stream after its first token.',
  client_e2e_ms: 'End-to-end time includes waiting and decoding, so it is not the same as TTFT.',
  client_itl_ms: 'Client inter-chunk latency describes gaps between streamed chunks; one chunk may contain multiple tokens.',
  work_per_request: 'Equal delivered work is required before throughput and latency are compared.',
  output_tps: 'Output throughput is measured across valid output tokens in the selected window.',
  ttft_p50_ms: 'Median client-visible first-token wait rises with load.',
  ttft_p95_ms: 'The tail first-token wait may move differently from the median.',
  tpot_p50_ms: 'Time per output token after the first token rises with load.',
  decode_p10_tps: 'The declared experience floor is 20 tok/s.',
  error_rate_pct: 'The declared validity limit is 1%.',
  running_requests_mean: 'Runtime-native running requests are context, not a cross-engine ranking.',
  waiting_requests_mean: 'Runtime-native waiting requests are context, not a cross-engine ranking.',
  gpu_utilization_pct: 'Device utilization is sampled over the measured window.',
  gpu_power_w: 'Board power is sampled over the measured window.',
  gpu_memory_gib: 'Maximum sampled GPU memory is a contextual device reading, not a per-request allocation.'
};
function EvidenceChapter({ episode, value, route, setParam }: { episode: 0 | 1; value: string; route: Route; setParam(key: string, value: string, replace?: boolean): void }) {
  const [windowWidth, setWindowWidth] = useState(innerWidth);
  useEffect(() => { const update = () => setWindowWidth(innerWidth); addEventListener('resize', update); return () => removeEventListener('resize', update); }, []);
  const mainWidth = windowWidth >= 981 ? Math.min(1040, windowWidth - 348) : windowWidth - 32;
  const columns = mainWidth >= 860 ? 3 : mainWidth >= 520 ? 2 : 1;
  const rows = readings(episode, value);
  const mode = route.params.get('mode') === 'loads' ? 'loads' : 'engines';
  const requestedBase = route.params.get('base');
  const baseline = comparisonBaseline(mode, value, requestedBase);
  const metrics = episode === 1 ? specs1 : specs0;
  const groups = episode === 1 ? [
    { title: 'Directional comparisons', note: 'Symbol and colour show the change in each metric’s better direction.', metrics: metrics.slice(0, 4) },
    { title: 'Declared thresholds', note: 'Met or missed is judged against the declared threshold, never against the other engine.', metrics: metrics.slice(4, 6) },
    { title: 'Context only', note: 'Engine and device readings describe the setting. They are not ranked.', metrics: metrics.slice(6) }
  ] : [
    { title: 'Directional comparisons', note: 'Six categorical workloads. Points are not joined: there is no sweep between them.', metrics: metrics.slice(0, 4) },
    { title: 'Delivered work', note: 'The equal-work check that gates every comparison above.', metrics: [metrics[5]] }
  ];
  const [input, concurrency] = value.split('-c').map(Number);
  const cells = episode === 0 ? episode0.cells.filter(c => c.input_tokens_min === input && c.concurrency === concurrency) : [];
  const equalWork = episode === 1 || cells.length === 2 && Math.abs(cells[0].successful_output_tokens / cells[0].successful_requests - cells[1].successful_output_tokens / cells[1].successful_requests) < 1e-9;
  const requestedMetric = route.params.get('metric');
  const directionalIds = groups[0].metrics.map(spec => spec.id);
  const selectedMetric = requestedMetric && !directionalIds.includes(requestedMetric) ? requestedMetric : null;
  const explanationOpen = requestedMetric && metrics.some(spec => spec.id === requestedMetric) ? requestedMetric : '';
  const evidenceTitle = episode === 1 ? mode === 'loads' ? `Loads compared with ${baseline} users` : `Engines at ${value} users` : `${input.toLocaleString()}-token input · ${concurrency} concurrent`;
  const lede = episode === 1 ? mode === 'loads' ? baseline === value ? 'The baseline equals the selected load, so there is no change to report. Choose another baseline, or move the measured load.' : `Each engine at ${value} users relative to itself at ${baseline} users. The engines are not compared with each other in this mode.` : `${baseline === 'vllm' ? 'SGLang' : 'vLLM'} relative to ${baseline === 'vllm' ? 'vLLM' : 'SGLang'} for the selected load only.` : equalWork ? 'SGLang relative to vLLM for the selected workload only. Workloads are never compared with each other.' : 'This workload delivered unequal work, so values are shown without better or worse. Every other workload remains selectable above.';
  const operands = episode === 1 ? mode === 'loads' ? `Directional operands: vLLM at ${value} users versus vLLM at ${baseline} users, and SGLang at ${value} users versus SGLang at ${baseline} users. Each engine is compared only with itself.` : `Directional operands: ${baseline === 'vllm' ? 'SGLang' : 'vLLM'} (subject) versus ${baseline === 'vllm' ? 'vLLM' : 'SGLang'} (baseline), both at ${value} users.` : `Directional operands: SGLang (subject) versus vLLM (baseline) at the ${input.toLocaleString()}-token, ${concurrency}-concurrent workload${equalWork ? ', after the equal delivered-work gate.' : '; unequal delivered work blocks ranking.'}`;
  function metricStates(spec: MetricSpec) {
    const a = rows[0].values[spec.id], b = rows[1].values[spec.id];
    if (spec.id === 'work_per_request') return [{ symbol: equalWork ? '=' : '≠', text: equalWork ? 'Equal delivered work' : 'Unequal work — not compared', kind: equalWork ? 'equal' : 'band' }];
    if (episode === 1 && (spec.id === 'decode_p10_tps' || spec.id === 'error_rate_pct')) return rows.map(row => { const v = row.values[spec.id]; const good = v != null && (spec.id === 'decode_p10_tps' ? v >= 20 : v <= 1); return { symbol: v == null ? '∅' : good ? spec.id === 'decode_p10_tps' ? '≥' : '≤' : spec.id === 'decode_p10_tps' ? '<' : '>', text: `${row.name} · ${v == null ? 'No recorded value' : good ? spec.id === 'decode_p10_tps' ? 'Meets 20 tok/s floor' : 'Within 1% validity limit' : spec.id === 'decode_p10_tps' ? 'Below 20 tok/s floor' : 'Over 1% validity limit'}`, kind: v == null ? 'empty' : good ? 'better' : 'worse' }; });
    if (episode === 1 && metrics.indexOf(spec) >= 6) return rows.map(row => ({ symbol: '△', text: `${row.name} · Context only — not ranked`, kind: 'context' }));
    if (!equalWork) return [{ symbol: '≠', text: 'Unequal work — not compared', kind: 'band' }];
    if (episode === 1 && mode === 'loads') return rows.map(row => baseline === value ? { symbol: '∅', text: `${row.name} · No change computed`, kind: 'empty' } : { ...decision(row.values[spec.id], readings(1, baseline).find(baselineRow => baselineRow.name === row.name)?.values[spec.id], spec.higher), name: row.name, text: `${row.name} · ${decision(row.values[spec.id], readings(1, baseline).find(baselineRow => baselineRow.name === row.name)?.values[spec.id], spec.higher).text}` });
    return [decision(baseline === 'sglang' && episode === 1 ? a : b, baseline === 'sglang' && episode === 1 ? b : a, spec.higher)];
  }
  function metricView(spec: MetricSpec) {
    const states = metricStates(spec);
    const context = episode === 1 && metrics.indexOf(spec) >= 6;
    const subjectIndex = episode === 1 && mode === 'engines' && baseline === 'sglang' ? 0 : 1;
    const ranked = !context && equalWork && spec.id !== 'work_per_request' && spec.id !== 'decode_p10_tps' && spec.id !== 'error_rate_pct';
    const selectedState = states[0]?.kind;
    const direction = spec.id === 'work_per_request' ? 'Equal work required' : context ? 'Context only' : spec.id === 'decode_p10_tps' ? 'Floor ≥ 20 tok/s' : spec.id === 'error_rate_pct' ? 'Limit ≤ 1%' : spec.higher ? 'Higher is better' : 'Lower is better';
    return <><span className="tbt-plot-header"><b>{spec.title}</b><small>{direction}</small></span><MetricPlot episode={episode} metric={spec.id} selected={value} mode={mode} baseline={baseline} /><span className="tbt-plot-values">{rows.map((row,i) => <span data-plot-value key={row.name}><span aria-hidden="true">{i===0?'●':'◆'}</span> {row.name} <b className={ranked && (mode === 'loads' || i === subjectIndex) ? `state-${mode === 'loads' ? states[i]?.kind : selectedState}` : ''}>{format(row.values[spec.id],spec.unit)}</b></span>)}</span><span className="tbt-plot-states">{states.map((state,i) => <span key={i} className={`state-${state.kind}`}>{state.symbol} {state.text}</span>)}</span><span className="tbt-plot-notice">{evidenceNotes[spec.id]}</span></>;
  }
  function card(spec: MetricSpec) { if (spec.id === directionalIds[0]) return directionalWorkbench; if (directionalIds.includes(spec.id)) return null; const expanded = selectedMetric === spec.id; return <div data-metric={spec.id} data-expanded={expanded} className="tbt-plot-card">{metricView(spec)}<button type="button" data-metric-toggle={spec.id} className="tbt-explain-affordance" aria-expanded={expanded} aria-controls={`ex-${spec.id}`} onClick={() => setParam('metric', expanded ? '' : spec.id, true)}><span>{expanded ? 'Close explanation' : 'Open explanation'}</span><b aria-hidden="true">{expanded ? '−' : '+'}</b></button></div>; }
  function explanation(spec: MetricSpec) {
    const definition = episode === 1 ? episode1.metric_definitions.find(m => m.id === spec.id)?.explanation : evidenceNotes[spec.id];
    const kind = spec.id === 'work_per_request' ? 'Delivered work equality gate' : spec.id === 'decode_p10_tps' || spec.id === 'error_rate_pct' ? 'Declared threshold for each engine' : episode === 1 && specs1.indexOf(spec) >= 6 ? 'Context only — not ranked' : 'Directional comparison';
    const rule = spec.id === 'work_per_request' ? 'Equal delivered output per successful request is required before throughput and latency can be ranked.' : spec.id === 'decode_p10_tps' ? 'Each engine is judged against the declared 20 tok/s decode floor.' : spec.id === 'error_rate_pct' ? 'Each engine is judged against the declared 1% validity limit.' : kind.startsWith('Context') ? 'These runtime or device readings describe conditions and have no better direction.' : `${spec.higher ? 'Higher' : 'Lower'} is better. Changes under ±2% are shown in a descriptive display band, not a significance test.`;
    const states = metricStates(spec);
    const metricOperands = spec.id === 'work_per_request' ? `Equality operands: SGLang and vLLM delivered output per successful request at the ${input.toLocaleString()}-token, ${concurrency}-concurrent workload. Equality gates the directional comparisons.` : spec.id === 'decode_p10_tps' ? `Threshold operands at ${value} users: each engine’s decode p10 versus Episode 01’s declared 20 tok/s floor; engines are not compared with each other for this gate.` : spec.id === 'error_rate_pct' ? `Threshold operands at ${value} users: each engine’s error rate versus Episode 01’s declared 1% limit; engines are not compared with each other for this gate.` : kind.startsWith('Context') ? `Context at ${value} users: vLLM and SGLang values are shown by identity without ranking.` : operands;
    return <div id={`ex-${spec.id}`} role="region" aria-label={`Explanation: ${spec.title}`} className="tbt-explanation-row"><div><small>Explaining</small><h4>{spec.title}</h4><p>{definition}</p><dl><dt>Evidence kind</dt><dd>{kind}</dd><dt>Rule</dt><dd>{rule}</dd><dt>Unit</dt><dd>{spec.unit}</dd><dt>Source</dt><dd>{episode === 1 ? 'Public aggregate evidence' : spec.id === 'work_per_request' ? 'Client results' : 'Client stream events'}</dd></dl></div><div><small>Comparison</small><p>{metricOperands}</p><small>Selected states</small>{states.map((state,i) => <p key={i} className={`state-${state.kind}`}>{state.symbol} {state.text}</p>)}<small>What to notice</small><p>{evidenceNotes[spec.id]}</p></div><div><small>Exact recorded values</small><div className="tbt-ledger"><table><thead><tr><th>Identity</th>{(episode === 1 ? measuredLoads.map(String) : workloadIds).map(x => <th key={x}>{episode === 1 ? `${x} users` : x}</th>)}</tr></thead><tbody>{['vLLM','SGLang'].map(name => <tr key={name}><th>{name}</th>{(episode === 1 ? measuredLoads.map(String) : workloadIds).map(x => <td key={x} className={x === value ? 'selected' : ''}>{format(readings(episode,x).find(row => row.name === name)?.values[spec.id],spec.unit)}</td>)}</tr>)}</tbody></table></div><button type="button" onClick={() => { setParam('metric','',true); requestAnimationFrame(() => document.querySelector<HTMLElement>(`[data-metric-toggle="${spec.id}"]`)?.focus()); }}>Close explanation</button></div><p data-viz-note className="tbt-viz-note">For a roomier visualization, {GRAFANA_URL ? <><a href={GRAFANA_URL} target="_blank" rel="noopener noreferrer">open the Grafana dashboard</a> from the top navigation.</> : <>use the Grafana dashboard link in the top navigation when available.</>}</p></div>;
  }
  const directional = groups[0];
  const activeDirectional = directional.metrics.find(spec => spec.id === requestedMetric) ?? directional.metrics[0];
  function pickDirectional(spec: MetricSpec) { setParam('metric', spec.id, true); requestAnimationFrame(() => document.querySelector<HTMLElement>(`[data-metric-tab="${spec.id}"]`)?.focus()); }
  function directionalKey(event: React.KeyboardEvent<HTMLDivElement>) {
    const index = directional.metrics.indexOf(activeDirectional);
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? directional.metrics.length - 1 : event.key === 'ArrowDown' || event.key === 'ArrowRight' ? Math.min(directional.metrics.length - 1, index + 1) : event.key === 'ArrowUp' || event.key === 'ArrowLeft' ? Math.max(0, index - 1) : -1;
    if (next < 0) return;
    event.preventDefault(); pickDirectional(directional.metrics[next]);
  }
  const observedSignals = episode === 1 ? (() => {
    const vllm = rows.find(row => row.name === 'vLLM')!;
    const sglang = rows.find(row => row.name === 'SGLang')!;
    const tailSpec = metrics.find(spec => spec.id === 'ttft_p95_ms')!;
    const tailStates = metricStates(tailSpec);
    return <aside data-observed-signals className="tbt-observed-signals" aria-label="Recorded signals that caught our eye"><div><small>Tail latency</small><strong>TTFT p95</strong>{tailStates.map((tail, i) => <span key={i} className={`state-${tail.kind}`}>{tail.symbol} {tail.text}</span>)}</div><div><small>Queueing signal</small><strong>Waiting requests</strong><span>{format(sglang.values.waiting_requests_mean,'req',2)} SGLang · {format(vllm.values.waiting_requests_mean,'req',2)} vLLM</span><em>At the selected load · context only — runtime-native gauges are not ranked across engines.</em></div></aside>;
  })() : null;
  const directionalWorkbench = <div data-metric-workbench data-focused={Boolean(explanationOpen && directionalIds.includes(explanationOpen))} className="tbt-metric-workbench">{observedSignals}<div role="tablist" aria-label="Directional metrics" className="tbt-metric-tabs" onKeyDown={directionalKey}>{directional.metrics.map(spec => { const state = metricStates(spec)[0]; const active = spec.id === activeDirectional.id; return <button id={`metric-tab-${spec.id}`} key={spec.id} type="button" role="tab" data-metric-tab={spec.id} aria-selected={active} aria-controls="directional-metric-panel" tabIndex={active ? 0 : -1} onClick={() => pickDirectional(spec)}>{active && <i data-active-wedge aria-hidden="true" />}<span>{spec.title}{spec.id === 'ttft_p95_ms' && <small>Tail</small>}{active && <small className="tbt-showing">Showing →</small>}</span><b className={`state-${state?.kind}`}>{state?.symbol} {state?.text}</b></button>; })}</div><div id="directional-metric-panel" role="tabpanel" aria-label={`${activeDirectional.title} details`} aria-labelledby={`metric-tab-${activeDirectional.id}`} className="tbt-metric-panel"><div data-selected-metric={activeDirectional.id} className="tbt-plot-card tbt-selected-plot">{metricView(activeDirectional)}</div>{explanation(activeDirectional)}</div></div>;
  return <section id="ch-evidence" data-screen-label="03 Evidence" data-explanation-open={explanationOpen || undefined} className="tbt-chapter"><ChapterHeading number={3} title="Evidence" heading={evidenceTitle} id="evidence" /><p>{lede}</p>{episode === 1 && <EvidenceControls route={route} selected={value} setParam={setParam} />}<p className="tbt-operands">{operands}</p><div data-identity-legend className="tbt-identity-legend"><span>● ── vLLM</span><span>◆ ╌╌ SGLang</span><span>Shaded column — selected load · vertical dashed rule — baseline load · horizontal dashed rule — baseline engine value or declared threshold</span></div>{groups.map(group => <div data-evidence-group key={group.title} className="tbt-evidence-group"><h3><span>{group.title}</span><small>{group.note}</small></h3>{Array.from({length:Math.ceil(group.metrics.length / columns)},(_,i) => { const segment = group.metrics.slice(i*columns,(i+1)*columns); const opened = segment.find(spec => spec.id === selectedMetric); return <div key={i}><div className="tbt-plot-row" style={{gridTemplateColumns:`repeat(${columns},minmax(0,1fr))`}}>{segment.map(spec => <div key={spec.id}>{card(spec)}</div>)}</div>{opened && explanation(opened)}</div>; })}</div>)}{episode === 0 && <><div data-workload-telemetry className="tbt-evidence-group"><h3><span>Workload-level telemetry</span><small>For the selected workload. Medians of repetition-level readings; definitions are runtime-native.</small></h3><div className="tbt-ledger"><table><thead><tr><th>Reading · context only</th><th>● vLLM</th><th>◆ SGLang</th></tr></thead><tbody>{(() => { const t = episode0Telemetry.workloads.find(x => x.id === value); return t ? <><tr><th>KV cache peak</th><td>{format(t.engines.vLLM.kv_cache_peak*100,'%')}</td><td>{format(t.engines.SGLang.kv_cache_peak*100,'%')}</td></tr><tr><th>Waiting requests peak</th><td>{format(t.engines.vLLM.waiting_requests_peak,'req')}</td><td>{format(t.engines.SGLang.waiting_requests_peak,'req')}</td></tr></> : null; })()}</tbody></table></div>{(() => { const t = episode0Telemetry.workloads.find(x => x.id === value); return t ? <div data-native-phase-readings className="tbt-native-readings"><h4>vLLM-native phase timing</h4><p>Prefill {format(t.engines.vLLM.prefill_duration_seconds,'s',2)} · Decode {format(t.engines.vLLM.decode_duration_seconds,'s',2)}</p></div> : null; })()}</div><div className="tbt-evidence-group"><h3><span>Run-level device telemetry</span><small>One peak spans three workloads. It does not change with the selected workload and is not attributable to one workload.</small></h3><div className="tbt-run-telemetry">{(['Baseline','Stress'] as const).map(tier => <article key={tier} data-run-telemetry><h4>{tier} run</h4><p>Spans {episode0Telemetry.workloads.filter(w => w.tier === tier).map(w => w.id).join(', ')} · {episode0Telemetry.workloads.find(w => w.id === value)?.tier === tier ? 'Contains the selected workload' : 'Does not contain the selected workload'}</p>{(['V','S'] as const).map(engine => { const item = episode0Telemetry.runs[tier][engine]; return <p key={engine}>{engine === 'V' ? '● vLLM' : '◆ SGLang'} util {item.utilization_pct}% · mem {format(item.memory_mib/1024,'GiB')} · power {format(item.power_w,'W',0)} · {item.temperature_c} °C · {item.samples} samples</p>; })}</article>)}</div></div></>}<p className="tbt-validity">{episode === 1 ? episode1.arms.map(arm => { const point = arm.points.find(point => point.users === Number(value))!; return <span key={arm.engine}>{arm.engine === 'vLLM' ? '●' : '◆'} {arm.engine} · {point.valid_requests}/{point.total_requests} valid requests · level {point.level_valid ? 'valid' : 'invalid'}</span>; }) : <>● vLLM · recorded valid requests <span>◆ SGLang · recorded valid requests</span></>}</p><button className="tbt-ledger-toggle" type="button" aria-expanded={route.params.get('depth') === 'ledger'} onClick={() => setParam('depth',route.params.get('depth') === 'ledger' ? 'lab' : 'ledger')}>Exact measurement ledger <span>{route.params.get('depth') === 'ledger' ? 'Hide' : 'Show'}</span></button>{route.params.get('depth') === 'ledger' && <div className="tbt-ledger tbt-wide-ledger"><table><thead><tr><th>Metric</th>{['vLLM','SGLang'].flatMap(name => (episode === 1 ? measuredLoads.map(String) : workloadIds).map(x => <th key={`${name}-${x}`}>{name} · {x}</th>))}<th>Selected comparison</th></tr></thead><tbody>{metrics.map(spec => <tr key={spec.id}><th>{spec.title} ({spec.unit})</th>{['vLLM','SGLang'].flatMap(name => (episode === 1 ? measuredLoads.map(String) : workloadIds).map(x => <td key={`${name}-${x}`} className={x === value ? 'selected' : ''}>{format(readings(episode,x).find(row => row.name === name)?.values[spec.id],spec.unit)}</td>))}<td>{metricStates(spec).map((state,i) => <span key={i} className={`state-${state.kind}`}>{state.symbol} {state.text}<br /></span>)}</td></tr>)}</tbody></table></div>}</section>;
}

function BoundariesChapter({ episode }: { episode: 0 | 1 }) {
  const one = episode === 1;
  const blocks = one ? [
    ['Matched', ['One H200 per recorded arm', 'Same model family and precision', 'Same synthetic session population, users, slots, warm-up and window', 'Same client measurement and validity contract']],
    ['Deployment-specific', ['Runtime-native gauge definitions', 'Cache accounting is outside the cross-engine ranking']],
    ['Observed', [`At ${measuredLoads[0]} and ${measuredLoads[1]} users SGLang recorded more output and lower median TTFT than vLLM`, `At ${measuredLoads[2]} users the output difference reversed and median TTFT fell inside the display band`, `Both met the decode floor at ${measuredLoads[0]} users; both fell below it at ${measuredLoads[1]} and ${measuredLoads[2]}`]],
    ['Not established', ['Capacity under the declared service objectives', 'Statistical significance of any difference', 'Engine-only causation', 'Behaviour between the recorded loads']]
  ] : [
    ['Compatibility', ['Both engines used the same hardware class, model family, precision, prompt construction, sampling contract and client harness within each workload.']],
    ['Scope', ['The study covers vLLM and SGLang.', 'No latency objective was declared, so SLO-qualified goodput is outside this study.']],
    ['Preflight', ['Every measured arm passed hardware identity, readiness and warm-up checks.', `All ${episode0.cells.reduce((sum,c) => sum + c.successful_requests, 0)} measured requests succeeded.`]],
    ['Not established', ['A winner across workloads', 'A controlled concurrency sweep', 'Stable p99 tails from a weak tail sample', 'SLO-qualified capacity']]
  ];
  return <section id="ch-boundaries" data-screen-label="04 Boundaries" className="tbt-chapter tbt-boundaries"><ChapterHeading number={4} title="Boundaries" heading={one ? 'A deployment comparison, not an engine-only verdict' : 'An exploratory study, not a ranking'} id="boundaries" /><p>{one ? 'Read this before sharing. The public bundle holds measured outcomes, not serving recipes.' : 'Read this before sharing. The categories below come from the normalised study record.'}</p><div className="tbt-boundary-grid">{blocks.map(([title,items]) => <div data-boundary-block key={title as string}><h3>{title as string}</h3><ul>{(items as string[]).map(item => <li key={item}>{item}</li>)}</ul></div>)}</div></section>;
}
function SourceChapter({ episode, route }: { episode: 0 | 1; route: Route }) {
  const one = episode === 1;
  const file = one ? 'episode-1-public-site.json' : 'episode-0-public-site.json';
  const sourceUrl = one ? episode1DataUrl : episode0DataUrl;
  const schema = one ? episode1.schema_version : String(episode0.schema_version);
  const rows = [
    ['Client/public aggregate data', <a href={sourceUrl} download={file}>Download {file}</a>],
    ...(!one ? [['Workload and run telemetry', <a href={episode0TelemetryUrl} download="episode-0-public-telemetry.json">Download episode-0-public-telemetry.json — rounded from retained public runtime and GPU records</a>]] as [string, React.ReactNode][] : []),
    ['Schema', schema],
    ['Public command', 'The offline evidence client is available from source. Real benchmark submission is not released.'],
    ['Definitions', <a href="#methodology">Metric definitions and evidence states — Methodology →</a>]
  ] as const;
  return <section id="ch-source" data-screen-label="05 Source" className="tbt-chapter tbt-source"><ChapterHeading number={5} title="Source" heading="Where these numbers come from" id="source" /><p>{one ? 'Aggregated from aligned client, engine and GPU measurements into a static publication bundle. Selecting a load or comparison changes the view only; it never reruns the benchmark.' : 'Sanitized public aggregates: client streaming results per workload, workload-level runtime telemetry and run-level device peaks. Selecting a workload changes the view only.'}</p><dl>{rows.map(([key,content]) => <div data-source-row key={key}><dt>{key}</dt><dd>{content}</dd></div>)}</dl><div className="tbt-source-actions"><button type="button" onClick={() => navigator.clipboard.writeText(location.href)}>Copy link to this view</button><span>The address already encodes episode, selection, comparison, depth, chapter and metric.</span></div></section>;
}

function MethodChapter({ episode }: { episode: 0 | 1 }) {
  const [anatomy, setAnatomy] = useState<'ttft' | 'tpot' | 'decode' | 'e2e'>('ttft');
  const isOne = episode === 1;
  const cards = isOne ? [
    ['What', 'vLLM and SGLang deployments of one matched model, one H200 each, recorded at 12, 16 and 24 simulated users.'],
    ['Why', 'Aggregate output and visible latency can move in different directions as load rises. One load point cannot describe the trade.'],
    ['How', 'Synthetic conversations with aligned client, engine and GPU readings over one measured window.']
  ] : [
    ['What', 'vLLM and SGLang serving a matched model in BF16, one H100 80GB per run.'],
    ['Why', 'A first, honest look at how delivered work complicates runtime rankings before any capacity claim.'],
    ['How', 'Six input-length and concurrency workloads in two tiers; client-side streaming measurement on every request.']
  ];
  const protocol = isOne ? [
    ['Simulated users', measuredLoads.join(' · ')],
    ['Session slots', '24 · 32 · 48 — two sessions per user. Slots are not necessarily simultaneous active requests.'],
    ['Warm-up and window', `${episode1.methodology.warmup_seconds} s warm-up, then a ${episode1.methodology.measurement_seconds} s measured window per load`],
    ['Declared experience floor', 'Decode p10 ≥ 20 tok/s, declared before measurement'],
    ['Validity limit', '≤ 1% of measured requests failing the validity contract']
  ] : [
    ['Workloads', '128-token input at 1 and 16 concurrent; 2,048 at 4 and 24; 8,192 at 8 and 32'],
    ['Tiers', 'Baseline (1, 4, 8 concurrent) and Stress (16, 24, 32 concurrent)'],
    ['Repetitions', '3 per baseline workload · 2 per stress workload'],
    ['Matched', 'Hardware class, model, precision, prompt construction, sampling contract and client harness'],
    ['Telemetry scope', 'Queue, KV and phase readings are per workload. GPU peaks are per run and span a whole tier.']
  ];
  const anatomyOptions = {
    ttft: { name: 'TTFT', left: '0%', width: '38%', text: 'time to first token: queueing, prefill and the first token together. This is the wait a user sees.' },
    tpot: { name: 'TPOT', left: '38%', width: '62%', text: 'time per output token after the first: decode duration divided by the remaining tokens.' },
    decode: { name: 'Decode p10', left: '38%', width: '62%', text: 'decode speed in tokens per second; p10 is the speed 90% of requests met or beat.' },
    e2e: { name: 'End-to-end', left: '0%', width: '100%', text: 'from request sent through terminal stream and usage validation.' }
  };
  const chosen = anatomyOptions[anatomy];
  return <section id="ch-method" data-screen-label="02 Method" className="tbt-chapter tbt-method"><ChapterHeading number={2} title="Method" heading={isOne ? 'One GPU, two engines, three matched loads' : 'Six workloads, two engines, one GPU class'} id="method" /><p>{isOne ? 'Two serving deployments of one matched model were recorded on identical single-GPU hardware. Each deployment met the same synthetic session population at three load levels.' : 'A closed-loop synthetic workload with exact-token prompts, run on both engines with the same model, precision and client harness.'}</p><div className="tbt-method-cards">{cards.map(([title,copy]) => <div key={title}><h3>{title}</h3><p>{copy}</p></div>)}</div><dl className="tbt-protocol">{protocol.map(([key,copy]) => <div data-protocol-row key={key}><dt>{key}</dt><dd>{copy}</dd></div>)}</dl>{isOne && <figure data-request-anatomy className="tbt-anatomy"><figcaption><b>Anatomy of one request</b><span>Schematic explanation — not measured traces.</span></figcaption><div role="group" aria-label="Choose a metric to locate on the request">{([['ttft','TTFT'],['tpot','TPOT'],['decode','Decode p10'],['e2e','End-to-end']] as const).map(([key,label]) => <button key={key} type="button" aria-pressed={anatomy===key} onClick={() => setAnatomy(key)}>{label}</button>)}</div><div className="tbt-anatomy-track" aria-hidden="true"><div><span>Queue</span><span>Prefill</span><span></span><span>Decode, one token at a time</span></div><i style={{left:chosen.left,width:chosen.width}} /></div><p><b>{chosen.name}</b> — {chosen.text}</p></figure>}<p className="tbt-method-link"><a href="#methodology">Metric definitions and evidence states — Methodology</a></p></section>;
}

function BriefChapter({ episode, value, rows, equalWork, lab, toggleLab, toggleRef }: { episode: 0 | 1; value: string; rows: ReturnType<typeof readings>; equalWork: boolean; lab: boolean; toggleLab(): void; toggleRef: React.RefObject<HTMLButtonElement | null> }) {
  const specs = episode === 1 ? [specs1[0], specs1[1], specs1[3], specs1[4]] : [specs0[0], specs0[1], specs0[2], specs0[5]];
  const [input, concurrency] = value.split('-c').map(Number);
  const a = rows[0], b = rows[1];
  const outputA = b.values[specs[0].id], outputB = a.values[specs[0].id];
  const ttftA = b.values[specs[1].id], ttftB = a.values[specs[1].id];
  const outputState = decision(outputA, outputB, true), ttftState = decision(ttftA, ttftB, false);
  const pct = (x: number | null | undefined, y: number | null | undefined) => x == null || y == null || y === 0 ? '—' : `${Math.abs((x-y)/y*100).toFixed(1)}%`;
  const work = episode === 0 ? episode0.cells.filter(c => c.input_tokens_min === input && c.concurrency === concurrency) : [];
  const vllmWork = work.find(c => c.runtime === 'vLLM');
  const sglangWork = work.find(c => c.runtime === 'SGLang');
  const intro = episode === 1 ? `At ${value} users, ` : `With ${input.toLocaleString()}-token inputs and ${concurrency} concurrent requests, `;
  const caveats = episode === 1 ? [
    'The study measured only the listed closed-loop loads; it did not determine the maximum sustainable request rate under a declared latency-and-error SLO.',
    'This is a recorded deployment comparison, not an engine-only benchmark.',
    'The decode floor is a declared threshold, not a capacity claim.'
  ] : [
    'No winner is claimed across workloads, and workloads are not compared with each other.',
    'Input length and concurrency change together, so the six workloads are categorical observations, not a sweep.',
    'In the two 8,192-token workloads the engines delivered unequal work; their rate and latency are not compared.'
  ];
  function stateFor(spec: MetricSpec) {
    if (spec.id === 'work_per_request') return { symbol: equalWork ? '=' : '≠', text: equalWork ? 'Equal delivered work' : 'Unequal work — not compared', kind: equalWork ? 'equal' : 'band' };
    if (spec.id === 'decode_p10_tps') { const both = rows.every(row => (row.values[spec.id] ?? -1) >= 20); return { symbol: both ? '≥' : '<', text: both ? 'Both meet 20 tok/s floor' : 'Below 20 tok/s floor', kind: both ? 'better' : 'worse' }; }
    return equalWork ? decision(b.values[spec.id], a.values[spec.id], spec.higher) : { symbol: '≠', text: 'Unequal work — not compared', kind: 'band' };
  }
  return <section id="ch-brief" data-screen-label="01 Brief" className="tbt-chapter tbt-brief"><h2 id="h-brief" tabIndex={-1} className="tbt-brief-heading"><span aria-hidden="true" className="tbt-chapter-bar" />01 Brief</h2><p className="tbt-finding">{episode === 0 && !equalWork ? <>{intro}the engines delivered <span className="state-band">≠ unequal work</span> — vLLM {format(vllmWork ? vllmWork.successful_output_tokens / vllmWork.successful_requests : null, 'tokens per request')} vs SGLang {format(sglangWork ? sglangWork.successful_output_tokens / sglangWork.successful_requests : null, 'tokens per request')} — so throughput and latency are not compared.</> : <>{intro}SGLang recorded <span className={`state-${outputState.kind}`}>{outputState.symbol} {pct(outputA,outputB)} {outputA != null && outputB != null && outputA >= outputB ? episode === 1 ? 'more output' : 'higher output rate' : episode === 1 ? 'less output' : 'lower output rate'}</span> and <span className={`state-${ttftState.kind}`}>{ttftState.symbol} {pct(ttftA,ttftB)} {ttftA != null && ttftB != null && ttftA <= ttftB ? 'lower' : 'higher'} median TTFT</span> than vLLM.</>}</p><p className="tbt-small">{episode === 0 && !equalWork ? 'Different delivered work prevents a like-for-like comparison for this workload.' : `Change = (SGLang − vLLM) ÷ vLLM ${episode === 1 ? `at ${value} users` : 'for this workload'}. Under ±2% shows as ≈ — a descriptive band, not a significance test.`}</p><div className="tbt-brief-table-wrap"><table className="tbt-brief-table"><tbody>{specs.map(spec => { const state = stateFor(spec); const rankable = equalWork && spec.id !== 'work_per_request' && spec.id !== 'decode_p10_tps'; return <tr key={spec.id}><th><b>{spec.title}</b><small>{spec.id === 'work_per_request' ? 'Equal work is required to compare' : spec.id === 'decode_p10_tps' ? 'Threshold ≥ 20 tok/s' : spec.higher ? 'Higher is better' : 'Lower is better'}</small></th><td><small>● vLLM</small><b>{format(a.values[spec.id],spec.unit)}</b></td><td><small>◆ SGLang</small><b className={rankable ? `state-${state.kind}` : ''}>{format(b.values[spec.id],spec.unit)}</b></td><td className={`state-${state.kind}`}>{state.symbol} {state.text}<small>{spec.id === 'decode_p10_tps' ? 'Each engine vs declared floor' : 'SGLang vs vLLM'}</small></td></tr>; })}</tbody></table></div><div className="tbt-caveat"><h3>What this does not say</h3><ul>{caveats.map(item => <li key={item}>{item}</li>)}</ul></div><dl className="tbt-apparatus"><div><dt>Hardware</dt><dd>{episode === 1 ? 'One H200 per recorded arm' : 'One H100 per run'}</dd></div><div><dt>Engines</dt><dd>● vLLM · ◆ SGLang</dd></div><div><dt>Model</dt><dd>Matched model family</dd></div><div><dt>{episode === 1 ? 'Window' : 'Requests'}</dt><dd>{episode === 1 ? `${episode1.methodology.measurement_seconds} s measured per load` : `${(vllmWork?.successful_requests ?? 0) + (sglangWork?.successful_requests ?? 0)} measured`}</dd></div></dl></section>;
}

type ConfigurationState = { label: string; detail: string; state: 'enabled' | 'inherited' | 'disabled' };
const experimentContracts = {
  0: {
    title: 'Episode 00 recorded settings',
    stamp: 'Public record · retained reproduction contract',
    summary: 'Recorded settings and built-in engine behavior from the retained H100 record. A checked item was recorded; amber means engine behavior not isolated as an experiment; an empty circle means no enabled arm was recorded.',
    facts: [['Hardware', '1× NVIDIA H100 per run'], ['Engines', 'vLLM · SGLang'], ['Model', 'Qwen2.5-32B-Instruct'], ['Precision', 'BF16 weights'], ['Context', '16,384 tokens'], ['Warm-up', 'Required before measurement']],
    states: [
      { label: 'Prefix caching', detail: 'Enabled in both recorded arms', state: 'enabled' },
      { label: 'Chunked prefill', detail: 'Enabled in both recorded arms', state: 'enabled' },
      { label: 'Continuous batching', detail: 'Built-in engine scheduling; not isolated', state: 'inherited' },
      { label: 'KV-cache paging', detail: 'Built-in engine memory management; not isolated', state: 'inherited' },
      { label: 'Attention backend', detail: 'vLLM FlashAttention-3 · SGLang Triton', state: 'inherited' },
      { label: 'Warm-up gate', detail: 'Required before measurement', state: 'enabled' },
      { label: 'Speculative decoding', detail: 'No speculative arm recorded', state: 'disabled' },
      { label: 'Multi-GPU parallelism', detail: 'Not used — one H100 per run', state: 'disabled' }
    ] satisfies ConfigurationState[],
    record: {
      hardware: { accelerator_class: 'H100 80GB HBM3', devices_per_run: 1 },
      model: { family: 'Qwen2.5-32B-Instruct', weight_dtype: 'bfloat16', context_tokens: 16384 },
      runtime: { prefix_caching: true, chunked_prefill: true, continuous_batching: 'engine_behavior_not_isolated', paged_kv_management: 'engine_capability_not_isolated', attention_backend: { vllm: 'FlashAttention', sglang: 'Triton attention' }, speculative_arm_recorded: false, multi_gpu: false },
      measurement: { warmup_gate: 'required', repetitions: { baseline: 3, stress: 2 } }
    },
    boundary: 'This reviewed public reproduction contract contains the settings supported by retained evidence. It is not a runnable deployment profile.'
  },
  1: {
    title: 'Episode 01 baseline settings',
    stamp: 'Public record · recorded configuration extract',
    summary: 'Recorded settings and built-in engine behavior from the H200 baseline. A checked item was recorded; amber means engine behavior or configuration not isolated as an experiment; an empty circle means the feature was not used in this comparison.',
    facts: [['Hardware', '1× NVIDIA H200 per arm'], ['Engines', 'vLLM · SGLang'], ['Model', 'Qwen3.8-27B-FP8'], ['Context', '262,144 tokens'], ['Workload', '12 / 16 / 24 users × 2 sessions'], ['Warm-up', '120 s before every measured load']],
    states: [
      { label: 'Prefix caching', detail: 'Enabled in both recorded arms', state: 'enabled' },
      { label: 'FP8 KV cache', detail: 'vLLM FP8 · SGLang FP8 E4M3', state: 'enabled' },
      { label: 'Continuous batching', detail: 'Built-in engine scheduling; not isolated', state: 'inherited' },
      { label: 'Prefill scheduling', detail: 'Engine-managed; not isolated', state: 'inherited' },
      { label: 'KV-cache paging', detail: 'Built-in engine memory management; not isolated', state: 'inherited' },
      { label: 'Attention backend', detail: 'vLLM runtime-selected · SGLang FA3 recorded', state: 'inherited' },
      { label: 'Speculative decoding', detail: 'Off in the published baseline arms', state: 'disabled' },
      { label: 'Tensor parallelism', detail: 'TP = 1 · one H200 per arm', state: 'disabled' }
    ] satisfies ConfigurationState[],
    record: {
      hardware: { accelerator_class: 'H200', devices_per_arm: 1 },
      model: { family: 'Qwen3.8-27B-FP8', weight_dtype: 'fp8_checkpoint', context_tokens: 262144 },
      runtime: { prefix_caching: true, kv_cache_dtype: { vllm: 'fp8', sglang: 'fp8_e4m3' }, continuous_batching: 'built_in_not_isolated', prefill_scheduling: 'engine_managed_not_isolated', paged_kv_management: 'built_in_not_isolated', attention_backend: { vllm: 'runtime_selected_no_override_recorded', sglang: 'fa3' }, admission_cap_per_arm: 1024, speculative_decoding_in_published_baseline: false, tensor_parallel_size: 1 },
      workload: { user_levels: [12, 16, 24], sessions_per_user: 2 },
      measurement: { warmup_seconds: 120, measurement_seconds: 300, decode_p10_floor_tps: 20 }
    },
    boundary: 'This is the reviewed public configuration extract, not a runnable serving profile. Endpoints, credentials, private profile names and deployment recipes remain private.'
  }
} as const;
function ExperimentContract({ episode }: { episode: 0 | 1 }) {
  const [open, setOpen] = useState(false);
  const contract = experimentContracts[episode];
  return <section data-experiment-contract className="tbt-contract" aria-labelledby="experiment-contract-title">
    <div className="tbt-contract-head"><div><p className="tbt-contract-label">Recorded experiment contract</p><h2 id="experiment-contract-title">What was fixed and recorded</h2><p>{contract.summary}</p></div><button type="button" className="tbt-unfold" aria-expanded={open} aria-controls="recorded-configuration" onClick={() => setOpen(value => !value)}>{open ? 'Fold configuration note ↑' : 'Unfold recorded JSON ↓'}</button></div>
    <div className="tbt-config-grid">{contract.states.map(item => <div key={item.label} data-config-state={item.state}><i aria-hidden="true">{item.state === 'enabled' ? '✓' : item.state === 'inherited' ? '•' : '○'}</i><span><b>{item.label}</b><small>{item.detail}</small></span></div>)}</div>
    <div id="recorded-configuration" data-configuration-note={open ? '' : undefined} aria-hidden={!open} className={`tbt-paper-stage ${open ? 'open' : ''}`}><article className="tbt-paper"><span className="tbt-paper-stamp">{contract.stamp}</span><h3>{contract.title}</h3><div className="tbt-paper-grid"><dl>{contract.facts.map(([term, value]) => <div key={term}><dt>{term}</dt><dd>{value}</dd></div>)}</dl><pre>{JSON.stringify(contract.record, null, 2)}</pre></div><p className="tbt-paper-privacy">{contract.boundary}</p></article></div>
  </section>;
}
function RunCost({ episode }: { episode: 0 | 1 }) {
  if (episode === 0) return <section data-run-cost data-cost-kind="observed" className="tbt-run-cost" aria-labelledby="run-cost-title"><div className="tbt-cost-head"><div><p className="tbt-contract-label">Cost basis · observed billing</p><h3 id="run-cost-title">What the Episode 00 campaign billed</h3><p>The <span data-cost-provider>RUNPOD</span> billing total is split below into non-overlapping categories. Only the H100 is part of the published benchmark; RTX PRO 6000 and A100 activity is classified as trial and setup.</p></div><div className="tbt-cost-total"><small>Campaign billing</small><strong>$11.83</strong><span>$11.69 GPU · $0.14 storage</span></div></div><div className="tbt-cost-cards"><div><small>Published-study GPU class</small><strong>$6.43</strong><span>H100 GPU billing</span></div><div><small>Trial and setup</small><strong>$5.26</strong><span>RTX PRO 6000 + A100 GPU billing</span></div><div><small>Attached storage</small><strong>$0.14</strong><span>Campaign storage billing</span></div></div><p className="tbt-cost-boundary"><strong>Check:</strong> $6.43 + $5.26 + $0.14 = $11.83. Provider billing does not isolate successful requests, warm-up, retries or idle time within the H100 amount. A separate RTX PRO 4500 bill is excluded because the retained record does not establish that it belongs to Episode 00.</p></section>;
  return <section data-run-cost data-cost-kind="observed" className="tbt-run-cost" aria-labelledby="run-cost-title"><div className="tbt-cost-head"><div><p className="tbt-contract-label">Cost basis · observed billing</p><h3 id="run-cost-title">What the Episode 01 campaign billed</h3><p>The <span data-cost-provider>RUNPOD</span> billing total is split below into non-overlapping categories. Only the H200 is part of the published benchmark; RTX PRO 6000 activity is classified as trial and setup.</p></div><div className="tbt-cost-total"><small>Campaign billing</small><strong>$19.07</strong><span>$18.87 GPU · $0.20 storage</span></div></div><div className="tbt-cost-cards"><div><small>Published-study GPU class</small><strong>$7.26</strong><span>H200 GPU billing</span></div><div><small>Trial and setup</small><strong>$11.61</strong><span>RTX PRO 6000 GPU billing</span></div><div><small>Attached storage</small><strong>$0.20</strong><span>Campaign storage billing</span></div></div><p className="tbt-cost-boundary"><strong>Check:</strong> $7.26 + $11.61 + $0.20 = $19.07. The $3.21 comparable-window figure is a rate × protocol-time estimate inside the campaign, not an additional bill or a provider allocation. Billing does not isolate successful measurement from setup, retries or idle time within the H200 amount.</p></section>;
}

function Study({ episode, route, setParam }: { episode: 0 | 1; route: Route; setParam(key: string, value: string, replace?: boolean): void }) {
  const key = episode === 1 ? 'load' : 'wl';
  const allowed = episode === 1 ? measuredLoads.map(String) : workloadIds;
  const value = allowed.includes(route.params.get(key) ?? '') ? route.params.get(key)! : episode === 1 ? '16' : '2048-c24';
  const invalid = route.params.has(key) && !allowed.includes(route.params.get(key)!);
  const [lab, setLab] = useState(route.params.get('depth') === 'lab' || route.params.get('depth') === 'ledger' || (route.params.has('ch') && route.params.get('ch') !== 'brief'));
  const [openMetric, setOpenMetric] = useState<string | null>(null);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const rows = readings(episode, value);
  const specs = episode === 1 ? specs1 : specs0;
  const equalWork = episode === 1 || (() => {
    const [input, concurrency] = value.split('-c').map(Number);
    const cells = episode0.cells.filter(c => c.input_tokens_min === input && c.concurrency === concurrency);
    return cells.length === 2 && Math.abs(cells[0].successful_output_tokens / cells[0].successful_requests - cells[1].successful_output_tokens / cells[1].successful_requests) < 1e-9;
  })();
  const compare = (a: number | null | undefined, b: number | null | undefined, higher = true) => equalWork ? decision(a, b, higher) : { symbol: '≠', text: 'Unequal work — not compared', kind: 'band' };
  const title = episode === 1 ? 'Measure what matters' : 'Warm-up';
  const question = episode === 1 ? <>Can the <span data-headline-accent>throughput leader</span> still miss the decode floor?</> : <>Can <span data-headline-accent>48.9% more throughput</span> come with 19.8% higher median TPOT?</>;
  const deck = episode === 1
    ? <>What did vLLM and SGLang deliver at three matched loads on <span data-headline-count-accent>one</span> <span data-headline-hardware-accent>H200</span>?</>
    : <>What did vLLM and SGLang deliver across six workloads on <span data-headline-count-accent>one</span> <span data-headline-hardware-accent>H100</span>?</>;
  const output = compare(rows[1]?.values[specs[0].id], rows[0]?.values[specs[0].id]);
  const percent = (a: number | null | undefined, b: number | null | undefined) => a == null || b == null || b === 0 ? null : Math.abs((a - b) / b * 100).toFixed(1);
  const outputA = rows[1]?.values[specs[0].id], outputB = rows[0]?.values[specs[0].id];
  const ttftA = rows[1]?.values[specs[1].id], ttftB = rows[0]?.values[specs[1].id];
  const cellsForWork = episode === 0 ? episode0.cells.filter(c => `${c.input_tokens_min}-c${c.concurrency}` === value) : [];
  const finding = episode === 0 && !equalWork && cellsForWork.length === 2
    ? `With ${Number(value.split('-c')[0]).toLocaleString()}-token inputs and ${value.split('-c')[1]} concurrent requests, the engines delivered ≠ unequal work — vLLM ${format(cellsForWork.find(c => c.runtime === 'vLLM')!.successful_output_tokens / cellsForWork.find(c => c.runtime === 'vLLM')!.successful_requests, 'tokens per request')} vs SGLang ${format(cellsForWork.find(c => c.runtime === 'SGLang')!.successful_output_tokens / cellsForWork.find(c => c.runtime === 'SGLang')!.successful_requests, 'tokens per request')} — so throughput and latency are not compared.`
    : outputA == null || outputB == null || ttftA == null || ttftB == null
      ? `At ${value} users only one engine has a recorded point. ∅ No comparison is available.`
      : `${episode === 1 ? `At ${value} users, ` : `With ${Number(value.split('-c')[0]).toLocaleString()}-token inputs and ${value.split('-c')[1]} concurrent requests, `}SGLang recorded ${outputA >= outputB ? '✓' : '✕'} ${percent(outputA, outputB)}% ${outputA >= outputB ? 'more' : 'less'} output and ${ttftA < ttftB ? '✓' : '✕'} ${percent(ttftA, ttftB)}% ${ttftA < ttftB ? 'lower' : 'higher'} median TTFT than vLLM.`;
  const toggleLab = () => { trackAnalyticsEvent('evidence-lab-toggle', { episode: String(episode).padStart(2, '0'), state: lab ? 'closed' : 'open' }); if (lab) { setLab(false); setParam('depth', 'brief'); requestAnimationFrame(() => toggleRef.current?.focus()); } else { setLab(true); setParam('depth', 'lab'); requestAnimationFrame(() => document.getElementById('h-method')?.focus()); } };
  useEffect(() => { setLab(route.params.get('depth') === 'lab' || route.params.get('depth') === 'ledger' || (route.params.has('ch') && route.params.get('ch') !== 'brief')); }, [route.page, route.params]);
  const showAnalysisHeadline = route.params.get('head') !== 'title';
  return <article className="tbt-study">{route.notices.length>0&&<div className="tbt-notice" role="status"><b>Link adjusted</b> {route.notices.join(' ')}</div>}{invalid && <div className="tbt-notice" role="status"><b>Link adjusted</b> {route.params.get(key)} is not recorded. Showing {value}.</div>}<header data-screen-label="Episode header" className="tbt-study-header">{showAnalysisHeadline ? <><p className="tbt-eyebrow">Episode {String(episode).padStart(2,'0')}: <strong>{title}</strong> · Recorded study</p><h1 id="page-title" className="question">{question}</h1></> : <><p className="tbt-eyebrow">Episode {String(episode).padStart(2,'0')} · Recorded study</p><h1 id="page-title">{title}</h1></>}<p className="tbt-deck">{deck}</p><p className="tbt-quals"><span>Recorded exploratory comparison</span><span>{episode === 1 ? 'One H200 per arm' : 'One H100 per run'}</span><span>Tested loads only · maximum sustainable rate not measured</span></p></header><Selector episode={episode} value={value} select={(v, replace) => setParam(key, v, replace)} /><BriefChapter episode={episode} value={value} rows={rows} equalWork={equalWork} lab={lab} toggleLab={toggleLab} toggleRef={toggleRef} /><ExperimentContract episode={episode} /><div className="tbt-lab-toggle-row"><button id="lab-toggle" ref={toggleRef} type="button" aria-expanded={lab} aria-controls="lab" onClick={toggleLab} className="tbt-lab-toggle">{lab ? 'Collapse lab ↑' : 'Open evidence lab ↓'}</button></div>{lab && <div id="lab"><MethodChapter episode={episode} /><EvidenceChapter episode={episode} value={value} route={route} setParam={setParam} /><BoundariesChapter episode={episode} /><SourceChapter episode={episode} route={route} /></div>}<RunCost episode={episode} /><EpisodePager number={episode} /></article>;
}
function Planned({ number }: { number: number }) { const e = episodes.find(e => e.number === number)!; return <article className="tbt-study tbt-planned-page"><p className="tbt-eyebrow">Episode {String(number).padStart(2,'0')} · Planned</p><section className="tbt-planned-outline"><span data-planned-watermark aria-hidden="true">Planned</span><div className="tbt-planned-copy"><span className="tbt-planned-state">Planned</span><h1 id="page-title">{e.title}</h1><p>{e.summary}</p><p><strong>What is being tested:</strong> {number === 2 ? 'whether deployment behavior changes when the useful work contract, workload and measurement rules are fixed across every arm.' : 'whether the declared change alters serving behavior under a fixed work contract and reviewed measurement rules.'}</p><a href={`#episodes?open=${e.id}`}>Read the experiment roadmap →</a></div></section><EpisodePager number={number} /></article>; }
function Methodology() {
  const process = [
    ['1', 'Freeze the contract', 'Name the model family, tokenizer and template, endpoint, runtime, hardware, workload, output policy, sampling settings, measured loads and declared thresholds before reading results. Each episode publishes the safe subset of its own protocol.'],
    ['2', 'Resolve the workload', 'Use either a declared exact-token corpus or a versioned request corpus. AgentBench pins dataset revisions, seeds and source records; model-specific token counts are cached against the model revision.'],
    ['3', 'Check the endpoint', 'Verify served identity and context limits, then run fresh-code coherence probes for recall, long-context retrieval and tool calling. A one-user smoke test exercises the complete streaming and measurement path.'],
    ['4', 'Separate warm-up', 'Warm-up traffic is marked and excluded. Episode 01 used 120 seconds of warm-up before each 300-second measured window; other episodes disclose their own windows.'],
    ['5', 'Replay recorded load', 'For session studies, each simulated user owns declared session slots. Requests preserve order within a slot and use recorded or modeled gaps. A slot is not continuously decoding and is not the same as an active server request.'],
    ['6', 'Measure both sides', 'The client records visible TTFT, post-first-token timing, output, completion validity, failures and timestamps. Engine and GPU telemetry provide request, cache, utilization, memory and power context when comparable definitions are available.'],
    ['7', 'Validate, then report', 'Minimum samples, stream integrity, error limits, equal-work checks and episode-specific thresholds determine which observations qualify. Reports retain invalid states and recorded evidence gaps instead of silently replacing them.']
  ];
  const glossary = [
    ['Output throughput', 'Successful output tokens divided by measured seconds. Higher is better only when delivered work is comparable.'],
    ['TTFT p50 / p95', 'Client-visible time from request to first token. p50 is the median; p95 describes the slower tail. Lower is better.'],
    ['TPOT p50', 'Median time per generated output token after the first token. Lower is better.'],
    ['Decode p10', 'Per-request decode speed at the tenth percentile: 90% of valid requests meet or exceed it. Episode 01 alone declares a 20 tok/s floor; other studies need their own declared gate.'],
    ['Error rate', 'Failed or invalid requests divided by measured requests. Episode 01 declares a 1% validity limit.'],
    ['Delivered work', 'Successful output tokens per successful request. Equal work is a gate before comparing Episode 00 rate and latency.'],
    ['Runtime and device context', 'Running and waiting requests, cache, GPU utilization, memory and power describe recorded conditions. They are not cross-engine rankings.']
  ];
  const states = [
    ['✓ Favorable direction', 'A directional value improves relative to its named baseline, with comparable delivered work where required.'],
    ['✕ Unfavorable direction', 'A directional value worsens relative to its named baseline.'],
    ['≥ / ≤ Threshold met', 'An individual identity meets its episode-specific declared floor or limit. Episode 01 defines its own decode and validity gates.'],
    ['< / > Threshold missed', 'An individual identity misses its episode-specific declared floor or limit. This is not an engine-to-engine comparison.'],
    ['≈ Within band', 'Absolute change under 2%; descriptive display band, not statistical significance.'],
    ['= Equal work / ≠ unequal work', 'Delivered output per request matches or does not match. Unequal work blocks ranking.'],
    ['△ Context only', 'Recorded value has no cross-engine better direction.'],
    ['Invalid level', 'A measured load fails its protocol’s validity contract. Request counts and the level-valid flag remain visible; invalid evidence cannot qualify capacity.']
  ];
  const groups = [...new Set(methodologySources.map(source => source.group))];
  return <article className="tbt-study tbt-methodology">
    <header className="tbt-study-header"><p className="tbt-eyebrow">Methodology · shared rules, episode-specific protocols</p><h1 id="page-title">How the <span data-methodology-accent>lab</span> measures</h1><p className="tbt-deck">How AgentBench turns declared workloads into reviewed evidence, how Token by Token decides what may be compared, and which open-source contributors make the workload paths possible.</p></header>
    <section className="tbt-chapter" id="ch-process"><h2 id="h-process" tabIndex={-1}>01 Benchmark process</h2><p>Like established benchmark publishers, each study separates the system under test, workload, scenario, metric rules, validity gates and evidence boundary. The episode Method chapter remains the authority when a study differs from this shared path.</p><ol className="tbt-method-steps">{process.map(([number,title,description]) => <li key={number}><b>{number}</b><div><h3>{title}</h3><p>{description}</p></div></li>)}</ol><aside className="tbt-method-reference"><strong>Reporting model</strong><p>This presentation follows the disclosure pattern used by <a href="https://docs.mlcommons.org/inference/" target="_blank" rel="noopener noreferrer">MLPerf Inference</a> and <a href="https://artificialanalysis.ai/methodology" target="_blank" rel="noopener noreferrer">Artificial Analysis methodology</a>: define the workload and system, publish metric rules and thresholds, and state what the evidence cannot establish. Token by Token is independent and is not an MLPerf submission or certification.</p></aside></section>
    <section className="tbt-chapter" id="ch-definitions"><h2 id="h-definitions" tabIndex={-1}>02 Definitions</h2><dl className="tbt-protocol">{glossary.map(([term,definition]) => <div key={term}><dt>{term}</dt><dd>{definition}</dd></div>)}</dl></section>
    <section className="tbt-chapter" id="ch-states"><h2 id="h-states" tabIndex={-1}>03 Evidence states</h2><dl className="tbt-protocol">{states.map(([term,definition]) => <div key={term}><dt>{term}</dt><dd>{definition}</dd></div>)}</dl></section>
    <section className="tbt-chapter" id="ch-identity"><h2 id="h-identity" tabIndex={-1}>04 Identity</h2><p>vLLM uses a circle and solid line; SGLang uses a diamond and dashed line. Each plotted value and state retains its identity.</p></section>
    <section className="tbt-chapter" id="ch-rules"><h2 id="h-rules" tabIndex={-1}>05 Rules</h2><p>Compare only recorded loads or matched workloads. A selected baseline supplies the comparison reference; declared thresholds use their own fixed rules. Only recorded values are displayed; no missing point is estimated. A line connecting measured loads is a reading aid, not an interpolated measurement.</p><div className="tbt-rule-grid"><p><strong>Work before speed.</strong> Throughput and latency are ranked only after delivered work is comparable.</p><p><strong>Validity before capacity.</strong> Failed or incomplete levels cannot qualify a deployment, even when surviving requests look fast.</p><p><strong>Observed, not inferred.</strong> The site reports tested points; it does not interpolate an unmeasured maximum sustainable rate.</p><p><strong>Context is not a ranking.</strong> Runtime-native queue, cache and device gauges describe the setting unless a common definition exists.</p></div></section>
    <section className="tbt-chapter" id="ch-protocols"><h2 id="h-protocols" tabIndex={-1}>06 Episode protocols</h2><p><a href="#episode-0?depth=lab&ch=method">Episode 00 method</a> · <a href="#episode-1?depth=lab&ch=method">Episode 01 method</a></p><p className="tbt-small">Episode 00 uses categorical exact-token synthetic workloads. Episode 01 uses a synthetic multi-turn session population at three recorded loads. Their results share evidence rules but are not pooled into one experiment.</p></section>
    <section className="tbt-chapter" id="ch-sources"><h2 id="h-sources" tabIndex={-1}>07 Sources &amp; credits</h2><p>AgentBench is a private Mirastack Labs benchmarking harness. It uses and credits open datasets and tools; that does not make AgentBench itself open source or transfer an upstream license to the harness.</p><p className="tbt-source-scope"><strong>Episode scope:</strong> Episode 00 used declared exact-token synthetic workloads. The public Episode 01 record identifies a synthetic multi-turn session population. Neither public record claims that the bundled open-dataset mixture below produced its measurements.</p><div className="tbt-source-boundary"><strong>License boundary</strong><p>Attribution is not permission. Original licenses continue to govern source and transformed content. Model, endpoint, agent-client and repository terms remain separate. “Supported” does not mean a source was used by every published episode.</p></div>{groups.map(group => <section className="tbt-source-group" key={group}><h3>{group}</h3><div className="tbt-source-ledger">{methodologySources.filter(source => source.group === group).map(source => <article key={source.name}><header><div><a href={source.url} target="_blank" rel="noopener noreferrer">{source.name}</a><p>{source.contributor}</p></div><span>{source.status}</span></header><dl><div><dt>Use</dt><dd>{source.use}</dd></div><div><dt>Handling</dt><dd>{source.handling}</dd></div><div><dt>License / terms</dt><dd>{source.license}</dd></div><div><dt>Revision</dt><dd><code>{source.revision}</code></dd></div></dl></article>)}</div></section>)}<aside className="tbt-compliance-note"><strong>Review status</strong><p>The bundled corpus records source revisions, licenses, sampling seeds and transformations. Items marked optional require their own pinned version and terms review before a public run. Trace content and task-derived material can carry nested rights or personal-data risks; qualified legal review remains appropriate before redistribution.</p></aside></section>
  </article>;
}
export function PublicSite() {
  const [route, setRoute] = useState(readRoute);
  const [theme, setTheme] = useState<Theme>(getInitialTheme);
  const [epMenu, setEpMenu] = useState(false);
  const [siteMenu, setSiteMenu] = useState(false);
  const [labMenu, setLabMenu] = useState(false);
  const [live, setLive] = useState('');
  const previewTheme = route.params.get('theme');
  const shownTheme: Theme = previewTheme === 'light' || previewTheme === 'dark' ? previewTheme : theme;
  const page = route.page;
  const episodeMatch = /^episode-(\d+)$/.exec(page);
  const episodeNumber = episodeMatch ? Number(episodeMatch[1]) : null;
  const isStudy = episodeNumber !== null && episodeNumber <= 1;
  const isPlanned = episodeNumber !== null && episodeNumber >= 2 && episodeNumber <= 16;
  const chapters = page === 'episodes' ? ['recorded','planned'] : page === 'methodology' ? ['process','definitions','states','identity','rules','protocols','sources'] : isStudy ? [...CHAPTERS] : [];
  const chapterKey = chapters.join('|');
  const [activeChapter, setActiveChapter] = useState(chapters[0] ?? '');
  const previousPage = useRef(page);
  useEffect(() => { const update = () => { setRoute(readRoute()); setEpMenu(false); setSiteMenu(false); setLabMenu(false); }; window.addEventListener('hashchange',update); window.addEventListener('popstate',update); return () => { window.removeEventListener('hashchange',update); window.removeEventListener('popstate',update); }; }, []);
  useLayoutEffect(() => {
    if (previousPage.current === page) return;
    previousPage.current = page;
    if (page === 'episodes' && route.params.get('open')) return;
    window.scrollTo({ top: 0, left: 0, behavior: 'instant' });
  }, [page, route.params]);
  useEffect(() => { document.title = `${page === 'episodes' ? 'Token by Token' : page === 'methodology' ? 'Methodology' : episodeNumber !== null ? `Episode ${String(episodeNumber).padStart(2,'0')}` : 'Not found'} — INFERENCE LAB`; }, [page, episodeNumber]);
  useEffect(() => { const normalized = url(page, route.params); if (location.hash !== normalized) history.replaceState(null,'',normalized); }, [page, route.params]);
  useEffect(() => { document.documentElement.dataset.theme = shownTheme; document.documentElement.style.colorScheme = shownTheme; }, [shownTheme]);
  useEffect(() => { const size = route.params.get('text'); document.documentElement.style.fontSize = size === '125' || size === '150' || size === '200' ? `${size}%` : ''; return () => { document.documentElement.style.fontSize = ''; }; }, [route.params]);
  useEffect(() => {
    setActiveChapter(route.params.get('ch') ?? chapters[0] ?? '');
    if (!chapters.length) return;
    let frame = 0;
    const update = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const selector = document.querySelector<HTMLElement>('.tbt-selector');
        const selectorBottom = selector && selector.getBoundingClientRect().top <= 0 ? selector.getBoundingClientRect().bottom : 0;
        const threshold = Math.max(72, selectorBottom + 24, innerHeight * .45);
        let current = chapters[0];
        const renderedChapters: string[] = [];
        for (const chapter of chapters) {
          const section = document.getElementById(`ch-${chapter}`);
          if (section) renderedChapters.push(chapter);
          if (section && section.getBoundingClientRect().top <= threshold) current = chapter;
        }
        if (scrollY + innerHeight >= document.documentElement.scrollHeight - 2 && renderedChapters.length) current = renderedChapters[renderedChapters.length - 1];
        setActiveChapter(previous => previous === current ? previous : current);
      });
    };
    update();
    addEventListener('scroll', update, { passive: true });
    addEventListener('resize', update);
    return () => { cancelAnimationFrame(frame); removeEventListener('scroll', update); removeEventListener('resize', update); };
  }, [page, chapterKey, route.params]);

  function setParam(key: string, value: string, replace = false) {
    normalizedNotice = null;
    const next = new URLSearchParams(route.params);
    if (value === '') next.delete(key); else next.set(key,value);
    if (key === 'depth' && value === 'brief') { next.delete('ch'); next.delete('metric'); }
    if (key === 'mode') next.delete('base');
    history[replace ? 'replaceState' : 'pushState'](null,'',url(page,next));
    setRoute({page,params:next,notices:[]});
    trackAnalyticsEvent('study-control', { page, control: key, value: value || 'closed' });
    if (key === 'load') {
      const [a,b] = readings(1,value);
      const state = decision(b.values.output_tps,a.values.output_tps,true);
      setLive(`${value} users selected. SGLang ${state.text} output throughput than vLLM at this recorded load.`);
    } else if (key === 'wl') {
      const [input,concurrency] = value.split('-c').map(Number);
      const cells = episode0.cells.filter(c => c.input_tokens_min === input && c.concurrency === concurrency);
      const equal = cells.length === 2 && cells[0].successful_output_tokens / cells[0].successful_requests === cells[1].successful_output_tokens / cells[1].successful_requests;
      const [a,b] = readings(0,value);
      const state = decision(b.values.output_tokens_per_second,a.values.output_tokens_per_second,true);
      setLive(`${input.toLocaleString()}-token input and ${concurrency} concurrent requests selected. ${equal ? `SGLang ${state.text} delivered output rate than vLLM.` : 'Unequal delivered work — throughput and latency are not compared.'}`);
    }
  }
  useEffect(() => {
    function esc(event: KeyboardEvent) {
      if (event.key !== 'Escape') return;
      if (epMenu) { setEpMenu(false); requestAnimationFrame(() => document.getElementById('ep-menu-btn')?.focus()); return; }
      if (siteMenu) { setSiteMenu(false); requestAnimationFrame(() => document.getElementById('site-menu-btn')?.focus()); return; }
      if (labMenu) { setLabMenu(false); requestAnimationFrame(() => document.getElementById('lab-tools-btn')?.focus()); return; }
      const metric = route.params.get('metric');
      if (metric) { setParam('metric','',true); requestAnimationFrame(() => document.querySelector<HTMLElement>(`[data-metric-tab="${metric}"], [data-metric-toggle="${metric}"]`)?.focus()); }
    }
    document.addEventListener('keydown',esc);
    return () => document.removeEventListener('keydown',esc);
  }, [epMenu, siteMenu, labMenu, route]);
  const lastChapter = useRef('');
  const smoothChapter = useRef(false);
  useEffect(() => {
    const ch = route.params.get('ch');
    const targetKey = `${page}:${ch ?? ''}`;
    if (!ch) { lastChapter.current = ''; return; }
    if (lastChapter.current === targetKey) return;
    lastChapter.current = targetKey;
    const id = `h-${ch}`;
    requestAnimationFrame(() => requestAnimationFrame(() => {
      const target = document.getElementById(id);
      if (!target) return;
      const selector = document.querySelector<HTMLElement>('.tbt-selector');
      const clearance = selector ? selector.getBoundingClientRect().height + 12 : 16;
      const top = Math.max(0, scrollY + target.getBoundingClientRect().top - clearance);
      const smooth = smoothChapter.current && !matchMedia('(prefers-reduced-motion: reduce)').matches;
      smoothChapter.current = false;
      window.scrollTo({ top, left: 0, behavior: smooth ? 'smooth' : 'instant' });
      target.focus({ preventScroll: true });
    }));
  }, [page, route.params]);
  function goChapter(ch: string) {
    const next = new URLSearchParams(route.params);
    next.set('ch',ch);
    if (isStudy && ch !== 'brief') next.set('depth','lab');
    history.replaceState(null,'',url(page,next));
    lastChapter.current = '';
    smoothChapter.current = true;
    setRoute({page,params:next,notices:[]});
    setEpMenu(false);
  }
  const epLinks = episodes.map(e => <a key={e.id} href={`#${e.id}`} aria-current={page === e.id ? 'page' : undefined}><b className={e.status === 'available' || page === e.id ? 'recorded' : 'planned'}>{String(e.number).padStart(2,'0')}</b><span><span data-episode-title>{e.title}</span>{e.status === 'planned' && <small>Planned</small>}</span></a>);
  const chapterLinks = chapters.map((ch,i) => <button key={ch} type="button" aria-current={activeChapter === ch ? 'location' : undefined} onClick={() => goChapter(ch)}><b>{String(i+1).padStart(2,'0')}</b><span>{ch === 'process' ? 'Benchmark process' : ch === 'states' ? 'Evidence states' : ch === 'protocols' ? 'Episode protocols' : ch === 'sources' ? 'Sources & credits' : ch[0].toUpperCase()+ch.slice(1)}</span></button>);
  useEngagementAnalytics(page, activeChapter);
  return <div data-tbt data-theme={shownTheme}>
    <Analytics />
    <div className="sr-only" aria-live="polite" role="status">{live}</div>
    <a className="tbt-skip" href="#main" onClick={event => { event.preventDefault(); const main = document.getElementById('main'); main?.scrollIntoView({ block: 'start' }); main?.focus({ preventScroll: true }); }}>Skip to content</a>
    <header data-screen-label="Site bar" className="tbt-sitebar">
      <div className="tbt-sitebar-inner">
        <a className="tbt-brand" href="#episodes" data-umami-event="brand-home"><img src="/token-by-token.svg" width="32" height="32" alt="" /><span><span>Token</span> <span data-brand-part="by">By</span> <span>Token</span></span></a>
        <nav aria-label="Site" className="tbt-site-nav"><a href="#episodes" aria-current={page==='episodes'?'page':undefined}>Episodes</a><a href="#methodology" aria-current={page==='methodology'?'page':undefined}>Methodology</a><button id="lab-tools-btn" type="button" aria-expanded={labMenu} onClick={() => setLabMenu(!labMenu)}>Lab tools ▾</button><a href="#episodes" data-home-link aria-label="Home"><svg aria-hidden="true" viewBox="0 0 20 20" width="17" height="17" fill="none" stroke="currentColor" strokeWidth="1.6"><path d="M3 9.2 10 3l7 6.2v7.3H12v-4.8H8v4.8H3Z" /></svg></a></nav>
        <div className="tbt-wide-links"><ExternalLinks /></div>
        <div className="tbt-theme-group" role="group" aria-label="Color theme">{(['light','dark'] as const).map(t => <button type="button" key={t} aria-pressed={theme===t} onClick={() => { applyTheme(t); setTheme(t); trackAnalyticsEvent('theme-change', { theme: t }); }}>{t}</button>)}</div>
        <button className="tbt-mobile-episodes" id="ep-menu-btn" type="button" aria-expanded={epMenu} aria-controls="ep-menu" onClick={() => { setEpMenu(!epMenu); setSiteMenu(false); }}>Episodes ▾</button>
        <button id="site-menu-btn" className="tbt-mobile-menu" type="button" aria-expanded={siteMenu} aria-controls="site-menu" onClick={() => { setSiteMenu(!siteMenu); setEpMenu(false); }}>Menu</button>
      </div>
      {labMenu && <aside id="lab-tools" className="tbt-popup" aria-labelledby="lab-tools-title"><p className="tbt-eyebrow">About the harness</p><h2 id="lab-tools-title">Benchmarking harness powered by AgentBench from <span data-mirastack-labs>Mirastack Labs</span></h2><p>Public studies expose reviewed aggregates. Private profiles, deployment recipes and raw payloads remain private.</p><a href="mailto:hello@mirastacklabs.ai">hello@mirastacklabs.ai</a></aside>}
      {siteMenu && <nav id="site-menu" className="tbt-mobile-panel" aria-label="Site"><a href="#episodes">Home</a><a href="#methodology">Methodology</a><ExternalLinks /><p>About the harness</p><small>Benchmarking harness powered by AgentBench from <span data-mirastack-labs>Mirastack Labs</span>. Contact hello@mirastacklabs.ai.</small></nav>}
      {epMenu && <nav id="ep-menu" className={`tbt-mobile-panel ${isStudy || isPlanned ? 'tbt-five-chapter' : ''}`} aria-label="Episodes and chapters">{chapters.length>0 && <><p>On this page</p>{chapterLinks}</>}<p>Episodes</p>{epLinks}</nav>}
    </header>
    <div className="tbt-layout"><nav data-screen-label="Episode rail" className="tbt-rail" aria-label="Episodes and chapters"><p>Episodes</p><div className="tbt-rail-episodes">{epLinks}</div>{chapters.length>0 && <><p>On this page</p><div className={`tbt-rail-chapters ${isStudy || isPlanned ? 'tbt-five-chapter' : ''}`}>{chapterLinks}</div></>}</nav><main id="main" tabIndex={-1}>{page==='episodes'?<Landing openEpisode={route.params.get('open')}/>:page==='methodology'?<Methodology/>:isStudy?<Study episode={episodeNumber as 0|1} route={route} setParam={setParam}/>:isPlanned?<Planned number={episodeNumber!}/>:<article><h1 id="page-title">Not in the catalog</h1><p>Nothing is published at this address.</p><a href="#episodes">All episodes</a></article>}</main></div>
  </div>;
}
