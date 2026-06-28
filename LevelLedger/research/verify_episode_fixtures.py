"""Verify hand-seeded band lifecycle episode fixtures.

This script turns user-memory fixture windows into objective replay summaries
from MarketRecorder snapshots and current synthetic LL/EAR ownership grammar.
It does not decide trading rules. Its job is to prepare clean episode chunks
for later hypothesis tests and holdout/stress-test selection.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import traceback
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RESEARCH = ROOT / "research"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(RESEARCH))

from candidate_timing_probe import CandidateTimingProbe, load_filtered_snapshots  # noqa: E402
from ownership_bands_probe import Transition  # noqa: E402
from replay_levelledger import (  # noqa: E402
    BOOK_LOOKBACK_SEC,
    EVENT_Z_THRESHOLD,
    abbrev,
    build_sample,
    ny_hms,
    parse_ny,
    snapshot_timing_summary,
)


DEFAULT_SPEC = RESEARCH / "band_lifecycle_fixture_specs_2026-06-22_2026-06-26.json"
DEFAULT_OUT_DIR = RESEARCH / "out"


@dataclass(frozen=True)
class FixtureSpec:
    id: str
    date: str
    symbol: str
    window: str
    capture_root: str
    memory_label: str
    expected_type: str
    expected_side: str
    notes: str

    @property
    def session(self) -> str:
        return f"{self.date}:{self.symbol}"


def parse_window(date: str, window: str) -> tuple[datetime, datetime]:
    start_s, end_s = window.split("-", 1)
    return parse_ny(date, start_s), parse_ny(date, end_s)


def side_score(side: str, counts: Counter[tuple[str, str]]) -> int:
    other = "demand" if side == "supply" else "supply"
    return (
        counts[("OWNED", side)]
        + counts[("CONSUMED", side)]
        + counts[("HOLD", side)]
        + counts[("FAIL", other)]
    )


def transition_counts(transitions: list[Transition]) -> Counter[tuple[str, str]]:
    counts: Counter[tuple[str, str]] = Counter()
    for tr in transitions:
        counts[(tr.action, tr.side)] += 1
    return counts


def price_stats(snapshots: pl.DataFrame, start: datetime, end: datetime) -> dict[str, Any]:
    lo = int(start.timestamp() * 1_000_000)
    hi = int(end.timestamp() * 1_000_000)
    win = snapshots.filter((pl.col("timestamp_us") >= lo) & (pl.col("timestamp_us") <= hi))
    if win.height == 0:
        return {
            "start_tick": None,
            "end_tick": None,
            "high_tick": None,
            "low_tick": None,
            "net_ticks": None,
            "range_ticks": None,
        }
    ref = win["ref_tick"].to_list()
    return {
        "start_tick": int(ref[0]),
        "end_tick": int(ref[-1]),
        "high_tick": int(max(ref)),
        "low_tick": int(min(ref)),
        "net_ticks": int(ref[-1] - ref[0]),
        "range_ticks": int(max(ref) - min(ref)),
    }


def classify_episode(spec: FixtureSpec, stats: dict[str, Any], counts: Counter[tuple[str, str]]) -> tuple[str, str, str]:
    demand_score = side_score("demand", counts)
    supply_score = side_score("supply", counts)
    claims = (
        counts[("OWNED", "demand")]
        + counts[("OWNED", "supply")]
        + counts[("CONSUMED", "demand")]
        + counts[("CONSUMED", "supply")]
    )
    total_fails = counts[("FAIL", "demand")] + counts[("FAIL", "supply")]
    both_sides_active = (
        (counts[("OWNED", "demand")] + counts[("CONSUMED", "demand")] + counts[("FAIL", "demand")]) > 0
        and (counts[("OWNED", "supply")] + counts[("CONSUMED", "supply")] + counts[("FAIL", "supply")]) > 0
    )
    dominant_side = "demand" if demand_score > supply_score else "supply" if supply_score > demand_score else "mixed"
    dominant = max(demand_score, supply_score)
    opposing = min(demand_score, supply_score)
    ratio = dominant / max(1, opposing)
    range_ticks = stats.get("range_ticks") or 0
    net_ticks = stats.get("net_ticks") or 0

    if range_ticks >= 60 and claims <= 2:
        label = "no_build_directional"
    elif both_sides_active and total_fails >= 4 and ratio < 1.6:
        label = "balance_distribution"
    elif dominant >= 4 and ratio >= 1.6:
        label = f"directional_{dominant_side}"
    elif both_sides_active:
        label = "contested_or_repair"
    elif abs(net_ticks) >= 40 and claims <= 4:
        label = "thin_directional_or_no_build"
    else:
        label = "inconclusive"

    if label.startswith("directional"):
        use = "primary_directional" if dominant_side == spec.expected_side else "counter_or_review"
    elif label in ("balance_distribution", "contested_or_repair"):
        use = "stress_balance"
    elif "no_build" in label:
        use = "counter_no_build"
    else:
        use = "review"

    confidence = "medium"
    if label == "inconclusive":
        confidence = "low"
    elif ratio >= 2.2 or label in ("balance_distribution", "no_build_directional"):
        confidence = "high"

    return label, use, confidence


def top_transitions(transitions: list[Transition], limit: int = 12) -> str:
    selected = [
        tr for tr in transitions
        if tr.action in ("OWNED", "CONSUMED", "TEST", "HOLD", "FAIL")
    ][:limit]
    parts = []
    for tr in selected:
        price = abbrev((tr.min_tick + tr.max_tick) // 2)
        parts.append(f"{ny_hms(tr.ts)} {tr.action}:{tr.side}@{price}")
    return "; ".join(parts)


def replay_fixture(spec: FixtureSpec, args: argparse.Namespace) -> dict[str, Any]:
    start, end = parse_window(spec.date, spec.window)
    snapshots = load_filtered_snapshots(
        spec.capture_root,
        spec.symbol,
        spec.date,
        start - timedelta(minutes=args.warmup_min),
        end,
    )
    _, _, _, gaps = snapshot_timing_summary(snapshots, args.gap_threshold_sec)
    probe = CandidateTimingProbe(
        session=spec.session,
        gap_threshold_sec=args.gap_threshold_sec,
        event_z=args.event_z,
        cluster_min_events=args.cluster_min_events,
        cluster_ticks=args.cluster_ticks,
        cluster_sec=args.cluster_sec,
        cluster_min_score=args.cluster_min_score,
        confirm_ticks=args.confirm_ticks,
        confirm_sec=args.confirm_sec,
        test_buffer_ticks=args.test_buffer_ticks,
        fail_buffer_ticks=args.fail_buffer_ticks,
        fail_confirm_ticks=args.fail_confirm_ticks,
        fail_sec=args.fail_sec,
        hold_confirm_ticks=args.hold_confirm_ticks,
        book_lookback_sec=args.book_lookback_sec,
    )
    for row in snapshots.iter_rows(named=True):
        probe.on_sample(build_sample(row))
    probe.finish(end)

    transitions = [tr for tr in probe.transitions if start <= tr.ts <= end]
    counts = transition_counts(transitions)
    stats = price_stats(snapshots, start, end)
    verified_label, recommended_use, confidence = classify_episode(spec, stats, counts)
    demand_score = side_score("demand", counts)
    supply_score = side_score("supply", counts)
    dominant_side = "demand" if demand_score > supply_score else "supply" if supply_score > demand_score else "mixed"

    return {
        "id": spec.id,
        "session": spec.session,
        "date": spec.date,
        "symbol": spec.symbol,
        "window": spec.window,
        "capture_root": spec.capture_root,
        "memory_label": spec.memory_label,
        "expected_type": spec.expected_type,
        "expected_side": spec.expected_side,
        "verified_label": verified_label,
        "recommended_use": recommended_use,
        "confidence": confidence,
        "dominant_side": dominant_side,
        "demand_score": demand_score,
        "supply_score": supply_score,
        "start_tick": stats["start_tick"],
        "end_tick": stats["end_tick"],
        "high_tick": stats["high_tick"],
        "low_tick": stats["low_tick"],
        "start_price": abbrev(stats["start_tick"]) if stats["start_tick"] is not None else "",
        "end_price": abbrev(stats["end_tick"]) if stats["end_tick"] is not None else "",
        "net_ticks": stats["net_ticks"],
        "range_ticks": stats["range_ticks"],
        "transitions": len(transitions),
        "claims_demand": counts[("OWNED", "demand")] + counts[("CONSUMED", "demand")],
        "claims_supply": counts[("OWNED", "supply")] + counts[("CONSUMED", "supply")],
        "owned_demand": counts[("OWNED", "demand")],
        "owned_supply": counts[("OWNED", "supply")],
        "consumed_demand": counts[("CONSUMED", "demand")],
        "consumed_supply": counts[("CONSUMED", "supply")],
        "tests_demand": counts[("TEST", "demand")],
        "tests_supply": counts[("TEST", "supply")],
        "holds_demand": counts[("HOLD", "demand")],
        "holds_supply": counts[("HOLD", "supply")],
        "fails_demand": counts[("FAIL", "demand")],
        "fails_supply": counts[("FAIL", "supply")],
        "snapshot_gaps": len(gaps),
        "notes": spec.notes,
        "transition_excerpt": top_transitions(transitions),
    }


def load_specs(path: Path) -> list[FixtureSpec]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [FixtureSpec(**item) for item in data]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0].keys()) if rows else []
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def pct(value: int, total: int) -> str:
    if total <= 0:
        return "n/a"
    return f"{100.0 * value / total:.1f}%"


def write_markdown(path: Path, rows: list[dict[str, Any]], args: argparse.Namespace) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Verified Band Lifecycle Episode Chunks",
        "",
        "These are replay-derived fixture summaries from user-memory seed windows. Labels are provisional and should be reviewed before becoming canonical fixtures.",
        "",
        "## Availability",
        "",
    ]
    roots = sorted({str(row["capture_root"]) for row in rows})
    dates = sorted({str(row["date"]) for row in rows})
    for root in roots:
        root_dates = sorted({str(row["date"]) for row in rows if str(row["capture_root"]) == root})
        lines.append(f"- `{root}`: {', '.join(root_dates)}")
    lines.extend([
        "- No live EAR logs were used.",
        "",
        "## Summary",
        "",
    ])
    use_counts = Counter(row["recommended_use"] for row in rows)
    label_counts = Counter(row["verified_label"] for row in rows)
    for use, count in sorted(use_counts.items()):
        lines.append(f"- `{use}`: {count}")
    lines.extend(["", "Verified labels:", ""])
    for label, count in sorted(label_counts.items()):
        lines.append(f"- `{label}`: {count}")

    lines.extend(
        [
            "",
            "## Episode Chunks",
            "",
            "| id | window | memory | verified | use | side | range/net | claims D/S | fails D/S | gaps |",
            "| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in rows:
        lines.append(
            f"| `{row['id']}` | {row['session']} {row['window']} | "
            f"{row['memory_label']} | `{row['verified_label']}` | "
            f"`{row['recommended_use']}` | {row['dominant_side']} | "
            f"{row['range_ticks']}/{row['net_ticks']} | "
            f"{row['claims_demand']}/{row['claims_supply']} | "
            f"{row['fails_demand']}/{row['fails_supply']} | "
            f"{row['snapshot_gaps']} |"
        )

    lines.extend(["", "## Detailed Notes", ""])
    for row in rows:
        lines.extend(
            [
                f"### {row['id']}",
                "",
                f"- window: `{row['session']} {row['window']}`",
                f"- memory: {row['memory_label']}",
                f"- expected: `{row['expected_type']}` / `{row['expected_side']}`",
                f"- verified: `{row['verified_label']}` / `{row['recommended_use']}` / confidence `{row['confidence']}`",
                f"- price: start `{row['start_price']}` end `{row['end_price']}`, range `{row['range_ticks']}` ticks, net `{row['net_ticks']}` ticks",
                f"- claims D/S: `{row['claims_demand']}/{row['claims_supply']}`, tests D/S: `{row['tests_demand']}/{row['tests_supply']}`, holds D/S: `{row['holds_demand']}/{row['holds_supply']}`, fails D/S: `{row['fails_demand']}/{row['fails_supply']}`",
                f"- transition excerpt: {row['transition_excerpt'] or '(none)'}",
                f"- review note: {row['notes']}",
                "",
            ]
        )

    lines.extend(
        [
            "## Parameters",
            "",
            f"- event_z: `{args.event_z}`",
            f"- cluster_min_events: `{args.cluster_min_events}`",
            f"- cluster_ticks: `{args.cluster_ticks}`",
            f"- cluster_sec: `{args.cluster_sec}`",
            f"- cluster_min_score: `{args.cluster_min_score}`",
            f"- confirm_ticks/sec: `{args.confirm_ticks}` / `{args.confirm_sec}`",
            f"- fail_confirm_ticks/sec: `{args.fail_confirm_ticks}` / `{args.fail_sec}`",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", default=str(DEFAULT_SPEC))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--tag", default="20260622_20260626")
    parser.add_argument("--warmup-min", type=int, default=90)
    parser.add_argument("--event-z", type=float, default=EVENT_Z_THRESHOLD)
    parser.add_argument("--book-lookback-sec", type=int, default=BOOK_LOOKBACK_SEC)
    parser.add_argument("--cluster-min-events", type=int, default=3)
    parser.add_argument("--cluster-ticks", type=int, default=10)
    parser.add_argument("--cluster-sec", type=int, default=90)
    parser.add_argument("--cluster-min-score", type=float, default=8.0)
    parser.add_argument("--confirm-ticks", type=int, default=8)
    parser.add_argument("--confirm-sec", type=int, default=10)
    parser.add_argument("--test-buffer-ticks", type=int, default=4)
    parser.add_argument("--fail-buffer-ticks", type=int, default=2)
    parser.add_argument("--fail-confirm-ticks", type=int, default=24)
    parser.add_argument("--fail-sec", type=int, default=20)
    parser.add_argument("--hold-confirm-ticks", type=int, default=10)
    parser.add_argument("--gap-threshold-sec", type=float, default=5.0)
    args = parser.parse_args()

    specs = load_specs(Path(args.spec))
    rows: list[dict[str, Any]] = []
    for spec in specs:
        print(f"verifying {spec.id} {spec.session} {spec.window}", flush=True)
        try:
            rows.append(replay_fixture(spec, args))
        except Exception:
            traceback.print_exc()
            raise
    out_dir = Path(args.output_dir)
    csv_path = out_dir / f"band_lifecycle_verified_episode_chunks_{args.tag}.csv"
    md_path = out_dir / f"band_lifecycle_verified_episode_chunks_{args.tag}.md"
    write_csv(csv_path, rows)
    write_markdown(md_path, rows, args)
    print(f"wrote {csv_path}")
    print(f"wrote {md_path}")


if __name__ == "__main__":
    main()
