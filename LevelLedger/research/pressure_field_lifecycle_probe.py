"""Fixture-scoped side-aware pressure-field probe.

This is Thesis 6 from the Skurry Now Lens research note. It attaches a
side-aware pressure field to the same lifecycle anchors used by the T3-T5
passes:

- demand-positive evidence: bid adds plus ask removes;
- supply-positive evidence: ask adds plus bid removes;
- evidence is spread over nearby ticks with a Gaussian-like kernel;
- evidence decays by half-life over a rolling lookback window;
- output is purity/support context, not a replacement ownership grammar.

This first broad pass uses canonical MarketRecorder snapshots. Raw quote-event
replay remains the better source for exact add/remove ordering.
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

from capture_loader import MARKET_RECORDER_ROOT, load_capture_window, snapshot_columns, us  # noqa: E402
from replay_levelledger import BOOK_LOOKBACK_SEC, EVENT_Z_THRESHOLD, build_sample, ny_hms  # noqa: E402


DEFAULT_ANCHORS = RESEARCH / "out" / "episode_terrain_lifecycle_probe_20260623_20260626.csv"
DEFAULT_OUT_DIR = RESEARCH / "out"


@dataclass(frozen=True)
class SessionSpec:
    date: str
    symbol: str

    @property
    def label(self) -> str:
        return f"{self.date}:{self.symbol}"


@dataclass(frozen=True)
class PressureEvent:
    ts_us: int
    tick: int
    demand: float
    supply: float

    @property
    def total(self) -> float:
        return self.demand + self.supply


@dataclass(frozen=True)
class ActivityPoint:
    ts_us: int
    total: float


@dataclass
class PressureSeries:
    events: list[PressureEvent]
    times: list[int]
    activity: list[ActivityPoint]
    activity_times: list[int]

    @classmethod
    def from_snapshots(cls, snapshots) -> "PressureSeries":
        rows = snapshots.sort("timestamp_us").to_dicts()
        events: list[PressureEvent] = []
        activity: list[ActivityPoint] = []
        prev_bid: dict[int, float] | None = None
        prev_ask: dict[int, float] | None = None
        prev_ts = 0
        for row in rows:
            ts_us = int(row["timestamp_us"])
            bid = side_depths(row, +1)
            ask = side_depths(row, -1)
            if prev_bid is None or prev_ask is None:
                prev_bid = bid
                prev_ask = ask
                prev_ts = ts_us
                continue
            if ts_us <= prev_ts:
                prev_bid = bid
                prev_ask = ask
                prev_ts = ts_us
                continue
            total = 0.0
            for tick in sorted(set(prev_bid).union(bid)):
                delta = bid.get(tick, 0.0) - prev_bid.get(tick, 0.0)
                if abs(delta) < 1e-9:
                    continue
                total += abs(delta)
                if delta > 0:
                    events.append(PressureEvent(ts_us, tick, delta, 0.0))
                else:
                    events.append(PressureEvent(ts_us, tick, 0.0, -delta))
            for tick in sorted(set(prev_ask).union(ask)):
                delta = ask.get(tick, 0.0) - prev_ask.get(tick, 0.0)
                if abs(delta) < 1e-9:
                    continue
                total += abs(delta)
                if delta > 0:
                    events.append(PressureEvent(ts_us, tick, 0.0, delta))
                else:
                    events.append(PressureEvent(ts_us, tick, -delta, 0.0))
            activity.append(ActivityPoint(ts_us, total))
            prev_bid = bid
            prev_ask = ask
            prev_ts = ts_us
        events.sort(key=lambda item: item.ts_us)
        activity.sort(key=lambda item: item.ts_us)
        return cls(
            events=events,
            times=[item.ts_us for item in events],
            activity=activity,
            activity_times=[item.ts_us for item in activity],
        )

    @classmethod
    def from_ll_events(cls, snapshots, args: argparse.Namespace) -> "PressureSeries":
        samples = deque()
        events: list[PressureEvent] = []
        activity: list[ActivityPoint] = []
        for row in snapshots.sort("timestamp_us").iter_rows(named=True):
            sample = build_sample(row)
            samples.append(sample)
            cutoff = sample.ts - timedelta(seconds=max(5, args.book_lookback_sec * 2))
            while samples and samples[0].ts < cutoff:
                samples.popleft()
            if len(samples) < 5:
                continue

            mbi, sbi = mean_std(samples, sample.ts, args.book_lookback_sec, lambda item: item.bid_inner)
            mai, sai = mean_std(samples, sample.ts, args.book_lookback_sec, lambda item: item.ask_inner)
            mbc, sbc = mean_std(samples, sample.ts, args.book_lookback_sec, lambda item: item.bid_centroid)
            mac, sac = mean_std(samples, sample.ts, args.book_lookback_sec, lambda item: item.ask_centroid)

            zbi = (sample.bid_inner - mbi) / max(1.0, sbi)
            zai = (sample.ask_inner - mai) / max(1.0, sai)
            zbc = (sample.bid_centroid - mbc) / max(0.01, sbc)
            zac = (sample.ask_centroid - mac) / max(0.01, sac)

            ts_us = us(sample.ts)
            total = 0.0
            for side, abs_z in ll_event_contributions(zbi, zai, zbc, zac, args.event_z):
                total += abs_z
                if side == "demand":
                    events.append(PressureEvent(ts_us, sample.mid_tick, abs_z, 0.0))
                else:
                    events.append(PressureEvent(ts_us, sample.mid_tick, 0.0, abs_z))
            activity.append(ActivityPoint(ts_us, total))
        events.sort(key=lambda item: item.ts_us)
        activity.sort(key=lambda item: item.ts_us)
        return cls(
            events=events,
            times=[item.ts_us for item in events],
            activity=activity,
            activity_times=[item.ts_us for item in activity],
        )

    def field_at(
        self,
        anchor_ts: datetime,
        min_tick: int,
        max_tick: int,
        owner_side: str,
        args: argparse.Namespace,
    ) -> dict[str, object]:
        anchor_us = us(anchor_ts)
        start_us = anchor_us - int(args.lookback_sec * 1_000_000)
        lo = bisect.bisect_left(self.times, start_us)
        hi = bisect.bisect_right(self.times, anchor_us)
        demand = 0.0
        supply = 0.0
        aligned_support = 0
        opposed_support = 0
        latest_aligned_us: int | None = None
        latest_opposed_us: int | None = None

        for event in self.events[lo:hi]:
            age_sec = max(0.0, (anchor_us - event.ts_us) / 1_000_000)
            time_weight = 0.5 ** (age_sec / max(1.0, args.half_life_sec))
            distance = distance_to_band(event.tick, min_tick, max_tick)
            if distance > args.kernel_ticks * 3:
                continue
            x = distance / max(1.0, args.kernel_ticks)
            price_weight = math.exp(-0.5 * x * x)
            weight = time_weight * price_weight
            if event.demand > 0.0:
                contribution = event.demand * weight
                demand += contribution
                if owner_side == "demand":
                    aligned_support += 1
                    latest_aligned_us = event.ts_us if latest_aligned_us is None else max(latest_aligned_us, event.ts_us)
                else:
                    opposed_support += 1
                    latest_opposed_us = event.ts_us if latest_opposed_us is None else max(latest_opposed_us, event.ts_us)
            if event.supply > 0.0:
                contribution = event.supply * weight
                supply += contribution
                if owner_side == "supply":
                    aligned_support += 1
                    latest_aligned_us = event.ts_us if latest_aligned_us is None else max(latest_aligned_us, event.ts_us)
                else:
                    opposed_support += 1
                    latest_opposed_us = event.ts_us if latest_opposed_us is None else max(latest_opposed_us, event.ts_us)

        activity = self.activity_at(anchor_us, start_us, args)
        owner = demand if owner_side == "demand" else supply
        opposing = supply if owner_side == "demand" else demand
        total = demand + supply
        owner_share = owner / total if total > 0 else 0.0
        purity = (owner - opposing) / total if total > 0 else 0.0
        ratio = owner / max(1.0, opposing)
        density_norm = total / max(1.0, activity)
        latest_aligned_age = (
            (anchor_us - latest_aligned_us) / 1_000_000
            if latest_aligned_us is not None
            else None
        )
        latest_opposed_age = (
            (anchor_us - latest_opposed_us) / 1_000_000
            if latest_opposed_us is not None
            else None
        )
        label = pressure_label(
            owner=owner,
            opposing=opposing,
            total=total,
            owner_share=owner_share,
            aligned_support=aligned_support,
            opposed_support=opposed_support,
            latest_aligned_age=latest_aligned_age,
            args=args,
        )
        return {
            "pressure_demand": demand,
            "pressure_supply": supply,
            "pressure_owner": owner,
            "pressure_opposing": opposing,
            "pressure_total": total,
            "pressure_activity": activity,
            "pressure_density_norm": density_norm,
            "pressure_owner_share": owner_share,
            "pressure_purity": purity,
            "pressure_owner_ratio": ratio,
            "pressure_aligned_support": aligned_support,
            "pressure_opposed_support": opposed_support,
            "pressure_latest_aligned_age_sec": latest_aligned_age,
            "pressure_latest_opposed_age_sec": latest_opposed_age,
            "pressure_label": label,
        }

    def activity_at(self, anchor_us: int, start_us: int, args: argparse.Namespace) -> float:
        lo = bisect.bisect_left(self.activity_times, start_us)
        hi = bisect.bisect_right(self.activity_times, anchor_us)
        total = 0.0
        for point in self.activity[lo:hi]:
            age_sec = max(0.0, (anchor_us - point.ts_us) / 1_000_000)
            total += point.total * (0.5 ** (age_sec / max(1.0, args.half_life_sec)))
        return total


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


def mean_std(samples: deque, now: datetime, seconds: float, selector) -> tuple[float, float]:
    cutoff = now - timedelta(seconds=seconds)
    values = [selector(sample) for sample in samples if sample.ts >= cutoff]
    if len(values) < 2:
        return 0.0, 0.0
    mean = sum(values) / len(values)
    var = sum(value * value for value in values) / len(values) - mean * mean
    return mean, math.sqrt(var) if var > 0 else 0.0


def ll_event_contributions(
    z_bid_inner: float,
    z_ask_inner: float,
    z_bid_centroid: float,
    z_ask_centroid: float,
    event_z: float,
) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    if z_bid_inner >= event_z:
        out.append(("demand", abs(z_bid_inner)))  # BID_BUILD
    elif z_bid_inner <= -event_z:
        out.append(("supply", abs(z_bid_inner)))  # BID_PULL
    if z_ask_inner >= event_z:
        out.append(("supply", abs(z_ask_inner)))  # ASK_BUILD
    elif z_ask_inner <= -event_z:
        out.append(("demand", abs(z_ask_inner)))  # ASK_PULL
    if z_bid_centroid >= event_z:
        out.append(("supply", abs(z_bid_centroid)))  # BID_OUT
    elif z_bid_centroid <= -event_z:
        out.append(("demand", abs(z_bid_centroid)))  # BID_IN
    if z_ask_centroid >= event_z:
        out.append(("demand", abs(z_ask_centroid)))  # ASK_OUT
    elif z_ask_centroid <= -event_z:
        out.append(("supply", abs(z_ask_centroid)))  # ASK_IN
    return out


def distance_to_band(tick: int, min_tick: int, max_tick: int) -> int:
    if tick < min_tick:
        return min_tick - tick
    if tick > max_tick:
        return tick - max_tick
    return 0


def pressure_label(
    *,
    owner: float,
    opposing: float,
    total: float,
    owner_share: float,
    aligned_support: int,
    opposed_support: int,
    latest_aligned_age: float | None,
    args: argparse.Namespace,
) -> str:
    if (
        total < args.min_density
        or aligned_support + opposed_support < args.min_support
    ):
        return "sparse_pressure"
    if latest_aligned_age is None or latest_aligned_age > args.fresh_sec:
        if owner_share >= args.aligned_share:
            return "stale_aligned_pressure"
    if owner_share >= args.aligned_share and owner >= args.min_density:
        return "aligned_pressure"
    if owner_share <= args.opposed_share and opposing >= args.min_density:
        return "opposed_pressure"
    return "mixed_pressure"


def parse_iso_ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def owner_side(row: dict[str, str]) -> str:
    return row.get("band_side") or row.get("moveaway_side") or row.get("break_side") or "demand"


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


def add_pressure(rows: list[dict[str, str]], args: argparse.Namespace) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for spec, session_rows in group_by_session(rows).items():
        anchors = [parse_iso_ts(row["anchor_ts"]) for row in session_rows]
        start = min(anchors) - timedelta(seconds=args.lookback_sec + args.snapshot_max_age_sec)
        end = max(anchors) + timedelta(seconds=args.snapshot_max_age_sec)
        print(f"pressure snapshots {spec.label} anchors={len(session_rows)}", flush=True)
        snapshots = load_capture_window(
            "snapshots",
            spec.symbol,
            start,
            end,
            snapshot_columns(30),
            inclusive_end=True,
        )
        if args.pressure_source == "snapshot_deltas":
            series = PressureSeries.from_snapshots(snapshots)
        else:
            series = PressureSeries.from_ll_events(snapshots, args)
        for row in session_rows:
            enriched: dict[str, object] = dict(row)
            anchor_ts = parse_iso_ts(row["anchor_ts"])
            side = owner_side(row)
            enriched["pressure_owner_side"] = side
            enriched.update(
                series.field_at(
                    anchor_ts,
                    int(row["min_tick"]),
                    int(row["max_tick"]),
                    side,
                    args,
                )
            )
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
        "| fixture | time | anchor | owner | pressure | share | purity | support | lifecycle |",
        "| --- | --- | --- | --- | --- | ---: | ---: | ---: | --- |",
    ]
    for row in selected:
        lines.append(
            f"| `{row.get('fixture_id')}` | {row.get('anchor_ny')} | "
            f"{row.get('anchor_class')}@{row.get('band_price')} | {row.get('pressure_owner_side')} | "
            f"`{row.get('pressure_label')}` | {float(row.get('pressure_owner_share') or 0):.2f} | "
            f"{float(row.get('pressure_purity') or 0):.2f} | "
            f"{int(float(row.get('pressure_aligned_support') or 0))}/"
            f"{int(float(row.get('pressure_opposed_support') or 0))} | "
            f"`{row.get('lifecycle_label')}` |"
        )
    return lines


def write_report(path: Path, rows: list[dict[str, object]], args: argparse.Namespace) -> None:
    tests = [row for row in rows if row.get("anchor_class") == "band_test"]
    failures = [row for row in rows if row.get("anchor_class") == "band_failure"]
    conversions = [row for row in rows if row.get("anchor_class") == "consumed_conversion"]
    primary = [row for row in rows if row.get("curated_bucket") == "primary_dev"]
    lines = [
        "# Pressure Field Lifecycle Probe",
        "",
        "Fixture-scoped Thesis 6 pass. Anchors come from the T3 lifecycle probe; pressure metrics are side-aware book-pressure context.",
        "",
        "## Coverage",
        "",
        f"- anchor rows: `{len(rows)}`",
        f"- tests: `{len(tests)}`",
        f"- failures: `{len(failures)}`",
        f"- consumed conversions: `{len(conversions)}`",
        f"- anchor source: `{args.anchors}`",
        f"- source: `{args.pressure_source}` from MarketRecorder snapshots",
        "",
        "## Lifecycle By Pressure Label",
        "",
    ]
    lines.extend(summarize(rows, ["anchor_class", "pressure_label"]))
    lines.extend(["", "## Fixture Bucket By Pressure Label", ""])
    lines.extend(summarize(rows, ["curated_bucket", "pressure_label"]))
    lines.extend(["", "## Band Tests Only", ""])
    lines.extend(summarize(tests, ["pressure_label"]))
    lines.extend(["", "## Failures Only", ""])
    lines.extend(summarize(failures, ["pressure_label"]))
    lines.extend(["", "## Consumed Conversions Only", ""])
    lines.extend(summarize(conversions, ["pressure_label"]))
    lines.extend(["", "## Primary Development Fixtures", ""])
    lines.extend(summarize(primary, ["anchor_class", "pressure_label"]))
    lines.extend(["", "## Metric Sketch", ""])
    for label in (
        "aligned_pressure",
        "opposed_pressure",
        "mixed_pressure",
        "stale_aligned_pressure",
        "sparse_pressure",
    ):
        subset = [row for row in rows if row.get("pressure_label") == label]
        if not subset:
            continue
        lines.append(f"- `{label}` owner share: {numeric_summary(subset, 'pressure_owner_share')}")
        lines.append(f"- `{label}` purity: {numeric_summary(subset, 'pressure_purity')}")
        lines.append(f"- `{label}` density norm: {numeric_summary(subset, 'pressure_density_norm')}")
        lines.append(f"- `{label}` move-away aligned ticks: {numeric_summary(subset, 'moveaway_price_net_aligned_ticks')}")
    lines.extend(["", "## Example Rows", ""])
    lines.extend(example_rows(rows))
    lines.extend(
        [
            "",
            "## Parameters",
            "",
            f"- lookback_sec: `{args.lookback_sec}`",
            f"- half_life_sec: `{args.half_life_sec}`",
            f"- kernel_ticks: `{args.kernel_ticks}`",
            f"- event_z: `{args.event_z}`",
            f"- book_lookback_sec: `{args.book_lookback_sec}`",
            f"- min_density: `{args.min_density}`",
            f"- min_support: `{args.min_support}`",
            f"- aligned_share / opposed_share: `{args.aligned_share}` / `{args.opposed_share}`",
            f"- fresh_sec: `{args.fresh_sec}`",
            "",
            "## Guardrails",
            "",
            "- Default `ll_events` mode uses LL-style side-aware z events from snapshots; it is not raw quote-event replay.",
            "- `snapshot_deltas` mode is available, but 1 Hz depth deltas can blend real adds, pulls, and price-level churn.",
            "- Pressure labels are descriptive context, not ownership outcomes.",
            "- `pressure_density_norm` is local pressure divided by decayed whole-book snapshot activity; it is a scale hint, not a thresholded rule.",
            "- Lifecycle labels remain the primary outcome.",
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
    parser.add_argument("--lookback-sec", type=float, default=120.0)
    parser.add_argument("--half-life-sec", type=float, default=45.0)
    parser.add_argument("--kernel-ticks", type=float, default=12.0)
    parser.add_argument("--pressure-source", choices=("ll_events", "snapshot_deltas"), default="ll_events")
    parser.add_argument("--event-z", type=float, default=EVENT_Z_THRESHOLD)
    parser.add_argument("--book-lookback-sec", type=float, default=BOOK_LOOKBACK_SEC)
    parser.add_argument("--snapshot-max-age-sec", type=float, default=2.5)
    parser.add_argument("--min-density", type=float, default=2.5)
    parser.add_argument("--min-support", type=int, default=2)
    parser.add_argument("--aligned-share", type=float, default=0.65)
    parser.add_argument("--opposed-share", type=float, default=0.35)
    parser.add_argument("--fresh-sec", type=float, default=90.0)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--tag", default="20260623_20260626")
    args = parser.parse_args()

    anchors = load_anchors(Path(args.anchors), args)
    rows = add_pressure(anchors, args)
    out_dir = Path(args.output_dir)
    csv_path = out_dir / f"pressure_field_lifecycle_probe_{args.tag}.csv"
    report_path = out_dir / f"pressure_field_lifecycle_probe_{args.tag}.md"
    write_csv(csv_path, rows)
    write_report(report_path, rows, args)
    print(f"wrote {csv_path}")
    print(f"wrote {report_path}")


if __name__ == "__main__":
    main()
