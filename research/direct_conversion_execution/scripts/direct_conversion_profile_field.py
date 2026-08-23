"""Point-in-time traded-profile location for direct-conversion research.

The direct-conversion and ownership definitions stay unchanged. This probe
only asks where an already-detected event, retest, entry, or material return
sat in the traded-volume topology that existed at that instant.

Profiles are built incrementally from MarketRecorder ticks. No trade occurring
after a query timestamp can affect that query's HVN/LVN classification.
"""

from __future__ import annotations

import argparse
import csv
import glob
import math
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from _paths import OUTPUT_ROOT

from capture_loader import load_capture_window, tick_columns  # noqa: E402


NY = ZoneInfo("America/New_York")
TICK_SIZE = 0.25
DEFAULT_LINEAGE = (
    OUTPUT_ROOT / "direct_conversion_sponsor_lineage" / "lineage.csv"
)
DEFAULT_STEPS = (
    OUTPUT_ROOT
    / "direct_conversion_road_steps_20260717_20260724"
    / "steps.csv"
)
DEFAULT_OUT = (
    OUTPUT_ROOT / "direct_conversion_profile_field_20260716_20260724"
)
DEFAULT_ENTRY_GLOB = str(
    OUTPUT_ROOT
    / "direct_conversion_entry_field_202607*"
    / "entry_provision.csv"
)


@dataclass(frozen=True)
class Query:
    query_id: str
    source: str
    session_id: str
    date: str
    root_id: str
    step_ordinal: str
    query_kind: str
    ts_us: int
    ts_et: str
    side: str
    anchor_price: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lineage", type=Path, default=DEFAULT_LINEAGE)
    parser.add_argument("--steps", type=Path, default=DEFAULT_STEPS)
    parser.add_argument("--entry-glob", default=DEFAULT_ENTRY_GLOB)
    parser.add_argument("--symbol-dir", default="NQU6")
    parser.add_argument("--start-date", default="2026-07-16")
    parser.add_argument("--end-date", default="2026-07-24")
    parser.add_argument("--bin-points", default="2,4")
    parser.add_argument("--scopes", default="rth,30m,60m")
    parser.add_argument("--hvn-quantile", type=float, default=0.70)
    parser.add_argument("--lvn-quantile", type=float, default=0.30)
    parser.add_argument("--valley-ratio", type=float, default=0.65)
    parser.add_argument("--peak-search-points", type=float, default=60.0)
    parser.add_argument("--edge-bins", type=int, default=1)
    parser.add_argument("--min-profile-minutes", type=float, default=5.0)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    return parser.parse_args()


def parse_et(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=NY) if parsed.tzinfo is None else parsed.astimezone(NY)


def to_us(value: str) -> int:
    return int(parse_et(value).timestamp() * 1_000_000)


