"""Volatility/liquidity urgency state at direct-conversion confirmation.

Question is deliberately NOT "will this event succeed". Prior passes established
that nothing measurable at the fight predicts the resolution. This asks the
execution question instead: at the moment a conversion confirms, does the
volatility/liquidity state tell us whether *we* should act now or wait?

Framing follows the stochastic-liquidity execution literature (Almgren 2012;
Souza & Thamsten 2021, arXiv:2101.02731). An agent holding inventory pays a
power-law impact cost to trade fast and an inventory-risk cost to trade slow,
with both coefficients driven by a common latent factor. The characteristic
Almgren-Chriss urgency scale is sqrt(gamma * sigma^2 / eta): volatility over
root-impact. So the state variable is

    U = sigma_hat / sqrt(lambda_hat)

with sigma_hat a subsampled realized volatility and lambda_hat a Kyle-style
price-impact coefficient, both estimated causally on the window ENDING at
confirmation.

The target is a race, decided strictly after confirmation: does price offer a
materially better entry before it runs away? That maps directly onto stand-back
versus get-in-now, and unlike event survival it does not require predicting the
resolution.

Tick-only by construction. Book resilience (the "reloading" term) is a separate,
more expensive pass and is deliberately not bundled here: if the tick-side index
carries nothing, the book pass is not worth running.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import datetime as dt
import math
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from _paths import OUTPUT_ROOT

from capture_loader import load_capture_window, tick_columns, NY  # noqa: E402
from ear_rails import load_rails  # noqa: E402

TICK_SIZE = 0.25
DEFAULT_EVENTS = Path.home() / "Documents" / "ExecAssistantRuntime" / "events.jsonl"

# Estimation window ending at confirmation. 60s balances estimator noise against
# regime staleness; lambda in particular is very noisy below ~30s.
EST_WINDOW_S = 60.0
BIN_S = 1.0

# Race thresholds in points. 1.0 and 2.0 points = 4 and 8 ticks.
RACE_LEVELS = (1.0, 2.0)
RACE_HORIZON_S = 120.0


@dataclass
class State:
    sigma: float = math.nan          # realized vol, points per sqrt(minute)
    lam: float = math.nan            # points per contract
    urgency: float = math.nan        # sigma / sqrt(lambda)
    aggr_rate: float = math.nan      # signed contracts per second
    aggr_abs_rate: float = math.nan  # total contracts per second
    trades: int = 0
    bins_used: int = 0


def realized_vol(times: list[int], prices: list[float], lo_us: int, hi_us: int) -> float:
    """Subsampled realized volatility on 1s grid, scaled to points/sqrt(min).

    Sampling on a fixed clock grid rather than per trade is the cheap defence
    against microstructure noise inflating RV (cf. Gatheral & Oomen 2010).
    """
    grid: list[float] = []
    t = lo_us
    while t <= hi_us:
        i = bisect.bisect_right(times, t) - 1
        if i >= 0:
            grid.append(prices[i])
        t += int(BIN_S * 1_000_000)
    if len(grid) < 5:
        return math.nan
    rets = [grid[i + 1] - grid[i] for i in range(len(grid) - 1)]
    var = sum(r * r for r in rets)
    per_sec = var / max(len(rets) * BIN_S, 1e-9)
    return math.sqrt(max(per_sec, 0.0) * 60.0)


def kyle_lambda(
    times: list[int],
    prices: list[float],
    sizes: list[float],
    signs: list[int],
    lo_us: int,
    hi_us: int,
) -> float:
    """Price move per unit signed volume, regressed on a 1s grid through origin.

    Slope through the origin rather than OLS with intercept: a drift term would
    absorb exactly the directional pressure we are trying to price.
    """
    i0 = bisect.bisect_left(times, lo_us)
    i1 = bisect.bisect_right(times, hi_us)
    if i1 - i0 < 20:
        return math.nan
    step = int(BIN_S * 1_000_000)
    bins: dict[int, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])  # signed vol, first, last
    for k in range(i0, i1):
        b = (times[k] - lo_us) // step
        rec = bins[b]
        rec[0] += sizes[k] * signs[k]
        if rec[1] == 0.0:
            rec[1] = prices[k]
        rec[2] = prices[k]
    num = 0.0
    den = 0.0
    used = 0
    for _, (q, first, last) in sorted(bins.items()):
        if first == 0.0:
            continue
        dp = last - first
        num += q * dp
        den += q * q
        used += 1
    if used < 10 or den <= 1e-9:
        return math.nan
    lam = num / den
    # A negative estimate means price moved against the aggressor over the
    # window - real, but not an impact coefficient. Floor it rather than
    # propagate a negative into a square root.
    return lam if lam > 1e-9 else math.nan


def measure_state(
    times: list[int],
    prices: list[float],
    sizes: list[float],
    signs: list[int],
    t0_us: int,
) -> State:
    lo = t0_us - int(EST_WINDOW_S * 1_000_000)
    st = State()
    i0 = bisect.bisect_left(times, lo)
    i1 = bisect.bisect_right(times, t0_us)
    st.trades = i1 - i0
    if st.trades < 20:
        return st
    st.sigma = realized_vol(times, prices, lo, t0_us)
    st.lam = kyle_lambda(times, prices, sizes, signs, lo, t0_us)
    if not math.isnan(st.sigma) and not math.isnan(st.lam):
        st.urgency = st.sigma / math.sqrt(st.lam)
    signed = sum(sizes[k] * signs[k] for k in range(i0, i1))
    total = sum(sizes[k] for k in range(i0, i1))
    st.aggr_rate = signed / EST_WINDOW_S
    st.aggr_abs_rate = total / EST_WINDOW_S
    return st


def race_outcome(
    times: list[int],
    prices: list[float],
    t0_us: int,
    favorable_sign: int,
    level_pts: float,
) -> tuple[str, float, float]:
    """Which comes first after confirmation: a better entry, or a runaway?

    `favorable_sign` is +1 when the winning side profits from price rising.
    A move against that sign offers a better entry to someone still waiting.
    """
    i0 = bisect.bisect_right(times, t0_us)
    if i0 >= len(times):
        return "none", math.nan, math.nan
    p0 = prices[i0 - 1] if i0 > 0 else prices[0]
    hi_us = t0_us + int(RACE_HORIZON_S * 1_000_000)
    best_improve = 0.0
    best_run = 0.0
    verdict = "neither"
    for k in range(i0, len(times)):
        if times[k] > hi_us:
            break
        move = (prices[k] - p0) * favorable_sign
        if move > best_run:
            best_run = move
        if -move > best_improve:
            best_improve = -move
        if verdict == "neither":
            if -move >= level_pts:
                verdict = "better_entry_first"
            elif move >= level_pts:
                verdict = "runaway_first"
    return verdict, best_improve, best_run


FIELDS = [
    "date",
    "band_id",
    "owned_et",
    "side",
    "first_test_verdict",
    "sigma",
    "lambda",
    "urgency",
    "aggr_rate",
    "aggr_abs_rate",
    "aggr_aligned",
    "trades_60s",
    "race_1pt",
    "race_2pt",
    "max_improve_pts",
    "max_runaway_pts",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", default=str(DEFAULT_EVENTS))
    parser.add_argument(
        "--dates",
        default="2026-07-17,2026-07-20,2026-07-21,2026-07-22,2026-07-23,2026-07-24",
    )
    parser.add_argument("--symbol-dir", default="NQU6")
    parser.add_argument(
        "--out-dir", default=str(OUTPUT_ROOT / "conversion_urgency")
    )
    args = parser.parse_args()

    dates = [d.strip() for d in args.dates.split(",") if d.strip()]
    rails = load_rails(Path(args.events), set(dates), {"Consumed"})
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    for day in dates:
        day_rails = [r for r in rails if r.date == day]
        if not day_rails:
            continue
        start = dt.datetime.fromisoformat(day).replace(tzinfo=NY)
        end = start + dt.timedelta(days=1)
        ticks = load_capture_window("ticks", args.symbol_dir, start, end, tick_columns())
        times = ticks["timestamp_us"].to_list()
        prices = ticks["price"].to_list()
        sizes = ticks["size"].to_list()
        signs = ticks["aggressor_sign"].to_list()

        for rail in day_rails:
            t0 = int(rail.owned_utc.timestamp() * 1_000_000)
            # Supply rail wins when price falls; Demand rail wins when it rises.
            fav = -1 if rail.side == "Supply" else 1
            st = measure_state(times, prices, sizes, signs, t0)
            verdict, _, _ = race_outcome(times, prices, t0, fav, RACE_LEVELS[0])
            verdict2, imp, run = race_outcome(times, prices, t0, fav, RACE_LEVELS[1])
            rows.append(
                {
                    "date": day,
                    "band_id": rail.band_id,
                    "owned_et": rail.owned_et,
                    "side": rail.side,
                    "first_test_verdict": rail.first_test()[0],
                    "sigma": round(st.sigma, 4) if not math.isnan(st.sigma) else "",
                    "lambda": round(st.lam, 6) if not math.isnan(st.lam) else "",
                    "urgency": round(st.urgency, 4) if not math.isnan(st.urgency) else "",
                    "aggr_rate": round(st.aggr_rate, 3) if not math.isnan(st.aggr_rate) else "",
                    "aggr_abs_rate": round(st.aggr_abs_rate, 3)
                    if not math.isnan(st.aggr_abs_rate)
                    else "",
                    # Aggression aligned with the winning side, in contracts/sec.
                    "aggr_aligned": round(st.aggr_rate * fav, 3)
                    if not math.isnan(st.aggr_rate)
                    else "",
                    "trades_60s": st.trades,
                    "race_1pt": verdict,
                    "race_2pt": verdict2,
                    "max_improve_pts": round(imp, 2) if not math.isnan(imp) else "",
                    "max_runaway_pts": round(run, 2) if not math.isnan(run) else "",
                }
            )
        print(f"{day}: rails={len(day_rails)} ticks={len(times)}", flush=True)

    path = out_dir / "urgency.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    usable = [r for r in rows if r["urgency"] != ""]
    print(f"\nrows={len(rows)} with urgency={len(usable)}")
    if usable:
        vals = sorted(float(r["urgency"]) for r in usable)
        print(f"urgency median={statistics.median(vals):.3f} "
              f"p10={vals[len(vals)//10]:.3f} p90={vals[9*len(vals)//10]:.3f}")
    for key in ("race_1pt", "race_2pt"):
        counts: dict[str, int] = defaultdict(int)
        for r in rows:
            counts[r[key]] += 1
        print(f"{key}: {dict(counts)}")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
