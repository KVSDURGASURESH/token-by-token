import catalog from "./data/episodes.json";

export function EpisodeIndex() {
  const repo = catalog.repository;
  return (
    <article className="episode-index">
      <header className="lab-introduction">
        <img className="lab-logo" src="/token-by-token.svg" alt="Token by Token: three tokens advancing along a line" width="80" height="80" />
        <p className="lab-eyebrow">{catalog.tagline} / A hands-on series</p>
        <h1>{catalog.project}</h1>
        <p className="lab-deck">Understand the serving path.<br />Measure each change. Find the fit.</p>
        <p className="lab-purpose">An interactive assistant needs a fast first token. A batch job needs useful work per dollar. A long-context application needs room for its KV cache. The right serving configuration depends on the workload.</p>
        <p className="lab-purpose">This lab turns inference concepts into repeatable experiments. We test optimizations in sequence against quality, latency, memory and cost targets, then combine and retest the promising settings for a chosen use case.</p>
      </header>

      <section className="episode-contents" aria-labelledby="episode-contents-title">
        <div className="lab-section-heading">
          <h2 id="episode-contents-title">Table of contents</h2>
          <p>Open an episode for its experiment, charts and evidence.</p>
        </div>
        <ol className="episode-list">
          {catalog.episodes.map(episode => (
            <li key={episode.id}>
              <span className="episode-number" aria-hidden="true">{String(episode.number).padStart(2, "0")}</span>
              <div className="episode-entry">
                <p className="episode-state">{episode.status === "available" ? "Available" : "Planned"} <span>· {episode.evidence}</span></p>
                <h3>{episode.status === "available" ? <a href={`#${episode.id}`}>Episode {episode.number} — {episode.title} <span aria-hidden="true">↗</span></a> : `Episode ${episode.number} — ${episode.title}`}</h3>
                <p>{episode.summary}</p>
                <p className="episode-context">{episode.model} / {episode.hardware}</p>
                {episode.status === "available" && <div className="episode-links"><a href={`#${episode.id}`}>Explore results</a><a href={`${repo}/blob/main/${episode.guide}`}>Read the experiment guide ↗</a></div>}
              </div>
            </li>
          ))}
        </ol>
        <p className="lab-next">More episodes will appear here as experiments are completed. The <a href={`${repo}/blob/main/docs/roadmap.md`}>experiment map ↗</a> is the maintained plan for what comes next.</p>
      </section>

      <section className="lab-start" aria-labelledby="lab-start-title">
        <h2 id="lab-start-title">Start with the evidence</h2>
        <div>
          <p>Browse the retained results locally with no GPU rental. Use the repository to rehearse the workflow, choose a GPU and prepare a new measurement.</p>
          <p><a href={`${repo}#start-here`}>Setup &amp; quickstart ↗</a><a href="#local-results">Open your own local results</a></p>
        </div>
      </section>
      <footer className="lab-footer"><span>{catalog.project} / {catalog.tagline}</span><a href={repo}>GitHub project ↗</a></footer>
    </article>
  );
}
