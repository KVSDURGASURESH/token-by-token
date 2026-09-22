#!/usr/bin/env python3
"""Build shareable, data-derived benchmark charts and a LinkedIn draft."""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
import re
from pathlib import Path
from typing import Any


METRICS = ("client_ttft_ms", "client_tpot_ms", "client_itl_ms", "client_e2e_ms")
PERCENTILES = ("p50", "p95", "p99")
GOODPUT_SLO_KEYS = frozenset(
    ("ttft_ms", "tpot_ms", "client_inter_chunk_ms", "e2e_ms")
)


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{label} must be finite and nonnegative")
    return result


def _validated(study: object) -> dict[str, Any]:
    if not isinstance(study, dict) or study.get("schema_version") != 1:
        raise ValueError("study must be a schema_version 1 object")
    for field in ("model", "model_revision", "gpu", "precision"):
        if not isinstance(study.get(field), str) or not study[field]:
            raise ValueError(f"{field} is required")
    cells = study.get("cells")
    if not isinstance(cells, list) or not cells:
        raise ValueError("cells must be a non-empty list")
    for index, cell in enumerate(cells):
        if not isinstance(cell, dict):
            raise ValueError(f"cells[{index}] must be an object")
        for field in ("runtime", "profile"):
            if not isinstance(cell.get(field), str) or not cell[field]:
                raise ValueError(f"cells[{index}].{field} is required")
        for field in ("successful_requests", "failed_requests"):
            if isinstance(cell.get(field), bool) or not isinstance(cell.get(field), int) or cell[field] < 0:
                raise ValueError(f"cells[{index}].{field} must be a nonnegative integer")
        if cell.get("successful_output_tokens") is not None:
            output_total = cell["successful_output_tokens"]
            if (
                isinstance(output_total, bool)
                or not isinstance(output_total, int)
                or output_total < 0
            ):
                raise ValueError(
                    f"cells[{index}].successful_output_tokens must be a nonnegative integer"
                )
        for metric in METRICS:
            distribution = cell.get(metric)
            if not isinstance(distribution, dict):
                raise ValueError(f"cells[{index}].{metric} is required")
            if distribution.get("available") is True:
                for percentile in PERCENTILES:
                    _number(distribution.get(percentile), f"cells[{index}].{metric}.{percentile}")
            elif distribution.get("available") is not False:
                raise ValueError(f"cells[{index}].{metric}.available must be boolean")
            elif any(percentile in distribution for percentile in PERCENTILES):
                raise ValueError(f"cells[{index}].{metric} unavailable values must be omitted")
            count = distribution.get("count")
            if count is not None and (
                isinstance(count, bool) or not isinstance(count, int) or count < 0
            ):
                raise ValueError(f"cells[{index}].{metric}.count must be nonnegative or null")
            for field in ("percentile_method", "source"):
                if distribution.get(field) is not None and not isinstance(distribution[field], str):
                    raise ValueError(f"cells[{index}].{metric}.{field} must be a string or null")
            if not isinstance(distribution.get("warnings"), list) or not all(
                isinstance(item, str) for item in distribution["warnings"]
            ):
                raise ValueError(f"cells[{index}].{metric}.warnings must be strings")
        throughput = cell.get("output_tokens_per_second")
        if throughput is not None:
            _number(throughput, f"cells[{index}].output_tokens_per_second")
        goodput = cell.get("goodput")
        if not isinstance(goodput, dict):
            raise ValueError(f"cells[{index}].goodput is required")
        if not isinstance(goodput.get("slo_contract"), dict):
            raise ValueError(f"cells[{index}].goodput.slo_contract is required")
        slo_contract = goodput["slo_contract"]
        if not set(slo_contract).issubset(GOODPUT_SLO_KEYS):
            raise ValueError(f"cells[{index}].goodput.slo_contract has unsupported keys")
        for name, threshold in slo_contract.items():
            _number(threshold, f"cells[{index}].goodput.slo_contract.{name}")
        if goodput.get("available") not in (True, False):
            raise ValueError(f"cells[{index}].goodput.available must be boolean")
        if goodput["available"]:
            qualifying = goodput.get("qualifying_requests")
            if (
                isinstance(qualifying, bool)
                or not isinstance(qualifying, int)
                or not 0 <= qualifying <= cell["successful_requests"]
            ):
                raise ValueError(f"cells[{index}].goodput.qualifying_requests is invalid")
            output_tokens = goodput.get("output_tokens")
            if (
                isinstance(output_tokens, bool)
                or not isinstance(output_tokens, int)
                or output_tokens < 0
            ):
                raise ValueError(f"cells[{index}].goodput.output_tokens is invalid")
            rate = _number(
                goodput.get("tokens_per_second"),
                f"cells[{index}].goodput.tokens_per_second",
            )
            if len({qualifying > 0, output_tokens > 0, rate > 0}) != 1:
                raise ValueError(
                    f"cells[{index}].goodput count, tokens, and rate are incoherent"
                )
            if not slo_contract:
                raise ValueError(f"cells[{index}].goodput.slo_contract must be nonempty")
            if goodput.get("unavailable_reason") is not None:
                raise ValueError(f"cells[{index}].goodput unavailable reason contradicts availability")
        else:
            if any(
                field in goodput
                for field in ("qualifying_requests", "output_tokens", "tokens_per_second")
            ):
                raise ValueError(f"cells[{index}].goodput unavailable numeric evidence must be absent")
            reason = goodput.get("unavailable_reason")
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError(f"cells[{index}].goodput unavailable reason is required")
    facts = study.get("study_facts")
    required_fact_fields = {"compatibility", "exclusions", "preflight", "future_work"}
    if not isinstance(facts, dict) or set(facts) != required_fact_fields:
        raise ValueError("study_facts must contain exactly compatibility, exclusions, preflight, and future_work")
    for field in sorted(required_fact_fields):
        if not isinstance(facts[field], list) or not all(
            isinstance(item, str) and item for item in facts[field]
        ):
            raise ValueError(f"study_facts.{field} must be a list of non-empty strings")
    return study


