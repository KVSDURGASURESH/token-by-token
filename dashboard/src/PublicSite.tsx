import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import catalog from './data/site-v2/catalog.json';
import episode0 from './data/site-v2/episode-0.json';
import episode1 from './data/site-v2/episode-1.json';
import episode0DataUrl from './data/site-v2/episode-0.json?url';
import episode1DataUrl from './data/site-v2/episode-1.json?url';
import fieldNote from './data/site-v2/field-note.json';
import fieldNoteDataUrl from './data/site-v2/field-note.json?url';
import episode0Telemetry from './data/site-v2/episode-0-telemetry.json';
import episode0TelemetryUrl from './data/site-v2/episode-0-telemetry.json?url';
import { applyTheme, getInitialTheme, type Theme } from './theme';
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
  const resolved = page === 'recorded-study' ? 'episode-0' : page === 'session-study' ? 'field-notes' : page || 'episodes';
  const params = new URLSearchParams(query ?? '');
  const notices: string[] = [];
  const validMetric = resolved === 'episode-1' ? specs1.map(x => x.id) : resolved === 'episode-0' ? specs0.map(x => x.id) : resolved === 'field-notes' ? fieldMetrics.map(x => x.id) : [];
  const validChapter = resolved === 'methodology' ? ['definitions','states','identity','rules','protocols'] : resolved === 'episodes' ? ['recorded','notes','planned'] : [...CHAPTERS];
  for (const [key, allowed] of [['mode',['engines','loads']],['ch',validChapter],['metric',validMetric]] as [string,string[]][]) {
    if (params.has(key) && !allowed.includes(params.get(key)!)) { notices.push(`${key} is not available; showing the default.`); params.delete(key); }
  }
  if (params.has('depth') && !['brief','lab','ledger'].includes(params.get('depth')!)) { notices.push('depth is not available; showing the default.'); params.delete('depth'); }
  if (resolved !== 'episode-1') { params.delete('mode'); params.delete('base'); }
  const mode = params.get('mode') === 'loads' ? 'loads' : 'engines';
  const bases = mode === 'loads' ? measuredLoads.map(String) : ['vllm','sglang'];
  if (params.has('base') && !bases.includes(params.get('base')!)) { notices.push('baseline is not available; showing the default.'); params.delete('base'); }
  if (params.get('ch') && params.get('ch') !== 'brief' && (resolved === 'episode-0' || resolved === 'episode-1' || resolved === 'field-notes') && !['lab','ledger'].includes(params.get('depth') ?? '')) params.set('depth','lab');
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
  if (a == null || b == null || b === 0) return { symbol: '∅', text: 'Unavailable', kind: 'empty' };
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
  return <div className="tbt-externals"><a href={GITHUB_URL} target="_blank" rel="noopener noreferrer" aria-label="Source on GitHub (opens in a new tab)"><svg aria-hidden="true" width="16" height="16" viewBox="0 0 16 16" fill="currentColor"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" /></svg>GitHub <small aria-hidden="true">↗</small></a>{GRAFANA_URL && <a href={GRAFANA_URL} target="_blank" rel="noopener noreferrer" aria-label="Live Grafana dashboard, hosted separately (opens in a new tab)"><svg aria-hidden="true" width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4"><rect x="1.5" y="2" width="13" height="12" /><path d="M4 11V8.5M7 11V5.5M10 11V7M13 11V4" /></svg>Live dashboard <small aria-hidden="true">↗</small></a>}</div>;
}
function TokenStrip() {
  const tokens = ['Time', '·to', '·first', '·token', '·is', '·the', '·wait', '·a', '·user', '·feels.'];
  return <figure className="tbt-tokens"><div aria-hidden="true" className="tbt-token-row">{tokens.map((token, i) => <span data-token key={i}><b>{token}</b><small>t{String(i).padStart(2, '0')}</small></span>)}</div><figcaption><span><i className="first" />First token — TTFT</span><span><i className="later" />Every token after — TPOT</span></figcaption></figure>;
}
function Landing() {
  const recorded = episodes.filter(e => e.status === 'available');
  const planned = episodes.filter(e => e.status === 'planned');
  return <article className="tbt-landing"><header data-screen-label="Landing" className="tbt-hero"><p className="tbt-eyebrow">Token by Token · an open inference lab</p><h1 id="page-title">Every token is a measurement.</h1><p className="tbt-deck">We run open model-serving engines under recorded load and read the results one claim at a time — what a user waits for, what the hardware does, and where the evidence stops.</p><TokenStrip /><div className="tbt-cta"><a className="primary" href="#episode-0">Start with Episode 00 →</a><a className="secondary" href="#episode-1">Episode 01 · Measure what matters</a><a className="tertiary" href="#methodology">How the lab measures</a></div><p className="tbt-counts"><span>{recorded.length} recorded episodes</span><span>1 field note</span><span>{planned.length} planned</span></p></header><section id="ch-recorded" className="tbt-index-group"><h2 id="h-recorded" tabIndex={-1}>01 Recorded</h2>{recorded.map(e => <a key={e.id} href={`#${e.id}`}><b>{String(e.number).padStart(2,'0')}</b><span><strong>{e.title}</strong><small>{e.summary}</small></span><em>↗</em></a>)}</section><section id="ch-notes" className="tbt-index-group"><h2 id="h-notes" tabIndex={-1}>02 Field notes</h2><a href="#field-notes"><b>—</b><span><strong>Session capacity</strong><small>One deployment, recorded conversation load and first-token wait.</small></span><em>↗</em></a></section><section id="ch-planned" className="tbt-index-group"><h2 id="h-planned" tabIndex={-1}>03 Planned</h2>{planned.map(e => <a key={e.id} href={`#${e.id}`}><b>{String(e.number).padStart(2,'0')}</b><span><strong>{e.title}</strong><small>{e.summary}</small></span><em>↗</em></a>)}</section></article>;
}
function Selector({ episode, value, select }: { episode: 0 | 1; value: string; select(v: string, replace?: boolean): void }) {
  const stripRef = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);
  const [motion, setMotion] = useState(false);
  useLayoutEffect(() => { if (episode !== 0) return; const strip = stripRef.current; const card = strip?.querySelector<HTMLElement>(`[data-val="${value}"]`); if (strip && card) strip.scrollTo({ left: card.offsetLeft - (strip.clientWidth - card.offsetWidth) / 2, behavior: motion && !matchMedia('(prefers-reduced-motion: reduce)').matches ? 'smooth' : 'instant' }); setMotion(true); }, [episode, value]);
  const options = episode === 1 ? measuredLoads.map(String) : workloadIds;
  const index = options.indexOf(value);
  function move(next: number) { const bounded = Math.max(0, Math.min(options.length - 1, next)); select(options[bounded]); requestAnimationFrame(() => document.querySelector<HTMLElement>(`[data-seg="${episode === 1 ? 'load' : 'wl'}"][data-val="${options[bounded]}"]`)?.focus()); }
  function key(event: React.KeyboardEvent) { let next = index; if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next++; else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') next--; else if (event.key === 'Home') next = 0; else if (event.key === 'End') next = options.length - 1; else return; event.preventDefault(); move(next); }
  const point = (v: number) => `${((v - 10) / 16) * 100}%`;
  function snap(event: React.PointerEvent<HTMLDivElement>, replace: boolean, force = false) { const rect = event.currentTarget.getBoundingClientRect(); const estimated = 10 + (event.clientX - rect.left) / rect.width * 16; const nearest = measuredLoads.reduce((a, b) => Math.abs(a - estimated) <= Math.abs(b - estimated) ? a : b); if (force || String(nearest) !== value) select(String(nearest), replace); }
  return <div data-screen-label="Selector" className="tbt-selector"><span id="sel-label" className="tbt-eyebrow">{episode === 1 ? 'Measured load' : 'Recorded workload'}</span>{episode === 1 ? <div role="group" aria-labelledby="sel-label" data-track onKeyDown={key} onPointerDown={event => { if ((event.target as HTMLElement).closest('button')) return; dragging.current = true; snap(event, false, true); event.currentTarget.setPointerCapture(event.pointerId); }} onPointerMove={event => { if (dragging.current) snap(event, true); }} onPointerUp={event => { dragging.current = false; if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId); }} onPointerCancel={() => { dragging.current = false; }} className="tbt-track"><div className="tbt-track-rail" /><div className="tbt-track-fill" style={{ left: point(12), width: `${((Number(value) - 12) / 16) * 100}%` }} />{measuredLoads.map(v => <button key={v} type="button" data-seg="load" data-val={v} aria-pressed={String(v) === value} tabIndex={String(v) === value ? 0 : -1} onClick={() => select(String(v))} style={{ left: point(v) }}><i /><b>{v}</b><small>Users</small></button>)}<div className="tbt-thumb" aria-hidden="true" style={{ left: point(Number(value)) }} /></div> : <div className="tbt-workload-wrap"><button type="button" aria-label="Previous workload" disabled={index === 0} onClick={() => move(index - 1)}>←</button><div role="group" aria-labelledby="sel-label" data-strip ref={stripRef} onKeyDown={key} className="tbt-workload-strip">{workloadIds.map((id, i) => { const [input, concurrent] = id.split('-c').map(Number); const cells = episode0.cells.filter(c => c.input_tokens_min === input && c.concurrency === concurrent); const unequal = cells.length === 2 && Math.abs(cells[0].successful_output_tokens / cells[0].successful_requests - cells[1].successful_output_tokens / cells[1].successful_requests) > 1e-9; return <button type="button" key={id} data-seg="wl" data-val={id} aria-pressed={id === value} tabIndex={id === value ? 0 : -1} onClick={() => select(id)}><small>{i % 2 ? 'Stress' : 'Baseline'} · {i + 1} of 6</small><b>{input.toLocaleString()}-token input</b><small>{concurrent} concurrent request{concurrent === 1 ? '' : 's'}</small><small>{unequal ? '≠ unequal work — not compared' : '= equal work'}</small></button>; })}</div><button type="button" aria-label="Next workload" disabled={index === options.length - 1} onClick={() => move(index + 1)}>→</button></div>}<span className="tbt-selector-note">{episode === 1 ? 'Drag, tap or use ← →. Snaps to recorded loads only — the dashed rail between them was never measured.' : 'Input length and concurrency change together. These are six separate workloads, not a sweep.'}</span></div>;
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
  { id: 'gpu_memory_gib', title: 'GPU memory', unit: 'GiB', higher: false },
  { id: 'cache_context', title: 'Cache context', unit: '%', higher: false },
];
const specs0 = [
  { id: 'output_tokens_per_second', title: 'Delivered output rate', unit: 'tok/s', higher: true },
  { id: 'client_ttft_ms', title: 'TTFT p50', unit: 'ms', higher: false },
  { id: 'client_tpot_ms', title: 'TPOT p50', unit: 'ms/token', higher: false },
  { id: 'client_e2e_ms', title: 'End-to-end p50', unit: 'ms', higher: false },
  { id: 'client_itl_ms', title: 'Inter-token latency p50', unit: 'ms', higher: false },
  { id: 'work_per_request', title: 'Delivered output per request', unit: 'tok/req', higher: true },
];
function readings(episode: 0 | 1, value: string) {
  if (episode === 1) return episode1.arms.map(arm => ({ name: arm.engine, values: Object.fromEntries(Object.entries(arm.points.find(p => p.users === Number(value))?.readings ?? {}).map(([key, reading]) => [key, reading.value])) as Record<string, number | null> }));
  const [input, concurrency] = value.split('-c').map(Number);
  return ['vLLM', 'SGLang'].map(name => { const cell = episode0.cells.find(c => c.runtime === name && c.input_tokens_min === input && c.concurrency === concurrency); return { name, values: { output_tokens_per_second: cell?.output_tokens_per_second ?? null, client_ttft_ms: cell?.client_ttft_ms.p50 ?? null, client_tpot_ms: cell?.client_tpot_ms.p50 ?? null, client_e2e_ms: cell?.client_e2e_ms.p50 ?? null, client_itl_ms: cell?.client_itl_ms.p50 ?? null, work_per_request: cell ? cell.successful_output_tokens / cell.successful_requests : null } as Record<string, number | null> }; });
}
function MetricPlot({ episode, metric, selected, mode, baseline }: { episode: 0 | 1; metric: string; selected: string; mode?: string; baseline?: string }) {
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
  return <svg data-plot viewBox="0 0 280 108" role="img" aria-label={`${metric} across recorded ${episode === 1 ? 'loads' : 'workloads'}`}><rect x={18 + xs.indexOf(selected) * 244 / xs.length} y="0" width={244 / xs.length} height="88" fill="var(--panel)" /><line x1="18" x2="262" y1="88" y2="88" stroke="var(--line-strong)" />{episode === 1 && mode === 'loads' && baseline && <line data-reference="Selected baseline load" x1={x(xs.indexOf(baseline))} x2={x(xs.indexOf(baseline))} y1="8" y2="88" stroke="var(--neutral)" strokeDasharray="3 3" aria-label={`${baseline} users: selected baseline load for both engines`} />}{references.map(reference => <line key={reference.name} data-reference={reference.name} x1="18" x2="262" y1={y(reference.value)} y2={y(reference.value)} stroke="var(--neutral)" strokeDasharray="3 3" aria-label={`${reference.name}: ${reference.value}`} />)}{episode === 1 && <><path d={path(0)} fill="none" stroke="var(--ink)" strokeWidth="1.5" /><path d={path(1)} fill="none" stroke="var(--muted)" strokeWidth="1.5" strokeDasharray="5 4" /></>}{series.flatMap((pair,i) => pair.map((row,k) => { const v = row.values[metric]; if (v == null) return null; return k === 0 ? <circle key={`${i}-${k}`} cx={x(i) - (episode === 0 ? 4 : 0)} cy={y(v)} r="3" fill="var(--paper)" stroke="var(--ink)" strokeWidth="1.5" /> : <rect key={`${i}-${k}`} x={x(i) - (episode === 0 ? -1 : 3)} y={y(v) - 3} width="6" height="6" transform={`rotate(45 ${x(i)} ${y(v)})`} fill="var(--paper)" stroke="var(--muted)" strokeWidth="1.5" />; }))}{xs.map((val,i) => <text key={val} x={x(i)} y="99" textAnchor="middle" fill="var(--muted)" fontSize="8">{episode === 1 ? val : <><tspan x={x(i)}>{Number(val.split('-c')[0]).toLocaleString()}</tspan><tspan x={x(i)} dy="8">c{val.split('-c')[1]}</tspan></>}</text>)}</svg>;
}
function EvidenceControls({ route, selected, setParam }: { route: Route; selected: string; setParam(key: string, value: string, replace?: boolean): void }) {
  const mode = route.params.get('mode') === 'loads' ? 'loads' : 'engines';
  const baseOptions = mode === 'loads' ? measuredLoads.map(String) : ['vllm', 'sglang'];
  const requested = route.params.get('base');
  const baseline = requested && baseOptions.includes(requested) ? requested : mode === 'loads' ? selected === '12' ? '16' : '12' : 'vllm';
  function key(event: React.KeyboardEvent<HTMLDivElement>, options: string[], current: string, pick: (v: string) => void, segment: string) {
    const i = options.indexOf(current);
    const j = event.key === 'Home' ? 0 : event.key === 'End' ? options.length - 1 : event.key === 'ArrowRight' || event.key === 'ArrowDown' ? Math.min(options.length - 1, i + 1) : event.key === 'ArrowLeft' || event.key === 'ArrowUp' ? Math.max(0, i - 1) : -1;
    if (j < 0) return;
    event.preventDefault(); pick(options[j]); requestAnimationFrame(() => document.querySelector<HTMLElement>(`[data-seg="${segment}"][data-val="${options[j]}"]`)?.focus());
  }
  return <div className="tbt-compare-controls"><div><span id="mode-label" className="tbt-eyebrow">Comparison</span><div role="group" aria-labelledby="mode-label" onKeyDown={event => key(event, ['engines', 'loads'], mode, v => setParam('mode', v), 'mode')}>{[['engines','Engines at this load'],['loads','Loads within each engine']].map(([v,label]) => <button key={v} type="button" data-seg="mode" data-val={v} aria-pressed={mode === v} tabIndex={mode === v ? 0 : -1} onClick={() => setParam('mode', v)}>{label}</button>)}</div></div><div><span id="base-label" className="tbt-eyebrow">{mode === 'loads' ? 'Baseline load' : 'Baseline engine'}</span><div role="group" aria-labelledby="base-label" onKeyDown={event => key(event, baseOptions, baseline, v => setParam('base', v), 'base')}>{baseOptions.map(v => <button key={v} type="button" data-seg="base" data-val={v} aria-pressed={baseline === v} tabIndex={baseline === v ? 0 : -1} onClick={() => setParam('base', v)}>{v === 'vllm' ? 'vLLM' : v === 'sglang' ? 'SGLang' : v}</button>)}</div></div><p>Operands: {mode === 'loads' ? `vLLM at ${selected} versus ${baseline} users, and SGLang at ${selected} versus ${baseline} users; each engine is its own baseline.` : `${baseline === 'vllm' ? 'SGLang' : 'vLLM'} is the subject and ${baseline === 'vllm' ? 'vLLM' : 'SGLang'} is the baseline, both at ${selected} users.`}</p></div>;
}
type MetricSpec = { id: string; title: string; unit: string; higher: boolean };
const evidenceNotes: Record<string, string> = {
  output_tokens_per_second: 'Rate rises with concurrency, but delivered output per request must match before ranking.',
  client_ttft_ms: 'Input length and concurrency change together, so first-token time cannot be attributed to either alone.',
  client_tpot_ms: 'Per-token time describes the visible stream after its first token.',
  client_e2e_ms: 'End-to-end time includes waiting and decoding, so it is not the same as TTFT.',
  client_itl_ms: 'Inter-token latency describes gaps between streamed chunks.',
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
  gpu_memory_gib: 'Memory is reserved up front and remains a contextual device reading.',
  cache_context: 'Not available with a comparable public definition.'
};
function EvidenceChapter({ episode, value, route, setParam }: { episode: 0 | 1; value: string; route: Route; setParam(key: string, value: string, replace?: boolean): void }) {
  const [windowWidth, setWindowWidth] = useState(innerWidth);
  useEffect(() => { const update = () => setWindowWidth(innerWidth); addEventListener('resize', update); return () => removeEventListener('resize', update); }, []);
  const mainWidth = windowWidth >= 981 ? Math.min(1040, windowWidth - 348) : windowWidth - 32;
  const columns = mainWidth >= 860 ? 3 : mainWidth >= 520 ? 2 : 1;
  const rows = readings(episode, value);
  const mode = route.params.get('mode') === 'loads' ? 'loads' : 'engines';
  const baseOptions = mode === 'loads' ? measuredLoads.map(String) : ['vllm', 'sglang'];
  const requestedBase = route.params.get('base');
  const baseline = requestedBase && baseOptions.includes(requestedBase) ? requestedBase : mode === 'loads' ? value === '12' ? '16' : '12' : 'vllm';
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
  const selectedMetric = route.params.get('metric');
  const evidenceTitle = episode === 1 ? mode === 'loads' ? `Loads compared with ${baseline} users` : `Engines at ${value} users` : `${input.toLocaleString()}-token input · ${concurrency} concurrent`;
  const lede = episode === 1 ? mode === 'loads' ? baseline === value ? 'The baseline equals the selected load, so there is no change to report. Choose another baseline, or move the measured load.' : `Each engine at ${value} users relative to itself at ${baseline} users. The engines are not compared with each other in this mode.` : `${baseline === 'vllm' ? 'SGLang' : 'vLLM'} relative to ${baseline === 'vllm' ? 'vLLM' : 'SGLang'} for the selected load only.` : equalWork ? 'SGLang relative to vLLM for the selected workload only. Workloads are never compared with each other.' : 'This workload delivered unequal work, so values are shown without better or worse. Every other workload remains selectable above.';
  const operands = episode === 1 ? mode === 'loads' ? `Directional operands: vLLM at ${value} users versus vLLM at ${baseline} users, and SGLang at ${value} users versus SGLang at ${baseline} users. Each engine is compared only with itself.` : `Directional operands: ${baseline === 'vllm' ? 'SGLang' : 'vLLM'} (subject) versus ${baseline === 'vllm' ? 'vLLM' : 'SGLang'} (baseline), both at ${value} users.` : `Directional operands: SGLang (subject) versus vLLM (baseline) at the ${input.toLocaleString()}-token, ${concurrency}-concurrent workload${equalWork ? ', after the equal delivered-work gate.' : '; unequal delivered work blocks ranking.'}`;
  function metricStates(spec: MetricSpec) {
    const a = rows[0].values[spec.id], b = rows[1].values[spec.id];
    if (spec.id === 'cache_context') return [{ symbol: '∅', text: 'Unavailable', kind: 'empty' }];
    if (spec.id === 'work_per_request') return [{ symbol: equalWork ? '=' : '≠', text: equalWork ? 'Equal delivered work' : 'Unequal work — not compared', kind: equalWork ? 'equal' : 'band' }];
    if (episode === 1 && (spec.id === 'decode_p10_tps' || spec.id === 'error_rate_pct')) return rows.map(row => { const v = row.values[spec.id]; const good = v != null && (spec.id === 'decode_p10_tps' ? v >= 20 : v <= 1); return { symbol: v == null ? '∅' : good ? spec.id === 'decode_p10_tps' ? '≥' : '≤' : spec.id === 'decode_p10_tps' ? '<' : '>', text: `${row.name} · ${v == null ? 'Unavailable' : good ? spec.id === 'decode_p10_tps' ? 'Meets 20 tok/s floor' : 'Within 1% validity limit' : spec.id === 'decode_p10_tps' ? 'Below 20 tok/s floor' : 'Over 1% validity limit'}`, kind: v == null ? 'empty' : good ? 'better' : 'worse' }; });
    if (episode === 1 && metrics.indexOf(spec) >= 6) return rows.map(row => ({ symbol: '△', text: `${row.name} · Context only — not ranked`, kind: 'context' }));
    if (!equalWork) return [{ symbol: '≠', text: 'Unequal work — not compared', kind: 'band' }];
    if (episode === 1 && mode === 'loads') return rows.map(row => baseline === value ? { symbol: '∅', text: `${row.name} · No change computed`, kind: 'empty' } : { ...decision(row.values[spec.id], readings(1, baseline).find(baselineRow => baselineRow.name === row.name)?.values[spec.id], spec.higher), name: row.name, text: `${row.name} · ${decision(row.values[spec.id], readings(1, baseline).find(baselineRow => baselineRow.name === row.name)?.values[spec.id], spec.higher).text}` });
    return [decision(baseline === 'sglang' && episode === 1 ? a : b, baseline === 'sglang' && episode === 1 ? b : a, spec.higher)];
  }
  function card(spec: MetricSpec) {
    const states = metricStates(spec);
    const context = episode === 1 && metrics.indexOf(spec) >= 6;
    const subjectIndex = episode === 1 && mode === 'engines' && baseline === 'sglang' ? 0 : 1;
    const ranked = !context && equalWork && spec.id !== 'work_per_request' && spec.id !== 'cache_context' && spec.id !== 'decode_p10_tps' && spec.id !== 'error_rate_pct';
    const selectedState = states[0]?.kind;
    const direction = spec.id === 'work_per_request' ? 'Equal work required' : context ? 'Context only' : spec.id === 'decode_p10_tps' ? 'Floor ≥ 20 tok/s' : spec.id === 'error_rate_pct' ? 'Limit ≤ 1%' : spec.higher ? 'Higher is better' : 'Lower is better';
    return <button type="button" data-metric={spec.id} aria-expanded={selectedMetric === spec.id} aria-controls={`ex-${spec.id}`} onClick={() => setParam('metric', selectedMetric === spec.id ? '' : spec.id, true)} className="tbt-plot-card"><span className="tbt-plot-header"><b>{spec.title}</b><small>{direction}</small></span>{spec.id === 'cache_context' ? <span className="tbt-plot-unavailable">∅ Unavailable — {evidenceNotes[spec.id]}</span> : <MetricPlot episode={episode} metric={spec.id} selected={value} mode={mode} baseline={baseline} />}<span className="tbt-plot-values">{rows.map((row,i) => <span data-plot-value key={row.name}><span aria-hidden="true">{i===0?'●':'◆'}</span> {row.name} <b className={ranked && (mode === 'loads' || i === subjectIndex) ? `state-${mode === 'loads' ? states[i]?.kind : selectedState}` : ''}>{format(row.values[spec.id],spec.unit)}</b></span>)}</span><span className="tbt-plot-states">{states.map((state,i) => <span key={i} className={`state-${state.kind}`}>{state.symbol} {state.text}</span>)}</span><span className="tbt-plot-notice">{evidenceNotes[spec.id]}</span></button>;
  }
  function explanation(spec: MetricSpec) {
    const definition = episode === 1 ? episode1.metric_definitions.find(m => m.id === spec.id)?.explanation : evidenceNotes[spec.id];
    const kind = spec.id === 'work_per_request' ? 'Delivered work equality gate' : spec.id === 'decode_p10_tps' || spec.id === 'error_rate_pct' ? 'Declared threshold for each engine' : episode === 1 && specs1.indexOf(spec) >= 6 ? 'Context only — not ranked' : 'Directional comparison';
    const rule = spec.id === 'work_per_request' ? 'Equal delivered output per successful request is required before throughput and latency can be ranked.' : spec.id === 'decode_p10_tps' ? 'Each engine is judged against the declared 20 tok/s decode floor.' : spec.id === 'error_rate_pct' ? 'Each engine is judged against the declared 1% validity limit.' : kind.startsWith('Context') ? 'These runtime or device readings describe conditions and have no better direction.' : `${spec.higher ? 'Higher' : 'Lower'} is better. Changes under ±2% are shown in a descriptive display band, not a significance test.`;
    const states = metricStates(spec);
    const metricOperands = spec.id === 'work_per_request' ? `Equality operands: SGLang and vLLM delivered output per successful request at the ${input.toLocaleString()}-token, ${concurrency}-concurrent workload. Equality gates the directional comparisons.` : spec.id === 'decode_p10_tps' ? `Threshold operands at ${value} users: each engine’s decode p10 versus Episode 01’s declared 20 tok/s floor; engines are not compared with each other for this gate.` : spec.id === 'error_rate_pct' ? `Threshold operands at ${value} users: each engine’s error rate versus Episode 01’s declared 1% limit; engines are not compared with each other for this gate.` : kind.startsWith('Context') ? `Context at ${value} users: vLLM and SGLang values are shown by identity without ranking.` : operands;
    return <div id={`ex-${spec.id}`} role="region" aria-label={`Explanation: ${spec.title}`} className="tbt-explanation-row"><div><small>Explaining</small><h4>{spec.title}</h4><p>{definition}</p><dl><dt>Evidence kind</dt><dd>{kind}</dd><dt>Rule</dt><dd>{rule}</dd><dt>Unit</dt><dd>{spec.unit}</dd><dt>Source</dt><dd>{episode === 1 ? 'Public aggregate evidence' : spec.id === 'work_per_request' ? 'Client results' : 'Client stream events'}</dd></dl></div><div><small>Comparison</small><p>{metricOperands}</p><small>Selected states</small>{states.map((state,i) => <p key={i} className={`state-${state.kind}`}>{state.symbol} {state.text}</p>)}<small>What to notice</small><p>{evidenceNotes[spec.id]}</p></div><div><small>Exact recorded values</small><div className="tbt-ledger"><table><thead><tr><th>Identity</th>{(episode === 1 ? measuredLoads.map(String) : workloadIds).map(x => <th key={x}>{episode === 1 ? `${x} users` : x}</th>)}</tr></thead><tbody>{['vLLM','SGLang'].map(name => <tr key={name}><th>{name}</th>{(episode === 1 ? measuredLoads.map(String) : workloadIds).map(x => <td key={x} className={x === value ? 'selected' : ''}>{format(readings(episode,x).find(row => row.name === name)?.values[spec.id],spec.unit)}</td>)}</tr>)}</tbody></table></div><button type="button" onClick={() => { setParam('metric','',true); requestAnimationFrame(() => document.querySelector<HTMLElement>(`[data-metric="${spec.id}"]`)?.focus()); }}>Close explanation</button></div></div>;
  }
  return <section id="ch-evidence" data-screen-label="03 Evidence" className="tbt-chapter"><ChapterHeading number={3} title="Evidence" heading={evidenceTitle} id="evidence" /><p>{lede}</p>{episode === 1 && <EvidenceControls route={route} selected={value} setParam={setParam} />}<p className="tbt-operands">{operands}</p><div data-identity-legend className="tbt-identity-legend"><span>● ── vLLM</span><span>◆ ╌╌ SGLang</span><span>Shaded column — selected load · vertical dashed rule — baseline load · horizontal dashed rule — baseline engine value or declared threshold</span></div>{groups.map(group => <div data-evidence-group key={group.title} className="tbt-evidence-group"><h3><span>{group.title}</span><small>{group.note}</small></h3>{Array.from({length:Math.ceil(group.metrics.length / columns)},(_,i) => { const segment = group.metrics.slice(i*columns,(i+1)*columns); const opened = segment.find(spec => spec.id === selectedMetric); return <div key={i}><div className="tbt-plot-row" style={{gridTemplateColumns:`repeat(${columns},minmax(0,1fr))`}}>{segment.map(spec => <div key={spec.id}>{card(spec)}</div>)}</div>{opened && explanation(opened)}</div>; })}</div>)}{episode === 0 && <><div data-workload-telemetry className="tbt-evidence-group"><h3><span>Workload-level telemetry</span><small>For the selected workload. Medians of repetition-level readings; definitions are runtime-native.</small></h3><div className="tbt-ledger"><table><thead><tr><th>Reading · context only</th><th>● vLLM</th><th>◆ SGLang</th></tr></thead><tbody>{(() => { const t = episode0Telemetry.workloads.find(x => x.id === value); return t ? <><tr><th>KV cache peak</th><td>{format(t.engines.vLLM.kv_cache_peak*100,'%')}</td><td>{format(t.engines.SGLang.kv_cache_peak*100,'%')}</td></tr><tr><th>Waiting requests peak</th><td>{format(t.engines.vLLM.waiting_requests_peak,'req')}</td><td>{format(t.engines.SGLang.waiting_requests_peak,'req')}</td></tr><tr><th>Prefill duration (native)</th><td>{format(t.engines.vLLM.prefill_duration_seconds,'s',2)}</td><td>∅ Not exposed by this runtime</td></tr><tr><th>Decode duration (native)</th><td>{format(t.engines.vLLM.decode_duration_seconds,'s',2)}</td><td>∅ Not exposed by this runtime</td></tr></> : null; })()}</tbody></table></div></div><div className="tbt-evidence-group"><h3><span>Run-level device telemetry</span><small>One peak spans three workloads. It does not change with the selected workload and is not attributable to one workload.</small></h3><div className="tbt-run-telemetry">{(['Baseline','Stress'] as const).map(tier => <article key={tier} data-run-telemetry><h4>{tier} run</h4><p>Spans {episode0Telemetry.workloads.filter(w => w.tier === tier).map(w => w.id).join(', ')} · {episode0Telemetry.workloads.find(w => w.id === value)?.tier === tier ? 'Contains the selected workload' : 'Does not contain the selected workload'}</p>{(['V','S'] as const).map(engine => { const item = episode0Telemetry.runs[tier][engine]; return <p key={engine}>{engine === 'V' ? '● vLLM' : '◆ SGLang'} util {item.utilization_pct}% · mem {format(item.memory_mib/1024,'GiB')} · power {format(item.power_w,'W',0)} · {item.temperature_c} °C · {item.samples} samples</p>; })}</article>)}</div></div></>}<p className="tbt-validity">{episode === 1 ? episode1.arms.map(arm => { const point = arm.points.find(point => point.users === Number(value))!; return <span key={arm.engine}>{arm.engine === 'vLLM' ? '●' : '◆'} {arm.engine} · {point.valid_requests}/{point.total_requests} valid requests · level {point.level_valid ? 'valid' : 'invalid'}</span>; }) : <>● vLLM · recorded valid requests <span>◆ SGLang · recorded valid requests</span></>}</p><button className="tbt-ledger-toggle" type="button" aria-expanded={route.params.get('depth') === 'ledger'} onClick={() => setParam('depth',route.params.get('depth') === 'ledger' ? 'lab' : 'ledger')}>Exact measurement ledger <span>{route.params.get('depth') === 'ledger' ? 'Hide' : 'Show'}</span></button>{route.params.get('depth') === 'ledger' && <div className="tbt-ledger tbt-wide-ledger"><table><thead><tr><th>Metric</th>{['vLLM','SGLang'].flatMap(name => (episode === 1 ? measuredLoads.map(String) : workloadIds).map(x => <th key={`${name}-${x}`}>{name} · {x}</th>))}<th>Selected comparison</th></tr></thead><tbody>{metrics.map(spec => <tr key={spec.id}><th>{spec.title} ({spec.unit})</th>{['vLLM','SGLang'].flatMap(name => (episode === 1 ? measuredLoads.map(String) : workloadIds).map(x => <td key={`${name}-${x}`} className={x === value ? 'selected' : ''}>{format(readings(episode,x).find(row => row.name === name)?.values[spec.id],spec.unit)}</td>))}<td>{metricStates(spec).map((state,i) => <span key={i} className={`state-${state.kind}`}>{state.symbol} {state.text}<br /></span>)}</td></tr>)}</tbody></table></div>}</section>;
}

