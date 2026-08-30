"""Order-level (MBO) feature builder over MarketRecorder book_events.

MarketRecorder captures true MBO: every resting quote has a `quote_id_hash`,
a monotonic `priority` (queue-entry sequence), and an explicit close row.
That lets us measure things aggregate-depth math cannot:

  * fill vs cancel   - a size removal coincident with a trade at that price is
                       a fill; an unmatched removal is a pull.
  * replenishment    - size arriving from NEW quote ids after consumption.
  * resting vs churn - quote lifetime separates real defenders (seconds) from
                       HFT flicker (median ~120ms in the ES top-of-book band).
  * participant grain- size divided by distinct orders at a level.

`trade_id` is empty on every captured row, so aggressor identity is
unavailable. Passive identity is not, and for absorption/sponsorship reads it
is the better primitive.

CLOCK DOMAINS (verified 2026-08-29, ESU6 2026-08-28)
----------------------------------------------------
`book_events.receipt_timestamp_us` runs a median 895ms BEHIND
`exchange_timestamp_us` (p05 824ms, p95 924ms). The tick tape's
`timestamp_us` is on exchange time. Joining book events to trades on receipt
time therefore misaligns them by nearly a second and yields ~20% attribution;
joining on `exchange_timestamp_us` yields 99.3% at 5ms buckets with zero
residual lag. Always align on exchange time. Receipt time is only useful as a
capture-order/arrival diagnostic.

Outputs a per (price, side, second) feature frame. Read that, not raw events.
"""
from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import polars as pl

NY = ZoneInfo("America/New_York")
CAPTURE_ROOT = os.environ.get(
    "MARKET_RECORDER_ROOT",
    r"C:\Quantower\Settings\Scripts\Indicators\MarketRecorder\captures",
)
SCHEMA_DRIFT = {"missing_columns": "insert", "extra_columns": "ignore"}

# Widen the receipt-time prefilter so the exchange-time window is fully covered
# despite the ~0.9s clock offset between the two domains.
CLOCK_SLACK_US = 5_000_000
FILL_BUCKET_US = 5_000


def ny_us(day: str, hhmm: str) -> int:
    y, m, d = map(int, day.split("-"))
    h, mi = map(int, hhmm.split(":"))
    return int(dt.datetime(y, m, d, h, mi, tzinfo=NY).timestamp() * 1_000_000)


def ny_str(us: int) -> str:
    return dt.datetime.fromtimestamp(us / 1e6, NY).strftime("%H:%M:%S")


@dataclass(frozen=True)
class Window:
    symbol_dir: str
    day: str
    start: str
    end: str
    tick_size: float = 0.25
    price_lo: float | None = None
    price_hi: float | None = None

    @property
    def t0(self) -> int:
        return ny_us(self.day, self.start)

    @property
    def t1(self) -> int:
        return ny_us(self.day, self.end)

    def path(self, sub: str) -> str:
        return os.path.join(CAPTURE_ROOT, self.symbol_dir, self.day, sub, "*.parquet")

    def padded(self, before_min: float, after_min: float) -> "Window":
        """Same window widened in time. Needed whenever quote LIFECYCLES matter:
        a quote resting since before the window, or closing after it, is
        invisible otherwise, which silently undercounts queue depth."""
        def hhmm(us: int) -> str:
            return dt.datetime.fromtimestamp(us / 1e6, NY).strftime("%H:%M")
        return Window(
            self.symbol_dir, self.day,
            hhmm(self.t0 - int(before_min * 60_000_000)),
            hhmm(self.t1 + int(after_min * 60_000_000)),
            self.tick_size, self.price_lo, self.price_hi,
        )


def load_ticks(w: Window, banded: bool = True) -> pl.DataFrame:
    """Trades in window. `banded` applies the window price band, which is what
    fill attribution and coverage stats need; pass False for the raw tape."""
    lf = (
        pl.scan_parquet(w.path("ticks"), **SCHEMA_DRIFT)
        .filter((pl.col("timestamp_us") >= w.t0) & (pl.col("timestamp_us") < w.t1))
        .select("timestamp_us", "price", "size", "aggressor_sign")
    )
    if banded and w.price_lo is not None:
        lf = lf.filter(pl.col("price") >= w.price_lo)
    if banded and w.price_hi is not None:
        lf = lf.filter(pl.col("price") <= w.price_hi)
    return lf.sort("timestamp_us").collect()


