import { useEffect, useState } from "react";
import { PublishedRunpodStudy } from "./PublishedRunpodStudy";
import { ReaderResults } from "./ReaderResults";

export function App() {
  const [local, setLocal] = useState(window.location.hash === "#local-results");
  useEffect(() => {
    document.title = local ? "Local results — INFERENCE LAB" : "Qwen2.5-32B-Instruct runtime study — Exploratory noncanonical";
  }, [local]);
  useEffect(() => {
    const update = () => setLocal(window.location.hash === "#local-results");
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);
  return (
    <main>
      <nav className="view-switch" aria-label="Results view">
        <a href="#recorded-study" aria-current={!local ? "page" : undefined}>Episode 0 study</a>
        <a href="#local-results" aria-current={local ? "page" : undefined}>Open local results</a>
      </nav>
      {local ? <ReaderResults /> : <PublishedRunpodStudy />}
    </main>
  );
}
