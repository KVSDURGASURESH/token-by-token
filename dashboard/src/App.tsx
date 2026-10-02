import { useEffect, useState } from "react";
import { PublishedRunpodStudy } from "./PublishedRunpodStudy";
import { ReaderResults } from "./ReaderResults";
import { EpisodeIndex } from "./EpisodeIndex";
import { Episode1Fixture } from "./Episode1Fixture";
import { QuickTest } from "./QuickTest";
import { ExperimentPlanner } from "./ExperimentPlanner";
import { EpisodeRunner } from "./EpisodeRunner";
import { CanonicalLaunch } from "./CanonicalLaunch";
import catalog from "./data/episodes.json";

type CatalogEpisode = (typeof catalog.episodes)[number] & { dashboardView?: string; guide?: string };
const episodes = catalog.episodes as CatalogEpisode[];

function currentView() {
  const hash = window.location.hash.slice(1).split("?")[0];
  return hash === "recorded-study" ? "episode-0" : hash || "episodes";
}

export function App() {
  const [view, setView] = useState(currentView);
  const local = view === "local-results";
  const quick = view === "quick-test";
  const planner = view === "experiment-planner";
  const runner = view === "episode-runner";
  const canonical = view === "canonical-launch";
  const episode = episodes.find(entry => entry.id === view && entry.dashboardView);
  const studyLink = episode ?? episodes.find(entry => entry.status === "available");
  useEffect(() => {
    document.title = canonical ? "Canonical launch — INFERENCE LAB" : runner ? "Episode runner — INFERENCE LAB" : planner ? "Experiment planner — INFERENCE LAB" : quick ? "Quick test — INFERENCE LAB" : local ? "Local results — INFERENCE LAB" : episode?.dashboardView === "qwen32b-runtime-study" ? "Qwen2.5-32B-Instruct runtime study — Exploratory noncanonical" : episode?.dashboardView === "episode1-fixture" ? "Episode 1 local fixture — INFERENCE LAB" : `${catalog.project} — ${catalog.tagline}`;
  }, [local, quick, planner, runner, canonical, episode]);
  useEffect(() => {
    const update = () => { setView(currentView()); window.scrollTo(0, 0); };
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);
  return (
      <main className={!local && !quick && !planner && !runner && !canonical && !episode ? "lab-home" : planner ? "planner-home" : runner || canonical ? "runner-home" : undefined}>
      <nav className="view-switch" aria-label="Results view">
        <a href="#episodes" aria-current={!local && !quick && !planner && !runner && !canonical && !episode ? "page" : undefined}>All episodes</a>
        {studyLink && <a href={`#${studyLink.id}`} aria-current={episode ? "page" : undefined}>Episode {studyLink.number} study</a>}
        <a href="#local-results" aria-current={local ? "page" : undefined}>Open local results</a>
        <a href="#quick-test" aria-current={quick ? "page" : undefined}>Quick test</a>
        <a href="#experiment-planner" aria-current={planner ? "page" : undefined}>Experiment planner</a>
        <a href="#episode-runner" aria-current={runner ? "page" : undefined}>Episode runner</a>
        <a href="#canonical-launch" aria-current={canonical ? "page" : undefined}>Canonical launch</a>
      </nav>
      {canonical ? <CanonicalLaunch /> : runner ? <EpisodeRunner /> : planner ? <ExperimentPlanner /> : quick ? <QuickTest /> : local ? <ReaderResults /> : episode?.dashboardView === "qwen32b-runtime-study" ? <PublishedRunpodStudy /> : episode?.dashboardView === "episode1-fixture" ? <Episode1Fixture /> : episode ? <section className="episode-guide"><h1>{episode.title}</h1><p>{episode.summary}</p></section> : <EpisodeIndex />}
    </main>
  );
}
