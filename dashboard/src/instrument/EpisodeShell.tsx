import { useEffect, useRef, useState, type ReactNode } from "react";
import catalog from "../data/episodes.json";
import type { EvidenceStudy } from "./evidence";

export function EpisodeShell({ study, chapters, children }: { study: EvidenceStudy; chapters: Array<{ id: string; label: string }>; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") { setOpen(false); trigger.current?.focus(); }
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [open]);
  const activateChapter = (id: string) => {
    const target = document.getElementById(id);
    if (!target) return;
    target.tabIndex = -1;
    target.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
    target.focus({ preventScroll: true });
  };

  return <div className="instrument-shell">
    <header className="instrument-masthead">
      <div>
        <span className="instrument-series">TOKEN BY TOKEN / INFERENCE LAB</span>
        <button ref={trigger} className="episode-chooser" type="button" aria-expanded={open} aria-controls="episode-chooser-panel" onClick={() => setOpen(value => !value)}>
          Choose episode <span aria-hidden="true">{open ? "×" : "+"}</span>
        </button>
      </div>
      {open && <section id="episode-chooser-panel" className="episode-chooser-panel" aria-label="Episode index">
        {catalog.episodes.map((episode) => <a key={episode.id} href={episode.status === "available" ? `#${episode.id}` : `#experiment-planner?episode=${episode.number}`} aria-current={episode.id === `episode-${study.number}` ? "page" : undefined} onClick={() => setOpen(false)}>
          <b>{String(episode.number).padStart(2, "0")}</b><span>{episode.title}<small>{episode.status === "available" ? episode.evidence : "Planned"}</small></span>
        </a>)}
      </section>}
    </header>
    <div className="instrument-layout">
      <aside className="instrument-rail">
        <div className="instrument-episode-number">{study.kind === "episode" ? `EP ${String(study.number).padStart(2, "0")}` : "FIELD NOTE"}</div>
        <p className={`instrument-state ${study.state}`}>{study.statusLabel}</p>
        <dl className="instrument-brief">
          <div><dt>What</dt><dd>{study.what}</dd></div>
          <div><dt>Why</dt><dd>{study.why}</dd></div>
          <div><dt>How</dt><dd>{study.how}</dd></div>
        </dl>
        <nav className="instrument-chapters" aria-label="Study chapters">
          {chapters.map((chapter, index) => <button key={chapter.id} type="button" onClick={() => activateChapter(chapter.id)}><span>{String(index + 1).padStart(2, "0")}</span>{chapter.label}</button>)}
        </nav>
      </aside>
      <article className="instrument-story">
        <header className="instrument-hero" id="overview">
          <p>{study.title} / {study.model}</p>
          <h1>{study.question}</h1>
          <div className="instrument-provenance"><span>{study.hardware}</span><span>{study.provenance}</span></div>
        </header>
        {children}
      </article>
    </div>
  </div>;
}
