from __future__ import annotations

import argparse
import json
import math
from html import escape
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = (
    ROOT / "artifacts" / "public" / "summary_factuality_review_metrics.json"
)
DEFAULT_OUTPUT = ROOT / "docs" / "assets" / "summary_factuality_review.svg"

WIDTH = 1200
HEIGHT = 650
BACKGROUND = "#fbfaf7"
INK = "#20242a"
MUTED = "#68717b"
RULE = "#d6d9dc"
GRID = "#e7e9eb"
NEUTRAL = "#aeb6bf"
NEUTRAL_DARK = "#7b858f"
ACCENT = "#a75b2d"


def _number(value: Any, *, name: str, integer: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    if integer and number != int(number):
        raise ValueError(f"{name} must be an integer")
    return number


def load_metrics(source_path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(source_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"source artifact does not exist: {source_path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"source artifact is not valid JSON: {source_path}") from exc
    if not isinstance(payload, dict):
        raise TypeError("source artifact must contain a JSON object")

    score_distribution = payload.get("score_distribution")
    if not isinstance(score_distribution, dict):
        raise TypeError("score_distribution must be an object")
    counts: dict[int, int] = {}
    for score in range(1, 6):
        raw = score_distribution.get(str(score))
        count = _number(raw, name=f"score_distribution[{score}]", integer=True)
        if count < 0:
            raise ValueError(f"score_distribution[{score}] must be non-negative")
        counts[score] = int(count)

    reviewed = int(
        _number(
            payload.get("reviewed_sample_count"),
            name="reviewed_sample_count",
            integer=True,
        )
    )
    lineage_bound = int(
        _number(
            payload.get("lineage_bound_review_count"),
            name="lineage_bound_review_count",
            integer=True,
        )
    )
    if reviewed < 1:
        raise ValueError("reviewed_sample_count must be positive")
    if sum(counts.values()) != reviewed:
        raise ValueError("score counts must sum to reviewed_sample_count")
    if lineage_bound != reviewed:
        raise ValueError("lineage_bound_review_count must equal reviewed_sample_count")

    mean = _number(payload.get("mean_factuality_score"), name="mean_factuality_score")
    weighted_mean = sum(score * count for score, count in counts.items()) / reviewed
    if not math.isclose(mean, weighted_mean, rel_tol=1e-9, abs_tol=1e-9):
        raise ValueError("mean_factuality_score does not match the score distribution")
    if not 1 <= mean <= 5:
        raise ValueError("mean_factuality_score must be between 1 and 5")

    rates: dict[str, float] = {}
    for key in ("exact_quote_rate", "all_claims_supported_rate"):
        rate = _number(payload.get(key), name=key)
        if not 0 <= rate <= 1:
            raise ValueError(f"{key} must be between 0 and 1")
        rates[key] = rate

    created_at = payload.get("created_at")
    if not isinstance(created_at, str) or len(created_at) < 10:
        raise ValueError("created_at must be an ISO date or timestamp")
    reviewer_mode = payload.get("reviewer_mode")
    if not isinstance(reviewer_mode, str) or not reviewer_mode.strip():
        raise ValueError("reviewer_mode must be nonblank")
    if reviewer_mode != "human_review_with_ai_assistance":
        raise ValueError(f"unsupported reviewer_mode: {reviewer_mode}")

    return {
        "counts": counts,
        "reviewed": reviewed,
        "lineage_bound": lineage_bound,
        "mean": mean,
        "exact_quote_rate": rates["exact_quote_rate"],
        "all_claims_supported_rate": rates["all_claims_supported_rate"],
        "created_date": created_at[:10],
        "reviewer_mode": reviewer_mode,
        "reviewer_mode_label": "Human review with AI assistance",
    }


def _text(
    value: str,
    *,
    x: float,
    y: float,
    size: int,
    fill: str = INK,
    weight: str = "400",
    anchor: str = "start",
    family: str = "system",
) -> str:
    font = (
        "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
        if family == "mono"
        else "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    )
    return (
        f'<text x="{x}" y="{y}" fill="{fill}" font-family="{font}" '
        f'font-size="{size}px" font-weight="{weight}" text-anchor="{anchor}">{escape(value)}</text>'
    )


def _rate(value: float) -> str:
    return f"{value:.0%}"


def render_svg(metrics: dict[str, Any], *, source_label: str) -> str:
    counts: dict[int, int] = metrics["counts"]
    max_count = max(counts.values())
    y_max = max(50, int(math.ceil(max_count / 10) * 10))
    chart_left, chart_top, chart_height = 110, 155, 300
    baseline = chart_top + chart_height
    bar_width, gap = 76, 34
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="auto" viewBox="0 0 {WIDTH} {HEIGHT}" preserveAspectRatio="xMidYMid meet" role="img" aria-labelledby="figure-title figure-description">',
        '<title id="figure-title">Distribution of factuality scores across reviewed complaint summaries</title>',
        '<desc id="figure-description">A bar chart of five factuality-score categories with a compact summary of the frozen human review evidence.</desc>',
        f'<rect width="{WIDTH}" height="{HEIGHT}" fill="{BACKGROUND}"/>',
        _text("Summary factuality review", x=72, y=55, size=28, weight="600"),
        _text(
            f"Frozen, lineage-bound sample · score distribution · n = {metrics['reviewed']}",
            x=72,
            y=84,
            size=15,
            fill=MUTED,
        ),
        f'<line x1="72" y1="110" x2="1128" y2="110" stroke="{RULE}" stroke-width="1"/>',
    ]

    for tick in (0, 15, 30, 45, 50):
        y = baseline - (tick / y_max) * chart_height
        parts.append(
            f'<line x1="{chart_left}" y1="{y:.1f}" x2="680" y2="{y:.1f}" stroke="{GRID}" stroke-width="1"/>'
        )
        parts.append(
            _text(
                str(tick),
                x=88,
                y=y + 5,
                size=12,
                fill=MUTED,
                anchor="end",
                family="mono",
            )
        )

    parts.extend(
        [
            f'<line x1="{chart_left}" y1="{chart_top}" x2="{chart_left}" y2="{baseline}" stroke="{INK}" stroke-width="1.2"/>',
            f'<line x1="{chart_left}" y1="{baseline}" x2="680" y2="{baseline}" stroke="{INK}" stroke-width="1.2"/>',
            _text(
                "Reviewed summaries", x=28, y=315, size=14, fill=MUTED, anchor="middle"
            ),
            _text(
                "Factuality score", x=395, y=510, size=14, fill=MUTED, anchor="middle"
            ),
        ]
    )
    # Rotate the y-axis title around its own anchor without changing the chart viewBox.
    parts[-2] = (
        '<text x="28" y="315" fill="'
        + MUTED
        + '" font-family="-apple-system, BlinkMacSystemFont, \'Segoe UI\', sans-serif" font-size="14px" text-anchor="middle" transform="rotate(-90 28 315)">Reviewed summaries</text>'
    )

    for index, score in enumerate(range(1, 6)):
        x = chart_left + 42 + index * (bar_width + gap)
        count = counts[score]
        height = (count / y_max) * chart_height
        y = baseline - height
        fill = ACCENT if score == 5 else NEUTRAL
        if count == 0:
            parts.append(
                f'<rect class="bar-score-{score}" data-score="{score}" data-count="0" x="{x}" y="{baseline - 1:.1f}" width="{bar_width}" height="2" fill="none" stroke="{NEUTRAL_DARK}" stroke-width="1.2"/>'
            )
            label_y = baseline - 12
        else:
            parts.append(
                f'<rect class="bar-score-{score}" data-score="{score}" data-count="{count}" x="{x}" y="{y:.1f}" width="{bar_width}" height="{height:.1f}" fill="{fill}"/>'
            )
            label_y = max(y - 12, chart_top - 2)
        parts.append(
            _text(
                str(count),
                x=x + bar_width / 2,
                y=label_y,
                size=15,
                weight="600",
                anchor="middle",
                family="mono",
            )
        )
        parts.append(
            _text(
                str(score),
                x=x + bar_width / 2,
                y=baseline + 27,
                size=14,
                fill=MUTED,
                anchor="middle",
                family="mono",
            )
        )

    panel_x, panel_y, panel_width, panel_height = 780, 145, 320, 330
    parts.extend(
        [
            f'<rect x="{panel_x}" y="{panel_y}" width="{panel_width}" height="{panel_height}" fill="none" stroke="{RULE}" stroke-width="1"/>',
            _text("Evidence summary", x=810, y=183, size=16, weight="600"),
        ]
    )
    summary_rows = [
        ("Mean factuality", f"{metrics['mean']:.2f}/5"),
        ("Exact quotes", _rate(metrics["exact_quote_rate"])),
        ("All claims supported", _rate(metrics["all_claims_supported_rate"])),
        ("Lineage-bound reviews", f"n = {metrics['lineage_bound']}"),
    ]
    for row_index, (label, value) in enumerate(summary_rows):
        y = 225 + row_index * 57
        parts.append(_text(label, x=810, y=y, size=13, fill=MUTED))
        parts.append(
            _text(value, x=810, y=y + 26, size=22, weight="600", family="mono")
        )
        if row_index < len(summary_rows) - 1:
            parts.append(
                f'<line x1="810" y1="{y + 39}" x2="1070" y2="{y + 39}" stroke="{GRID}" stroke-width="1"/>'
            )
    parts.append(
        _text(metrics["reviewer_mode_label"], x=810, y=445, size=12, fill=MUTED)
    )

    parts.append(
        f'<line x1="72" y1="545" x2="1128" y2="545" stroke="{INK}" stroke-width="1.2"/>'
    )
    boundary_1 = f"Frozen, lineage-bound {metrics['reviewed']}-case sample. {metrics['reviewer_mode_label']}. Aggregate evidence only;"
    boundary_2 = "not a population estimate. The public demo does not persist the private review store."
    parts.append(_text(boundary_1, x=72, y=580, size=15, fill=INK, weight="500"))
    parts.append(_text(boundary_2, x=72, y=607, size=15, fill=INK, weight="500"))
    parts.append(
        _text(
            f"Source: {source_label} · Evidence date: {metrics['created_date']}",
            x=72,
            y=638,
            size=11,
            fill=MUTED,
            family="mono",
        )
    )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def generate_visual(
    source_path: Path = DEFAULT_SOURCE, output_path: Path = DEFAULT_OUTPUT
) -> None:
    metrics = load_metrics(source_path)
    svg = render_svg(
        metrics, source_label="artifacts/public/summary_factuality_review_metrics.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(svg, encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate the public summary-factuality evidence SVG."
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        generate_visual(args.source, args.output)
    except (OSError, TypeError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
