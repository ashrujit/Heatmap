"""Fixture-scoped Horizon probe.

This is Thesis 5 from the Skurry Now Lens research note. It attaches farther
book context to the same lifecycle anchors used by the T3/T4 passes:

- front Horizon: 21-30 ticks beyond the band, reliable with 30-level snapshots;
- requested Horizon: 21-64 ticks beyond the band, reported with explicit
  snapshot coverage because the current recorder defaults to 30 levels/side;
- nearest observed far wall, largest observed air gap, and open/mixed bins.

The output is descriptive context for lifecycle labels. It does not discover
new bands and does not consume live EAR logs.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import math
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Iterable


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RESEARCH = ROOT / "research"
sys.path.insert(0, str(RESEARCH))
sys.path.insert(0, str(HERE))

from capture_loader import MARKET_RECORDER_ROOT, load_capture_window, snapshot_columns, us  # noqa: E402
from replay_levelledger import abbrev, ny_hms  # noqa: E402


DEFAULT_ANCHORS = RESEARCH / "out" / "episode_terrain_lifecycle_probe_20260623_20260626.csv"
DEFAULT_OUT_DIR = RESEARCH / "out"

FRONT_START_TICKS = 21
FRONT_END_TICKS = 30
FULL_START_TICKS = 21
FULL_END_TICKS = 64


@dataclass(frozen=True)
class SessionSpec:
    date: str
    symbol: str

    @property
    def label(self) -> str:
        return f"{self.date}:{self.symbol}"


@dataclass
class SnapshotSeries:
    rows: list[dict]
    times: list[int]
    max_age_sec: float

    @classmethod
    def load(
        cls,
        capture_root: str,
        spec: SessionSpec,
        start: datetime,
        end: datetime,
        max_age_sec: float,
    ) -> "SnapshotSeries":
        del capture_root  # loader reads MARKET_RECORDER_ROOT today; kept for CLI provenance.
        snapshots = load_capture_window(
            "snapshots",
            spec.symbol,
            start,
            end,
            snapshot_columns(30),
            inclusive_end=True,
        )
        rows = snapshots.to_dicts()
        return cls(rows=rows, times=[int(row["timestamp_us"]) for row in rows], max_age_sec=max_age_sec)

    def at_or_after(self, ts: datetime) -> tuple[dict | None, float | None]:
        target = us(ts)
        idx = bisect.bisect_left(self.times, target)
        if idx >= len(self.rows):
            return None, None
        age = max(0.0, (self.times[idx] - target) / 1_000_000)
        if age > self.max_age_sec:
            return None, age
        return self.rows[idx], age

    def at_or_before(self, ts: datetime) -> tuple[dict | None, float | None]:
        target = us(ts)
        idx = bisect.bisect_right(self.times, target) - 1
        if idx < 0:
            return None, None
        age = max(0.0, (target - self.times[idx]) / 1_000_000)
        if age > self.max_age_sec:
            return None, age
        return self.rows[idx], age


def parse_iso_ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def side_sign(side: str) -> int:
    return 1 if side == "demand" else -1


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


def captured_span(row: dict, side: int) -> tuple[int | None, int | None]:
    depths = side_depths(row, side)
    if not depths:
        return None, None
    return min(depths), max(depths)


def target_range(side: str, min_tick: int, max_tick: int, start_ticks: int, end_ticks: int) -> tuple[int, int]:
    if side == "demand":
        return max_tick + start_ticks, max_tick + end_ticks
    return min_tick - end_ticks, min_tick - start_ticks


def max_run(flags: Iterable[bool]) -> int:
    best = 0
    current = 0
    for flag in flags:
        if flag:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def horizon_metrics(
    row: dict,
    horizon_side: str,
    min_tick: int,
    max_tick: int,
    start_ticks: int,
    end_ticks: int,
    args: argparse.Namespace,
) -> dict[str, object]:
    passive_opposition = -side_sign(horizon_side)
    depths = side_depths(row, passive_opposition)
    target_lo, target_hi = target_range(horizon_side, min_tick, max_tick, start_ticks, end_ticks)
    span_lo, span_hi = captured_span(row, passive_opposition)
    target_ticks = list(range(target_lo, target_hi + 1))
    target_count = len(target_ticks)

    if span_lo is None or span_hi is None:
        return {
            "range_start": start_ticks,
            "range_end": end_ticks,
            "target_tick_count": target_count,
            "covered_tick_count": 0,
            "coverage_frac": 0.0,
            "sum": 0.0,
            "mean": 0.0,
            "max": 0.0,
            "nearest_wall_distance": None,
            "largest_air_gap": 0,
            "air_frac": 0.0,
            "bin": "missing_depth",
        }

    covered_ticks = [tick for tick in target_ticks if span_lo <= tick <= span_hi]
    sizes = [float(depths.get(tick, 0.0)) for tick in covered_ticks]
    wall_distances = [
        abs(tick - (max_tick if horizon_side == "demand" else min_tick))
        for tick, size in zip(covered_ticks, sizes)
        if size >= args.wall_min_size
    ]
    air_flags = [size <= args.air_size_max for size in sizes]
    coverage = len(covered_ticks) / max(1, target_count)
    mean = sum(sizes) / max(1, len(sizes))
    max_size = max(sizes) if sizes else 0.0
    air_frac = sum(air_flags) / max(1, len(air_flags))
    nearest_wall = min(wall_distances) if wall_distances else None
    largest_air_gap = max_run(air_flags)

    if coverage < args.min_coverage_frac:
        bin_label = "truncated"
    elif nearest_wall is not None and nearest_wall <= args.near_far_wall_ticks:
        bin_label = "far_wall_near"
    elif nearest_wall is not None:
        bin_label = "far_wall_later"
    elif air_frac >= args.open_air_frac and mean <= args.open_mean_max:
        bin_label = "open_horizon"
    else:
        bin_label = "mixed_horizon"

    return {
        "range_start": start_ticks,
        "range_end": end_ticks,
        "target_tick_count": target_count,
        "covered_tick_count": len(covered_ticks),
        "coverage_frac": coverage,
        "sum": sum(sizes),
        "mean": mean,
        "max": max_size,
        "nearest_wall_distance": nearest_wall,
        "largest_air_gap": largest_air_gap,
        "air_frac": air_frac,
        "captured_span_min_tick": span_lo,
        "captured_span_max_tick": span_hi,
        "bin": bin_label,
    }


def prefixed(prefix: str, values: dict[str, object]) -> dict[str, object]:
    return {f"{prefix}_{key}": value for key, value in values.items()}


def anchor_horizon_side(row: dict[str, str]) -> str:
    if row.get("anchor_class") == "band_failure":
        return row.get("break_side") or row.get("moveaway_side") or row.get("band_side")
    if row.get("anchor_class") == "consumed_conversion":
        return row.get("band_side") or row.get("moveaway_side")
    return row.get("moveaway_side") or row.get("band_side")


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
    groups: dict[SessionSpec, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        groups[SessionSpec(row["date"], row["symbol"])].append(row)
    return groups


def add_horizon(rows: list[dict[str, str]], args: argparse.Namespace) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for spec, session_rows in group_by_session(rows).items():
        anchors = [parse_iso_ts(row["anchor_ts"]) for row in session_rows]
        start = min(anchors) - timedelta(seconds=args.before_sec + args.snapshot_max_age_sec)
        end = max(anchors) + timedelta(seconds=args.after_sec + args.snapshot_max_age_sec)
        print(f"horizon snapshots {spec.label} anchors={len(session_rows)}", flush=True)
        series = SnapshotSeries.load(args.capture_root, spec, start, end, args.snapshot_max_age_sec)
        for row in session_rows:
            anchor_ts = parse_iso_ts(row["anchor_ts"])
            before_row, before_age = series.at_or_before(anchor_ts - timedelta(seconds=args.before_sec))
            after_row, after_age = series.at_or_after(anchor_ts + timedelta(seconds=args.after_sec))
            enriched: dict[str, object] = dict(row)
            side = anchor_horizon_side(row)
            min_tick = int(row["min_tick"])
            max_tick = int(row["max_tick"])
            enriched.update(
                {
                    "horizon_side": side,
                    "horizon_after_age_sec": after_age,
                    "horizon_before_age_sec": before_age,
                    "horizon_available": after_row is not None,
                    "front_horizon_available": after_row is not None,
                }
            )
            if after_row is not None:
                front = horizon_metrics(
                    after_row,
                    side,
                    min_tick,
                    max_tick,
                    FRONT_START_TICKS,
                    FRONT_END_TICKS,
                    args,
                )
                full = horizon_metrics(
                    after_row,
                    side,
                    min_tick,
                    max_tick,
                    FULL_START_TICKS,
                    FULL_END_TICKS,
                    args,
                )
                enriched.update(prefixed("front", front))
                enriched.update(prefixed("full", full))
            if before_row is not None:
                before_front = horizon_metrics(
                    before_row,
                    side,
                    min_tick,
                    max_tick,
                    FRONT_START_TICKS,
                    FRONT_END_TICKS,
                    args,
                )
                before_full = horizon_metrics(
                    before_row,
                    side,
                    min_tick,
                    max_tick,
                    FULL_START_TICKS,
                    FULL_END_TICKS,
                    args,
                )
                enriched.update(prefixed("before_front", before_front))
                enriched.update(prefixed("before_full", before_full))
                if "front_sum" in enriched:
                    enriched["front_sum_delta"] = float(enriched["front_sum"]) - float(before_front["sum"])
                    enriched["full_sum_delta"] = float(enriched["full_sum"]) - float(before_full["sum"])
            out.append(enriched)
    return out


def pct(value: int, total: int) -> str:
    if total <= 0:
        return "n/a"
    return f"{100.0 * value / total:.1f}%"


def summarize(rows: list[dict[str, object]], fields: list[str], outcome_field: str = "lifecycle_label") -> list[str]:
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


def example_rows(rows: list[dict[str, object]], limit: int = 24) -> list[str]:
    selected = sorted(
        rows,
        key=lambda row: (
            str(row.get("curated_bucket", "")),
            str(row.get("fixture_id", "")),
            str(row.get("anchor_ny", "")),
        ),
    )[:limit]
    lines = [
        "| fixture | time | anchor | side | front | full coverage | wall | gap | lifecycle |",
        "| --- | --- | --- | --- | --- | ---: | ---: | ---: | --- |",
    ]
    for row in selected:
        min_tick = int(row.get("min_tick") or 0)
        max_tick = int(row.get("max_tick") or min_tick)
        anchor = abbrev((min_tick + max_tick) // 2)
        wall = row.get("front_nearest_wall_distance") or row.get("full_nearest_wall_distance") or ""
        lines.append(
            f"| `{row.get('fixture_id')}` | {row.get('anchor_ny')} | "
            f"{row.get('anchor_class')}@{anchor} | {row.get('horizon_side')} | "
            f"`{row.get('front_bin', '')}` | {float(row.get('full_coverage_frac') or 0):.2f} | "
            f"{wall} | {row.get('front_largest_air_gap', '')} | `{row.get('lifecycle_label')}` |"
        )
    return lines


def write_report(path: Path, rows: list[dict[str, object]], args: argparse.Namespace) -> None:
    clean = [row for row in rows if row.get("horizon_available") is True]
    front_observed = [row for row in clean if row.get("front_bin") not in ("", None, "missing_depth")]
    front_covered = [
        row for row in clean
        if float(row.get("front_coverage_frac") or 0.0) >= args.min_coverage_frac
    ]
    full_covered = [
        row for row in clean
        if float(row.get("full_coverage_frac") or 0.0) >= args.min_coverage_frac
    ]
    tests = [row for row in clean if row.get("anchor_class") == "band_test"]
    failures = [row for row in clean if row.get("anchor_class") == "band_failure"]
    conversions = [row for row in clean if row.get("anchor_class") == "consumed_conversion"]
    lines = [
        "# Horizon Lifecycle Probe",
        "",
        "Fixture-scoped Thesis 5 pass. Anchors come from the T3 lifecycle probe; Horizon metrics are farther book context.",
        "",
        "## Coverage",
        "",
        f"- anchor rows: `{len(rows)}`",
        f"- clean Horizon rows: `{len(clean)}`",
        f"- front Horizon observed rows: `{len(front_observed)}`",
        f"- front Horizon rows meeting coverage threshold: `{len(front_covered)}`",
        f"- full 21-64 Horizon rows meeting coverage threshold: `{len(full_covered)}`",
        f"- anchor source: `{args.anchors}`",
        f"- snapshot depth: `30 levels/side`",
        f"- front Horizon: `{FRONT_START_TICKS}-{FRONT_END_TICKS}` ticks beyond band",
        f"- requested Horizon: `{FULL_START_TICKS}-{FULL_END_TICKS}` ticks beyond band, coverage-reported",
        "",
        "## Lifecycle By Front Horizon",
        "",
    ]
    lines.extend(summarize(clean, ["anchor_class", "front_bin"]))
    lines.extend(["", "## Lifecycle By Fixture Bucket And Front Horizon", ""])
    lines.extend(summarize(clean, ["curated_bucket", "front_bin"]))
    lines.extend(["", "## Band Tests Only", ""])
    lines.extend(summarize(tests, ["front_bin"]))
    lines.extend(["", "## Failures Only", ""])
    lines.extend(summarize(failures, ["front_bin"]))
    lines.extend(["", "## Consumed Conversions Only", ""])
    lines.extend(summarize(conversions, ["front_bin"]))
    lines.extend(["", "## Metric Sketch", ""])
    for label in ("open_horizon", "far_wall_near", "far_wall_later", "mixed_horizon", "truncated"):
        subset = [row for row in clean if row.get("front_bin") == label]
        if not subset:
            continue
        lines.append(f"- `{label}` front air gap: {numeric_summary(subset, 'front_largest_air_gap')}")
        lines.append(f"- `{label}` front wall distance: {numeric_summary(subset, 'front_nearest_wall_distance')}")
        lines.append(f"- `{label}` move-away aligned ticks: {numeric_summary(subset, 'moveaway_price_net_aligned_ticks')}")
        lines.append(f"- `{label}` move-away adverse ticks: {numeric_summary(subset, 'moveaway_price_max_adverse_ticks')}")
    lines.extend(["", "## Full Horizon Coverage", ""])
    for label in sorted({str(row.get("anchor_class", "")) for row in clean}):
        subset = [row for row in clean if row.get("anchor_class") == label]
        lines.append(f"- `{label}` full coverage: {numeric_summary(subset, 'full_coverage_frac')}")
    lines.extend(["", "## Example Rows", ""])
    lines.extend(example_rows(clean))
    lines.extend(
        [
            "",
            "## Parameters",
            "",
            f"- before_sec / after_sec: `{args.before_sec}` / `{args.after_sec}`",
            f"- wall_min_size: `{args.wall_min_size}`",
            f"- air_size_max: `{args.air_size_max}`",
            f"- open_air_frac: `{args.open_air_frac}`",
            f"- open_mean_max: `{args.open_mean_max}`",
            f"- min_coverage_frac: `{args.min_coverage_frac}`",
            "",
            "## Guardrails",
            "",
            "- This broad pass uses 30-level MarketRecorder snapshots. It cannot fully validate 21-64 tick Horizon where coverage is low.",
            "- `front_*` metrics are the reliable broad-pass read only when `front_bin` is not `truncated`.",
            "- Full 21-64 metrics are included only with explicit coverage; do not treat missing far levels as zero displayed depth.",
            "- Move-away ticks are secondary context. Lifecycle labels remain the primary outcome.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--anchors", default=str(DEFAULT_ANCHORS))
    parser.add_argument("--capture-root", default=MARKET_RECORDER_ROOT)
    parser.add_argument("--fixture-id", action="append", default=[])
    parser.add_argument("--bucket", action="append", default=[])
    parser.add_argument("--anchor-class", action="append", default=[])
    parser.add_argument("--lifecycle-label", action="append", default=[])
    parser.add_argument("--before-sec", type=float, default=5.0)
    parser.add_argument("--after-sec", type=float, default=2.0)
    parser.add_argument("--snapshot-max-age-sec", type=float, default=2.5)
    parser.add_argument("--wall-min-size", type=float, default=7.0)
    parser.add_argument("--air-size-max", type=float, default=1.0)
    parser.add_argument("--near-far-wall-ticks", type=int, default=32)
    parser.add_argument("--open-air-frac", type=float, default=0.65)
    parser.add_argument("--open-mean-max", type=float, default=2.0)
    parser.add_argument("--min-coverage-frac", type=float, default=0.80)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--tag", default="20260623_20260626")
    args = parser.parse_args()

    anchors = load_anchors(Path(args.anchors), args)
    rows = add_horizon(anchors, args)
    out_dir = Path(args.output_dir)
    csv_path = out_dir / f"horizon_lifecycle_probe_{args.tag}.csv"
    report_path = out_dir / f"horizon_lifecycle_probe_{args.tag}.md"
    write_csv(csv_path, rows)
    write_report(report_path, rows, args)
    print(f"wrote {csv_path}")
    print(f"wrote {report_path}")


if __name__ == "__main__":
    main()
