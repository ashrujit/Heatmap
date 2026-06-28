"""Replay Road/Terrain around LL/EAR ownership failures and conversions.

This is Thesis 3 from the Skurry Now Lens research note. It asks what sits just
beyond an apparent ownership failure or consumed conversion:

- open road / vacuum in the direction of the break
- an immediate opposing wall
- renewed opposing commitment beyond the break
- renewed same-side support behind the break

The primary labels are structural LL/EAR outcomes, not fixed-horizon price
excursion.
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

import polars as pl


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RESEARCH = ROOT / "research"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(RESEARCH))

from candidate_timing_probe import CandidateTimingProbe, load_filtered_snapshots  # noqa: E402
from capture_loader import MARKET_RECORDER_ROOT, us  # noqa: E402
from ownership_bands_probe import Transition, opposite  # noqa: E402
from replay_levelledger import (  # noqa: E402
    BOOK_LOOKBACK_SEC,
    EVENT_Z_THRESHOLD,
    build_sample,
    ny_hms,
    parse_ny,
    snapshot_timing_summary,
)


DEFAULT_OUTPUT_DIR = ROOT / "research" / "out"


@dataclass(frozen=True)
class SessionSpec:
    date: str
    symbol: str
    window: str

    @property
    def label(self) -> str:
        return f"{self.date}:{self.symbol}"


@dataclass
class ReplayRun:
    spec: SessionSpec
    window_start: datetime
    window_end: datetime
    probe: CandidateTimingProbe
    snapshots: pl.DataFrame
    snapshot_gaps: int


@dataclass(frozen=True)
class SnapshotPoint:
    ts_us: int
    row: dict


class SnapshotSeries:
    def __init__(self, snapshots: pl.DataFrame, max_age_sec: float) -> None:
        self.points = [
            SnapshotPoint(int(row["timestamp_us"]), row)
            for row in snapshots.iter_rows(named=True)
        ]
        self.times = [point.ts_us for point in self.points]
        self.max_age_sec = max_age_sec

    def at_or_before(self, ts: datetime) -> tuple[dict | None, float | None]:
        target = us(ts)
        idx = self._bisect_right(target) - 1
        if idx < 0:
            return None, None
        point = self.points[idx]
        age = max(0.0, (target - point.ts_us) / 1_000_000)
        if age > self.max_age_sec:
            return None, age
        return point.row, age

    def at_or_after(self, ts: datetime) -> tuple[dict | None, float | None]:
        target = us(ts)
        idx = self._bisect_left(target)
        if idx >= len(self.points):
            return None, None
        point = self.points[idx]
        age = max(0.0, (point.ts_us - target) / 1_000_000)
        if age > self.max_age_sec:
            return None, age
        return point.row, age

    def _bisect_left(self, target: int) -> int:
        lo = 0
        hi = len(self.times)
        while lo < hi:
            mid = (lo + hi) // 2
            if self.times[mid] < target:
                lo = mid + 1
            else:
                hi = mid
        return lo

    def _bisect_right(self, target: int) -> int:
        lo = 0
        hi = len(self.times)
        while lo < hi:
            mid = (lo + hi) // 2
            if self.times[mid] <= target:
                lo = mid + 1
            else:
                hi = mid
        return lo


def parse_session(value: str, default_window: str) -> SessionSpec:
    parts = value.split(":", 2)
    if len(parts) < 2:
        raise argparse.ArgumentTypeError("session must be YYYY-MM-DD:SYMBOL[:HH:MM-HH:MM]")
    window = parts[2] if len(parts) > 2 else default_window
    start, end = parse_window(parts[0], window)
    if end <= start:
        raise argparse.ArgumentTypeError("session window end must be after start")
    return SessionSpec(parts[0], parts[1], window)


def parse_window(date: str, window: str) -> tuple[datetime, datetime]:
    start_s, end_s = window.split("-", 1)
    return parse_ny(date, start_s), parse_ny(date, end_s)


def side_sign(side: str) -> int:
    return 1 if side == "demand" else -1


def range_distance(left_min: int, left_max: int, right_min: int, right_max: int) -> int:
    if left_max < right_min:
        return right_min - left_max
    if right_max < left_min:
        return left_min - right_max
    return 0


def center_tick(tr: Transition) -> float:
    return (tr.min_tick + tr.max_tick) / 2.0


def relevant_after(
    origin: Transition,
    candidate: Transition,
    break_side: str,
    max_distance_ticks: int,
) -> bool:
    if candidate.ts <= origin.ts:
        return False
    if range_distance(origin.min_tick, origin.max_tick, candidate.min_tick, candidate.max_tick) > max_distance_ticks:
        return False
    origin_center = center_tick(origin)
    candidate_center = center_tick(candidate)
    if break_side == "demand":
        return candidate_center >= origin_center - max_distance_ticks * 0.25
    return candidate_center <= origin_center + max_distance_ticks * 0.25


def classify_next_structure(
    origin: Transition,
    transitions: Iterable[Transition],
    break_side: str,
    *,
    lookahead_sec: int,
    max_distance_ticks: int,
) -> tuple[str, str, str]:
    until = origin.ts + timedelta(seconds=lookahead_sec)
    opposing = opposite(break_side)
    for tr in sorted(transitions, key=lambda item: item.ts):
        if tr.ts <= origin.ts or tr.ts > until:
            continue
        if not relevant_after(origin, tr, break_side, max_distance_ticks):
            continue
        if tr.action == "FAIL" and tr.side == opposing:
            return "drive_destroyed_opposite", tr.action, tr.side
        if tr.action in ("OWNED", "CONSUMED") and tr.side == break_side:
            return "drive_owned_next", tr.action, tr.side
        if tr.action in ("OWNED", "CONSUMED", "HOLD") and tr.side == opposing:
            return "opposition_renewed", tr.action, tr.side
        if tr.action == "FAIL" and tr.side == break_side:
            return "drive_failed", tr.action, tr.side
    return "no_structural_followthrough", "", ""


def side_depths(row: dict, side: int) -> dict[int, float]:
    ref_tick = int(row["ref_tick"])
    prefix = "bid" if side > 0 else "ask"
    out: dict[int, float] = {}
    for idx in range(30):
        size = float(row[f"{prefix}_size_{idx}"])
        if not math.isfinite(size) or size <= 0.0:
            continue
        tick = ref_tick + int(row[f"{prefix}_offset_{idx}"])
        out[tick] = out.get(tick, 0.0) + size
    return out


def ticks_ahead(break_side: str, min_tick: int, max_tick: int, count: int) -> list[int]:
    if break_side == "demand":
        return list(range(max_tick + 1, max_tick + count + 1))
    return list(range(min_tick - count, min_tick))


def ticks_support(break_side: str, min_tick: int, max_tick: int, count: int) -> list[int]:
    if break_side == "demand":
        return list(range(min_tick, max_tick + count + 1))
    return list(range(min_tick - count, max_tick + 1))


def max_run(values: list[bool]) -> int:
    best = 0
    current = 0
    for value in values:
        if value:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def metric_set(
    row: dict,
    break_side: str,
    min_tick: int,
    max_tick: int,
    args: argparse.Namespace,
) -> dict[str, float | int | None]:
    break_sign = side_sign(break_side)
    passive_opposing_side = -break_sign
    passive_support_side = break_sign
    ahead_ticks = ticks_ahead(break_side, min_tick, max_tick, args.ahead_ticks)
    support_ticks = ticks_support(break_side, min_tick, max_tick, args.support_ticks)
    opposing_depths = side_depths(row, passive_opposing_side)
    support_depths = side_depths(row, passive_support_side)
    ahead_sizes = [float(opposing_depths.get(tick, 0.0)) for tick in ahead_ticks]
    support_sizes = [float(support_depths.get(tick, 0.0)) for tick in support_ticks]
    wall_indexes = [
        idx for idx, size in enumerate(ahead_sizes, start=1)
        if size >= args.wall_min_size
    ]
    vacuum_flags = [size <= args.vacuum_size_max for size in ahead_sizes]
    return {
        "ahead_sum": sum(ahead_sizes),
        "ahead_mean": sum(ahead_sizes) / max(1, len(ahead_sizes)),
        "ahead_max": max(ahead_sizes) if ahead_sizes else 0.0,
        "ahead_wall_distance": min(wall_indexes) if wall_indexes else None,
        "ahead_vacuum_frac": sum(vacuum_flags) / max(1, len(vacuum_flags)),
        "ahead_vacuum_run": max_run(vacuum_flags),
        "support_sum": sum(support_sizes),
        "support_mean": sum(support_sizes) / max(1, len(support_sizes)),
        "support_max": max(support_sizes) if support_sizes else 0.0,
    }


def road_bin(after: dict[str, float | int | None], args: argparse.Namespace) -> str:
    wall_distance = after.get("ahead_wall_distance")
    if isinstance(wall_distance, int) and wall_distance <= args.immediate_wall_ticks:
        return "immediate_wall"
    if float(after["ahead_max"] or 0.0) >= args.wall_min_size:
        return "wall_later"
    if (
        float(after["ahead_vacuum_frac"] or 0.0) >= args.open_vacuum_frac
        and float(after["ahead_mean"] or 0.0) <= args.open_mean_max
    ):
        return "open_road"
    return "mixed"


def delta_bin(delta: float | None, min_build: float) -> str:
    if delta is None or not math.isfinite(delta):
        return "missing"
    if delta >= min_build:
        return "building"
    if delta <= -min_build:
        return "eroding"
    return "flat"


def replay_run(args: argparse.Namespace, spec: SessionSpec) -> ReplayRun:
    window_start, window_end = parse_window(spec.date, spec.window)
    replay_start = window_start - timedelta(minutes=args.warmup_min)
    snapshots = load_filtered_snapshots(
        args.capture_root,
        spec.symbol,
        spec.date,
        replay_start,
        window_end + timedelta(seconds=args.after_sec + args.snapshot_max_age_sec),
    )
    _, _, _, gaps = snapshot_timing_summary(snapshots, args.gap_threshold_sec)
    probe = CandidateTimingProbe(
        session=spec.label,
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
    probe.finish(window_end)
    return ReplayRun(spec, window_start, window_end, probe, snapshots, len(gaps))


def event_rows(run: ReplayRun, args: argparse.Namespace) -> list[dict[str, object]]:
    series = SnapshotSeries(run.snapshots, args.snapshot_max_age_sec)
    rows: list[dict[str, object]] = []
    transitions = [
        tr for tr in run.probe.transitions
        if run.window_start <= tr.ts <= run.window_end
    ]
    for tr in transitions:
        if tr.action not in ("FAIL", "CONSUMED"):
            continue
        break_side = tr.side if tr.action == "CONSUMED" else opposite(tr.side)
        event_class = "consumed_conversion" if tr.action == "CONSUMED" else "apparent_fail"
        before_row, before_age = series.at_or_before(tr.ts - timedelta(seconds=args.before_sec))
        after_row, after_age = series.at_or_after(tr.ts + timedelta(seconds=args.after_sec))
        if before_row is None or after_row is None:
            continue
        before = metric_set(before_row, break_side, tr.min_tick, tr.max_tick, args)
        after = metric_set(after_row, break_side, tr.min_tick, tr.max_tick, args)
        ahead_delta = float(after["ahead_sum"] or 0.0) - float(before["ahead_sum"] or 0.0)
        support_delta = float(after["support_sum"] or 0.0) - float(before["support_sum"] or 0.0)
        outcome, next_action, next_side = classify_next_structure(
            tr,
            transitions,
            break_side,
            lookahead_sec=args.structure_lookahead_sec,
            max_distance_ticks=args.structure_distance_ticks,
        )
        row: dict[str, object] = {
            "session": run.spec.label,
            "ts": tr.ts.isoformat(),
            "ny_time": ny_hms(tr.ts),
            "event_class": event_class,
            "transition_action": tr.action,
            "source_side": tr.side,
            "break_side": break_side,
            "source": tr.source,
            "band_id": tr.band_id,
            "min_tick": tr.min_tick,
            "max_tick": tr.max_tick,
            "event_count": tr.event_count,
            "score": tr.score,
            "max_abs_z": tr.max_abs_z,
            "current_mid_tick": tr.current_mid_tick,
            "before_age_sec": before_age,
            "after_age_sec": after_age,
            "road_bin": road_bin(after, args),
            "opposition_book_bin": delta_bin(ahead_delta, args.build_min_delta),
            "support_book_bin": delta_bin(support_delta, args.build_min_delta),
            "structure_outcome": outcome,
            "next_action": next_action,
            "next_side": next_side,
            "ahead_delta": ahead_delta,
            "support_delta": support_delta,
            "snapshot_gaps": run.snapshot_gaps,
        }
        for prefix, values in (("before", before), ("after", after)):
            for key, value in values.items():
                row[f"{prefix}_{key}"] = value
        rows.append(row)
    return rows


def pct(value: int, total: int) -> str:
    if total <= 0:
        return "n/a"
    return f"{100.0 * value / total:.1f}%"


def summarize(rows: list[dict[str, object]], group_fields: list[str]) -> list[str]:
    groups: dict[tuple[str, ...], Counter[str]] = defaultdict(Counter)
    for row in rows:
        key = tuple(str(row.get(field, "")) for field in group_fields)
        groups[key][str(row.get("structure_outcome", ""))] += 1
    if not groups:
        return ["No rows."]
    outcomes = sorted({outcome for counter in groups.values() for outcome in counter})
    header = "| " + " | ".join(group_fields) + " | n | " + " | ".join(outcomes) + " |"
    sep = "| " + " | ".join("---" for _ in group_fields) + " | ---: | " + " | ".join("---:" for _ in outcomes) + " |"
    lines = [header, sep]
    for key in sorted(groups):
        counter = groups[key]
        total = sum(counter.values())
        values = [f"{counter[outcome]} ({pct(counter[outcome], total)})" for outcome in outcomes]
        lines.append("| " + " | ".join(key) + f" | {total} | " + " | ".join(values) + " |")
    return lines


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_report(path: Path, specs: list[SessionSpec], rows: list[dict[str, object]], runs: list[ReplayRun], args: argparse.Namespace) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Terrain Band Probe",
        "",
        "Primary outcome is structural follow-through or repair, not fixed-horizon price excursion.",
        "",
        "## Sessions",
        "",
    ]
    for run in runs:
        lines.append(
            f"- `{run.spec.label}` `{run.spec.window}` transitions={len(run.probe.transitions)} "
            f"rows={sum(1 for row in rows if row['session'] == run.spec.label)} "
            f"snapshot_gaps={run.snapshot_gaps}"
        )

    sections = [
        ("Outcome By Event Class And Road", ["event_class", "road_bin"]),
        ("Outcome By Event Class And Opposing Book Change", ["event_class", "opposition_book_bin"]),
        ("Outcome By Event Class And Same-Side Support Change", ["event_class", "support_book_bin"]),
        ("Outcome By Road And Opposing Book Change", ["road_bin", "opposition_book_bin"]),
    ]
    for title, fields in sections:
        lines.extend(["", f"## {title}", ""])
        lines.extend(summarize(rows, fields))

    lines.extend(
        [
            "",
            "## Parameters",
            "",
            f"- before_sec: `{args.before_sec}`",
            f"- after_sec: `{args.after_sec}`",
            f"- ahead_ticks: `{args.ahead_ticks}`",
            f"- support_ticks: `{args.support_ticks}`",
            f"- wall_min_size: `{args.wall_min_size}`",
            f"- vacuum_size_max: `{args.vacuum_size_max}`",
            f"- open_vacuum_frac: `{args.open_vacuum_frac}`",
            f"- structure_lookahead_sec: `{args.structure_lookahead_sec}`",
            f"- structure_distance_ticks: `{args.structure_distance_ticks}`",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", action="append", required=True, help="YYYY-MM-DD:SYMBOL[:HH:MM-HH:MM]")
    parser.add_argument("--window", default="09:30-16:00")
    parser.add_argument("--capture-root", default=MARKET_RECORDER_ROOT)
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
    parser.add_argument("--snapshot-max-age-sec", type=float, default=2.5)
    parser.add_argument("--before-sec", type=float, default=1.0)
    parser.add_argument("--after-sec", type=float, default=2.0)
    parser.add_argument("--ahead-ticks", type=int, default=20)
    parser.add_argument("--support-ticks", type=int, default=8)
    parser.add_argument("--wall-min-size", type=float, default=7.0)
    parser.add_argument("--vacuum-size-max", type=float, default=1.0)
    parser.add_argument("--immediate-wall-ticks", type=int, default=5)
    parser.add_argument("--open-vacuum-frac", type=float, default=0.35)
    parser.add_argument("--open-mean-max", type=float, default=2.5)
    parser.add_argument("--build-min-delta", type=float, default=8.0)
    parser.add_argument("--structure-lookahead-sec", type=int, default=600)
    parser.add_argument("--structure-distance-ticks", type=int, default=80)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--tag", default="")
    args = parser.parse_args()

    specs = [parse_session(value, args.window) for value in args.session]
    tag = args.tag or "_".join(f"{spec.date}_{spec.symbol}" for spec in specs)
    rows: list[dict[str, object]] = []
    runs: list[ReplayRun] = []
    for spec in specs:
        run = replay_run(args, spec)
        runs.append(run)
        rows.extend(event_rows(run, args))

    out_dir = Path(args.output_dir)
    csv_path = out_dir / f"terrain_band_probe_{tag}.csv"
    report_path = out_dir / f"terrain_band_probe_{tag}.md"
    write_csv(csv_path, rows)
    write_report(report_path, specs, rows, runs, args)
    print(f"wrote {csv_path}")
    print(f"wrote {report_path}")


if __name__ == "__main__":
    main()
