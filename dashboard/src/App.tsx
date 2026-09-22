import { useEffect, useState } from "react";
import { PublishedRunpodStudy } from "./PublishedRunpodStudy";
import { ReaderResults } from "./ReaderResults";
import { EpisodeIndex } from "./EpisodeIndex";
import catalog from "./data/episodes.json";

function currentView() {
  const hash = window.location.hash.slice(1);
  return hash === "recorded-study" ? "episode-0" : hash || "episodes";
}

export function App() {
  const [view, setView] = useState(currentView);
  const local = view === "local-results";
  const episode = catalog.episodes.find(entry => entry.id === view && entry.status === "available");
  const studyLink = episode ?? catalog.episodes.find(entry => entry.status === "available");
  useEffect(() => {
    document.title = local ? "Local results — INFERENCE LAB" : episode?.dashboardView === "qwen32b-runtime-study" ? "Qwen2.5-32B-Instruct runtime study — Exploratory noncanonical" : `${catalog.project} — ${catalog.tagline}`;
  }, [local, episode]);
  useEffect(() => {
    const update = () => { setView(currentView()); window.scrollTo(0, 0); };
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);
  return (
    <main className={!local && !episode ? "lab-home" : undefined}>
      <nav className="view-switch" aria-label="Results view">
        <a href="#episodes" aria-current={!local && !episode ? "page" : undefined}>All episodes</a>
        {studyLink && <a href={`#${studyLink.id}`} aria-current={episode ? "page" : undefined}>Episode {studyLink.number} study</a>}
        <a href="#local-results" aria-current={local ? "page" : undefined}>Open local results</a>
      </nav>
      {local ? <ReaderResults /> : episode?.dashboardView === "qwen32b-runtime-study" ? <PublishedRunpodStudy /> : episode ? <section className="episode-guide"><h1>{episode.title}</h1><p>{episode.summary}</p><a href={`${catalog.repository}/blob/main/${episode.guide}`}>Read this episode’s experiment guide ↗</a></section> : <EpisodeIndex />}
    </main>
  );
}
