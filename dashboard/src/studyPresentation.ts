export type Distribution = {
  available: boolean;
  unavailable_reason: string | null;
  count: number | null;
  percentile_method: string | null;
  source: string | null;
  warnings: string[];
  p50?: number;
  p95?: number;
  p99?: number;
};

export type Goodput = {
  available: boolean;
  unavailable_reason: string | null;
  slo_contract: Record<string, unknown>;
  qualifying_requests?: number;
  output_tokens?: number;
  tokens_per_second?: number;
  warnings?: string[];
};

export type PublishedCell = {
  runtime: string;
  profile: string;
  successful_requests: number;
  successful_output_tokens: number;
  failed_requests: number;
  output_tokens_per_second: number | null;
  goodput: Goodput;
  client_ttft_ms: Distribution;
  client_tpot_ms: Distribution;
  client_itl_ms: Distribution;
  client_e2e_ms: Distribution;
};

export type StudyFacts = {
  compatibility: string[];
  exclusions: string[];
  preflight: string[];
  future_work: string[];
};

export type PublishedStudy = {
  classification: string;
  model: string;
  model_revision: string;
  gpu: string;
  precision: string;
  cells: PublishedCell[];
  study_facts: StudyFacts;
};

const integer = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

function humanize(value: string) {
  const spaced = value.replaceAll("_", " ").replaceAll("-", " ").trim();
  return spaced ? `${spaced[0].toUpperCase()}${spaced.slice(1)}` : "Unclassified";
}

export function studyIdentity(study: PublishedStudy) {
  const modelName = study.model.split("/").filter(Boolean).at(-1) ?? study.model;
  return {
    title: `${modelName} runtime study`,
    classification: humanize(study.classification),
  };
}

export function documentTitle(study: PublishedStudy) {
  const identity = studyIdentity(study);
  return `${identity.title} — ${identity.classification}`;
}

export function setDocumentTitle(target: { title: string }, study: PublishedStudy) {
  target.title = documentTitle(study);
}

export function studyTotals(study: PublishedStudy) {
  const throughputs = study.cells
    .map((cell) => cell.output_tokens_per_second)
    .filter((metric): metric is number => typeof metric === "number" && Number.isFinite(metric));
  return {
    engineCount: new Set(study.cells.map((cell) => cell.runtime)).size,
    cellCount: study.cells.length,
    attempted: study.cells.reduce(
      (total, cell) => total + cell.successful_requests + cell.failed_requests,
      0,
    ),
    failures: study.cells.reduce((total, cell) => total + cell.failed_requests, 0),
    peakThroughput: throughputs.length > 0 ? Math.max(...throughputs) : null,
    availableGoodputCells: study.cells.filter((cell) => cell.goodput.available).length,
  };
}

export function disclosureGroups(facts: StudyFacts) {
  return [
    { key: "compatibility", label: "Compatibility", facts: facts.compatibility },
    { key: "exclusions", label: "Exclusions", facts: facts.exclusions },
    { key: "preflight", label: "Preflight facts", facts: facts.preflight },
    { key: "future_work", label: "Future work", facts: facts.future_work },
  ].filter((group) => group.facts.length > 0);
}

export function evidenceLines(metric: Distribution) {
  const lines = [
    metric.count === null ? "Count not retained" : `n=${integer.format(metric.count)}`,
    metric.percentile_method ?? "Percentile method not retained",
    metric.source ?? "Source not retained",
  ];
  if (!metric.available) {
    lines.push(`Unavailable: ${metric.unavailable_reason ?? "reason not retained"}`);
  }
  lines.push(...metric.warnings.map((warning) => `Warning: ${warning}`));
  return lines;
}

function contractLine(contract: Record<string, unknown>) {
  const entries = Object.entries(contract).sort(([left], [right]) => left.localeCompare(right));
  return entries.length > 0
    ? `SLO contract: ${entries.map(([key, threshold]) => `${key}=${String(threshold)}`).join(", ")}`
    : null;
}

export function goodputLines(goodput: Goodput) {
  const lines: string[] = [];
  const contract = contractLine(goodput.slo_contract);
  if (contract) {
    lines.push(contract);
  } else if (goodput.available) {
    lines.push("SLO contract not retained");
  }

  if (goodput.available) {
    if (goodput.qualifying_requests !== undefined && goodput.output_tokens !== undefined) {
      lines.push(
        `${integer.format(goodput.qualifying_requests)} qualifying requests / ${integer.format(goodput.output_tokens)} output tokens`,
      );
    } else {
      if (goodput.qualifying_requests === undefined) lines.push("Qualifying request count not retained");
      if (goodput.output_tokens === undefined) lines.push("Goodput output-token count not retained");
    }
  } else {
    lines.push(`Unavailable: ${goodput.unavailable_reason ?? "reason not retained"}`);
  }
  lines.push(...(goodput.warnings ?? []).map((warning) => `Warning: ${warning}`));
  return lines;
}

export function goodputPresentation(goodput: Goodput) {
  return {
    available: goodput.available,
    tokensPerSecond: goodput.available && typeof goodput.tokens_per_second === "number"
      ? goodput.tokens_per_second
      : null,
    lines: goodputLines(goodput),
  };
}

function distributions(study: PublishedStudy) {
  return study.cells.flatMap((cell) => [
    cell.client_ttft_ms,
    cell.client_tpot_ms,
    cell.client_itl_ms,
    cell.client_e2e_ms,
  ]);
}

export function methodologyLimitations(study: PublishedStudy) {
  const metrics = distributions(study);
  const missingCounts = metrics.filter((metric) => metric.count === null).length;
  const missingMethods = metrics.filter((metric) => metric.percentile_method === null).length;
  const unavailableMetrics = metrics.filter((metric) => !metric.available).length;
  const unavailableGoodput = study.cells.filter((cell) => !cell.goodput.available).length;
  const lines = ["Percentiles are descriptive for the retained observations."];

  if (missingCounts > 0) {
    lines.push(`Observation count was not retained for ${missingCounts} of ${metrics.length} metric distributions.`);
  }
  if (missingMethods > 0) {
    lines.push(`Percentile method was not retained for ${missingMethods} of ${metrics.length} metric distributions.`);
  }
  if (unavailableMetrics > 0) {
    lines.push(`${unavailableMetrics} of ${metrics.length} metric distributions unavailable; reasons and warnings appear in the table.`);
  }
  if (unavailableGoodput === study.cells.length && study.cells.length > 0) {
    lines.push(`Goodput is unavailable for all ${study.cells.length} cells; retained reasons, contracts, and warnings appear in the table.`);
  } else if (unavailableGoodput > 0) {
    lines.push(`Goodput is unavailable for ${unavailableGoodput} of ${study.cells.length} cells; each row reports its retained evidence.`);
  } else if (study.cells.length > 0) {
    lines.push(`Goodput evidence is available for all ${study.cells.length} cells under each row's retained SLO contract.`);
  }
  lines.push("Interpret results with prompt length, concurrency, cache policy, runtime configuration, and the labeled disclosures above.");
  return lines;
}