PROFILE_RE = re.compile(r"^(?P<input_tokens>\d+)tok-c(?P<concurrency>\d+)$")


def _stress_cells(study: dict[str, Any]) -> list[dict[str, Any]]:
    """Select the highest-concurrency profile for each prompt length."""

    parsed: list[tuple[dict[str, Any], int, int]] = []
    for cell in study["cells"]:
        match = PROFILE_RE.fullmatch(cell["profile"])
        if match is None:
            return study["cells"]
        parsed.append(
            (
                cell,
                int(match.group("input_tokens")),
                int(match.group("concurrency")),
            )
        )
    maximums: dict[int, int] = {}
    for _, input_tokens, concurrency in parsed:
        maximums[input_tokens] = max(maximums.get(input_tokens, 0), concurrency)
    return [
        cell
        for cell, input_tokens, concurrency in parsed
        if concurrency == maximums[input_tokens]
    ]


def _latency_svg(study: dict[str, Any]) -> str:
    cells = _stress_cells(study)
    width, row_height = 1200, 92
    height = 230 + row_height * len(cells)
    if any(not cell["client_ttft_ms"]["available"] for cell in cells):
        raise ValueError("TTFT chart requested without available TTFT evidence")
    max_ttft = max(float(cell["client_ttft_ms"]["p99"]) for cell in cells) or 1.0
    rows: list[str] = []
    for index, cell in enumerate(cells):
        y = 170 + index * row_height
        count = cell["client_ttft_ms"].get("count", "unknown")
        label = html.escape(f'{cell["runtime"]} · {cell["profile"]} · n={count}')
        rows.append(f'<text x="40" y="{y}" class="label">{label}</text>')
        for offset, (percentile, color) in enumerate(zip(PERCENTILES, ("#39d98a", "#ffcc66", "#ff6b6b"))):
            value = float(cell["client_ttft_ms"][percentile])
            bar_width = 650 * math.log1p(value) / math.log1p(max_ttft)
            bar_y = y - 29 + offset * 19
            rows.append(f'<rect x="350" y="{bar_y}" width="{bar_width:.2f}" height="13" rx="4" fill="{color}"/>')
            rows.append(f'<text x="{365 + bar_width:.2f}" y="{bar_y + 11}" class="value">{percentile} {value:.1f} ms</text>')
    gpu = html.escape(study["gpu"])
    model = html.escape(study["model"])
    classification = html.escape(str(study.get("classification", "unclassified")))
    return f'''<svg data-classification="{classification}" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<rect width="100%" height="100%" fill="#0b1020"/>
<style>.title{{fill:#fff;font:700 30px system-ui}}.sub{{fill:#aab3c5;font:16px system-ui}}.label{{fill:#fff;font:600 17px system-ui}}.value{{fill:#dbe3f4;font:13px ui-monospace,monospace}}</style>
<text x="40" y="50" class="title">TTFT p50 / p95 / p99</text>
<text x="40" y="82" class="sub">Observed, not vendor-claimed · {model} · {gpu}</text>
<text x="40" y="108" class="sub">Client streaming measurements; lower is better. Log-scaled bar length; exact values shown.</text>
{''.join(rows)}
</svg>'''


