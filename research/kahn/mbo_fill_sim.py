"""Queue-aware passive fill simulation from MBO + 1Hz depth snapshots.

The scale-in and harvest questions are both really one question: *if I rest an
order here, do I actually get filled, and how much?* Aggregate depth alone
cannot answer it, because it cannot say how much of the size ahead of you left
by cancel versus by fill. MBO can, because every removal is attributable
against the trade tape at 5ms resolution.

Model
-----
An order joining the back of the queue at price P at time t0 must wait for the
size already resting there to leave. Two bounds bracket the truth:

  conservative - only FILLS ahead of us count. We reach the front after
                 cumulative attributed fill volume at P exceeds the resting
                 depth. Assumes nobody ahead of us ever cancels. This is the
                 number to plan with.
  optimistic   - every removal counts, fills and cancels alike. Assumes all
                 cancellation happened in front of us. Upper bound.

Queue depth comes from the 1Hz snapshots, NOT from replaying the event stream.
About 1.5% of quotes never emit a close, so an open-minus-close reconstruction
accumulates phantom size: at ESU6 7777.00 on 2026-08-28 11:21 the replay said
186 lots resting where the snapshot said 59.

Assumes our own order does not change others' behaviour -- reasonable at
campaign size (2-20 lots) against ES levels turning over thousands, but it is
an assumption, and it flatters us slightly.
"""
from __future__ import annotations

from dataclasses import dataclass

import polars as pl

from mbo_level_features import (
    FILL_BUCKET_US, Window, attribute_removals, load_book, load_ticks,
    ny_str, snapshot_depth,
)


@dataclass(frozen=True)
class RestingOrder:
    price: float
    side: int          # +1 rest on the bid (buy), -1 rest on the ask (sell)
    quantity: int
    placed_us: int
    ttl_us: int | None = None


@dataclass
class FillResult:
    order: RestingOrder
    queue_ahead: float | None       # None => outside snapshot depth range
    level_fill_volume: float
    level_removed_volume: float
    cleared_us: int | None          # conservative
    filled: float                   # conservative
    first_fill_us: int | None
    cleared_opt_us: int | None      # optimistic
    filled_opt: float

    @property
    def fill_ratio(self) -> float:
        return self.filled / self.order.quantity if self.order.quantity else 0.0


class FillSimulator:
    """Replays one window once, then answers many resting-order questions."""

    def __init__(self, w: Window, pad_before_min: float = 5.0,
                 pad_after_min: float = 5.0):
        self.w = w
        padded = w.padded(pad_before_min, pad_after_min)
        self.book = load_book(padded)
        self.ticks = load_ticks(padded)
        attributed = attribute_removals(self.book, self.ticks)
        self.level_flow = (
            attributed.select(
                (pl.col("b") * FILL_BUCKET_US).alias("t"),
                "price", "side", "fill_size", "removed_size",
            )
            .filter((pl.col("fill_size") > 0) | (pl.col("removed_size") > 0))
            .sort("t")
        )
        self.depth = snapshot_depth(padded)

    def queue_ahead(self, price: float, side: int, at_us: int) -> float | None:
        """Resting size at (price, side) from the most recent snapshot <= at_us.

        Snapshots carry 30 levels a side, so a rung placed far from the market
        has no depth row yet. Fall back to the FIRST snapshot after `at_us` in
        which the level appears. That overstates the queue ahead -- some of
        that size joined after we did, and would be behind us -- so it is a
        conservative substitute, not an equivalent.
        """
        at = self.depth.filter(
            (pl.col("price") == price) & (pl.col("side") == side)
            & (pl.col("t") <= at_us)
        )
        if at.height:
            return float(at.sort("t")["depth"][-1])
        later = self.depth.filter(
            (pl.col("price") == price) & (pl.col("side") == side)
            & (pl.col("t") > at_us)
        )
        if later.height:
            return float(later.sort("t")["depth"][0])
        return None

    def simulate(self, order: RestingOrder) -> FillResult:
        end = order.placed_us + order.ttl_us if order.ttl_us else self.w.t1
        ahead = self.queue_ahead(order.price, order.side, order.placed_us)
        flow = (
            self.level_flow.filter(
                (pl.col("price") == order.price)
                & (pl.col("side") == order.side)
                & (pl.col("t") > order.placed_us)
                & (pl.col("t") <= end)
            )
            .sort("t")
            .with_columns(
                pl.col("fill_size").cum_sum().alias("cum_fill"),
                pl.col("removed_size").cum_sum().alias("cum_removed"),
            )
        )
        lvl_fill = float(flow["fill_size"].sum()) if flow.height else 0.0
        lvl_rem = float(flow["removed_size"].sum()) if flow.height else 0.0
        if ahead is None or not flow.height:
            return FillResult(order, ahead, lvl_fill, lvl_rem,
                              None, 0.0, None, None, 0.0)

        def after(col: str) -> tuple[int | None, float, int | None]:
            hit = flow.filter(pl.col(col) >= ahead)
            if not hit.height:
                return None, 0.0, None
            t_clear = int(hit["t"][0])
            rest = flow.filter(pl.col("t") > t_clear)
            got = min(float(rest["fill_size"].sum()), float(order.quantity)) \
                if rest.height else 0.0
            first = int(rest.filter(pl.col("fill_size") > 0)["t"][0]) \
                if rest.filter(pl.col("fill_size") > 0).height else None
            return t_clear, got, first

        c_clear, c_filled, c_first = after("cum_fill")
        o_clear, o_filled, _ = after("cum_removed")
        return FillResult(order, ahead, lvl_fill, lvl_rem,
                          c_clear, c_filled, c_first, o_clear, o_filled)

    def ladder(self, orders: list[RestingOrder]) -> list[FillResult]:
        return [self.simulate(o) for o in orders]


def report(results: list[FillResult], label: str) -> tuple[float, float, float, float]:
    """Print the ladder table; return (cons_qty, cons_avg, opt_qty, opt_avg)."""
    print(f"\n## {label}")
    print(f"{'price':>9} {'qty':>4} {'placed':>9} {'ahead':>6} {'lvlFill':>8} "
          f"{'lvlRem':>8} {'clear':>9} {'fill':>5} | {'optClear':>9} {'optFill':>7}")
    ct = cn = ot = on = 0.0
    for r in results:
        o = r.order
        print(f"{o.price:9.2f} {o.quantity:4d} {ny_str(o.placed_us):>9} "
              f"{(r.queue_ahead if r.queue_ahead is not None else -1):6.0f} "
              f"{r.level_fill_volume:8.0f} {r.level_removed_volume:8.0f} "
              f"{ny_str(r.cleared_us) if r.cleared_us else '-':>9} {r.filled:5.0f} | "
              f"{ny_str(r.cleared_opt_us) if r.cleared_opt_us else '-':>9} "
              f"{r.filled_opt:7.0f}")
        ct += r.filled; cn += r.filled * o.price
        ot += r.filled_opt; on += r.filled_opt * o.price
    ca = cn / ct if ct else 0.0
    oa = on / ot if ot else 0.0
    print(f"{'TOTAL':>9} {'':4} {'':9} {'':6} {'':8} {'':8} {'':9} {ct:5.0f} "
          f"avg={ca:.4f} | {'':9} {ot:7.0f} avg={oa:.4f}")
    return ct, ca, ot, oa
