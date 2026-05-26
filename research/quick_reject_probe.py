"""Research-only quick-reject band replay.

This probe models provisional failed-probe bands before they are promoted into
indicator behavior.  A quick reject is intentionally weaker than a failed break:
price probes outside a reference, quickly reclaims, and leaves no active claim
that the larger auction has failed until later business confirms or cancels it.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import math
import os
import sys
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import polars as pl

from capture_loader import add_ny_ts, load_capture_window


try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


NY = ZoneInfo("America/New_York")
TICK_SIZE = 0.25
OUT_DIR = os.path.join(os.path.dirname(__file__), "out")


@dataclass(frozen=True)
class Bar:
    start: dt.datetime
    end: dt.datetime
    open: float
    high: float
    low: float
    close: float
    vol: float
    delta: float
    trades: int


@dataclass
class QuickReject:
    id: int
    source: str
    side: str
    ref_name: str
    ref_price: float
    extreme: float
    band_lo: float
    band_hi: float
    built_at: dt.datetime
    build_bar: dt.datetime
    probe_points: float
    outside_sec: int
    outside_vol: float
    outside_delta: float
    status: str = "ACTIVE"
    cancel_at: dt.datetime | None = None
    cancel_reason: str = ""
    cancel_outside_sec: int = 0
    cancel_outside_vol: float = 0.0
    cancel_close: float = math.nan


@dataclass(frozen=True)
class Reference:
    name: str
    side: str
    price: float
    active_from: dt.datetime


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--date", required=True)
    p.add_argument("--symbol-dir", default="NQM6")
    p.add_argument("--rth-start", default="09:30")
    p.add_argument("--rth-end", default="16:00")
    p.add_argument("--or-min", type=int, default=5)
    p.add_argument("--ib-min", type=int, default=60)
    p.add_argument("--bar-min", type=int, default=5)
    p.add_argument("--local-lookback-bars", type=int, default=3)
    p.add_argument("--min-probe-points", type=float, default=12.0)
    p.add_argument("--reclaim-points", type=float, default=2.0)
    p.add_argument("--quick-max-sec", type=int, default=180)
    p.add_argument("--cancel-min-vol", type=float, default=1200.0)
    p.add_argument("--cancel-min-sec", type=int, default=35)
    p.add_argument("--dedupe-points", type=float, default=4.0)
    p.add_argument("--out-dir", default=OUT_DIR)
    return p.parse_args()


def ny_dt(day: dt.date, hhmm: str) -> dt.datetime:
    hour, minute = [int(part) for part in hhmm.split(":", 1)]
    return dt.datetime(day.year, day.month, day.day, hour, minute, tzinfo=NY)


def ny_label(ts: dt.datetime | None) -> str:
    return "-" if ts is None else ts.astimezone(NY).strftime("%H:%M:%S")


def fmt(value: float) -> str:
    return "-" if not math.isfinite(value) else f"{value:.2f}"


def filter_window(ticks: pl.DataFrame, start: dt.datetime, end: dt.datetime) -> pl.DataFrame:
    return ticks.filter((pl.col("ts") >= start) & (pl.col("ts") < end))


def summarize_bar(ticks: pl.DataFrame, start: dt.datetime, end: dt.datetime) -> Bar | None:
    sub = filter_window(ticks, start, end)
    if sub.height == 0:
        return None
    row = sub.select(
        pl.col("price").first().alias("open"),
        pl.col("price").max().alias("high"),
        pl.col("price").min().alias("low"),
        pl.col("price").last().alias("close"),
        pl.col("size").sum().alias("vol"),
        (pl.col("size") * pl.col("aggressor_sign")).sum().alias("delta"),
        pl.len().alias("trades"),
    ).row(0, named=True)
    return Bar(
        start=start,
        end=end,
        open=float(row["open"]),
        high=float(row["high"]),
        low=float(row["low"]),
        close=float(row["close"]),
        vol=float(row["vol"]),
        delta=float(row["delta"]),
        trades=int(row["trades"]),
    )


def build_bars(ticks: pl.DataFrame, start: dt.datetime, end: dt.datetime, minutes: int) -> list[Bar]:
    bars: list[Bar] = []
    cur = start
    while cur < end:
        nxt = min(end, cur + dt.timedelta(minutes=minutes))
        bar = summarize_bar(ticks, cur, nxt)
        if bar is not None:
            bars.append(bar)
        cur = nxt
    return bars


def duplicate_active(
    active: list[QuickReject],
    side: str,
    ref: float,
    built_at: dt.datetime,
    dedupe_points: float,
) -> bool:
    for q in active:
        if q.side != side or q.status != "ACTIVE":
            continue
        if abs(q.ref_price - ref) <= dedupe_points:
            return True
        if q.built_at == built_at:
            return True
    return False


def reference_set(bars: list[Bar], rth_start: dt.datetime, or_min: int, ib_min: int) -> list[Reference]:
    if not bars:
        return []
    refs: list[Reference] = []
    rth_open = bars[0].open
    open_active = rth_start + dt.timedelta(minutes=or_min)
    refs.append(Reference("OPEN", "LOW", rth_open, open_active))
    refs.append(Reference("OPEN", "HIGH", rth_open, open_active))

    or_end = rth_start + dt.timedelta(minutes=or_min)
    or_bars = [b for b in bars if b.start < or_end]
    if or_bars:
        refs.append(Reference("OR5_LOW", "LOW", min(b.low for b in or_bars), or_end))
        refs.append(Reference("OR5_HIGH", "HIGH", max(b.high for b in or_bars), or_end))

    ib_end = rth_start + dt.timedelta(minutes=ib_min)
    ib_bars = [b for b in bars if b.start < ib_end]
    if ib_bars:
        refs.append(Reference("IB_LOW", "LOW", min(b.low for b in ib_bars), ib_end))
        refs.append(Reference("IB_HIGH", "HIGH", max(b.high for b in ib_bars), ib_end))
    return refs


def run(args: argparse.Namespace) -> tuple[list[QuickReject], list[str]]:
    day = dt.date.fromisoformat(args.date)
    rth_start = ny_dt(day, args.rth_start)
    rth_end = ny_dt(day, args.rth_end)
    ticks = add_ny_ts(load_capture_window("ticks", args.symbol_dir, rth_start, rth_end)).with_row_index("_row")
    bars = build_bars(ticks, rth_start, rth_end, args.bar_min)
    fixed_refs = reference_set(bars, rth_start, args.or_min, args.ib_min)

    qrs: list[QuickReject] = []
    completed_bars: list[Bar] = []
    cancel_seconds: dict[int, set[int]] = {}
    probes: dict[str, dict] = {}
    lines: list[str] = []
    next_id = 1
    probe = args.min_probe_points
    reclaim = args.reclaim_points
    bar_idx = 0
    current_bar: Bar | None = bars[0] if bars else None

    for row in ticks.select("ts", "price", "size", "aggressor_sign").iter_rows(named=True):
        ts = row["ts"]
        price = float(row["price"])
        size = float(row["size"])
        sign = int(row["aggressor_sign"])
        second = int(row["ts"].timestamp())

        while bar_idx < len(bars) and bars[bar_idx].end <= ts:
            completed_bars.append(bars[bar_idx])
            bar_idx += 1
            current_bar = bars[bar_idx] if bar_idx < len(bars) else None

        for qr in qrs:
            if qr.status != "ACTIVE" or ts <= qr.built_at:
                continue
            outside = price < qr.ref_price if qr.side == "LOW" else price > qr.ref_price
            if not outside:
                continue
            qr.cancel_outside_vol += size
            secs = cancel_seconds.setdefault(qr.id, set())
            secs.add(second)
            qr.cancel_outside_sec = len(secs)
            if qr.cancel_outside_vol >= args.cancel_min_vol and qr.cancel_outside_sec >= args.cancel_min_sec:
                qr.status = "CANCELLED"
                qr.cancel_at = ts
                qr.cancel_reason = "accepted outside rejected side"
                qr.cancel_close = price

        refs: list[Reference] = [r for r in fixed_refs if r.active_from <= ts]
        prev = completed_bars[-args.local_lookback_bars :]
        if prev:
            low = min(b.low for b in prev)
            high = max(b.high for b in prev)
            if not any(r.side == "LOW" and abs(r.price - low) <= args.dedupe_points for r in refs):
                refs.append(Reference(f"LOCAL_LOW_{ny_label(prev[-1].end)}", "LOW", low, ts))
            if not any(r.side == "HIGH" and abs(r.price - high) <= args.dedupe_points for r in refs):
                refs.append(Reference(f"LOCAL_HIGH_{ny_label(prev[-1].end)}", "HIGH", high, ts))

        active_keys: set[str] = set()
        for ref in refs:
            key = f"{ref.name}:{ref.side}:{ref.price:.2f}"
            active_keys.add(key)
            state = probes.setdefault(
                key,
                {
                    "source": "LOCAL" if ref.name.startswith("LOCAL") else "REF",
                    "name": ref.name,
                    "side": ref.side,
                    "ref": ref.price,
                    "active": False,
                    "expired": False,
                    "first": None,
                    "extreme": ref.price,
                    "vol": 0.0,
                    "delta": 0.0,
                    "secs": set(),
                },
            )
            state["source"] = "LOCAL" if ref.name.startswith("LOCAL") else "REF"
            state["name"] = ref.name
            state["side"] = ref.side
            state["ref"] = ref.price

            outside = price < ref.price if ref.side == "LOW" else price > ref.price
            if outside:
                if not state["active"]:
                    state["active"] = True
                    state["expired"] = False
                    state["first"] = ts
                    state["extreme"] = price
                    state["vol"] = 0.0
                    state["delta"] = 0.0
                    state["secs"] = set()
                state["extreme"] = min(float(state["extreme"]), price) if ref.side == "LOW" else max(float(state["extreme"]), price)
                state["vol"] = float(state["vol"]) + size
                state["delta"] = float(state["delta"]) + size * sign
                state["secs"].add(second)
                if (ts - state["first"]).total_seconds() > args.quick_max_sec or len(state["secs"]) > args.quick_max_sec:
                    state["expired"] = True
                continue

            if not state["active"]:
                continue

            reclaimed = price >= ref.price + reclaim if ref.side == "LOW" else price <= ref.price - reclaim
            if not reclaimed:
                if (ts - state["first"]).total_seconds() > args.quick_max_sec:
                    state["expired"] = True
                continue

            if (
                not state["expired"]
                and abs(float(state["extreme"]) - ref.price) >= probe
                and len(state["secs"]) <= args.quick_max_sec
                and not duplicate_active(qrs, ref.side, ref.price, ts, args.dedupe_points)
            ):
                extreme = float(state["extreme"])
                qrs.append(
                    QuickReject(
                        id=next_id,
                        source=str(state["source"]),
                        side=ref.side,
                        ref_name=ref.name,
                        ref_price=ref.price,
                        extreme=extreme,
                        band_lo=min(ref.price, extreme),
                        band_hi=max(ref.price, extreme),
                        built_at=ts,
                        build_bar=current_bar.start if current_bar is not None else ts,
                        probe_points=abs(extreme - ref.price),
                        outside_sec=len(state["secs"]),
                        outside_vol=float(state["vol"]),
                        outside_delta=float(state["delta"]),
                    )
                )
                next_id += 1

            state["active"] = False
            state["expired"] = False
            state["vol"] = 0.0
            state["delta"] = 0.0
            state["secs"] = set()

        stale_keys = [k for k in probes if k.startswith("LOCAL") and k not in active_keys]
        for key in stale_keys:
            probes.pop(key, None)

    lines.append(f"Quick-reject replay for {args.date} {args.symbol_dir}")
    lines.append(
        f"rules: probe>={args.min_probe_points:.1f}pts reclaim>={args.reclaim_points:.1f}pts "
        f"quick_sec<={args.quick_max_sec}; cancel if outside vol>={args.cancel_min_vol:.0f} "
        f"and sec>={args.cancel_min_sec}"
    )
    lines.append("")
    lines.append("Built / cancelled / persisted bands")
    lines.append("id status     src   side ref          band              built    cancel   outside          reason")
    for qr in qrs:
        status = "PERSIST" if qr.status == "ACTIVE" else qr.status
        outside = f"{qr.outside_vol:.0f}/{qr.outside_sec}s"
        reason = qr.cancel_reason
        if qr.status == "CANCELLED":
            reason += f" ({qr.cancel_outside_vol:.0f}/{qr.cancel_outside_sec}s C={fmt(qr.cancel_close)})"
        lines.append(
            f"{qr.id:2d} {status:<10} {qr.source:<5} {qr.side:<4} {qr.ref_name:<12} "
            f"{qr.band_lo:8.2f}-{qr.band_hi:<8.2f} {ny_label(qr.built_at):<8} "
            f"{ny_label(qr.cancel_at):<8} {outside:<14} {reason}"
        )

    return qrs, lines


def write_csv(path: str, qrs: list[QuickReject]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "id",
                "status",
                "source",
                "side",
                "ref_name",
                "ref_price",
                "extreme",
                "band_lo",
                "band_hi",
                "built_at",
                "build_bar",
                "probe_points",
                "outside_sec",
                "outside_vol",
                "outside_delta",
                "cancel_at",
                "cancel_reason",
                "cancel_outside_sec",
                "cancel_outside_vol",
                "cancel_close",
            ]
        )
        for q in qrs:
            w.writerow(
                [
                    q.id,
                    "PERSIST" if q.status == "ACTIVE" else q.status,
                    q.source,
                    q.side,
                    q.ref_name,
                    f"{q.ref_price:.2f}",
                    f"{q.extreme:.2f}",
                    f"{q.band_lo:.2f}",
                    f"{q.band_hi:.2f}",
                    q.built_at.isoformat(),
                    q.build_bar.isoformat(),
                    f"{q.probe_points:.2f}",
                    q.outside_sec,
                    f"{q.outside_vol:.0f}",
                    f"{q.outside_delta:.0f}",
                    q.cancel_at.isoformat() if q.cancel_at else "",
                    q.cancel_reason,
                    q.cancel_outside_sec,
                    f"{q.cancel_outside_vol:.0f}",
                    f"{q.cancel_close:.2f}" if math.isfinite(q.cancel_close) else "",
                ]
            )


def main() -> None:
    args = parse_args()
    os.makedirs(args.out_dir, exist_ok=True)
    qrs, lines = run(args)
    base = os.path.join(args.out_dir, f"quick_rejects_{args.date}")
    txt_path = base + ".txt"
    csv_path = base + ".csv"
    text = "\n".join(lines)
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    write_csv(csv_path, qrs)
    print(text)
    print(f"\nwritten: {txt_path}")
    print(f"csv: {csv_path}")


if __name__ == "__main__":
    main()