def _metric_matrix_svg(study: dict[str, Any]) -> str:
    cells = _stress_cells(study)
    labels = (
        ("TTFT", "client_ttft_ms"),
        ("TPOT", "client_tpot_ms"),
        ("ITL", "client_itl_ms"),
        ("E2E", "client_e2e_ms"),
    )
    width, row_height = 1320, 70
    height = 190 + row_height * len(cells)
    rows: list[str] = []
    for row_index, cell in enumerate(cells):
        y = 162 + row_index * row_height
        name = html.escape(f'{cell["runtime"]} · {cell["profile"]}')
        rows.append(f'<text x="32" y="{y}" class="row">{name}</text>')
        for column_index, (_, metric) in enumerate(labels):
            x = 390 + column_index * 225
            distribution = cell[metric]
            count = distribution.get("count")
            count_label = "unknown" if count is None else str(count)
            if distribution["available"]:
                p95 = float(distribution["p95"])
                p99 = float(distribution["p99"])
                rows.append(f'<text x="{x}" y="{y - 8}" class="value">p95 {p95:.1f} ms</text>')
                rows.append(f'<text x="{x}" y="{y + 15}" class="tail">p99 {p99:.1f} ms · n={count_label}</text>')
            else:
                rows.append(f'<text x="{x}" y="{y + 4}" class="value">unavailable · n={count_label}</text>')
        attempted = cell["successful_requests"] + cell["failed_requests"]
        rows.append(f'<text x="32" y="{y + 22}" class="value">{attempted} attempted</text>')
    headers = "".join(
        f'<text x="{390 + index * 225}" y="112" class="head">{label}</text>'
        for index, (label, _) in enumerate(labels)
    )
    classification = html.escape(str(study.get("classification", "unclassified")))
    return f'''<svg data-classification="{classification}" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<rect width="100%" height="100%" fill="#0b1020"/>
<style>.title{{fill:#fff;font:700 30px system-ui}}.sub{{fill:#aab3c5;font:17px system-ui}}.head{{fill:#7dd3fc;font:700 18px system-ui}}.row{{fill:#fff;font:600 17px system-ui}}.value{{fill:#ffcc66;font:16px ui-monospace,monospace}}.tail{{fill:#ff6b6b;font:700 16px ui-monospace,monospace}}</style>
<text x="32" y="48" class="title">Tail latency by metric</text>
<text x="32" y="78" class="sub">p95 and p99 · lower is better · attempted and metric n shown per row</text>
{headers}{''.join(rows)}
</svg>'''


def _throughput_svg(study: dict[str, Any]) -> str:
    cells = _stress_cells(study)
    width, row_height = 1200, 72
    height = 170 + row_height * len(cells)
    available_cells = [cell for cell in cells if cell["output_tokens_per_second"] is not None]
    if not available_cells:
        raise ValueError("throughput chart requested without exact token-rate evidence")
    peak = max(float(cell["output_tokens_per_second"]) for cell in available_cells) or 1.0
    rows: list[str] = []
    for index, cell in enumerate(cells):
        y = 130 + index * row_height
        if cell["output_tokens_per_second"] is None:
            continue
        value = float(cell["output_tokens_per_second"])
        bar_width = 650 * value / peak
        label = html.escape(f'{cell["runtime"]} · {cell["profile"]}')
        rows.append(f'<text x="32" y="{y}" class="row">{label}</text>')
        rows.append(f'<rect x="350" y="{y - 20}" width="{bar_width:.2f}" height="25" rx="6" fill="#39d98a"/>')
        output_total = cell.get("successful_output_tokens")
        mean_output = (
            output_total / cell["successful_requests"]
            if output_total is not None and cell["successful_requests"]
            else None
        )
        mean_label = "" if mean_output is None else f" · mean {mean_output:.2f} output tokens"
        rows.append(f'<text x="1160" y="{y}" text-anchor="end" class="value">{value:.1f} tok/s{mean_label}</text>')
    classification = html.escape(str(study.get("classification", "unclassified")))
    return f'''<svg data-classification="{classification}" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<rect width="100%" height="100%" fill="#0b1020"/>
<style>.title{{fill:#fff;font:700 30px system-ui}}.sub{{fill:#aab3c5;font:16px system-ui}}.row{{fill:#fff;font:600 16px system-ui}}.value{{fill:#dbe3f4;font:14px ui-monospace,monospace}}</style>
<text x="32" y="48" class="title">Output throughput</text>
<text x="32" y="78" class="sub">Successful streamed output tokens / measured wall time · higher is better</text>
{''.join(rows)}
</svg>'''


