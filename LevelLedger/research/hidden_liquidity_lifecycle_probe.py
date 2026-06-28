"""Fixture-scoped hidden-liquidity proxy probe.

This is Thesis 9 from the Skurry Now Lens research note. It looks for same-price
trade volume that is large relative to the maximum displayed passive size seen
in nearby MarketRecorder snapshots.

This is a broad proxy, not proof of hidden order replenishment. Snapshot cadence
and feed event ordering can miss displayed refresh behavior.
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

import polars as pl


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RESEARCH = ROOT / "research"
sys.path.insert(0, str(RESEARCH))
sys.path.insert(0, str(HERE))

from capture_loader import MARKET_RECORDER_ROOT, load_capture_window, snapshot_columns, tick_columns, us  # noqa: E402


DEFAULT_BRICK = RESEARCH / "out" / "brick_contact_response_probe_20260623_20260626.csv"
DEFAULT_OUT_DIR = RESEARCH / "out"
TICK_SIZE = 0.25

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
class TickWindow:
    times: list[int]
    price_ticks: list[int]
    sizes: list[float]
    signs: list[int]


@dataclass
class SnapshotWindow:
    times: list[int]
    rows: list[dict]


def parse_iso_ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def as_float(row: dict[str, str], field: str, default: float = 0.0) -> float:
    value = row.get(field, "")
    if value in ("", None):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def as_bool(row: dict[str, str], field: str) -> bool:
    return str(row.get(field, "")).strip().lower() == "true"


def clean_source(row: dict[str, str]) -> bool:
    return as_bool(row, "valid_book") and not as_bool(row, "invalidated_by_gap")


def side_sign(side: str) -> int:
    return 1 if side == "demand" else -1


def hidden_side_from_majority(majority_sign: int) -> str:
    return "supply" if majority_sign > 0 else "demand"


def passive_side_from_hidden(hidden_side: str) -> int:
    return -1 if hidden_side == "supply" else 1


def outcome_group(lifecycle: str) -> str:
    if lifecycle in DEFENSE_LIFECYCLES:
        return "owner_defended"
    if lifecycle in CONTESTED_LIFECYCLES:
        return "contested_or_balance"
    if lifecycle in FAILURE_LIFECYCLES:
        return "failed_or_no_followthrough"
    return "other"


def hidden_alignment(hidden_side: str, owner_side: str) -> str:
    if not hidden_side:
        return "no_hidden"
    return "aligned_hidden" if hidden_side == owner_side else "opposed_hidden"


def hidden_read(label: str, outcome: str) -> str:
    if label == "aligned_hidden" and outcome == "owner_defended":
        return "aligned_hidden_defended"
    if label == "aligned_hidden" and outcome == "failed_or_no_followthrough":
        return "aligned_hidden_failed"
    if label == "aligned_hidden" and outcome == "contested_or_balance":
        return "aligned_hidden_contested"
    if label == "opposed_hidden" and outcome == "owner_defended":
        return "opposed_hidden_owner_still_defended"
    if label == "opposed_hidden" and outcome == "failed_or_no_followthrough":
        return "opposed_hidden_failure"
    if label == "opposed_hidden" and outcome == "contested_or_balance":
        return "opposed_hidden_contested"
    return "no_hidden_context"


def load_source(path: Path, args: argparse.Namespace) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with path.open("r", newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if args.clean_only and not clean_source(row):
                continue
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


def load_ticks(spec: SessionSpec, rows: list[dict[str, str]], args: argparse.Namespace) -> TickWindow:
    anchors = [parse_iso_ts(row["anchor_ts"]) for row in rows]
    start = min(anchors) - timedelta(seconds=args.tick_before_sec + 2)
    end = max(anchors) + timedelta(seconds=args.tick_after_sec + 2)
    df = load_capture_window(
        "ticks",
        spec.symbol,
        start,
        end,
        tick_columns(),
        inclusive_end=True,
    )
    times = [int(item) for item in df["timestamp_us"].to_list()]
    price_ticks = [int(round(float(price) / TICK_SIZE)) for price in df["price"].to_list()]
    sizes = [float(size) for size in df["size"].to_list()]
    signs = [int(sign) for sign in df["aggressor_sign"].to_list()]
    return TickWindow(times=times, price_ticks=price_ticks, sizes=sizes, signs=signs)


def load_snapshots(spec: SessionSpec, rows: list[dict[str, str]], args: argparse.Namespace) -> SnapshotWindow:
    anchors = [parse_iso_ts(row["anchor_ts"]) for row in rows]
    start = min(anchors) - timedelta(seconds=args.display_before_sec + 2)
    end = max(anchors) + timedelta(seconds=args.display_after_sec + 2)
    df = load_capture_window(
        "snapshots",
        spec.symbol,
        start,
        end,
        snapshot_columns(30),
        inclusive_end=True,
    )
    snapshot_rows = df.to_dicts()
    return SnapshotWindow(
        times=[int(row["timestamp_us"]) for row in snapshot_rows],
        rows=snapshot_rows,
    )


def display_max_by_price(
    snapshots: SnapshotWindow,
    anchor_us: int,
    min_tick: int,
    max_tick: int,
    args: argparse.Namespace,
) -> tuple[dict[tuple[int, int], float], dict[tuple[int, int], bool], int]:
    lo_us = anchor_us - args.display_before_sec * 1_000_000
    hi_us = anchor_us + args.display_after_sec * 1_000_000
    lo_idx = bisect.bisect_left(snapshots.times, lo_us)
    hi_idx = bisect.bisect_right(snapshots.times, hi_us)
    wanted = set(range(min_tick - args.band_expand_ticks, max_tick + args.band_expand_ticks + 1))
    maxes: dict[tuple[int, int], float] = defaultdict(float)
    seen: dict[tuple[int, int], bool] = defaultdict(bool)
    for row in snapshots.rows[lo_idx:hi_idx]:
        ref_tick = int(row["ref_tick"])
        for idx in range(30):
            bid_size = float(row[f"bid_size_{idx}"])
            if math.isfinite(bid_size) and bid_size >= 0:
                tick = ref_tick + int(row[f"bid_offset_{idx}"])
                if tick in wanted:
                    key = (1, tick)
                    seen[key] = True
                    maxes[key] = max(maxes[key], bid_size)
            ask_size = float(row[f"ask_size_{idx}"])
            if math.isfinite(ask_size) and ask_size >= 0:
                tick = ref_tick + int(row[f"ask_offset_{idx}"])
                if tick in wanted:
                    key = (-1, tick)
                    seen[key] = True
                    maxes[key] = max(maxes[key], ask_size)
    return dict(maxes), dict(seen), hi_idx - lo_idx


def aggregate_trade_by_price(
    ticks: TickWindow,
    anchor_us: int,
    min_tick: int,
    max_tick: int,
    args: argparse.Namespace,
) -> dict[int, dict[str, float]]:
    lo_us = anchor_us - args.tick_before_sec * 1_000_000
    hi_us = anchor_us + args.tick_after_sec * 1_000_000
    lo_idx = bisect.bisect_left(ticks.times, lo_us)
    hi_idx = bisect.bisect_right(ticks.times, hi_us)
    lo_tick = min_tick - args.band_expand_ticks
    hi_tick = max_tick + args.band_expand_ticks
    by_price: dict[int, dict[str, float]] = {}
    for idx in range(lo_idx, hi_idx):
        tick = ticks.price_ticks[idx]
        if tick < lo_tick or tick > hi_tick:
            continue
        size = ticks.sizes[idx]
        if not math.isfinite(size) or size <= 0:
            continue
        entry = by_price.setdefault(tick, {"buy": 0.0, "sell": 0.0, "total": 0.0, "prints": 0.0})
        sign = ticks.signs[idx]
        if sign > 0:
            entry["buy"] += size
        elif sign < 0:
            entry["sell"] += size
        entry["total"] += size
        entry["prints"] += 1.0
    return by_price


def best_hidden_candidate(
    trade_by_price: dict[int, dict[str, float]],
    display_max: dict[tuple[int, int], float],
    display_seen: dict[tuple[int, int], bool],
    args: argparse.Namespace,
) -> dict[str, object]:
    candidates: list[dict[str, object]] = []
    for tick, values in trade_by_price.items():
        total = float(values["total"])
        if total < args.min_trade_volume:
            continue
        buy = float(values["buy"])
        sell = float(values["sell"])
        stronger = max(buy, sell)
        if stronger <= 0:
            continue
        share = stronger / max(1.0, total)
        if share < args.majority_share:
            continue
        majority_sign = 1 if buy >= sell else -1
        hidden_side = hidden_side_from_majority(majority_sign)
        passive_side = passive_side_from_hidden(hidden_side)
        displayed = float(display_max.get((passive_side, tick), 0.0))
        ratio = total / max(1.0, displayed)
        low_display = displayed <= args.max_display_size
        qualifies = low_display and ratio >= args.min_trade_display_ratio
        if not qualifies:
            continue
        candidates.append(
            {
                "hidden_side": hidden_side,
                "hidden_price_tick": tick,
                "hidden_price": tick * TICK_SIZE,
                "hidden_trade_volume": total,
                "hidden_buy_volume": buy,
                "hidden_sell_volume": sell,
                "hidden_majority_share": share,
                "hidden_display_max": displayed,
                "hidden_display_seen": bool(display_seen.get((passive_side, tick), False)),
                "hidden_trade_display_ratio": ratio,
                "hidden_prints": int(values["prints"]),
                "hidden_score": ratio * math.sqrt(total),
            }
        )
    if not candidates:
        return {
            "hidden_side": "",
            "hidden_price_tick": "",
            "hidden_price": "",
            "hidden_trade_volume": 0.0,
            "hidden_buy_volume": 0.0,
            "hidden_sell_volume": 0.0,
            "hidden_majority_share": 0.0,
            "hidden_display_max": 0.0,
            "hidden_display_seen": False,
            "hidden_trade_display_ratio": 0.0,
            "hidden_prints": 0,
            "hidden_score": 0.0,
        }
    return max(candidates, key=lambda item: float(item["hidden_score"]))


def enrich_rows(rows: list[dict[str, str]], args: argparse.Namespace) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for spec, session_rows in group_by_session(rows).items():
        print(f"hidden liquidity replay {spec.label} anchors={len(session_rows)}", flush=True)
        ticks = load_ticks(spec, session_rows, args)
        snapshots = load_snapshots(spec, session_rows, args)
        for row in session_rows:
            anchor_ts = parse_iso_ts(row["anchor_ts"])
            anchor_us = us(anchor_ts)
            min_tick = int(row["min_tick"])
            max_tick = int(row["max_tick"])
            display_max, display_seen, snapshot_count = display_max_by_price(
                snapshots,
                anchor_us,
                min_tick,
                max_tick,
                args,
            )
            trade_by_price = aggregate_trade_by_price(ticks, anchor_us, min_tick, max_tick, args)
            candidate = best_hidden_candidate(trade_by_price, display_max, display_seen, args)
            owner_side = row.get("owner_side") or row.get("band_side") or ""
            alignment = hidden_alignment(str(candidate["hidden_side"]), owner_side)
            outcome = outcome_group(row.get("lifecycle_label", ""))
            enriched: dict[str, object] = dict(row)
            enriched.update(candidate)
            enriched.update(
                {
                    "source_clean": clean_source(row),
                    "owner_side_for_hidden": owner_side,
                    "hidden_alignment": alignment,
                    "hidden_read": hidden_read(alignment, outcome),
                    "outcome_group": outcome,
                    "hidden_snapshot_count": snapshot_count,
                    "hidden_trade_price_count": len(trade_by_price),
                    "hidden_proxy_present": alignment != "no_hidden",
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


def example_rows(rows: list[dict[str, object]], label: str, limit: int = 16) -> list[str]:
    selected = [row for row in rows if row.get("hidden_alignment") == label][:limit]
    lines = [
        f"### {label}",
        "",
        "| fixture | time | anchor | owner/hidden | lifecycle | brick | vol | display | ratio | seen |",
        "| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | --- |",
    ]
    for row in selected:
        lines.append(
            f"| `{row.get('fixture_id')}` | {row.get('anchor_ny')} | "
            f"{row.get('anchor_class')}@{row.get('contacted_price', row.get('band_price'))} | "
            f"{row.get('owner_side_for_hidden')}/{row.get('hidden_side')} | "
            f"`{row.get('lifecycle_label')}` | `{row.get('brick_label_2s', '')}` | "
            f"{float(row.get('hidden_trade_volume') or 0):.0f} | "
            f"{float(row.get('hidden_display_max') or 0):.0f} | "
            f"{float(row.get('hidden_trade_display_ratio') or 0):.1f} | "
            f"{row.get('hidden_display_seen')} |"
        )
    if not selected:
        lines.append("| n/a | n/a | n/a | n/a | n/a | n/a | 0 | 0 | 0 | n/a |")
    return lines


def write_report(path: Path, rows: list[dict[str, object]], source_count: int, args: argparse.Namespace) -> None:
    hidden = [row for row in rows if row.get("hidden_proxy_present") is True]
    displayed_seen = [row for row in hidden if row.get("hidden_display_seen") is True]
    tests = [row for row in rows if row.get("anchor_class") == "band_test"]
    failures = [row for row in rows if row.get("anchor_class") == "band_failure"]
    conversions = [row for row in rows if row.get("anchor_class") == "consumed_conversion"]
    primary = [row for row in rows if row.get("curated_bucket") == "primary_dev"]
    lines = [
        "# Hidden Liquidity Lifecycle Probe",
        "",
        "Fixture-scoped Thesis 9 pass. This is a snapshot/tape hidden-liquidity proxy, not proof of hidden order refresh.",
        "",
        "## Coverage",
        "",
        f"- source rows: `{source_count}`",
        f"- analyzed rows: `{len(rows)}`",
        f"- hidden-proxy rows: `{len(hidden)}`",
        f"- hidden-proxy rows with passive display observed in snapshots: `{len(displayed_seen)}`",
        f"- band tests: `{len(tests)}`",
        f"- band failures: `{len(failures)}`",
        f"- consumed conversions: `{len(conversions)}`",
        f"- source: `{args.source}`",
        "",
        "## Outcome By Hidden Alignment",
        "",
    ]
    lines.extend(count_table(rows, ["hidden_alignment"], "outcome_group"))
    lines.extend(["", "## Lifecycle By Hidden Alignment", ""])
    lines.extend(count_table(rows, ["hidden_alignment"], "lifecycle_label"))
    lines.extend(["", "## Brick Label By Hidden Alignment", ""])
    lines.extend(count_table(rows, ["hidden_alignment"], "brick_label_2s"))
    lines.extend(["", "## Band Tests Only", ""])
    lines.extend(count_table(tests, ["hidden_alignment"], "lifecycle_label"))
    lines.extend(["", "## Band Failures Only", ""])
    lines.extend(count_table(failures, ["hidden_alignment"], "lifecycle_label"))
    lines.extend(["", "## Consumed Conversions Only", ""])
    lines.extend(count_table(conversions, ["hidden_alignment"], "lifecycle_label"))
    lines.extend(["", "## Primary Development Bucket", ""])
    lines.extend(count_table(primary, ["fixture_id", "hidden_alignment"], "lifecycle_label"))
    lines.extend(["", "## Metric Sketch", ""])
    for label in ["aligned_hidden", "opposed_hidden", "no_hidden"]:
        subset = [row for row in rows if row.get("hidden_alignment") == label]
        lines.append(f"- `{label}` hidden volume: {numeric_summary(subset, 'hidden_trade_volume')}")
        lines.append(f"- `{label}` hidden display max: {numeric_summary(subset, 'hidden_display_max')}")
        lines.append(f"- `{label}` hidden trade/display ratio: {numeric_summary(subset, 'hidden_trade_display_ratio')}")
        lines.append(f"- `{label}` move-away net aligned ticks: {numeric_summary(subset, 'moveaway_price_net_aligned_ticks')}")
    lines.extend(["", "## Example Rows", ""])
    for label in ["aligned_hidden", "opposed_hidden", "no_hidden"]:
        lines.extend(example_rows(rows, label))
        lines.append("")
    lines.extend(
        [
            "## Parameters",
            "",
            f"- tick_before_sec / tick_after_sec: `{args.tick_before_sec}` / `{args.tick_after_sec}`",
            f"- display_before_sec / display_after_sec: `{args.display_before_sec}` / `{args.display_after_sec}`",
            f"- band_expand_ticks: `{args.band_expand_ticks}`",
            f"- min_trade_volume: `{args.min_trade_volume}`",
            f"- majority_share: `{args.majority_share}`",
            f"- max_display_size: `{args.max_display_size}`",
            f"- min_trade_display_ratio: `{args.min_trade_display_ratio}`",
            "",
            "## Guardrails",
            "",
            "- Snapshot cadence can miss displayed refresh. Treat this as a broad proxy, not exchange-native hidden-size attribution.",
            "- A high trade/display ratio can also mean thin support under attack, not hidden defense.",
            "- Aggressor majority defines the passive hidden side: buy-majority implies hidden supply; sell-majority implies hidden demand.",
            "- Lifecycle labels remain the primary outcome.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=str(DEFAULT_BRICK))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--tag", default="20260623_20260626")
    parser.add_argument("--fixture-id", action="append", default=[])
    parser.add_argument("--bucket", action="append", default=[])
    parser.add_argument("--anchor-class", action="append", default=[])
    parser.add_argument("--lifecycle-label", action="append", default=[])
    parser.add_argument("--clean-only", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--capture-root", default=MARKET_RECORDER_ROOT)
    parser.add_argument("--tick-before-sec", type=int, default=1)
    parser.add_argument("--tick-after-sec", type=int, default=5)
    parser.add_argument("--display-before-sec", type=int, default=2)
    parser.add_argument("--display-after-sec", type=int, default=5)
    parser.add_argument("--band-expand-ticks", type=int, default=1)
    parser.add_argument("--min-trade-volume", type=float, default=20.0)
    parser.add_argument("--majority-share", type=float, default=0.65)
    parser.add_argument("--max-display-size", type=float, default=6.0)
    parser.add_argument("--min-trade-display-ratio", type=float, default=4.0)
    args = parser.parse_args()

    del args.capture_root  # capture_loader uses MARKET_RECORDER_ROOT today; retained for provenance.
    source_rows = load_source(Path(args.source), args)
    rows = enrich_rows(source_rows, args)
    out_dir = Path(args.output_dir)
    csv_path = out_dir / f"hidden_liquidity_lifecycle_probe_{args.tag}.csv"
    report_path = out_dir / f"hidden_liquidity_lifecycle_probe_{args.tag}.md"
    write_csv(csv_path, rows)
    write_report(report_path, rows, len(source_rows), args)
    print(f"source rows={len(source_rows)} hidden rows={sum(1 for row in rows if row.get('hidden_proxy_present') is True)}")
    print(f"wrote {csv_path}")
    print(f"wrote {report_path}")


if __name__ == "__main__":
    main()
