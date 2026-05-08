"""
Port of SinglePrints/SessionBuilder.cs into Python, fed from Skurry tick DB.

Goal: reproduce what the live indicator would compute on today's NQ session
(2026-05-08) and check why nothing renders during/after IB. Hypothesis: A's
single-print tails are at session extremes during the active session, so
ExcludeExtremes=true silently kills them.

Runs three scenarios for the active (in-progress) session:
  (A) baseline       — ExcludeExtremes=True  (current default)
  (B) keep_extremes  — ExcludeExtremes=False
  (C) skip_if_<2     — ExcludeExtremes=True, but skip the active session
                        if fewer than 2 closed brackets

Builds bars from ticks at 1-min granularity (chart bar size doesn't matter as
long as bars <= bracket size; SinglePrints walks bar high/low).
"""
from __future__ import annotations

import sqlite3
import datetime as dt
from collections import defaultdict
from dataclasses import dataclass

DB = r"C:\Users\j\Skurry\Skurry\data\ticks.db"
TICK_SIZE = 0.25
BRACKET_MIN = 30
SESSION_DATE_NY = dt.date(2026, 5, 8)
NY = dt.timezone(dt.timedelta(hours=-4))  # EDT in May
SESSION_START_NY = dt.datetime.combine(SESSION_DATE_NY, dt.time(9, 30), tzinfo=NY)
SESSION_END_NY   = dt.datetime.combine(SESSION_DATE_NY, dt.time(16,  0), tzinfo=NY)
SESSION_START_UTC = SESSION_START_NY.astimezone(dt.timezone.utc)
SESSION_END_UTC   = SESSION_END_NY.astimezone(dt.timezone.utc)


@dataclass
class Bar:
    t_utc: dt.datetime
    high: float
    low: float


def load_bars_1m(symbol: str = "NQ") -> list[Bar]:
    con = sqlite3.connect(DB)
    cur = con.cursor()
    start_us = int(SESSION_START_UTC.timestamp() * 1e6)
    end_us   = int(SESSION_END_UTC.timestamp()   * 1e6)
    cur.execute(
        "SELECT timestamp, price FROM ticks "
        "WHERE symbol=? AND timestamp >= ? AND timestamp < ? "
        "ORDER BY timestamp",
        (symbol, start_us, end_us),
    )
    bars: dict[dt.datetime, list[float]] = defaultdict(list)
    for ts_us, price in cur:
        ts = dt.datetime.fromtimestamp(ts_us / 1e6, dt.timezone.utc)
        # 1-min bin keyed by minute-floor
        key = ts.replace(second=0, microsecond=0)
        bars[key].append(price)
    con.close()
    out = []
    for k in sorted(bars):
        prices = bars[k]
        out.append(Bar(t_utc=k, high=max(prices), low=min(prices)))
    return out


def compute_zones(
    bars: list[Bar],
    bracket_size_min: int,
    tick_size: float,
    min_zone_ticks: int,
    exclude_extremes: bool,
):
    total_brackets = max(
        1,
        int(((SESSION_END_UTC - SESSION_START_UTC).total_seconds() / 60.0) / bracket_size_min + 0.999),
    )
    coverage: dict[int, set[int]] = defaultdict(set)  # tickKey -> set of bracket indices
    session_min_tick = None
    session_max_tick = None
    for b in bars:
        if b.t_utc < SESSION_START_UTC or b.t_utc >= SESSION_END_UTC:
            continue
        bidx = int((b.t_utc - SESSION_START_UTC).total_seconds() / 60.0 / bracket_size_min)
        if bidx < 0 or bidx >= total_brackets:
            continue
        lo_tick = round(b.low / tick_size)
        hi_tick = round(b.high / tick_size)
        if lo_tick > hi_tick:
            continue
        if session_min_tick is None or lo_tick < session_min_tick:
            session_min_tick = lo_tick
        if session_max_tick is None or hi_tick > session_max_tick:
            session_max_tick = hi_tick
        for t in range(lo_tick, hi_tick + 1):
            coverage[t].add(bidx)

    if session_min_tick is None:
        return [], (None, None), set()

    singles = sorted(t for t, brs in coverage.items() if len(brs) == 1)

    closed_brackets = set()
    for brs in coverage.values():
        closed_brackets |= brs

    zones = []

    def emit(bottom, top):
        height = top - bottom + 1
        if height < min_zone_ticks:
            return
        if exclude_extremes and (bottom <= session_min_tick or top >= session_max_tick):
            return
        # Find max bracket idx among zone ticks
        max_b = -1
        for t in range(bottom, top + 1):
            for br in coverage.get(t, ()):
                if br > max_b:
                    max_b = br
        zones.append({
            "bottom": bottom,
            "top": top,
            "height_ticks": height,
            "bottom_price": bottom * tick_size,
            "top_price": top * tick_size,
            "max_bracket": max_b,
        })

    if not singles:
        return zones, (session_min_tick, session_max_tick), closed_brackets

    zb = singles[0]
    zt = singles[0]
    for s in singles[1:]:
        if s == zt + 1:
            zt = s
        else:
            emit(zb, zt)
            zb = s
            zt = s
    emit(zb, zt)
    return zones, (session_min_tick, session_max_tick), closed_brackets