def load_book(w: Window) -> pl.DataFrame:
    """Book events in window on EXCHANGE time, price-banded.

    The receipt-time prefilter is widened by CLOCK_SLACK_US because the two
    clock domains differ by ~0.9s; the exact window is then cut on exchange
    time, which is the domain the tick tape shares.
    """
    lf = (
        pl.scan_parquet(w.path("book_events"), **SCHEMA_DRIFT)
        .filter(
            (pl.col("receipt_timestamp_us") >= w.t0 - CLOCK_SLACK_US)
            & (pl.col("receipt_timestamp_us") < w.t1 + CLOCK_SLACK_US)
            & (pl.col("event_kind") == 1)
            & (pl.col("side") != 0)
        )
        .filter(
            (pl.col("exchange_timestamp_us") >= w.t0)
            & (pl.col("exchange_timestamp_us") < w.t1)
        )
        .with_columns((pl.col("price_tick") * w.tick_size).alias("price"))
    )
    if w.price_lo is not None:
        lf = lf.filter(pl.col("price") >= w.price_lo)
    if w.price_hi is not None:
        lf = lf.filter(pl.col("price") <= w.price_hi)
    return (
        lf.select(
            pl.col("exchange_timestamp_us").alias("t"),
            "receipt_timestamp_us", "sequence", "side", "price", "size",
            "closed", "quote_id_hash", "priority",
        )
        .sort("sequence")
        .collect()
    )


def quote_lifecycle(book: pl.DataFrame) -> pl.DataFrame:
    """One row per quote: open time/size/priority, close time, lifetime.

    Quotes with more than two rows (~1.5%) are size modifications; take the
    first row as the open and the last as the close, and the max observed size
    as the resting size.
    """
    return (
        book.group_by("quote_id_hash")
        .agg(
            pl.col("price").first().alias("price"),
            pl.col("side").first().alias("side"),
            pl.col("t").first().alias("t_open"),
            pl.col("t").last().alias("t_close"),
            pl.col("size").max().alias("size"),
            pl.col("priority").max().alias("priority"),
            pl.col("closed").any().alias("did_close"),
            pl.len().alias("n_events"),
        )
        .with_columns(((pl.col("t_close") - pl.col("t_open")) / 1000.0).alias("life_ms"))
    )


def signed_depth_deltas(book: pl.DataFrame) -> pl.DataFrame:
    """Per-event signed size change, so depth is a cumulative sum per level.

    A close removes the whole resting size; a non-close row that shrinks the
    quote is a partial reduction (partial fill or size amend).
    """
    return (
        book.sort("quote_id_hash", "sequence")
        .with_columns(
            pl.when(pl.col("closed"))
            .then(-pl.col("size"))
            .otherwise(
                pl.col("size")
                - pl.col("size").shift(1).over("quote_id_hash").fill_null(0.0)
            )
            .alias("size_delta")
        )
        .sort("sequence")
    )