def _post(study: dict[str, Any]) -> str:
    runtimes = list(dict.fromkeys(cell["runtime"] for cell in study["cells"]))
    count_label = {1: "one", 2: "two", 3: "three", 4: "four"}.get(
        len(runtimes), str(len(runtimes))
    )
    configuration_label = "configuration" if len(runtimes) == 1 else "configurations"
    highlighted = _stress_cells(study)
    cell_lines = []
    for cell in highlighted:
        ttft = cell["client_ttft_ms"]
        tpot = cell["client_tpot_ms"]
        total = int(cell["successful_requests"]) + int(cell["failed_requests"])
        tpot_text = (
            f'TPOT p99 {tpot["p99"]:.1f} ms (n={tpot.get("count", "unknown")})'
            if tpot["available"]
            else f'TPOT unavailable ({tpot.get("unavailable_reason")})'
        )
        throughput = cell["output_tokens_per_second"]
        throughput_text = (
            f"{throughput:.1f} aggregate output tok/s"
            if throughput is not None
            else "output throughput unavailable"
        )
        output_total = cell.get("successful_output_tokens")
        output_text = ""
        if output_total is not None and cell["successful_requests"]:
            output_text = (
                f"; {output_total} delivered output tokens, mean "
                f'{output_total / cell["successful_requests"]:.2f} per successful request'
            )
        goodput = cell["goodput"]
        goodput_text = (
            f'{goodput["tokens_per_second"]:.1f} goodput tok/s from '
            f'{goodput["qualifying_requests"]} qualifying requests and '
            f'{goodput.get("output_tokens")} tokens under '
            f'{json.dumps(goodput["slo_contract"], sort_keys=True, allow_nan=False)}'
            if goodput.get("available") is True
            else f'goodput unavailable ({goodput.get("unavailable_reason")})'
        )
        cell_lines.append(
            f'- {cell["runtime"]} / {cell["profile"]}: TTFT p50/p95/p99 '
            f'{ttft["p50"]:.1f}/{ttft["p95"]:.1f}/{ttft["p99"]:.1f} ms; '
            f'n={ttft.get("count", "unknown")}; {tpot_text}; {throughput_text}; '
            f'{goodput_text}; '
            f'{cell["successful_requests"]} successful of {total} attempted{output_text}.'
        )
    facts = study["study_facts"]
    revised_tail_work = (
        "Repeat saturation cells as independent experimental runs and predeclare a "
        "tail-precision target; report uncertainty instead of treating any fixed "
        "request count as proof that p99 is stable."
    )
    future_work = [
        item for item in facts["future_work"] if "statistically stable" not in item
    ]
    if revised_tail_work not in future_work:
        future_work.insert(0, revised_tail_work)

    def section(title: str, values: list[str]) -> str:
        if not values:
            return ""
        return f"\n{title}:\n" + "\n".join(f"- {value}" for value in values) + "\n"

    opening = (
        "I ran hands-on serving measurements for "
        f'{count_label} runtime {configuration_label}: {", ".join(runtimes)}.'
    )
    return f'''{opening}

Model: {study["model"]} ({study["precision"]})
GPU: {study["gpu"]}
Revision: {study["model_revision"]}
{section("Comparability note", facts["compatibility"])}

The report retains attempted/success/failed counts and metric-specific sample counts. TTFT, TPOT, client inter-chunk latency, E2E latency, aggregate output rate, goodput, and failures are not treated as interchangeable samples.

{chr(10).join(cell_lines)}

These are observed results for this exact workload and hardware, not universal “ideal” numbers. The output-token setting is a maximum, not a guarantee of equal delivered work. p99 is descriptive and should always be read with its sample size, workload shape, cache state, and concurrency.

The useful reminder: throughput and tail latency can move in different directions. One average latency number is not enough for an inference SLO.
{section("Preflight evidence", facts["preflight"])}
{section("Exclusions", facts["exclusions"])}
{section("Future work", future_work)}

#LLM #Inference #MLOps #GPU #PerformanceEngineering
'''