def filter_active_session(bars: list[Bar], now_utc: dt.datetime, bracket_size_min: int) -> list[Bar]:
    """Mirrors RebuildZones() active-session bracket exclusion."""
    cur_idx = int((now_utc - SESSION_START_UTC).total_seconds() / 60.0 / bracket_size_min)
    cur_start = SESSION_START_UTC + dt.timedelta(minutes=cur_idx * bracket_size_min)
    return [b for b in bars if b.t_utc < cur_start]


def fmt_zone(z, tick_size):
    return (f"  bracket{z['max_bracket']:>2}  "
            f"{z['bottom_price']:>10.2f} – {z['top_price']:>10.2f}  "
            f"({z['height_ticks']:>3} ticks)")


def run_one(label, bars_for_compute, exclude_extremes, min_zone_ticks=2):
    zones, (lo, hi), closed = compute_zones(
        bars_for_compute,
        bracket_size_min=BRACKET_MIN,
        tick_size=TICK_SIZE,
        min_zone_ticks=min_zone_ticks,
        exclude_extremes=exclude_extremes,
    )
    print(f"\n[{label}]  bars={len(bars_for_compute)}  closed-brackets={sorted(closed)}")
    if lo is not None:
        print(f"  session range so far: {lo*TICK_SIZE:.2f} – {hi*TICK_SIZE:.2f}  "
              f"({hi-lo+1} ticks)")
    print(f"  zones emitted: {len(zones)}")
    for z in zones:
        print(fmt_zone(z, TICK_SIZE))


def main():
    bars_all = load_bars_1m()
    print(f"Total 1-min bars in RTH window: {len(bars_all)}")
    if not bars_all:
        return
    last_bar_t = bars_all[-1].t_utc
    print(f"Last bar (UTC): {last_bar_t}  =  NY {last_bar_t.astimezone(NY)}")

    # Simulate "now" at four points in the day to see how zones evolve.
    sim_times_ny = [
        dt.datetime.combine(SESSION_DATE_NY, dt.time(10, 15), tzinfo=NY),  # mid bracket B (only A closed)
        dt.datetime.combine(SESSION_DATE_NY, dt.time(10, 35), tzinfo=NY),  # bracket C (A,B closed)
        dt.datetime.combine(SESSION_DATE_NY, dt.time(11, 30), tzinfo=NY),  # bracket E (A,B,C,D closed)
        last_bar_t.astimezone(NY),                                          # actual current
    ]

    for sim_ny in sim_times_ny:
        sim_utc = sim_ny.astimezone(dt.timezone.utc)
        if sim_utc < SESSION_START_UTC:
            continue
        feed = filter_active_session(bars_all, sim_utc, BRACKET_MIN)
        print("\n" + "="*72)
        print(f"SIM now = {sim_ny.strftime('%H:%M NY')}  ({sim_utc.isoformat()})")
        run_one("A. baseline (ExcludeExtremes=True)",  feed, exclude_extremes=True)
        run_one("B. ExcludeExtremes=False",            feed, exclude_extremes=False)
        # Proposed fix: skip active session if <2 closed brackets
        cur_idx = int((sim_utc - SESSION_START_UTC).total_seconds() / 60.0 / BRACKET_MIN)
        if cur_idx < 2:
            print("\n[C. skip-if-<2-closed-brackets]  active session skipped (cur_idx=%d)" % cur_idx)
        else:
            run_one("C. skip-if-<2 (same as A here)", feed, exclude_extremes=True)


if __name__ == "__main__":
    main()