def fnum(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def in_range(day: str, start: str, end: str) -> bool:
    return start <= day <= end


def midpoint(row: dict[str, str]) -> float | None:
    lo = fnum(row.get("root_lo"))
    hi = fnum(row.get("root_hi"))
    if lo is None or hi is None:
        return None
    return (lo + hi) / 2.0


def add_query(
    queries: list[Query],
    *,
    source: str,
    session_id: str,
    date: str,
    root_id: str,
    step_ordinal: str,
    query_kind: str,
    ts_et: str,
    side: str,
    anchor_price: float | None,
) -> None:
    if not ts_et or anchor_price is None:
        return
    query_id = ":".join(
        (
            source,
            session_id or "-",
            date,
            root_id,
            step_ordinal or "-",
            query_kind,
        )
    )
    queries.append(
        Query(
            query_id=query_id,
            source=source,
            session_id=session_id,
            date=date,
            root_id=root_id,
            step_ordinal=step_ordinal,
            query_kind=query_kind,
            ts_us=to_us(ts_et),
            ts_et=ts_et,
            side=side,
            anchor_price=anchor_price,
        )
    )


def lineage_queries(path: Path, start: str, end: str) -> list[Query]:
    queries: list[Query] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            day = row["date"]
            if not in_range(day, start, end):
                continue
            anchor = midpoint(row)
            common = {
                "source": "lineage",
                "session_id": row.get("session_id", ""),
                "date": day,
                "root_id": row["root_id"],
                "step_ordinal": "",
                "side": row["side"],
                "anchor_price": anchor,
            }
            add_query(
                queries,
                query_kind="root_owned",
                ts_et=row.get("root_owned_et", ""),
                **common,
            )
            add_query(
                queries,
                query_kind="first_test",
                ts_et=row.get("root_first_tested_et", ""),
                **common,
            )
            if row.get("root_first_test_verdict") == "HELD_FIRST_TEST":
                add_query(
                    queries,
                    query_kind="first_hold",
                    ts_et=row.get("root_first_test_resolved_et", ""),
                    **common,
                )
            add_query(
                queries,
                query_kind="first_entry",
                ts_et=row.get("first_entry_et", ""),
                **common,
            )
    return queries


def step_queries(path: Path, start: str, end: str) -> list[Query]:
    if not path.exists():
        return []
    queries: list[Query] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            day = row["date"]
            if not in_range(day, start, end):
                continue
            common = {
                "source": "steps",
                "session_id": row.get("session_id", ""),
                "date": day,
                "root_id": row["root_id"],
                "step_ordinal": row["step_ordinal"],
                "side": row["side"],
            }
            add_query(
                queries,
                query_kind="step_start",
                ts_et=row.get("start_et", ""),
                anchor_price=fnum(row.get("start_price")),
                **common,
            )
            if row.get("relation") == "ENTRY_STEP":
                add_query(
                    queries,
                    query_kind="step_entry",
                    ts_et=row.get("entry_et", ""),
                    anchor_price=fnum(row.get("entry_step_price")),
                    **common,
                )
    return queries


def entry_queries(pattern: str, start: str, end: str) -> list[Query]:
    queries: list[Query] = []
    for raw_path in sorted(glob.glob(pattern)):
        path = Path(raw_path)
        with path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                day = row["date"]
                if not in_range(day, start, end):
                    continue
                lo = fnum(row.get("price_lo"))
                hi = fnum(row.get("price_hi"))
                anchor = (
                    (lo + hi) / 2.0
                    if lo is not None and hi is not None
                    else None
                )
                add_query(
                    queries,
                    source="entries",
                    session_id=row.get("session_id", ""),
                    date=day,
                    root_id=row.get("band_id", ""),
                    step_ordinal=row.get("intent_id", ""),
                    query_kind="order_decision",
                    ts_et=row.get("decision_et", ""),
                    side=(
                        "Demand"
                        if row.get("side") == "Long"
                        else "Supply"
                    ),
                    anchor_price=anchor,
                )
    return queries


def quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = max(0.0, min(1.0, q)) * (len(ordered) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return ordered[lo]
    weight = pos - lo
    return ordered[lo] * (1.0 - weight) + ordered[hi] * weight


def smooth(values: list[float]) -> list[float]:
    out: list[float] = []
    for idx, value in enumerate(values):
        left = values[idx - 1] if idx > 0 else 0.0
        right = values[idx + 1] if idx + 1 < len(values) else 0.0
        out.append(0.25 * left + 0.50 * value + 0.25 * right)
    return out


def true_regions(mask: list[bool]) -> list[tuple[int, int]]:
    regions: list[tuple[int, int]] = []
    start: int | None = None
    for idx, active in enumerate(mask):
        if active and start is None:
            start = idx
        elif not active and start is not None:
            regions.append((start, idx - 1))
            start = None
    if start is not None:
        regions.append((start, len(mask) - 1))
    return regions


def region_peak(
    region: tuple[int, int], values: list[float], bins: list[int]
) -> tuple[int, float]:
    start, end = region
    idx = max(range(start, end + 1), key=lambda i: values[i])
    return bins[idx], values[idx]


def empty_metrics(reason: str) -> dict[str, Any]:
    return {
        "profile_valid": False,
        "invalid_reason": reason,
        "topology": "invalid",
    }


def profile_metrics(
    volume: dict[int, float],
    *,
    anchor_price: float,
    side: str,
    bin_points: float,
    hvn_q: float,
    lvn_q: float,
    valley_cutoff: float,
    peak_search_points: float,
    edge_bins: int,
) -> dict[str, Any]:
    active = {key: value for key, value in volume.items() if value > 1e-9}
    if not active:
        return empty_metrics("empty_profile")

    bin_ticks = int(round(bin_points / TICK_SIZE))
    anchor_tick = int(round(anchor_price / TICK_SIZE))
    anchor_bin = anchor_tick // bin_ticks
    lo_bin = min(active)
    hi_bin = max(active)
    if anchor_bin < lo_bin or anchor_bin > hi_bin:
        return {
            **empty_metrics("anchor_outside_profile_range"),
            "profile_low": lo_bin * bin_points,
            "profile_high": (hi_bin + 1) * bin_points,
            "profile_range_pts": (hi_bin - lo_bin + 1) * bin_points,
            "profile_bins": hi_bin - lo_bin + 1,
            "touched_bins": len(active),
            "profile_total_volume": sum(active.values()),
        }

    bins = list(range(lo_bin, hi_bin + 1))
    raw = [active.get(key, 0.0) for key in bins]
    shaped = smooth(raw)
    anchor_idx = anchor_bin - lo_bin
    anchor_raw = raw[anchor_idx]
    anchor_value = shaped[anchor_idx]
    positive = [value for value in shaped if value > 1e-9]
    if len(positive) < 3:
        return empty_metrics("too_few_profile_bins")

    hvn_threshold = quantile(positive, hvn_q)
    lvn_threshold = quantile(positive, lvn_q)
    high_regions = true_regions(
        [value >= hvn_threshold and value > 0 for value in shaped]
    )
    containing = next(
        (
            region
            for region in high_regions
            if region[0] <= anchor_idx <= region[1]
        ),
        None,
    )
    search_bins = max(1, int(round(peak_search_points / bin_points)))
    left_regions = [
        region
        for region in high_regions
        if region[1] < anchor_idx
        and anchor_idx - region[1] <= search_bins
    ]
    right_regions = [
        region
        for region in high_regions
        if region[0] > anchor_idx
        and region[0] - anchor_idx <= search_bins
    ]
    left_region = max(left_regions, key=lambda item: item[1], default=None)
    right_region = min(right_regions, key=lambda item: item[0], default=None)

    left_peak = (
        region_peak(left_region, shaped, bins) if left_region else (None, None)
    )
    right_peak = (
        region_peak(right_region, shaped, bins) if right_region else (None, None)
    )
    vpoc_idx = min(
        (idx for idx, value in enumerate(shaped) if value == max(shaped)),
        key=lambda idx: abs(idx - anchor_idx),
    )
    vpoc_bin = bins[vpoc_idx]
    local_radius = max(1, int(round(20.0 / bin_points)))
    local_lo = max(0, anchor_idx - local_radius)
    local_hi = min(len(shaped), anchor_idx + local_radius + 1)
    local_max = max(shaped[local_lo:local_hi])

    between_nodes = left_region is not None and right_region is not None
    valley_ratio = None
    if between_nodes:
        bounding_peak = min(float(left_peak[1]), float(right_peak[1]))
        valley_ratio = anchor_value / bounding_peak if bounding_peak > 0 else None

    direction = 1 if side.lower() == "demand" else -1
    favorable_edge_distance = None
    adverse_edge_distance = None
    hvn_lo = None
    hvn_hi = None
    if containing is not None:
        start, end = containing
        hvn_lo = bins[start] * bin_points
        hvn_hi = (bins[end] + 1) * bin_points
        lower_distance = max(0.0, anchor_price - hvn_lo)
        upper_distance = max(0.0, hvn_hi - anchor_price)
        if direction > 0:
            favorable_edge_distance = upper_distance
            adverse_edge_distance = lower_distance
        else:
            favorable_edge_distance = lower_distance
            adverse_edge_distance = upper_distance

    if containing is not None:
        edge_points = edge_bins * bin_points
        if (
            favorable_edge_distance is not None
            and favorable_edge_distance <= edge_points
            and (
                adverse_edge_distance is None
                or favorable_edge_distance <= adverse_edge_distance
            )
        ):
            topology = "hvn_favorable_edge"
        elif (
            adverse_edge_distance is not None
            and adverse_edge_distance <= edge_points
        ):
            topology = "hvn_adverse_edge"
        else:
            topology = "hvn_interior"
    elif (
        between_nodes
        and anchor_value <= lvn_threshold
        and valley_ratio is not None
        and valley_ratio <= valley_cutoff
    ):
        topology = "between_hvns_lvn"
    elif anchor_value <= lvn_threshold:
        topology = "one_sided_lvn"
    else:
        topology = "transition"

    return {
        "profile_valid": True,
        "invalid_reason": "",
        "topology": topology,
        "profile_low": lo_bin * bin_points,
        "profile_high": (hi_bin + 1) * bin_points,
        "profile_range_pts": (hi_bin - lo_bin + 1) * bin_points,
        "profile_bins": len(bins),
        "touched_bins": len(active),
        "profile_total_volume": sum(active.values()),
        "anchor_bin_low": anchor_bin * bin_points,
        "anchor_bin_volume": anchor_raw,
        "anchor_smooth_volume": anchor_value,
        "volume_percentile": sum(
            1 for value in shaped if value <= anchor_value
        )
        / len(shaped),
        "volume_to_vpoc_ratio": (
            anchor_value / shaped[vpoc_idx] if shaped[vpoc_idx] > 0 else None
        ),
        "local_volume_ratio": (
            anchor_value / local_max if local_max > 0 else None
        ),
        "hvn_threshold": hvn_threshold,
        "lvn_threshold": lvn_threshold,
        "vpoc_price": (vpoc_bin + 0.5) * bin_points,
        "vpoc_signed_distance_pts": direction
        * (anchor_price - (vpoc_bin + 0.5) * bin_points),
        "left_hvn_price": (
            (float(left_peak[0]) + 0.5) * bin_points
            if left_peak[0] is not None
            else None
        ),
        "left_hvn_distance_pts": (
            anchor_price - (float(left_peak[0]) + 0.5) * bin_points
            if left_peak[0] is not None
            else None
        ),
        "right_hvn_price": (
            (float(right_peak[0]) + 0.5) * bin_points
            if right_peak[0] is not None
            else None
        ),
        "right_hvn_distance_pts": (
            (float(right_peak[0]) + 0.5) * bin_points - anchor_price
            if right_peak[0] is not None
            else None
        ),
        "between_hvns": between_nodes,
        "valley_ratio": valley_ratio,
        "hvn_region_low": hvn_lo,
        "hvn_region_high": hvn_hi,
        "favorable_edge_distance_pts": favorable_edge_distance,
        "adverse_edge_distance_pts": adverse_edge_distance,
    }


def current_field_metrics(
    metrics: dict[str, Any],
    *,
    anchor_price: float,
    current_price: float | None,
    side: str,
) -> dict[str, Any]:
    if current_price is None or not metrics.get("profile_valid"):
        return {
            "current_price": current_price,
            "current_favorable_displacement_pts": None,
            "current_vpoc_signed_distance_pts": None,
            "current_hvn_escape_margin_pts": None,
            "current_beyond_favorable_hvn_edge": None,
            "current_next_hvn_signed_gap_pts": None,
            "field_state": "invalid",
        }
    direction = 1 if side.lower() == "demand" else -1
    vpoc = fnum(metrics.get("vpoc_price"))
    hvn_lo = fnum(metrics.get("hvn_region_low"))
    hvn_hi = fnum(metrics.get("hvn_region_high"))
    topology = str(metrics.get("topology") or "")
    escape_margin = None
    if hvn_lo is not None and hvn_hi is not None:
        escape_margin = (
            current_price - hvn_hi
            if direction > 0
            else hvn_lo - current_price
        )
    favorable_hvn = (
        fnum(metrics.get("right_hvn_price"))
        if direction > 0
        else fnum(metrics.get("left_hvn_price"))
    )
    next_hvn_gap = (
        direction * (favorable_hvn - current_price)
        if favorable_hvn is not None
        else None
    )
    if topology.startswith("hvn_"):
        field_state = (
            "hvn_anchor_escaped"
            if escape_margin is not None and escape_margin > 0
            else "hvn_anchor_not_escaped"
        )
    elif topology == "between_hvns_lvn":
        field_state = "between_hvns_lvn"
    elif topology == "one_sided_lvn":
        field_state = "one_sided_lvn"
    else:
        field_state = topology
    return {
        "current_price": current_price,
        "current_favorable_displacement_pts": direction
        * (current_price - anchor_price),
        "current_vpoc_signed_distance_pts": (
            direction * (current_price - vpoc) if vpoc is not None else None
        ),
        "current_hvn_escape_margin_pts": escape_margin,
        "current_beyond_favorable_hvn_edge": (
            escape_margin > 0 if escape_margin is not None else None
        ),
        "current_next_hvn_signed_gap_pts": next_hvn_gap,
        "field_state": field_state,
    }


def scope_minutes(scope: str) -> float | None:
    if scope == "rth":
        return None
    if not scope.endswith("m"):
        raise ValueError(f"unsupported scope: {scope}")
    return float(scope[:-1])


def day_bounds(day: str) -> tuple[datetime, datetime]:
    parsed = datetime.fromisoformat(day).date()
    start = datetime.combine(parsed, time(9, 30), tzinfo=NY)
    return start, datetime.combine(parsed, time(16, 0), tzinfo=NY)


def fmt(value: Any) -> Any:
    if isinstance(value, float):
        if not math.isfinite(value):
            return ""
        return round(value, 6)
    return value


def evaluate_config(
    queries: list[Query],
    tick_times: list[int],
    tick_prices: list[float],
    tick_sizes: list[float],
    *,
    day: str,
    scope: str,
    bin_points: float,
    args: argparse.Namespace,
) -> list[dict[str, Any]]:
    if not tick_times:
        return []
    bin_ticks = int(round(bin_points / TICK_SIZE))
    tick_bins = [
        int(round(price / TICK_SIZE)) // bin_ticks for price in tick_prices
    ]
    lookback = scope_minutes(scope)
    window_us = int(lookback * 60 * 1_000_000) if lookback is not None else None
    rth_start, _ = day_bounds(day)
    rth_start_us = int(rth_start.timestamp() * 1_000_000)
    profile: dict[int, float] = defaultdict(float)
    left = 0
    right = 0
    out: list[dict[str, Any]] = []

    for query in sorted(queries, key=lambda item: item.ts_us):
        while right < len(tick_times) and tick_times[right] <= query.ts_us:
            profile[tick_bins[right]] += tick_sizes[right]
            right += 1
        required_start_us = rth_start_us
        if window_us is not None:
            required_start_us = max(rth_start_us, query.ts_us - window_us)
            while left < right and tick_times[left] < required_start_us:
                key = tick_bins[left]
                profile[key] -= tick_sizes[left]
                if profile[key] <= 1e-9:
                    del profile[key]
                left += 1

        first_used_us = tick_times[left] if left < right else None
        profile_age_s = (
            (query.ts_us - max(required_start_us, first_used_us)) / 1_000_000
            if first_used_us is not None
            else 0.0
        )
        capture_complete = tick_times[0] <= required_start_us + 5_000_000
        base = {
            "query_id": query.query_id,
            "source": query.source,
            "session_id": query.session_id,
            "date": query.date,
            "root_id": query.root_id,
            "step_ordinal": query.step_ordinal,
            "query_kind": query.query_kind,
            "query_ts_et": query.ts_et,
            "side": query.side,
            "anchor_price": query.anchor_price,
            "scope": scope,
            "bin_points": bin_points,
            "profile_age_s": profile_age_s,
            "capture_complete": capture_complete,
            "profile_tick_rows": right - left,
        }
        current_price = tick_prices[right - 1] if right > 0 else None
        if query.ts_us < rth_start_us:
            metrics = empty_metrics("pre_rth_query")
        elif not capture_complete:
            metrics = empty_metrics("capture_started_after_profile_window")
        elif profile_age_s < args.min_profile_minutes * 60:
            metrics = empty_metrics("immature_profile")
        else:
            metrics = profile_metrics(
                profile,
                anchor_price=query.anchor_price,
                side=query.side,
                bin_points=bin_points,
                hvn_q=args.hvn_quantile,
                lvn_q=args.lvn_quantile,
                valley_cutoff=args.valley_ratio,
                peak_search_points=args.peak_search_points,
                edge_bins=args.edge_bins,
            )
        metrics.update(
            current_field_metrics(
                metrics,
                anchor_price=query.anchor_price,
                current_price=current_price,
                side=query.side,
            )
        )
        out.append({key: fmt(value) for key, value in {**base, **metrics}.items()})
    return out


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fields.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def parse_csv_list(value: str, cast: Any = str) -> list[Any]:
    return [cast(item.strip()) for item in value.split(",") if item.strip()]


def counts(rows: Iterable[dict[str, Any]], key: str) -> dict[str, int]:
    result: dict[str, int] = defaultdict(int)
    for row in rows:
        result[str(row.get(key, ""))] += 1
    return dict(sorted(result.items()))


def main() -> None:
    args = parse_args()
    queries = lineage_queries(args.lineage, args.start_date, args.end_date)
    queries.extend(step_queries(args.steps, args.start_date, args.end_date))
    queries.extend(entry_queries(args.entry_glob, args.start_date, args.end_date))
    deduped = {query.query_id: query for query in queries}
    queries = sorted(deduped.values(), key=lambda item: (item.date, item.ts_us))
    scopes = parse_csv_list(args.scopes)
    bin_points_values = parse_csv_list(args.bin_points, float)
    output: list[dict[str, Any]] = []
    manifest: list[str] = [
        "# Direct Conversion Point-In-Time Profile Field",
        "",
        f"Lineage: `{args.lineage}`",
        f"Road steps: `{args.steps}`",
        f"Individual entries: `{args.entry_glob}`",
        f"Dates: {args.start_date} through {args.end_date}",
        f"Queries: {len(queries)}",
        f"Scopes: {', '.join(scopes)}",
        "Bin sizes: " + ", ".join(f"{value:g}" for value in bin_points_values),
        "",
        "No future trades are admitted to a query profile.",
        "",
        "## Daily Capture",
        "",
        "| date | queries | tick rows | first tick | last tick |",
        "|---|---:|---:|---|---|",
    ]

    by_day: dict[str, list[Query]] = defaultdict(list)
    for query in queries:
        by_day[query.date].append(query)
    for day in sorted(by_day):
        start, end = day_bounds(day)
        ticks = load_capture_window(
            "ticks",
            args.symbol_dir,
            start,
            end,
            tick_columns(),
        )
        tick_times = [int(value) for value in ticks["timestamp_us"].to_list()]
        tick_prices = [float(value) for value in ticks["price"].to_list()]
        tick_sizes = [float(value) for value in ticks["size"].to_list()]
        first_text = (
            datetime.fromtimestamp(tick_times[0] / 1_000_000, NY).isoformat()
            if tick_times
            else ""
        )
        last_text = (
            datetime.fromtimestamp(tick_times[-1] / 1_000_000, NY).isoformat()
            if tick_times
            else ""
        )
        manifest.append(
            f"| {day} | {len(by_day[day])} | {len(tick_times)} | "
            f"{first_text} | {last_text} |"
        )
        for scope in scopes:
            for bin_points in bin_points_values:
                output.extend(
                    evaluate_config(
                        by_day[day],
                        tick_times,
                        tick_prices,
                        tick_sizes,
                        day=day,
                        scope=scope,
                        bin_points=bin_points,
                        args=args,
                    )
                )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    locations_path = args.out_dir / "profile_locations.csv"
    write_csv(locations_path, output)
    manifest.extend(
        [
            "",
            "## Output",
            "",
            f"- Rows: {len(output)}",
            f"- Validity: {counts(output, 'profile_valid')}",
            f"- Invalid reasons: {counts(output, 'invalid_reason')}",
            f"- Topology: {counts(output, 'topology')}",
            f"- CSV: `{locations_path}`",
            "",
        ]
    )
    (args.out_dir / "manifest.md").write_text(
        "\n".join(manifest), encoding="utf-8"
    )
    print(f"wrote {locations_path} rows={len(output)}")


if __name__ == "__main__":
    main()