def _alt_text(study: dict[str, Any]) -> str:
    selected = _stress_cells(study)
    runtimes = ", ".join(dict.fromkeys(cell["runtime"] for cell in study["cells"]))
    attempted = [cell["successful_requests"] + cell["failed_requests"] for cell in selected]
    attempted_text = (
        str(attempted[0])
        if len(set(attempted)) == 1
        else f"{min(attempted)}-{max(attempted)}"
    )
    return f'''# Accessibility text for social images

## TTFT p50 / p95 / p99

Horizontal bar chart of time to first token percentiles for {runtimes} across
{len(selected)} highest-concurrency runtime/profile cells on {study["gpu"]}.
Lower values are better; bar lengths use a disclosed logarithmic scale. Every
available row is labelled with exact p50, p95, and p99 milliseconds and its
metric-specific sample count. Cells contain
{attempted_text} attempted requests; unavailable metrics are labelled unavailable.

## Tail latency matrix

Table-style graphic listing p95 and p99 milliseconds for TTFT, TPOT, client
inter-chunk latency, and end-to-end latency for the same stress cells. It is
intended to show where tail behavior differs from median or throughput behavior.

## Output throughput

Horizontal bar chart of successful streamed output tokens per measured wall
second for the same {len(selected)} cells. Higher bars are better. Exact rates
and mean delivered output tokens per successful request are shown. Runtime
compatibility disclosures appear in the post and report and are required when
interpreting the chart.
'''


def build_assets(study: object, output_dir: Path) -> dict[str, Path]:
    validated = _validated(study)
    output_dir.mkdir(parents=True, exist_ok=True)
    latency_svg = output_dir / "ttft-tail-latency.svg"
    metric_matrix_svg = output_dir / "tail-latency-matrix.svg"
    throughput_svg = output_dir / "output-throughput.svg"
    linkedin_post = output_dir / "linkedin-post.md"
    alt_text = output_dir / "visual-alt-text.md"
    table = output_dir / "benchmark-summary.csv"
    latency_svg.write_text(_latency_svg(validated), encoding="utf-8")
    metric_matrix_svg.write_text(_metric_matrix_svg(validated), encoding="utf-8")
    throughput_svg.write_text(_throughput_svg(validated), encoding="utf-8")
    linkedin_post.write_text(_post(validated), encoding="utf-8")
    alt_text.write_text(_alt_text(validated), encoding="utf-8")
    with table.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow([
            "runtime", "profile", "attempted_requests", "successful_requests",
            "failed_requests", "metric", "count", "percentile_method", "source",
            "available", "unavailable_reason", "warnings", "p50_ms", "p95_ms",
            "p99_ms", "output_tokens_per_second", "qualifying_requests",
            "goodput_output_tokens", "goodput_tokens_per_second", "slo_contract",
            "successful_output_tokens", "mean_output_tokens",
        ])
        for cell in validated["cells"]:
            for metric in METRICS:
                values = cell[metric]
                goodput = cell["goodput"]
                output_total = cell.get("successful_output_tokens")
                mean_output = (
                    output_total / cell["successful_requests"]
                    if output_total is not None and cell["successful_requests"]
                    else None
                )
                writer.writerow([
                    cell["runtime"], cell["profile"],
                    cell["successful_requests"] + cell["failed_requests"],
                    cell["successful_requests"], cell["failed_requests"], metric,
                    values.get("count"), values.get("percentile_method"),
                    values.get("source"), values["available"],
                    values.get("unavailable_reason"), " | ".join(values["warnings"]),
                    values.get("p50"), values.get("p95"), values.get("p99"),
                    cell["output_tokens_per_second"], goodput.get("qualifying_requests"),
                    goodput.get("output_tokens"), goodput.get("tokens_per_second"),
                    json.dumps(goodput["slo_contract"], sort_keys=True, allow_nan=False),
                    output_total, mean_output,
                ])
    for path in (
        latency_svg,
        metric_matrix_svg,
        throughput_svg,
        linkedin_post,
        alt_text,
        table,
    ):
        path.chmod(0o600)
    return {
        "latency_svg": latency_svg,
        "metric_matrix_svg": metric_matrix_svg,
        "throughput_svg": throughput_svg,
        "linkedin_post": linkedin_post,
        "alt_text": alt_text,
        "summary_csv": table,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    arguments = parser.parse_args()
    study = json.loads(arguments.study.read_text(encoding="utf-8"))
    outputs = build_assets(study, arguments.output_dir)
    print(
        json.dumps(
            {name: str(path) for name, path in outputs.items()},
            sort_keys=True,
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