def attribute_removals(book: pl.DataFrame, ticks: pl.DataFrame,
                       bucket_us: int = FILL_BUCKET_US) -> pl.DataFrame:
    """Split every size removal into fill vs pull against the trade tape.

    A bid-side removal coincident with sell-aggressor volume at that price is a
    fill; the residual is a pull. Both sides are on exchange time, so 5ms
    buckets recover ~99% of traded volume. Returns one row per
    (bucket, price, side).
    """
    rem = (
        signed_depth_deltas(book)
        .filter(pl.col("size_delta") < 0)
        .with_columns((pl.col("t") // bucket_us).alias("b"))
        .group_by("b", "price", "side")
        .agg(
            (-pl.col("size_delta")).sum().alias("removed_size"),
            pl.col("closed").sum().alias("removed_closes"),
            pl.len().alias("removed_events"),
        )
    )
    # bid quotes (side=1) are consumed by sell aggressors (-1), and vice versa
    trades = (
        ticks.with_columns(
            (pl.col("timestamp_us") // bucket_us).alias("b"),
            (-pl.col("aggressor_sign")).alias("side"),
        )
        .group_by("b", "price", "side")
        .agg(pl.col("size").sum().alias("trade_size"))
    )
    return (
        rem.join(trades, on=["b", "price", "side"], how="full", coalesce=True)
        .with_columns(
            pl.col("removed_size").fill_null(0.0),
            pl.col("trade_size").fill_null(0.0),
            pl.col("removed_events").fill_null(0),
        )
        .with_columns(
            pl.min_horizontal("removed_size", "trade_size").alias("fill_size"),
            (pl.col("removed_size") - pl.min_horizontal("removed_size", "trade_size"))
            .alias("pull_size"),
        )
    )


def level_second_features(w: Window, resting_ms: float = 1000.0) -> pl.DataFrame:
    """The reusable table: one row per (price, side, second)."""
    book = load_book(w)
    ticks = load_ticks(w)
    life = quote_lifecycle(book)
    deltas = signed_depth_deltas(book)
    attributed = attribute_removals(book, ticks)

    sec = 1_000_000
    adds = (
        life.with_columns((pl.col("t_open") // sec).alias("s"))
        .group_by("s", "price", "side")
        .agg(
            pl.col("size").sum().alias("add_size"),
            pl.len().alias("add_orders"),
            pl.col("size").filter(pl.col("life_ms") >= resting_ms).sum()
            .alias("add_size_resting"),
            pl.col("size").filter(pl.col("life_ms") >= resting_ms).len()
            .alias("add_orders_resting"),
            pl.col("life_ms").median().alias("add_life_ms_med"),
        )
    )
    fl = (
        attributed.with_columns(((pl.col("b") * FILL_BUCKET_US) // sec).alias("s"))
        .group_by("s", "price", "side")
        .agg(
            pl.col("fill_size").sum().alias("fill_size"),
            pl.col("pull_size").sum().alias("pull_size"),
            pl.col("removed_events").sum().alias("removal_events"),
        )
    )
    depth = (
        deltas.with_columns((pl.col("t") // sec).alias("s"))
        .group_by("s", "price", "side")
        .agg(pl.col("size_delta").sum().alias("depth_delta"))
    )
    out = (
        adds.join(fl, on=["s", "price", "side"], how="full", coalesce=True)
        .join(depth, on=["s", "price", "side"], how="full", coalesce=True)
        .fill_null(0.0)
        .with_columns(pl.col("s").cast(pl.Int64), pl.col("side").cast(pl.Int32))
        .sort("price", "side", "s")
    )
    return out.with_columns(
        pl.col("depth_delta").cum_sum().over("price", "side").alias("depth"),
        pl.when(pl.col("fill_size") + pl.col("pull_size") > 0)
        .then(pl.col("add_size") / (pl.col("fill_size") + pl.col("pull_size")))
        .otherwise(None)
        .alias("replenish_ratio"),
    ).sort("s", "price")


def coverage_summary(w: Window) -> dict:
    """Sanity numbers to print before trusting any derived read.

    `trade_covered` should sit near 0.99. Materially lower means the clock
    alignment or the price band is wrong, not that the market was unusual.
    """
    book, ticks = load_book(w), load_ticks(w)
    life = quote_lifecycle(book)
    attributed = attribute_removals(book, ticks)
    traded = float(ticks["size"].sum())
    return {
        "book_events": book.height,
        "trades": ticks.height,
        "traded_size": traded,
        "distinct_quotes": life.height,
        "life_ms_median": float(life["life_ms"].median()),
        "life_ms_p90": float(life["life_ms"].quantile(0.90)),
        "removed_size": float(attributed["removed_size"].sum()),
        "fill_size": float(attributed["fill_size"].sum()),
        "pull_size": float(attributed["pull_size"].sum()),
        "trade_covered": float(attributed["fill_size"].sum() / traded) if traded else 0.0,
    }


def snapshot_depth(w: Window, levels: int = 30) -> pl.DataFrame:
    """Resting depth per (t, price, side) from the 1Hz top-of-book snapshots.

    Ground truth for queue depth. The event replay cannot be used for this:
    roughly 1.5% of quotes never emit a close, so a running open-minus-close
    reconstruction accumulates phantom size (measured 186 lots vs a true 59 at
    ESU6 7777.00 on 2026-08-28 11:21). Snapshots carry only `levels` levels per
    side, so prices further from the mid return no row.
    """
    sn = (
        pl.scan_parquet(w.path("snapshots"), **SCHEMA_DRIFT)
        .filter((pl.col("timestamp_us") >= w.t0) & (pl.col("timestamp_us") < w.t1))
        .collect()
    )
    if not sn.height:
        return pl.DataFrame(schema={"t": pl.Int64, "price": pl.Float64,
                                    "side": pl.Int32, "depth": pl.Float64})
    frames = []
    for i in range(levels):
        for side, tag in ((-1, "ask"), (1, "bid")):
            oc, sc = f"{tag}_offset_{i}", f"{tag}_size_{i}"
            if oc not in sn.columns:
                continue
            frames.append(
                sn.select(
                    pl.col("timestamp_us").alias("t"),
                    ((pl.col("ref_tick") + pl.col(oc)) * w.tick_size).alias("price"),
                    pl.lit(side, dtype=pl.Int32).alias("side"),
                    pl.col(sc).cast(pl.Float64).alias("depth"),
                )
            )
    return (
        pl.concat(frames, how="vertical_relaxed")
        .filter(pl.col("depth") > 0)
        .sort("t")
    )