function BoundariesChapter({ episode }: { episode: 0 | 1 }) {
  const one = episode === 1;
  const blocks = one ? [
    ['Matched', ['One H200 per recorded arm', 'Same model family and precision', 'Same synthetic session population, users, slots, warm-up and window', 'Same client measurement and validity contract']],
    ['Deployment-specific', ['Private serving details are withheld', 'Runtime-native gauge definitions', 'Cache accounting is not comparable, so not ranked']],
    ['Observed', [`At ${measuredLoads[0]} and ${measuredLoads[1]} users SGLang recorded more output and lower median TTFT than vLLM`, `At ${measuredLoads[2]} users the output difference reversed and median TTFT fell inside the display band`, `Both met the decode floor at ${measuredLoads[0]} users; both fell below it at ${measuredLoads[1]} and ${measuredLoads[2]}`]],
    ['Not established', ['Capacity under the declared service objectives', 'Statistical significance of any difference', 'Engine-only causation', 'Behaviour between the recorded loads']]
  ] : [
    ['Compatibility', ['Both engines used the same hardware class, model family, precision, prompt construction, sampling contract and client harness within each workload.', 'Private serving details are withheld.']],
    ['Exclusions', ['Other engines were not measured; their deployment contracts did not fit this study’s environment.', 'Kernel-level tracing was unavailable in the measurement environment.', 'Goodput is unavailable because no latency objective was declared before measurement.']],
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
    ...(!one ? [['Workload and run telemetry', <a href={episode0TelemetryUrl} download="episode-0-public-telemetry.json">Download episode-0-public-telemetry.json — contextual telemetry from approved design handoff</a>]] as [string, React.ReactNode][] : []),
    ['Schema', schema],
    ['Public command', 'A public command-line evidence reader is proposed, not released. No command is offered until it exists and is tested.'],
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
    ['Validity limit', '≤ 1% of measured requests failing the validity contract'],
    ['Withheld', 'Private serving details are not published.']
  ] : [
    ['Workloads', '128-token input at 1 and 16 concurrent; 2,048 at 4 and 24; 8,192 at 8 and 32'],
    ['Tiers', 'Baseline (1, 4, 8 concurrent) and Stress (16, 24, 32 concurrent)'],
    ['Repetitions', '3 per baseline workload · 2 per stress workload'],
    ['Matched', 'Hardware class, model, precision, prompt construction, sampling contract and client harness'],
    ['Telemetry scope', 'Queue, KV and phase readings are per workload. GPU peaks are per run and span a whole tier.'],
    ['Withheld', 'Private serving details are not published.']
  ];
  const anatomyOptions = {
    ttft: { name: 'TTFT', left: '0%', width: '38%', text: 'time to first token: queueing, prefill and the first token together. This is the wait a user sees.' },
    tpot: { name: 'TPOT', left: '38%', width: '62%', text: 'time per output token after the first: decode duration divided by the remaining tokens.' },
    decode: { name: 'Decode p10', left: '38%', width: '62%', text: 'decode speed in tokens per second; p10 is the speed 90% of requests met or beat.' },
    e2e: { name: 'End-to-end', left: '0%', width: '100%', text: 'from request sent to final token received.' }
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
    'Capacity was not established under the declared service objectives.',
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
  return <section id="ch-brief" data-screen-label="01 Brief" className="tbt-chapter tbt-brief"><h2 id="h-brief" tabIndex={-1} className="tbt-brief-heading"><span aria-hidden="true" className="tbt-chapter-bar" />01 Brief</h2><p className="tbt-finding">{episode === 0 && !equalWork ? <>{intro}the engines delivered <span className="state-band">≠ unequal work</span> — vLLM {format(vllmWork ? vllmWork.successful_output_tokens / vllmWork.successful_requests : null, 'tokens per request')} vs SGLang {format(sglangWork ? sglangWork.successful_output_tokens / sglangWork.successful_requests : null, 'tokens per request')} — so throughput and latency are not compared.</> : <>{intro}SGLang recorded <span className={`state-${outputState.kind}`}>{outputState.symbol} {pct(outputA,outputB)} {outputA != null && outputB != null && outputA >= outputB ? episode === 1 ? 'more output' : 'higher output rate' : episode === 1 ? 'less output' : 'lower output rate'}</span> and <span className={`state-${ttftState.kind}`}>{ttftState.symbol} {pct(ttftA,ttftB)} {ttftA != null && ttftB != null && ttftA <= ttftB ? 'lower' : 'higher'} median TTFT</span> than vLLM.</>}</p><p className="tbt-small">{episode === 0 && !equalWork ? 'Comparison withheld for this workload: delivered output per request differs between engines.' : `Change = (SGLang − vLLM) ÷ vLLM ${episode === 1 ? `at ${value} users` : 'for this workload'}. Under ±2% shows as ≈ — a descriptive band, not a significance test.`}</p><div className="tbt-brief-table-wrap"><table className="tbt-brief-table"><tbody>{specs.map(spec => { const state = stateFor(spec); const rankable = equalWork && spec.id !== 'work_per_request' && spec.id !== 'decode_p10_tps'; return <tr key={spec.id}><th><b>{spec.title}</b><small>{spec.id === 'work_per_request' ? 'Equal work is required to compare' : spec.id === 'decode_p10_tps' ? 'Threshold ≥ 20 tok/s' : spec.higher ? 'Higher is better' : 'Lower is better'}</small></th><td><small>● vLLM</small><b>{format(a.values[spec.id],spec.unit)}</b></td><td><small>◆ SGLang</small><b className={rankable ? `state-${state.kind}` : ''}>{format(b.values[spec.id],spec.unit)}</b></td><td className={`state-${state.kind}`}>{state.symbol} {state.text}<small>SGLang vs vLLM</small></td></tr>; })}</tbody></table></div><div className="tbt-caveat"><h3>What this does not say</h3><ul>{caveats.map(item => <li key={item}>{item}</li>)}</ul></div><dl className="tbt-apparatus"><div><dt>Hardware</dt><dd>{episode === 1 ? 'One H200 per recorded arm' : 'One H100 per run'}</dd></div><div><dt>Engines</dt><dd>● vLLM · ◆ SGLang</dd></div><div><dt>Model</dt><dd>Matched model family</dd></div><div><dt>{episode === 1 ? 'Window' : 'Requests'}</dt><dd>{episode === 1 ? `${episode1.methodology.measurement_seconds} s measured per load` : `${(vllmWork?.successful_requests ?? 0) + (sglangWork?.successful_requests ?? 0)} measured`}</dd></div></dl><button id="lab-toggle" ref={toggleRef} type="button" aria-expanded={lab} aria-controls="lab" onClick={toggleLab} className="tbt-lab-toggle">{lab ? 'Collapse lab ↑' : 'Open evidence lab ↓'}</button></section>;
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
  const question = episode === 1 ? 'What breaks first when two inference engines meet the same H200 workload?' : 'What happens to one request as prompts grow longer and the queue gets busier?';
  const deck = episode === 1 ? 'What did vLLM and SGLang deliver at three matched loads on one H200?' : 'What did vLLM and SGLang deliver across six workloads on one H100?';
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
  const toggleLab = () => { if (lab) { setLab(false); setParam('depth', 'brief'); requestAnimationFrame(() => toggleRef.current?.focus()); } else { setLab(true); setParam('depth', 'lab'); requestAnimationFrame(() => document.getElementById('h-method')?.focus()); } };
  useEffect(() => { setLab(route.params.get('depth') === 'lab' || route.params.get('depth') === 'ledger' || (route.params.has('ch') && route.params.get('ch') !== 'brief')); }, [route.page, route.params]);
  return <article className="tbt-study">{route.notices.length>0&&<div className="tbt-notice" role="status"><b>Link adjusted</b> {route.notices.join(' ')}</div>}{invalid && <div className="tbt-notice" role="status"><b>Link adjusted</b> {route.params.get(key)} is not recorded. Showing {value}.</div>}<header data-screen-label="Episode header" className="tbt-study-header">{route.params.get('head') === 'question' ? <><p className="tbt-eyebrow">Episode {String(episode).padStart(2,'0')} <strong>{title}</strong> · Recorded study</p><h1 id="page-title" className="question">{question}</h1></> : <><p className="tbt-eyebrow">Episode {String(episode).padStart(2,'0')} · Recorded study</p><h1 id="page-title">{title}</h1></>}<p className="tbt-deck">{deck}</p><p className="tbt-quals"><span>Recorded exploratory comparison</span><span>{episode === 1 ? 'One H200 per arm' : 'One H100 per run'}</span><span>Capacity not established</span></p></header><Selector episode={episode} value={value} select={(v, replace) => setParam(key, v, replace)} /><BriefChapter episode={episode} value={value} rows={rows} equalWork={equalWork} lab={lab} toggleLab={toggleLab} toggleRef={toggleRef} />{lab && <div id="lab"><MethodChapter episode={episode} /><EvidenceChapter episode={episode} value={value} route={route} setParam={setParam} /><BoundariesChapter episode={episode} /><SourceChapter episode={episode} route={route} /></div>}<EpisodePager number={episode} /></article>;
}
function Planned({ number }: { number: number }) { const e = episodes.find(e => e.number === number)!; return <article className="tbt-study"><header className="tbt-study-header"><p className="tbt-eyebrow">Episode {String(number).padStart(2,'0')} · Planned</p><h1 id="page-title">{e.title}</h1><p className="tbt-deck">{e.summary}</p><p className="tbt-quals">Planned — no measurements</p></header>{CHAPTERS.map((title,i) => <section id={`ch-${title}`} key={title} className="tbt-chapter"><ChapterHeading number={i+1} title={title[0].toUpperCase()+title.slice(1)} id={title} /><p>{i === 0 ? 'No recorded evidence yet. Nothing on this page is a result.' : i === 1 ? e.summary : i === 2 ? 'No measurements or comparison are available.' : i === 3 ? 'A finding appears only after a recorded run is published.' : 'Read the roadmap for this planned study.'}</p>{i === 4 && <a href={`${GITHUB_URL}/blob/main/docs/roadmap.md#${e.roadmapAnchor}`}>Roadmap ↗</a>}</section>)}<EpisodePager number={number} /></article>; }
function Methodology() {
  const glossary = [
    ['Output throughput', 'Successful output tokens divided by measured seconds. Higher is better only when delivered work is comparable.'],
    ['TTFT p50 / p95', 'Client-visible time from request to first token. p50 is the median; p95 describes the slower tail. Lower is better.'],
    ['TPOT p50', 'Median time per generated output token after the first token. Lower is better.'],
    ['Decode p10', 'Per-request decode speed at the tenth percentile: 90% of valid requests meet or exceed it. Episode 01 alone declares a 20 tok/s floor; other studies need their own declared gate.'],
    ['Error rate', 'Failed or invalid requests divided by measured requests. Episode 01 alone declares a 1% validity limit. The Field Note has no declared validity limit.'],
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
    ['∅ Unavailable', 'No comparable recorded value exists; no estimate is drawn.'],
    ['Invalid level', 'A measured load fails its protocol’s validity contract. Request counts and the level-valid flag remain visible; invalid evidence cannot qualify capacity.']
  ];
  return <article className="tbt-study tbt-methodology"><header className="tbt-study-header"><p className="tbt-eyebrow">Methodology · applies to all episodes</p><h1 id="page-title">How the lab measures</h1><p className="tbt-deck">Definitions and evidence rules shared by every episode. Each episode’s own protocol lives in its Method chapter.</p></header><section className="tbt-chapter" id="ch-definitions"><h2 id="h-definitions" tabIndex={-1}>01 Definitions</h2><dl className="tbt-protocol">{glossary.map(([term,definition]) => <div key={term}><dt>{term}</dt><dd>{definition}</dd></div>)}</dl></section><section className="tbt-chapter" id="ch-states"><h2 id="h-states" tabIndex={-1}>02 Evidence states</h2><dl className="tbt-protocol">{states.map(([term,definition]) => <div key={term}><dt>{term}</dt><dd>{definition}</dd></div>)}</dl></section><section className="tbt-chapter" id="ch-identity"><h2 id="h-identity" tabIndex={-1}>03 Identity</h2><p>vLLM uses a circle and solid line; SGLang uses a diamond and dashed line. Field Note names Deployment A and B because hardware differs. Each plotted value and state retains its identity.</p></section><section className="tbt-chapter" id="ch-rules"><h2 id="h-rules" tabIndex={-1}>04 Rules</h2><p>Compare only recorded loads or matched workloads. A selected baseline supplies the comparison reference; declared thresholds use their own fixed rules. Missing values remain unavailable. A line connecting measured loads is a reading aid, not an interpolated measurement.</p></section><section className="tbt-chapter" id="ch-protocols"><h2 id="h-protocols" tabIndex={-1}>05 Episode protocols</h2><p><a href="#episode-0?depth=lab&ch=method">Episode 00 method</a> · <a href="#episode-1?depth=lab&ch=method">Episode 01 method</a> · <a href="#field-notes?depth=lab&ch=method">Field Note method</a></p></section></article>;
}
function fieldValue(point: Record<string, unknown>, id: string) { const value = point[id] as number; return id === 'error_rate' ? value * 100 : value; }
const fieldMetrics = [
  { id: 'output_tps', title: 'Output throughput', unit: 'tok/s', higher: true },
  { id: 'visible_ttft_p50_s', title: 'Visible TTFT p50', unit: 's', higher: false },
  { id: 'visible_ttft_p95_s', title: 'Visible TTFT p95', unit: 's', higher: false },
  { id: 'error_rate', title: 'Error rate', unit: '%', higher: false }
] as const;
function FieldNote({ route, setParam }: { route: Route; setParam(key: string, value: string, replace?: boolean): void }) {
  const [lab, setLab] = useState(route.params.get('depth') === 'lab' || route.params.get('depth') === 'ledger' || (route.params.has('ch') && route.params.get('ch') !== 'brief'));
  const [openMetric, setOpenMetric] = useState<string | null>(route.params.get('metric'));
  const toggleRef = useRef<HTMLButtonElement>(null);
  const loads = fieldNote.levels.map(Number);
  const users = loads.includes(Number(route.params.get('users'))) ? Number(route.params.get('users')) : 16;
  const invalid = route.params.has('users') && !loads.includes(Number(route.params.get('users')));
  const [A, B] = fieldNote.deployments;
  const sweepA = A.sweep.find(point => point.users === users)!;
  const sweepB = B.sweep.find(point => point.users === users)!;
  const soakDelta = decision(B.soak.output_tps,A.soak.output_tps,true);
  const soakTtft = decision(B.soak.visible_ttft_p50_s,A.soak.visible_ttft_p50_s,false);
  useEffect(() => { setLab(route.params.get('depth') === 'lab' || route.params.get('depth') === 'ledger' || (route.params.has('ch') && route.params.get('ch') !== 'brief')); setOpenMetric(route.params.get('metric')); }, [route.params]);
  function toggleLab() { const next = !lab; setLab(next); setParam('depth',next?'lab':'brief'); requestAnimationFrame(() => next ? document.getElementById('h-method')?.focus() : toggleRef.current?.focus()); }
  function sweepKey(event: React.KeyboardEvent<HTMLDivElement>) { const i = loads.indexOf(users); let j=i; if (event.key==='ArrowRight'||event.key==='ArrowDown') j=Math.min(loads.length-1,i+1); else if(event.key==='ArrowLeft'||event.key==='ArrowUp')j=Math.max(0,i-1);else if(event.key==='Home')j=0;else if(event.key==='End')j=loads.length-1;else return;event.preventDefault();setParam('users',String(loads[j]));requestAnimationFrame(()=>document.querySelector<HTMLElement>(`[data-seg="users"][data-val="${loads[j]}"]`)?.focus()); }
  function plot(id: string) { const max=Math.max(...A.sweep.map(p=>fieldValue(p as unknown as Record<string,unknown>,id)),...B.sweep.map(p=>fieldValue(p as unknown as Record<string,unknown>,id)))*1.15||1; const x=(i:number)=>18+(i+.5)*244/loads.length; const y=(v:number)=>80-v/max*68; const path=(points:typeof A.sweep)=>points.map((p,i)=>`${i?'L':'M'}${x(i)} ${y(fieldValue(p as unknown as Record<string,unknown>,id))}`).join(' ');return <svg data-plot viewBox="0 0 280 108" role="img" aria-label={`${id} across recorded user levels`}><rect x={18+loads.indexOf(users)*244/loads.length} y="0" width={244/loads.length} height="88" fill="var(--panel)"/><line x1="18" x2="262" y1="88" y2="88" stroke="var(--line-strong)"/><path d={path(A.sweep)} fill="none" stroke="var(--ink)" strokeWidth="1.5"/><path d={path(B.sweep)} fill="none" stroke="var(--muted)" strokeDasharray="5 4" strokeWidth="1.5"/>{A.sweep.map((p,i)=><circle key={`a${i}`} cx={x(i)} cy={y(fieldValue(p as unknown as Record<string,unknown>,id))} r="2.5" fill="var(--paper)" stroke="var(--ink)"/>)}{B.sweep.map((p,i)=><rect key={`b${i}`} x={x(i)-2.5} y={y(fieldValue(p as unknown as Record<string,unknown>,id))-2.5} width="5" height="5" fill="var(--paper)" stroke="var(--muted)"/>)}{loads.map((load,i)=><text key={load} x={x(i)} y="102" textAnchor="middle" fill="var(--muted)" fontSize="8">{load}</text>)}</svg>; }
  return <article className="tbt-study tbt-field-note">{route.notices.length>0&&<div className="tbt-notice" role="status"><b>Link adjusted</b> {route.notices.join(' ')}</div>}{invalid&&<div className="tbt-notice" role="status"><b>Link adjusted</b> {route.params.get('users')} users is not a recorded sweep level. Showing 16 users.</div>}<header className="tbt-study-header"><p className="tbt-eyebrow">Field note · Recorded study</p><h1 id="page-title" className={route.params.get('head')==='question'?'question':''}>{route.params.get('head')==='question'?'How many conversations can one deployment hold before the first token stalls?':'Session capacity'}</h1><p className="tbt-deck">How did two vLLM deployments behave as conversational load increased?</p><p className="tbt-quals"><span>Recorded results with unverified provenance fields</span><span>Capacity not qualified</span><span>Different GPUs — a deployment comparison</span></p></header><section id="ch-brief" className="tbt-chapter tbt-brief"><h2 id="h-brief" tabIndex={-1} className="tbt-brief-heading"><span className="tbt-chapter-bar" aria-hidden="true"/>01 Brief</h2><p className="tbt-finding">Over a 15-minute soak at 16 users, Deployment B recorded <span className={`state-${soakDelta.kind}`}>{soakDelta.symbol} {Math.abs((B.soak.output_tps-A.soak.output_tps)/A.soak.output_tps*100).toFixed(1)}% more output</span> and <span className={`state-${soakTtft.kind}`}>{soakTtft.symbol} {Math.abs((B.soak.visible_ttft_p50_s-A.soak.visible_ttft_p50_s)/A.soak.visible_ttft_p50_s*100).toFixed(1)}% lower median visible TTFT</span> than Deployment A.</p><p className="tbt-small">Change = (Deployment B − Deployment A) ÷ Deployment A over the fixed 900 s soak at 16 users. The sweep in Evidence does not change this headline.</p><div className="tbt-brief-table-wrap"><table className="tbt-brief-table"><tbody>{fieldMetrics.slice(0,3).map(metric=>{const a=(A.soak as unknown as Record<string,number>)[metric.id],b=(B.soak as unknown as Record<string,number>)[metric.id],state=decision(b,a,metric.higher);return <tr key={metric.id}><th>{metric.title}</th><td>● Deployment A <b>{format(a,metric.unit)}</b></td><td>◆ Deployment B <b className={`state-${state.kind}`}>{format(b,metric.unit)}</b></td><td className={`state-${state.kind}`}>{state.symbol} {state.text}</td></tr>})}</tbody></table></div><div className="tbt-caveat"><h3>What this does not say</h3><ul><li>Capacity was not qualified: no service objective was declared.</li><li>Different GPUs make this a deployment comparison.</li><li>Some provenance fields remain unverified.</li></ul></div><button id="lab-toggle" ref={toggleRef} type="button" className="tbt-lab-toggle" aria-expanded={lab} aria-controls="lab" onClick={toggleLab}>{lab?'Collapse lab ↑':'Open evidence lab ↓'}</button></section>{lab&&<div id="lab"><section id="ch-method" className="tbt-chapter"><ChapterHeading number={2} title="Method" heading="One runtime, two deployments, one session replay" id="method"/><p>A synthetic multi-turn session replay, run against two single-GPU deployments of the same runtime.</p><dl className="tbt-protocol">{[['Sessions','50 sessions · 914 turns · two session slots per user'],['Prompt sizes','1,170 – 6,691 tokens, recorded'],['Warm-up','60 s before every measured window'],['Sweep window','180 s per level at 2, 4, 8, 16, 32, 64 and 100 users'],['Soak window','900 s at 16 users'],['Validity','No validity limit was declared for this field note']].map(([key,v])=><div key={key} data-protocol-row><dt>{key}</dt><dd>{v}</dd></div>)}</dl></section><section id="ch-evidence" className="tbt-chapter"><ChapterHeading number={3} title="Evidence" heading={`Sweep at ${users} users`} id="evidence"/><p>Deployment B relative to Deployment A at the selected sweep level. Lines join recorded levels only; nothing between them is measured.</p><div className="tbt-field-sweep"><span id="sweep-label" className="tbt-eyebrow">Sweep · simulated users</span><div role="group" aria-labelledby="sweep-label" onKeyDown={sweepKey}>{loads.map(load=><button type="button" key={load} data-seg="users" data-val={load} aria-pressed={load===users} tabIndex={load===users?0:-1} onClick={()=>setParam('users',String(load))}>{load}</button>)}</div><span>Changes only the sweep below. The soak headline stays fixed.</span></div><p className="tbt-operands">Directional operands: Deployment B (subject) versus Deployment A (baseline), both at {users} simulated users. Error rate is context only because this field note declared no validity limit.</p><div data-identity-legend className="tbt-identity-legend"><span>● ── Deployment A · {A.hardware}</span><span>◆ ╌╌ Deployment B · {B.hardware}</span></div><div data-evidence-group className="tbt-evidence-group"><h3><span>Directional comparisons</span><small>Deployment B relative to Deployment A at the selected sweep level.</small></h3><div className="tbt-plot-row tbt-field-plots">{fieldMetrics.map(metric=>{const a=fieldValue(sweepA as unknown as Record<string,unknown>,metric.id),b=fieldValue(sweepB as unknown as Record<string,unknown>,metric.id),state=metric.id==='error_rate'?{symbol:'△',text:'Context only — not ranked',kind:'context'}:decision(b,a,metric.higher);return <div key={metric.id}><button data-metric={metric.id} type="button" className="tbt-plot-card" aria-expanded={openMetric===metric.id} onClick={()=>{setOpenMetric(openMetric===metric.id?null:metric.id);setParam('metric',openMetric===metric.id?'':metric.id,true);}}><span className="tbt-plot-header"><b>{metric.title}</b><small>{metric.id==='error_rate'?'Context only':metric.higher?'Higher is better':'Lower is better'}</small></span>{plot(metric.id)}<span className="tbt-plot-values">● A {format(a,metric.unit,metric.id==='error_rate'?2:1)} · ◆ B <b className={metric.id==='error_rate'?'':`state-${state.kind}`}>{format(b,metric.unit,metric.id==='error_rate'?2:1)}</b></span><span className={`state-${state.kind}`}>{state.symbol} {state.text}</span></button>{openMetric===metric.id&&<div className="tbt-field-explanation" role="region" aria-label={`Explanation: ${metric.title}`}><h4>{metric.title}</h4><p>{metric.id==='error_rate'?'Context only — no validity limit was declared for this field note.':`${metric.higher?'Higher':'Lower'} is better for this deployment comparison.`}</p><p>Deployment A: {format(a,metric.unit,metric.id==='error_rate'?2:1)}. Deployment B: {format(b,metric.unit,metric.id==='error_rate'?2:1)}. {state.text}.</p><p>These values are from the {users}-user sweep; the 16-user soak headline remains fixed.</p></div>}</div>})}</div></div><button type="button" className="tbt-ledger-toggle" aria-expanded={route.params.get('depth')==='ledger'} onClick={()=>setParam('depth',route.params.get('depth')==='ledger'?'lab':'ledger')}>Exact measurement ledger ↓</button>{route.params.get('depth')==='ledger'&&<div className="tbt-ledger"><table><thead><tr><th>Users</th><th>Deployment A output</th><th>Deployment B output</th><th>A TTFT p50</th><th>B TTFT p50</th></tr></thead><tbody>{loads.map(load=>{const pa=A.sweep.find(p=>p.users===load)!,pb=B.sweep.find(p=>p.users===load)!;return <tr key={load}><th>{load}</th><td>{format(pa.output_tps,'tok/s')}</td><td>{format(pb.output_tps,'tok/s')}</td><td>{format(pa.visible_ttft_p50_s,'s',2)}</td><td>{format(pb.visible_ttft_p50_s,'s',2)}</td></tr>})}</tbody></table></div>}</section><section id="ch-boundaries" className="tbt-chapter"><ChapterHeading number={4} title="Boundaries" heading="A field note, not a capacity rating" id="boundaries"/><p>Different GPUs, the same runtime. Differences describe deployments, not engines.</p><div className="tbt-boundary-grid">{[['Matched','Same runtime and model family; same session replay, warm-up and windows'],['Deployment-specific','GPU model and memory; private serving details withheld'],['Observed','Visible waits climb steeply beyond 16 users'],['Not established','A capacity number, task correctness, or audited provenance for every field']].map(([title,copy])=><div data-boundary-block key={title}><h3>{title}</h3><p>{copy}</p></div>)}</div></section><section id="ch-source" className="tbt-chapter"><ChapterHeading number={5} title="Source" heading="Where these numbers come from" id="source"/><p>Recorded sweep and soak aggregates. Some provenance fields are unverified and labelled as such.</p><a href={fieldNoteDataUrl} download="field-note-public-site.json">Download public site JSON ↗</a></section></div>}</article>;
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
  const page = route.page === 'session-study' ? 'field-notes' : route.page;
  const episodeMatch = /^episode-(\d+)$/.exec(page);
  const episodeNumber = episodeMatch ? Number(episodeMatch[1]) : null;
  const isStudy = episodeNumber !== null && episodeNumber <= 1;
  const isPlanned = episodeNumber !== null && episodeNumber >= 2 && episodeNumber <= 16;
  const chapters = page === 'episodes' ? ['recorded','notes','planned'] : page === 'methodology' ? ['definitions','states','identity','rules','protocols'] : isStudy || isPlanned || page === 'field-notes' ? [...CHAPTERS] : [];
  const chapterKey = chapters.join('|');
  const [activeChapter, setActiveChapter] = useState(chapters[0] ?? '');
  useEffect(() => { const update = () => { setRoute(readRoute()); setEpMenu(false); setSiteMenu(false); setLabMenu(false); }; window.addEventListener('hashchange',update); window.addEventListener('popstate',update); return () => { window.removeEventListener('hashchange',update); window.removeEventListener('popstate',update); }; }, []);
  useEffect(() => { document.title = `${page === 'episodes' ? 'Token by Token' : page === 'methodology' ? 'Methodology' : page === 'field-notes' ? 'Field notes' : episodeNumber !== null ? `Episode ${String(episodeNumber).padStart(2,'0')}` : 'Not found'} — INFERENCE LAB`; }, [page, episodeNumber]);
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
        const threshold = Math.max(72, selectorBottom + 24);
        let current = chapters[0];
        for (const chapter of chapters) {
          const section = document.getElementById(`ch-${chapter}`);
          if (section && section.getBoundingClientRect().top <= threshold) current = chapter;
        }
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
    } else if (key === 'users') {
      const [a,b] = fieldNote.deployments.map(d => d.sweep.find(point => point.users === Number(value))!);
      const state = decision(b.output_tps,a.output_tps,true);
      setLive(`${value} users selected in the sweep. Deployment B ${state.text} output throughput than Deployment A. The fixed soak headline is unchanged.`);
    }
  }
  useEffect(() => {
    function esc(event: KeyboardEvent) {
      if (event.key !== 'Escape') return;
      if (epMenu) { setEpMenu(false); requestAnimationFrame(() => document.getElementById('ep-menu-btn')?.focus()); return; }
      if (siteMenu) { setSiteMenu(false); requestAnimationFrame(() => document.getElementById('site-menu-btn')?.focus()); return; }
      if (labMenu) { setLabMenu(false); requestAnimationFrame(() => document.getElementById('lab-tools-btn')?.focus()); return; }
      const metric = route.params.get('metric');
      if (metric) { setParam('metric','',true); requestAnimationFrame(() => document.querySelector<HTMLElement>(`[data-metric="${metric}"]`)?.focus()); }
    }
    document.addEventListener('keydown',esc);
    return () => document.removeEventListener('keydown',esc);
  }, [epMenu, siteMenu, labMenu, route]);
  const lastChapter = useRef('');
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
      target.scrollIntoView({ block: 'start' });
      const selector = document.querySelector<HTMLElement>('.tbt-selector');
      const clearance = selector && selector.getBoundingClientRect().top <= 0 ? selector.getBoundingClientRect().bottom + 12 : 16;
      const offset = target.getBoundingClientRect().top - clearance;
      if (offset < 0) window.scrollBy(0, offset);
      target.focus({ preventScroll: true });
    }));
  }, [page, route.params]);
  function goChapter(ch: string) {
    const next = new URLSearchParams(route.params);
    next.set('ch',ch);
    if ((isStudy || page === 'field-notes') && ch !== 'brief') next.set('depth','lab');
    history.replaceState(null,'',url(page,next));
    lastChapter.current = '';
    setRoute({page,params:next,notices:[]});
    setEpMenu(false);
  }
  const epLinks = episodes.map(e => <a key={e.id} href={`#${e.id}`} aria-current={page === e.id ? 'page' : undefined}><b className={e.status === 'available' || page === e.id ? 'recorded' : 'planned'}>{String(e.number).padStart(2,'0')}</b><span>{e.title}</span></a>);
  const chapterLinks = chapters.map((ch,i) => <button key={ch} type="button" aria-current={activeChapter === ch ? 'location' : undefined} onClick={() => goChapter(ch)}><b>{String(i+1).padStart(2,'0')}</b><span>{ch === 'notes' ? 'Field notes' : ch === 'states' ? 'Evidence states' : ch === 'protocols' ? 'Episode protocols' : ch[0].toUpperCase()+ch.slice(1)}</span></button>);
  return <div data-tbt data-theme={shownTheme}><div className="sr-only" aria-live="polite" role="status">{live}</div><a className="tbt-skip" href="#main" onClick={event => { event.preventDefault(); const main = document.getElementById('main'); main?.scrollIntoView({ block: 'start' }); main?.focus({ preventScroll: true }); }}>Skip to content</a><header data-screen-label="Site bar" className="tbt-sitebar"><div className="tbt-sitebar-inner"><a className="tbt-brand" href="#episodes"><img src="/token-by-token.svg" width="22" height="22" alt="" /><span>Token by Token <em>/ Inference lab</em></span></a><nav aria-label="Site" className="tbt-site-nav"><a href="#episodes" aria-current={page==='episodes'?'page':undefined}>Episodes</a><a href="#methodology" aria-current={page==='methodology'?'page':undefined}>Methodology</a><a href="#field-notes" aria-current={page==='field-notes'?'page':undefined}>Field notes</a><button id="lab-tools-btn" type="button" aria-expanded={labMenu} onClick={() => setLabMenu(!labMenu)}>Lab tools ▾</button></nav><div className="tbt-wide-links"><ExternalLinks /></div><div className="tbt-theme-group" role="group" aria-label="Color theme">{(['light','dark'] as const).map(t => <button type="button" key={t} aria-pressed={theme===t} onClick={() => { applyTheme(t); setTheme(t); }}>{t}</button>)}</div><button className="tbt-mobile-episodes" id="ep-menu-btn" type="button" aria-expanded={epMenu} aria-controls="ep-menu" onClick={() => { setEpMenu(!epMenu); setSiteMenu(false); }}>Episodes ▾</button><button id="site-menu-btn" className="tbt-mobile-menu" type="button" aria-expanded={siteMenu} aria-controls="site-menu" onClick={() => { setSiteMenu(!siteMenu); setEpMenu(false); }}>Menu</button></div>{labMenu && <div id="lab-tools" className="tbt-popup"><p className="tbt-eyebrow">Local operator tools</p><p>These run only in a local checkout of the lab. They are not public evidence and are not part of this public build.</p>{["Local results", "Quick test", "Experiment planner", "Episode runner", "Canonical launch"].map(tool => <div data-local-tool key={tool}><span>{tool}</span><small>LOCAL ONLY</small></div>)}</div>}{siteMenu && <nav id="site-menu" className="tbt-mobile-panel" aria-label="Site"><a href="#episodes">Episodes</a><a href="#methodology">Methodology</a><a href="#field-notes">Field notes</a><ExternalLinks /><p>Lab tools · local only</p><small>Local results, Quick test, Experiment planner, Episode runner and Canonical launch run only in a local checkout.</small></nav>}{epMenu && <nav id="ep-menu" className={`tbt-mobile-panel ${isStudy || isPlanned || page === 'field-notes' ? 'tbt-five-chapter' : ''}`} aria-label="Episodes and chapters">{chapters.length>0 && <><p>On this page</p>{chapterLinks}</>}<p>Episodes</p>{epLinks}</nav>}</header><div className="tbt-layout"><nav data-screen-label="Episode rail" className="tbt-rail" aria-label="Episodes and chapters"><p>Episodes</p><div className="tbt-rail-episodes">{epLinks}</div>{chapters.length>0 && <><p>On this page</p><div className={`tbt-rail-chapters ${isStudy || isPlanned || page === 'field-notes' ? 'tbt-five-chapter' : ''}`}>{chapterLinks}</div></>}</nav><main id="main" tabIndex={-1}>{page==='episodes'?<Landing/>:page==='methodology'?<Methodology/>:page==='field-notes'?<FieldNote route={route} setParam={setParam} />:isStudy?<Study episode={episodeNumber as 0|1} route={route} setParam={setParam}/>:isPlanned?<Planned number={episodeNumber!}/>:<article><h1 id="page-title">Not in the catalog</h1><p>This episode is unavailable.</p><a href="#episodes">All episodes</a></article>}</main></div></div>;
}
