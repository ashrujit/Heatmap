"""Summarize order outcomes from an episode_exec_lob_probe output directory."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta
from pathlib import Path


TIME_FMT = "%Y-%m-%d %H:%M:%S.%f"
BAR_TIME_FMT = "%Y-%m-%d %H:%M:%S"


FIELDS = [
    "episode_id",
    "ts_et",
    "role",
    "side",
    "reason",
    "resolution",
    "root_object_id",
    "price_lo",
    "price_hi",
    "fill_ts_et",
    "fill_avg_price",
    "fill_qty",
    "flatten_ts_et",
    "flatten_reason",
    "flatten_fill_price",
    "flatten_pnl_pts",
    "fav_2m",
    "adv_2m",
    "fav_5m",
    "adv_5m",
    "fav_10m",
    "adv_10m",
    "fav_episode",
    "adv_episode",
    "book_side_start",
    "book_side_end_2s",
    "book_side_end_5s",
    "book_side_end_10s",
    "book_opp_start",
    "book_opp_end_2s",
    "book_attack_2s",
    "book_attack_5s",
    "book_repl_2s",
    "book_repl_5s",
    "book_repl_10s",
    "book_rr_2s",
    "book_rr_5s",
    "book_rr_10s",
    "churn_label",
    "churn_subtype",
    "churn_score",
    "two_sided_fail",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def parse_time(value: str) -> datetime:
    value = value.strip()
    if "." not in value:
        return datetime.strptime(value, BAR_TIME_FMT)
    return datetime.strptime(value, TIME_FMT)


def fnum(value: str) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def signed_path(side: str, fill: float, high: float, low: float) -> tuple[float, float]:
    if side == "Long":
        return high - fill, fill - low
    if side == "Short":
        return fill - low, high - fill
    return 0.0, 0.0


def weighted_fill(fills: list[dict[str, str]]) -> tuple[str, float | None, float]:
    total_qty = 0.0
    total_px = 0.0
    first_ts = ""
    for fill in fills:
        qty = fnum(fill.get("quantity", "")) or fnum(fill.get("filled_quantity", "")) or 0.0
        px = fnum(fill.get("price", "")) or fnum(fill.get("fill_price", ""))
        if px is None or qty <= 0:
            continue
        if not first_ts:
            first_ts = fill.get("ts_et", "")
        total_qty += qty
        total_px += px * qty
    if total_qty <= 0:
        return first_ts, None, 0.0
    return first_ts, total_px / total_qty, total_qty


def path_for_bars(
    bars: list[dict[str, str]],
    episode_id: str,
    start: datetime,
    fill: float,
    side: str,
    horizon_s: int | None,
) -> tuple[float | str, float | str]:
    end = start + timedelta(seconds=horizon_s) if horizon_s is not None else None
    highs: list[float] = []
    lows: list[float] = []
    for bar in bars:
        if bar.get("episode_id") != episode_id:
            continue
        ts = parse_time(bar["bar_start_et"])
        if ts < start:
            continue
        if end is not None and ts > end:
            continue
        high = fnum(bar.get("high", ""))
        low = fnum(bar.get("low", ""))
        if high is not None and low is not None:
            highs.append(high)
            lows.append(low)
    if not highs or not lows:
        return "", ""
    fav, adv = signed_path(side, fill, max(highs), min(lows))
    return round(fav, 2), round(adv, 2)


def find_book_anchor(book_rows: list[dict[str, str]], order: dict[str, str]) -> dict[str, str] | None:
    source = f"order_submit:{order.get('role', '')}"
    for row in book_rows:
        if row.get("episode_id") != order.get("episode_id"):
            continue
        if row.get("ts_et") != order.get("ts_et"):
            continue
        if row.get("source") == source:
            return row
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe-dir", required=True, type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument(
        "--reason",
        action="append",
        default=["direct_conversion_retest"],
        help="Order-submit reason to include; repeatable.",
    )
    args = parser.parse_args()

    probe_dir = args.probe_dir
    events = read_csv(probe_dir / "ear_events.csv")
    bars = read_csv(probe_dir / "bars_5s.csv")
    book_rows = read_csv(probe_dir / "book_anchors.csv")
    churn_rows = {
        row["episode_id"]: row
        for row in read_csv(probe_dir / "churn_envelope_audit.csv")
    }

    out_rows: list[dict[str, object]] = []
    order_rows = [
        row
        for row in events
        if row.get("event") == "order_submit"
        and row.get("reason") in set(args.reason)
    ]

    for order in order_rows:
        ts = parse_time(order["ts_et"])
        side = order.get("side", "")
        qty = fnum(order.get("quantity", "")) or 0.0
        later_events = [
            row
            for row in events
            if row.get("episode_id") == order.get("episode_id")
            and row.get("ts_et")
            and parse_time(row["ts_et"]) >= ts
        ]
        fills = []
        for row in later_events:
            if row.get("event") != "trade_fill" or row.get("side") != side:
                continue
            if (parse_time(row["ts_et"]) - ts).total_seconds() > 5:
                continue
            fills.append(row)
            _, _, fill_qty = weighted_fill(fills)
            if fill_qty >= qty:
                break
        fill_ts, fill_avg, fill_qty = weighted_fill(fills)

        flatten = next((row for row in later_events if row.get("event") == "flatten_result"), None)
        flatten_fill = None
        flatten_ts = ""
        flatten_reason = ""
        flatten_pnl = ""
        if flatten is not None:
            flatten_ts = flatten.get("ts_et", "")
            flatten_reason = flatten.get("reason", "")
            flat_time = parse_time(flatten_ts)
            opposite = "Short" if side == "Long" else "Long"
            flat_fills = [
                row
                for row in later_events
                if row.get("event") == "trade_fill"
                and row.get("side") == opposite
                and parse_time(row["ts_et"]) >= flat_time
                and (parse_time(row["ts_et"]) - flat_time).total_seconds() <= 5
            ]
            _, flatten_fill, _ = weighted_fill(flat_fills)
            if flatten_fill is not None and fill_avg is not None:
                flatten_pnl = round(
                    (flatten_fill - fill_avg) if side == "Long" else (fill_avg - flatten_fill),
                    2,
                )

        book = find_book_anchor(book_rows, order) or {}
        churn = churn_rows.get(order.get("episode_id", ""), {})

        row: dict[str, object] = {
            "episode_id": order.get("episode_id", ""),
            "ts_et": order.get("ts_et", ""),
            "role": order.get("role", ""),
            "side": side,
            "reason": order.get("reason", ""),
            "resolution": order.get("resolution", ""),
            "root_object_id": order.get("root_object_id", ""),
            "price_lo": order.get("root_min_price", ""),
            "price_hi": order.get("root_max_price", ""),
            "fill_ts_et": fill_ts,
            "fill_avg_price": round(fill_avg, 2) if fill_avg is not None else "",
            "fill_qty": fill_qty,
            "flatten_ts_et": flatten_ts,
            "flatten_reason": flatten_reason,
            "flatten_fill_price": round(flatten_fill, 2) if flatten_fill is not None else "",
            "flatten_pnl_pts": flatten_pnl,
            "churn_label": churn.get("churn_label", ""),
            "churn_subtype": churn.get("churn_subtype", ""),
            "churn_score": churn.get("churn_score", ""),
            "two_sided_fail": churn.get("two_sided_fail", ""),
        }

        if fill_avg is not None and fill_ts:
            fill_time = parse_time(fill_ts)
            for label, horizon_s in [("2m", 120), ("5m", 300), ("10m", 600), ("episode", None)]:
                fav, adv = path_for_bars(
                    bars,
                    str(order.get("episode_id", "")),
                    fill_time,
                    fill_avg,
                    side,
                    horizon_s,
                )
                row[f"fav_{label}"] = fav
                row[f"adv_{label}"] = adv
        else:
            for label in ["2m", "5m", "10m", "episode"]:
                row[f"fav_{label}"] = ""
                row[f"adv_{label}"] = ""

        for dest, src in [
            ("book_side_start", "side_start"),
            ("book_side_end_2s", "side_end_2s"),
            ("book_side_end_5s", "side_end_5s"),
            ("book_side_end_10s", "side_end_10s"),
            ("book_opp_start", "opp_start"),
            ("book_opp_end_2s", "opp_end_2s"),
            ("book_attack_2s", "attack_vol_2s"),
            ("book_attack_5s", "attack_vol_5s"),
            ("book_repl_2s", "replenishment_2s"),
            ("book_repl_5s", "replenishment_5s"),
            ("book_repl_10s", "replenishment_10s"),
            ("book_rr_2s", "reload_ratio_2s"),
            ("book_rr_5s", "reload_ratio_5s"),
            ("book_rr_10s", "reload_ratio_10s"),
        ]:
            row[dest] = book.get(src, "")

        out_rows.append(row)

    out = args.out or (probe_dir / "direct_retest_outcomes.csv")
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(out_rows)
    print(f"wrote {out} rows={len(out_rows)}")


if __name__ == "__main__":
    main()
