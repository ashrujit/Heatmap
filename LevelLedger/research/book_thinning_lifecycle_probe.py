"""Fixture-scoped Book Thinning lifecycle probe.

This is Thesis 8 from the Skurry Now Lens research note. It reuses the existing
Skurry-style `book_thinning_probe` detector, then attaches nearby thinning
events to the T3 lifecycle anchors. The question is contextual:

- did liquidity disappear ahead of the move without matching tape?
- did that happen before/after tests, failures, or consumed conversions?
- does phase explain why the same measurement is noisy?

The output is descriptive research data only. It does not consume live EAR logs.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import math
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Iterable


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RESEARCH = ROOT / "research"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(RESEARCH))

from book_thinning_probe import ThinningEvent, phase_name, replay  # noqa: E402


DEFAULT_ANCHORS = RESEARCH / "out" / "episode_terrain_lifecycle_probe_20260623_20260626.csv"
DEFAULT_OUT_DIR = RESEARCH / "out"
PHASE_GATED_OUT = {"premarket", "open", "ib", "close", "after_hours"}

DEFENSE_LIFECYCLES = {
    "clean_hold",
    "weak_hold",
    "weak_hold_same_side_continued",
    "fake_failure_same_side_renewal",
    "direct_conversion_with_followthrough",
}
CONTESTED_LIFECYCLES = {
    "weak_hold_opposition_renewed",
    "failure_into_balance",
    "tested_not_disproved",
}
FAILURE_LIFECYCLES = {
    "terminal_failure",
    "no_structural_followthrough",
    "failed_or_churn_conversion",
    "conversion_no_followthrough",
}


@dataclass(frozen=True)
class SessionSpec:
    date: str
    symbol: str

    @property
    def label(self) -> str:
        return f"{self.date}:{self.symbol}"


@dataclass
class SessionThinning:
    spec: SessionSpec
    events: list[ThinningEvent]
    times: list[int]


def parse_iso_ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def us(ts: datetime) -> int:
    return int(ts.timestamp() * 1_000_000)


def side_to_direction(side: str) -> str:
    return "UP" if side == "demand" else "DOWN"


def direction_to_side(direction: str) -> str:
    return "demand" if direction == "UP" else "supply"


def anchor_expected_side(row: dict[str, str]) -> str:
    anchor_class = row.get("anchor_class", "")
    if anchor_class == "band_failure":
        return row.get("break_side") or row.get("moveaway_side") or row.get("band_side")
    if row.get("moveaway_side"):
        return row["moveaway_side"]
    if anchor_class == "consumed_conversion":
        return row.get("band_side") or row.get("break_side")
    return row.get("band_side") or row.get("break_side")


def outcome_group(lifecycle: str) -> str:
    if lifecycle in DEFENSE_LIFECYCLES:
        return "owner_defended"
    if lifecycle in CONTESTED_LIFECYCLES:
        return "contested_or_balance"
    if lifecycle in FAILURE_LIFECYCLES:
        return "failed_or_no_followthrough"
    return "other"


def phase_gate_label(phase: str) -> str:
    return "phase_gated_out" if phase in PHASE_GATED_OUT else "phase_allowed"


def event_strength(event: ThinningEvent) -> float:
    return event.size_dropped * max(0.0, event.drop_pct)


def near_events(
    session: SessionThinning,
    anchor_us: int,
    before_sec: int,
    after_sec: int,
) -> tuple[list[ThinningEvent], list[ThinningEvent]]:
    pre_start = anchor_us - before_sec * 1_000_000
    post_end = anchor_us + after_sec * 1_000_000
    lo = bisect.bisect_left(session.times, pre_start)
    mid = bisect.bisect_right(session.times, anchor_us)
    hi = bisect.bisect_right(session.times, post_end)
    return session.events[lo:mid], session.events[mid:hi]


def summarize_event_set(
    events: Iterable[ThinningEvent],
    expected_direction: str,
    phase_allowed_only: bool,
) -> dict[str, object]:
    selected = [
        event for event in events
        if not phase_allowed_only or phase_gate_label(event.phase) == "phase_allowed"
    ]
    aligned = [event for event in selected if event.direction == expected_direction]
    opposed = [event for event in selected if event.direction != expected_direction]
    best = max(selected, key=event_strength, default=None)
    best_aligned = max(aligned, key=event_strength, default=None)
    return {
        "count": len(selected),
        "aligned_count": len(aligned),
        "opposed_count": len(opposed),
        "best_direction": best.direction if best is not None else "",
        "best_phase": best.phase if best is not None else "",
        "best_size_dropped": best.size_dropped if best is not None else 0.0,
        "best_drop_pct": best.drop_pct if best is not None else 0.0,
        "best_tape_ratio": best.tape_ratio if best is not None else 0.0,
        "best_follow_ticks": best.follow_ticks if best is not None else 0,
        "best_adverse_ticks": best.adverse_ticks if best is not None else 0,
        "best_aligned_size_dropped": best_aligned.size_dropped if best_aligned is not None else 0.0,
        "best_aligned_drop_pct": best_aligned.drop_pct if best_aligned is not None else 0.0,
        "best_aligned_tape_ratio": best_aligned.tape_ratio if best_aligned is not None else 0.0,
    }


def thinning_label(pre: dict[str, object], post: dict[str, object]) -> str:
    pre_aligned = int(pre["aligned_count"])
    post_aligned = int(post["aligned_count"])
    pre_opposed = int(pre["opposed_count"])
    post_opposed = int(post["opposed_count"])
    aligned = pre_aligned + post_aligned
    opposed = pre_opposed + post_opposed
    if aligned > 0 and opposed > 0:
        return "mixed_thinning"
    if pre_aligned > 0 and post_aligned > 0:
        return "aligned_before_after"
    if pre_aligned > 0:
        return "aligned_before"
    if post_aligned > 0:
        return "aligned_after"
    if opposed > 0:
        return "opposed_only"
    return "no_near_thinning"


def prefixed(prefix: str, values: dict[str, object]) -> dict[str, object]:
    return {f"{prefix}_{key}": value for key, value in values.items()}


def load_anchors(path: Path, args: argparse.Namespace) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with path.open("r", newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if args.fixture_id and row.get("fixture_id") not in args.fixture_id:
                continue
            if args.bucket and row.get("curated_bucket") not in args.bucket:
                continue
            if args.anchor_class and row.get("anchor_class") not in args.anchor_class:
                continue
            if args.lifecycle_label and row.get("lifecycle_label") not in args.lifecycle_label:
                continue
            rows.append(row)
    return rows


def group_by_session(rows: Iterable[dict[str, str]]) -> dict[SessionSpec, list[dict[str, str]]]:
    grouped: dict[SessionSpec, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[SessionSpec(row["date"], row["symbol"])].append(row)
    return grouped


def load_session_thinning(spec: SessionSpec, args: argparse.Namespace) -> SessionThinning:
    prior_symbol = getattr(args, "symbol_dir", None)
    args.symbol_dir = spec.symbol
    print(f"book thinning replay {spec.label}", flush=True)
    events, _ = replay(spec.date, args)
    if prior_symbol is not None:
        args.symbol_dir = prior_symbol
    events = sorted(events, key=lambda item: item.us)
    return SessionThinning(spec=spec, events=events, times=[event.us for event in events])


def enrich_rows(rows: list[dict[str, str]], args: argparse.Namespace) -> tuple[list[dict[str, object]], dict[str, SessionThinning]]:
    sessions: dict[str, SessionThinning] = {}
    out: list[dict[str, object]] = []
    for spec, session_rows in group_by_session(rows).items():
        session = load_session_thinning(spec, args)
        sessions[spec.label] = session
        for row in session_rows:
            anchor_ts = parse_iso_ts(row["anchor_ts"])
            anchor_us = us(anchor_ts)
            pre_events, post_events = near_events(
                session,
                anchor_us,
                args.anchor_before_sec,
                args.anchor_after_sec,
            )
            expected_side = anchor_expected_side(row)
            expected_direction = side_to_direction(expected_side)
            pre_all = summarize_event_set(pre_events, expected_direction, phase_allowed_only=False)
            post_all = summarize_event_set(post_events, expected_direction, phase_allowed_only=False)
            pre_allowed = summarize_event_set(pre_events, expected_direction, phase_allowed_only=True)
            post_allowed = summarize_event_set(post_events, expected_direction, phase_allowed_only=True)
            anchor_phase = phase_name(anchor_ts)
            enriched: dict[str, object] = dict(row)
            enriched.update(
                {
                    "expected_side_for_thinning": expected_side,
                    "expected_direction_for_thinning": expected_direction,
                    "expected_passive_side_to_thin": "ask" if expected_direction == "UP" else "bid",
                    "anchor_phase": anchor_phase,
                    "anchor_phase_gate": phase_gate_label(anchor_phase),
                    "outcome_group": outcome_group(row.get("lifecycle_label", "")),
                    "thinning_label_all": thinning_label(pre_all, post_all),
                    "thinning_label_phase_allowed": thinning_label(pre_allowed, post_allowed),
                    "session_thinning_events": len(session.events),
                }
            )
            enriched.update(prefixed("pre_thin_all", pre_all))
            enriched.update(prefixed("post_thin_all", post_all))
            enriched.update(prefixed("pre_thin_phase_allowed", pre_allowed))
            enriched.update(prefixed("post_thin_phase_allowed", post_allowed))
            out.append(enriched)
    return out, sessions


def pct(value: int, total: int) -> str:
    if total <= 0:
        return "n/a"
    return f"{100.0 * value / total:.1f}%"


def count_table(rows: list[dict[str, object]], fields: list[str], outcome_field: str) -> list[str]:
    groups: dict[tuple[str, ...], Counter[str]] = defaultdict(Counter)
    for row in rows:
        key = tuple(str(row.get(field, "")) for field in fields)
        groups[key][str(row.get(outcome_field, ""))] += 1
    if not groups:
        return ["No rows."]
    outcomes = sorted({outcome for counter in groups.values() for outcome in counter})
    lines = [
        "| " + " | ".join(fields) + " | n | " + " | ".join(outcomes) + " |",
        "| " + " | ".join("---" for _ in fields) + " | ---: | " + " | ".join("---:" for _ in outcomes) + " |",
    ]
    for key in sorted(groups):
        counter = groups[key]
        total = sum(counter.values())
        cells = [f"{counter[outcome]} ({pct(counter[outcome], total)})" for outcome in outcomes]
        lines.append("| " + " | ".join(key) + f" | {total} | " + " | ".join(cells) + " |")
    return lines


def numeric_summary(rows: list[dict[str, object]], field: str) -> str:
    values: list[float] = []
    for row in rows:
        value = row.get(field)
        if value in ("", None):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            values.append(number)
    if not values:
        return "n/a"
    values.sort()
    p25 = values[min(len(values) - 1, max(0, math.ceil(0.25 * len(values)) - 1))]
    p75 = values[min(len(values) - 1, math.ceil(0.75 * len(values)) - 1)]
    return f"n={len(values)} median={median(values):.2f} p25={p25:.2f} p75={p75:.2f}"


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def example_rows(rows: list[dict[str, object]], label: str, limit: int = 18) -> list[str]:
    selected = [
        row for row in rows
        if row.get("thinning_label_all") == label
    ][:limit]
    lines = [
        f"### {label}",
        "",
        "| fixture | time | anchor | phase | expected | lifecycle | pre/post aligned | best drop |",
        "| --- | --- | --- | --- | --- | --- | ---: | ---: |",
    ]
    for row in selected:
        lines.append(
            f"| `{row.get('fixture_id')}` | {row.get('anchor_ny')} | "
            f"{row.get('anchor_class')}@{row.get('band_price')} | {row.get('anchor_phase')} | "
            f"{row.get('expected_direction_for_thinning')} | `{row.get('lifecycle_label')}` | "
            f"{int(row.get('pre_thin_all_aligned_count') or 0)}/{int(row.get('post_thin_all_aligned_count') or 0)} | "
            f"{max(float(row.get('pre_thin_all_best_aligned_size_dropped') or 0), float(row.get('post_thin_all_best_aligned_size_dropped') or 0)):.0f} |"
        )
    if not selected:
        lines.append("| n/a | n/a | n/a | n/a | n/a | n/a | 0 | 0 |")
    return lines


def write_report(
    path: Path,
    rows: list[dict[str, object]],
    sessions: dict[str, SessionThinning],
    args: argparse.Namespace,
) -> None:
    tests = [row for row in rows if row.get("anchor_class") == "band_test"]
    failures = [row for row in rows if row.get("anchor_class") == "band_failure"]
    conversions = [row for row in rows if row.get("anchor_class") == "consumed_conversion"]
    primary = [row for row in rows if row.get("curated_bucket") == "primary_dev"]
    phase_allowed = [row for row in rows if row.get("anchor_phase_gate") == "phase_allowed"]
    lines = [
        "# Book Thinning Lifecycle Probe",
        "",
        "Fixture-scoped Thesis 8 pass. It attaches Skurry-style book-thinning events to T3 lifecycle anchors.",
        "",
        "## Coverage",
        "",
        f"- anchor rows: `{len(rows)}`",
        f"- band tests: `{len(tests)}`",
        f"- band failures: `{len(failures)}`",
        f"- consumed conversions: `{len(conversions)}`",
        f"- phase-allowed anchor rows: `{len(phase_allowed)}`",
        f"- anchor source: `{args.anchors}`",
        f"- detector phase gate during replay: `{args.phase_gate}`",
        "",
    ]
    for label, session in sorted(sessions.items()):
        by_phase = Counter(event.phase for event in session.events)
        phase_text = ", ".join(f"{key}={value}" for key, value in sorted(by_phase.items()))
        lines.append(f"- `{label}` thinning_events={len(session.events)} {phase_text}")

    lines.extend(["", "## Outcome By Thinning Label", ""])
    lines.extend(count_table(rows, ["thinning_label_all"], "outcome_group"))
    lines.extend(["", "## Lifecycle By Thinning Label", ""])
    lines.extend(count_table(rows, ["thinning_label_all"], "lifecycle_label"))
    lines.extend(["", "## Phase Stratification", ""])
    lines.extend(count_table(rows, ["anchor_phase", "thinning_label_all"], "outcome_group"))
    lines.extend(["", "## Phase-Allowed Thinning Label", ""])
    lines.extend(count_table(rows, ["thinning_label_phase_allowed"], "outcome_group"))
    lines.extend(["", "## Band Tests Only", ""])
    lines.extend(count_table(tests, ["thinning_label_all"], "lifecycle_label"))
    lines.extend(["", "## Band Failures Only", ""])
    lines.extend(count_table(failures, ["thinning_label_all"], "lifecycle_label"))
    lines.extend(["", "## Consumed Conversions Only", ""])
    lines.extend(count_table(conversions, ["thinning_label_all"], "lifecycle_label"))
    lines.extend(["", "## Primary Development Bucket", ""])
    lines.extend(count_table(primary, ["fixture_id", "thinning_label_all"], "lifecycle_label"))
    lines.extend(["", "## Metric Sketch", ""])
    for label in sorted({str(row.get("thinning_label_all")) for row in rows}):
        subset = [row for row in rows if row.get("thinning_label_all") == label]
        lines.append(f"- `{label}` move-away net aligned ticks: {numeric_summary(subset, 'moveaway_price_net_aligned_ticks')}")
        lines.append(f"- `{label}` move-away adverse ticks: {numeric_summary(subset, 'moveaway_price_max_adverse_ticks')}")
        lines.append(f"- `{label}` pre aligned drop: {numeric_summary(subset, 'pre_thin_all_best_aligned_size_dropped')}")
        lines.append(f"- `{label}` post aligned drop: {numeric_summary(subset, 'post_thin_all_best_aligned_size_dropped')}")
    lines.extend(["", "## Example Rows", ""])
    for label in [
        "aligned_before",
        "aligned_after",
        "aligned_before_after",
        "mixed_thinning",
        "opposed_only",
        "no_near_thinning",
    ]:
        lines.extend(example_rows(rows, label))
        lines.append("")
    lines.extend(
        [
            "## Parameters",
            "",
            f"- detector top_n_levels: `{args.top_n_levels}`",
            f"- detector window_sec: `{args.window_sec}`",
            f"- detector thinning_percent: `{args.thinning_percent}`",
            f"- detector tape_volume_floor: `{args.tape_volume_floor}`",
            f"- detector cooldown_sec: `{args.cooldown_sec}`",
            f"- anchor_before_sec: `{args.anchor_before_sec}`",
            f"- anchor_after_sec: `{args.anchor_after_sec}`",
            "",
            "## Guardrails",
            "",
            "- Thinning is road/vacuum context, not ownership.",
            "- The broad pass runs without phase-gating by default so open/IB/close behavior can be stratified. `thinning_label_phase_allowed` shows what remains under the historical phase gate.",
            "- The detector is top-of-book aggregate thinning. It does not say who owns the auction after liquidity disappears.",
            "- Lifecycle labels remain the primary outcome.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--anchors", default=str(DEFAULT_ANCHORS))
    parser.add_argument("--fixture-id", action="append", default=[])
    parser.add_argument("--bucket", action="append", default=[])
    parser.add_argument("--anchor-class", action="append", default=[])
    parser.add_argument("--lifecycle-label", action="append", default=[])
    parser.add_argument("--window", default=None, help="NY replay window, default RTH")
    parser.add_argument("--warmup-min", type=int, default=5)
    parser.add_argument("--top-n-levels", type=int, default=20)
    parser.add_argument("--window-sec", type=int, default=5)
    parser.add_argument("--thinning-percent", type=float, default=0.25)
    parser.add_argument("--tape-volume-floor", type=float, default=0.20)
    parser.add_argument("--cooldown-sec", type=int, default=30)
    parser.add_argument("--phase-gate", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--follow-sec", type=int, default=60)
    parser.add_argument("--book-lookback-sec", type=int, default=30)
    parser.add_argument("--event-z-threshold", type=float, default=2.5)
    parser.add_argument("--context-overlap-sec", type=int, default=5)
    parser.add_argument("--first-lean-max-sec", type=int, default=30)
    parser.add_argument("--top", type=int, default=80)
    parser.add_argument("--anchor-before-sec", type=int, default=60)
    parser.add_argument("--anchor-after-sec", type=int, default=30)
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--tag", default="20260623_20260626")
    args = parser.parse_args()

    anchors = load_anchors(Path(args.anchors), args)
    rows, sessions = enrich_rows(anchors, args)
    out_dir = Path(args.out_dir)
    csv_path = out_dir / f"book_thinning_lifecycle_probe_{args.tag}.csv"
    report_path = out_dir / f"book_thinning_lifecycle_probe_{args.tag}.md"
    write_csv(csv_path, rows)
    write_report(report_path, rows, sessions, args)
    print(f"wrote {csv_path}")
    print(f"wrote {report_path}")


if __name__ == "__main__":
    main()
