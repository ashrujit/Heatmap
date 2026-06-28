"""Fixture-scoped short-half-life tape Driver probe.

This is Thesis 2 from the Skurry Now Lens research note. It attaches a
3-second half-life signed aggressor-flow impulse to the same lifecycle anchors
used by the T3-T9 passes.

Driver is treated as timing/effort context. Lifecycle labels remain the primary
auction outcome; this script does not score fixed-time favorable/adverse
excursion as success.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import math
import sys
from collections import Counter, defaultdict, deque
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

from capture_loader import MARKET_RECORDER_ROOT, load_capture_window, tick_columns, us  # noqa: E402


DEFAULT_ANCHORS = RESEARCH / "out" / "episode_terrain_lifecycle_probe_20260623_20260626.csv"
DEFAULT_OUT_DIR = RESEARCH / "out"

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


@dataclass(frozen=True)
class DriverPoint:
    ts_us: int
    state: float
    abs_state: float
    speed_z: float
    side: str


@dataclass
class DriverSeries:
    points: list[DriverPoint]
    times: list[int]

    @classmethod
    def from_ticks(
        cls,
        tick_rows: list[dict],
        sample_times: list[int],
        args: argparse.Namespace,
    ) -> "DriverSeries":
        half_life_us = max(0.001, args.half_life_sec) * 1_000_000
        decay_k = math.log(2.0) / half_life_us
        tick_idx = 0
        state = 0.0
        last_us = sample_times[0] if sample_times else 0
        rolling: deque[tuple[int, float]] = deque()
        rolling_sum = 0.0
        rolling_sum_sq = 0.0
        out: list[DriverPoint] = []

        for sample_us in sample_times:
            while tick_idx < len(tick_rows) and int(tick_rows[tick_idx]["timestamp_us"]) <= sample_us:
                tick_us = int(tick_rows[tick_idx]["timestamp_us"])
                if tick_us > last_us:
                    state *= math.exp(-(tick_us - last_us) * decay_k)
                    last_us = tick_us
                size = as_float(tick_rows[tick_idx], "size")
                sign = int(as_float(tick_rows[tick_idx], "aggressor_sign"))
                state += sign * size
                tick_idx += 1

            if sample_us > last_us:
                state *= math.exp(-(sample_us - last_us) * decay_k)
                last_us = sample_us

            cutoff = sample_us - int(args.rank_window_sec * 1_000_000)
            while rolling and rolling[0][0] < cutoff:
                _, old_value = rolling.popleft()
                rolling_sum -= old_value
                rolling_sum_sq -= old_value * old_value

            abs_state = abs(state)
            if len(rolling) >= args.min_rank_samples:
                mean = rolling_sum / len(rolling)
                variance = max(0.0, rolling_sum_sq / len(rolling) - mean * mean)
                std = math.sqrt(variance)
                speed_z = (abs_state - mean) / max(args.z_std_floor, std)
            else:
                speed_z = 0.0

            if abs_state < args.neutral_volume_floor:
                side = ""
            else:
                side = "demand" if state > 0 else "supply"

            out.append(DriverPoint(sample_us, state, abs_state, speed_z, side))
            rolling.append((sample_us, abs_state))
            rolling_sum += abs_state
            rolling_sum_sq += abs_state * abs_state

        return cls(points=out, times=[point.ts_us for point in out])

    def point_at_or_before(self, ts_us: int) -> DriverPoint | None:
        idx = bisect.bisect_right(self.times, ts_us) - 1
        if idx < 0:
            return None
        return self.points[idx]

    def window(self, start_us: int, end_us: int) -> list[DriverPoint]:
        lo = bisect.bisect_left(self.times, start_us)
        hi = bisect.bisect_right(self.times, end_us)
        return self.points[lo:hi]


def parse_iso_ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def as_float(row: dict, field: str, default: float = 0.0) -> float:
    value = row.get(field, default)
    if value in ("", None):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def side_sign(side: str) -> int:
    return 1 if side == "demand" else -1


def opposite_side(side: str) -> str:
    return "supply" if side == "demand" else "demand"


def outcome_group(lifecycle: str) -> str:
    if lifecycle in DEFENSE_LIFECYCLES:
        return "owner_defended"
    if lifecycle in CONTESTED_LIFECYCLES:
        return "contested_or_balance"
    if lifecycle in FAILURE_LIFECYCLES:
        return "failed_or_no_followthrough"
    return "other"


def anchor_driver_side(row: dict[str, str]) -> str:
    anchor_class = row.get("anchor_class", "")
    if anchor_class == "band_failure":
        return (
            row.get("break_side")
            or row.get("moveaway_side")
            or opposite_side(row.get("band_side", "demand"))
        )
    if anchor_class == "consumed_conversion":
        return row.get("moveaway_side") or row.get("band_side") or row.get("dominant_side") or ""
    return row.get("moveaway_side") or row.get("band_side") or row.get("dominant_side") or ""


def current_alignment(point: DriverPoint | None, expected_side: str) -> str:
    if point is None or not point.side or not expected_side:
        return "neutral"
    return "aligned" if point.side == expected_side else "opposed"


def label_driver(
    point: DriverPoint | None,
    expected_side: str,
    aligned_peak_z: float,
    opposed_peak_z: float,
    args: argparse.Namespace,
) -> str:
    if point is None:
        return "missing_driver"
    z = max(0.0, point.speed_z)
    alignment = current_alignment(point, expected_side)
    if z >= args.active_z and alignment == "aligned":
        return "aligned_active"
    if z >= args.active_z and alignment == "opposed":
        return "opposed_active"
    if z >= args.weak_z and alignment == "aligned":
        return "weak_aligned"
    if z >= args.weak_z and alignment == "opposed":
        return "weak_opposed"
    if aligned_peak_z >= args.exhausted_peak_z and aligned_peak_z >= opposed_peak_z + args.peak_margin_z:
        return "aligned_exhausted"
    if opposed_peak_z >= args.exhausted_peak_z and opposed_peak_z >= aligned_peak_z + args.peak_margin_z:
        return "opposed_exhausted"
    if max(aligned_peak_z, opposed_peak_z) >= args.exhausted_peak_z:
        return "mixed_exhausted"
    return "quiet"


def peak_summary(
    series: DriverSeries,
    anchor_us: int,
    expected_side: str,
    args: argparse.Namespace,
) -> dict[str, object]:
    expected = side_sign(expected_side)
    start_us = anchor_us - int(args.pre_peak_sec * 1_000_000)
    points = series.window(start_us, anchor_us)
    aligned_peak_z = 0.0
    opposed_peak_z = 0.0
    aligned_peak_age: float | None = None
    opposed_peak_age: float | None = None
    aligned_peak_state = 0.0
    opposed_peak_state = 0.0
    for point in points:
        z = max(0.0, point.speed_z)
        if not point.side:
            continue
        sign = 1 if point.side == "demand" else -1
        age = max(0.0, (anchor_us - point.ts_us) / 1_000_000)
        if sign == expected and z >= aligned_peak_z:
            aligned_peak_z = z
            aligned_peak_age = age
            aligned_peak_state = point.state
        if sign != expected and z >= opposed_peak_z:
            opposed_peak_z = z
            opposed_peak_age = age
            opposed_peak_state = point.state
    return {
        "driver_pre_aligned_peak_z": aligned_peak_z,
        "driver_pre_opposed_peak_z": opposed_peak_z,
        "driver_pre_aligned_peak_age_sec": aligned_peak_age,
        "driver_pre_opposed_peak_age_sec": opposed_peak_age,
        "driver_pre_aligned_peak_state": aligned_peak_state,
        "driver_pre_opposed_peak_state": opposed_peak_state,
        "driver_pre_peak_count": len(points),
    }


def driver_read(label: str, outcome: str) -> str:
    if label in {"aligned_active", "weak_aligned"} and outcome == "owner_defended":
        return "aligned_effort_confirmed"
    if label in {"aligned_active", "weak_aligned"} and outcome == "failed_or_no_followthrough":
        return "aligned_effort_failed"
    if label in {"opposed_active", "weak_opposed"} and outcome == "failed_or_no_followthrough":
        return "opposed_effort_warned"
    if label in {"opposed_active", "weak_opposed"} and outcome == "owner_defended":
        return "owner_absorbed_opposed_effort"
    if label == "aligned_exhausted":
        return "prior_aligned_effort_faded"
    if label == "opposed_exhausted":
        return "prior_opposed_effort_faded"
    return "driver_context"


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


def second_floor(ts_us: int) -> int:
    return (ts_us // 1_000_000) * 1_000_000


def second_ceil(ts_us: int) -> int:
    return ((ts_us + 999_999) // 1_000_000) * 1_000_000


def sample_times_for_rows(rows: list[dict[str, str]], args: argparse.Namespace) -> list[int]:
    anchors = [us(parse_iso_ts(row["anchor_ts"])) for row in rows]
    start = second_floor(min(anchors) - int((args.rank_window_sec + args.pre_peak_sec + 5) * 1_000_000))
    end = second_ceil(max(anchors) + int(2 * 1_000_000))
    grid = range(start, end + 1, 1_000_000)
    return sorted(set(grid).union(anchors))


def load_session_ticks(spec: SessionSpec, rows: list[dict[str, str]], args: argparse.Namespace) -> list[dict]:
    anchors = [parse_iso_ts(row["anchor_ts"]) for row in rows]
    start = min(anchors) - timedelta(seconds=args.rank_window_sec + args.pre_peak_sec + 10)
    end = max(anchors) + timedelta(seconds=3)
    df = load_capture_window(
        "ticks",
        spec.symbol,
        start,
        end,
        tick_columns(),
        inclusive_end=True,
    )
    return df.to_dicts()


def enrich_rows(rows: list[dict[str, str]], args: argparse.Namespace) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for spec, session_rows in group_by_session(rows).items():
        print(f"driver replay {spec.label} anchors={len(session_rows)}", flush=True)
        ticks = load_session_ticks(spec, session_rows, args)
        samples = sample_times_for_rows(session_rows, args)
        series = DriverSeries.from_ticks(ticks, samples, args)
        for row in session_rows:
            anchor_ts = parse_iso_ts(row["anchor_ts"])
            anchor_us = us(anchor_ts)
            expected_side = anchor_driver_side(row)
            point = series.point_at_or_before(anchor_us)
            peaks = peak_summary(series, anchor_us, expected_side, args)
            label = label_driver(
                point,
                expected_side,
                float(peaks["driver_pre_aligned_peak_z"]),
                float(peaks["driver_pre_opposed_peak_z"]),
                args,
            )
            outcome = outcome_group(row.get("lifecycle_label", ""))
            enriched: dict[str, object] = dict(row)
            enriched.update(peaks)
            enriched.update(
                {
                    "driver_expected_side": expected_side,
                    "driver_current_state": point.state if point else 0.0,
                    "driver_current_abs_state": point.abs_state if point else 0.0,
                    "driver_current_speed_z": point.speed_z if point else 0.0,
                    "driver_current_speed_z_pos": max(0.0, point.speed_z) if point else 0.0,
                    "driver_current_side": point.side if point else "",
                    "driver_current_alignment": current_alignment(point, expected_side),
                    "driver_label": label,
                    "driver_read": driver_read(label, outcome),
                    "outcome_group": outcome,
                    "driver_session_tick_count": len(ticks),
                    "driver_session_sample_count": len(series.points),
                }
            )
            out.append(enriched)
    return out


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
    selected = [row for row in rows if row.get("driver_label") == label][:limit]
    lines = [
        f"### {label}",
        "",
        "| fixture | time | anchor | expected/current | lifecycle | z | pre peaks aligned/opposed | move-away |",
        "| --- | --- | --- | --- | --- | ---: | ---: | ---: |",
    ]
    for row in selected:
        lines.append(
            f"| `{row.get('fixture_id')}` | {row.get('anchor_ny')} | "
            f"{row.get('anchor_class')}@{row.get('band_price')} | "
            f"{row.get('driver_expected_side')}/{row.get('driver_current_side')} | "
            f"`{row.get('lifecycle_label')}` | "
            f"{float(row.get('driver_current_speed_z_pos') or 0):.2f} | "
            f"{float(row.get('driver_pre_aligned_peak_z') or 0):.2f}/"
            f"{float(row.get('driver_pre_opposed_peak_z') or 0):.2f} | "
            f"{float(row.get('moveaway_price_net_aligned_ticks') or 0):.0f} |"
        )
    if not selected:
        lines.append("| n/a | n/a | n/a | n/a | n/a | 0 | 0/0 | 0 |")
    return lines


def write_report(path: Path, rows: list[dict[str, object]], args: argparse.Namespace) -> None:
    tests = [row for row in rows if row.get("anchor_class") == "band_test"]
    failures = [row for row in rows if row.get("anchor_class") == "band_failure"]
    conversions = [row for row in rows if row.get("anchor_class") == "consumed_conversion"]
    primary = [row for row in rows if row.get("curated_bucket") == "primary_dev"]
    direct = [row for row in conversions if row.get("lifecycle_label") == "direct_conversion_with_followthrough"]
    labels = sorted({str(row.get("driver_label")) for row in rows})
    lines = [
        "# Driver Lifecycle Probe",
        "",
        "Fixture-scoped Thesis 2 pass. It attaches a 3-second half-life signed tape impulse to T3 lifecycle anchors.",
        "",
        "## Coverage",
        "",
        f"- anchor rows: `{len(rows)}`",
        f"- band tests: `{len(tests)}`",
        f"- band failures: `{len(failures)}`",
        f"- consumed conversions: `{len(conversions)}`",
        f"- direct conversions with followthrough: `{len(direct)}`",
        f"- anchor source: `{args.anchors}`",
        "",
        "## Outcome By Driver Label",
        "",
    ]
    lines.extend(count_table(rows, ["driver_label"], "outcome_group"))
    lines.extend(["", "## Lifecycle By Driver Label", ""])
    lines.extend(count_table(rows, ["driver_label"], "lifecycle_label"))
    lines.extend(["", "## Anchor Class By Driver Label", ""])
    lines.extend(count_table(rows, ["anchor_class", "driver_label"], "outcome_group"))
    lines.extend(["", "## Band Tests Only", ""])
    lines.extend(count_table(tests, ["driver_label"], "lifecycle_label"))
    lines.extend(["", "## Band Failures Only", ""])
    lines.extend(count_table(failures, ["driver_label"], "lifecycle_label"))
    lines.extend(["", "## Consumed Conversions Only", ""])
    lines.extend(count_table(conversions, ["driver_label"], "lifecycle_label"))
    lines.extend(["", "## Direct Conversion Subset", ""])
    lines.extend(count_table(direct, ["driver_label"], "lifecycle_label"))
    lines.extend(["", "## Primary Development Bucket", ""])
    lines.extend(count_table(primary, ["fixture_id", "driver_label"], "lifecycle_label"))
    lines.extend(["", "## Metric Sketch", ""])
    for label in labels:
        subset = [row for row in rows if row.get("driver_label") == label]
        lines.append(f"- `{label}` current z: {numeric_summary(subset, 'driver_current_speed_z_pos')}")
        lines.append(f"- `{label}` aligned peak z: {numeric_summary(subset, 'driver_pre_aligned_peak_z')}")
        lines.append(f"- `{label}` opposed peak z: {numeric_summary(subset, 'driver_pre_opposed_peak_z')}")
        lines.append(f"- `{label}` move-away net aligned ticks: {numeric_summary(subset, 'moveaway_price_net_aligned_ticks')}")
        lines.append(f"- `{label}` move-away adverse ticks: {numeric_summary(subset, 'moveaway_price_max_adverse_ticks')}")
    lines.extend(["", "## Example Rows", ""])
    for label in [
        "aligned_active",
        "weak_aligned",
        "aligned_exhausted",
        "quiet",
        "opposed_exhausted",
        "weak_opposed",
        "opposed_active",
        "mixed_exhausted",
    ]:
        lines.extend(example_rows(rows, label))
        lines.append("")
    lines.extend(
        [
            "## Parameters",
            "",
            f"- half_life_sec: `{args.half_life_sec}`",
            f"- rank_window_sec: `{args.rank_window_sec}`",
            f"- pre_peak_sec: `{args.pre_peak_sec}`",
            f"- active_z / weak_z / exhausted_peak_z: `{args.active_z}` / `{args.weak_z}` / `{args.exhausted_peak_z}`",
            f"- peak_margin_z: `{args.peak_margin_z}`",
            f"- neutral_volume_floor: `{args.neutral_volume_floor}`",
            f"- z_std_floor: `{args.z_std_floor}`",
            "",
            "## Guardrails",
            "",
            "- Driver is present-tense tape effort, not ownership by itself.",
            "- Aligned Driver can mean valid initiative or late chase. Lifecycle consequence decides which.",
            "- Exhausted Driver is only a local timing state: effort was present in the previous window and faded by the anchor.",
            "- Existing approach/move-away tape fields remain separate; this pass tests the short-memory impulse specifically.",
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
    parser.add_argument("--capture-root", default=MARKET_RECORDER_ROOT)
    parser.add_argument("--half-life-sec", type=float, default=3.0)
    parser.add_argument("--rank-window-sec", type=int, default=1800)
    parser.add_argument("--min-rank-samples", type=int, default=120)
    parser.add_argument("--pre-peak-sec", type=int, default=10)
    parser.add_argument("--active-z", type=float, default=1.0)
    parser.add_argument("--weak-z", type=float, default=0.5)
    parser.add_argument("--exhausted-peak-z", type=float, default=1.5)
    parser.add_argument("--peak-margin-z", type=float, default=0.25)
    parser.add_argument("--neutral-volume-floor", type=float, default=1.0)
    parser.add_argument("--z-std-floor", type=float, default=1.0)
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--tag", default="20260623_20260626")
    args = parser.parse_args()

    del args.capture_root  # capture_loader uses MARKET_RECORDER_ROOT today; retained for provenance.
    anchors = load_anchors(Path(args.anchors), args)
    rows = enrich_rows(anchors, args)
    out_dir = Path(args.out_dir)
    csv_path = out_dir / f"driver_lifecycle_probe_{args.tag}.csv"
    report_path = out_dir / f"driver_lifecycle_probe_{args.tag}.md"
    write_csv(csv_path, rows)
    write_report(report_path, rows, args)
    print(f"anchors={len(anchors)} rows={len(rows)}")
    print(f"wrote {csv_path}")
    print(f"wrote {report_path}")


if __name__ == "__main__":
    main()
