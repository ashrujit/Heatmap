"""Prototype BubbleTape: a sparse footprint-compression chart.

The research question is visual, not predictive: if we compress meaningful
aggressive-volume clusters into bubbles on a naked time chart, does the auction
story stay readable when reviewing a prior session?
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import math
import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import polars as pl

from capture_loader import add_ny_ts, load_capture_window, us


NY = ZoneInfo("America/New_York")
OUT_DIR = os.path.join(os.path.dirname(__file__), "out", "bubble_tape")
TICK_SIZE = 0.25


@dataclass
class Cluster:
    bar_us: int
    bar_ts: dt.datetime
    side: int
    lo: float
    hi: float
    center: float
    buy: float
    sell: float
    volume: float
    delta: float
    abs_delta: float
    delta_share: float
    bins: int


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--date", default="2026-06-12", help="RTH date, e.g. 2026-06-12")
    p.add_argument("--symbol-dir", default="NQM6")
    p.add_argument("--session-start", default="prev:18:00")
    p.add_argument("--session-end", default="16:00")
    p.add_argument("--view-start", default=None)
    p.add_argument("--view-end", default=None)
    p.add_argument("--bar-min", type=int, default=5)
    p.add_argument("--band-points", type=float, default=2.0)
    p.add_argument("--min-cell-volume", type=float, default=12.0)
    p.add_argument("--min-delta-share", type=float, default=0.25)
    p.add_argument("--min-cluster-delta", type=float, default=30.0)
    p.add_argument("--cluster-percentile", type=float, default=92.0)
    p.add_argument("--max-clusters-per-bar-side", type=int, default=4)
    p.add_argument("--min-bubble-size", type=float, default=35.0)
    p.add_argument("--max-bubble-size", type=float, default=620.0)
    p.add_argument("--label-top", type=int, default=0)
    p.add_argument("--out-dir", default=OUT_DIR)
    return p.parse_args()


def ny_dt(day: dt.date, spec: str | None, fallback: dt.datetime | None = None) -> dt.datetime:
    if spec is None:
        if fallback is None:
            raise ValueError("missing datetime spec and no fallback")
        return fallback

    text = spec.strip()
    use_day = day
    if text.startswith("prev:"):
        use_day = day - dt.timedelta(days=1)
        text = text.split(":", 1)[1]

    if "T" in text or "-" in text:
        parsed = dt.datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=NY)
        return parsed.astimezone(NY)

    hour, minute = [int(part) for part in text.split(":", 1)]
    return dt.datetime(use_day.year, use_day.month, use_day.day, hour, minute, tzinfo=NY)


def ny_label(ts: dt.datetime | None, with_date: bool = False) -> str:
    if ts is None:
        return "-"
    fmt = "%Y-%m-%d %H:%M" if with_date else "%H:%M"
    return ts.astimezone(NY).strftime(fmt)


def interval_us(minutes: int) -> int:
    return minutes * 60 * 1_000_000


def dt_from_us(value: int) -> dt.datetime:
    return dt.datetime.fromtimestamp(value / 1_000_000, tz=dt.timezone.utc).astimezone(NY)


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(0, min(len(ordered) - 1, math.ceil((pct / 100.0) * len(ordered)) - 1))
    return float(ordered[rank])


def view_slug(start: dt.datetime, end: dt.datetime) -> str:
    if start.date() == end.date():
        return f"{start:%H%M}-{end:%H%M}"
    return f"{start:%m%d-%H%M}_{end:%m%d-%H%M}"


def filter_us(df: pl.DataFrame, start: dt.datetime, end: dt.datetime, column: str = "timestamp_us") -> pl.DataFrame:
    lo = us(start)
    hi = us(end)
    return df.filter((pl.col(column) >= lo) & (pl.col(column) < hi))


def add_bar_us(ticks: pl.DataFrame, bar_minutes: int) -> pl.DataFrame:
    step = interval_us(bar_minutes)
    return ticks.with_columns(((pl.col("timestamp_us") // step) * step).cast(pl.Int64).alias("bar_us"))


def build_bars(ticks: pl.DataFrame, bar_minutes: int) -> pl.DataFrame:
    with_bar = add_bar_us(ticks, bar_minutes)
    bars = (
        with_bar.group_by("bar_us")
        .agg(
            pl.col("price").first().alias("open"),
            pl.col("price").max().alias("high"),
            pl.col("price").min().alias("low"),
            pl.col("price").last().alias("close"),
            pl.col("size").sum().alias("volume"),
            (pl.col("size") * pl.col("aggressor_sign")).sum().alias("delta"),
            pl.len().alias("trades"),
        )
        .sort("bar_us")
        .with_columns(
            pl.from_epoch("bar_us", time_unit="us")
            .dt.replace_time_zone("UTC")
            .dt.convert_time_zone("America/New_York")
            .alias("bar_ts")
        )
        .with_columns(pl.col("delta").cum_sum().alias("cvd"))
    )
    return bars


def build_cells(
    ticks: pl.DataFrame,
    bar_minutes: int,
    band_points: float,
    min_cell_volume: float,
    min_delta_share: float,
) -> pl.DataFrame:
    with_bar = add_bar_us(ticks, bar_minutes)
    with_price = with_bar.with_columns(
        (pl.col("price") / band_points).floor().cast(pl.Int64).alias("price_bin"),
        pl.when(pl.col("aggressor_sign") > 0).then(pl.col("size")).otherwise(0.0).alias("buy_size"),
        pl.when(pl.col("aggressor_sign") < 0).then(pl.col("size")).otherwise(0.0).alias("sell_size"),
    )
    cells = (
        with_price.group_by(["bar_us", "price_bin"])
        .agg(
            pl.col("buy_size").sum().alias("buy"),
            pl.col("sell_size").sum().alias("sell"),
            pl.col("size").sum().alias("volume"),
            pl.len().alias("trades"),
        )
        .with_columns(
            (pl.col("buy") - pl.col("sell")).alias("delta"),
            ((pl.col("price_bin").cast(pl.Float64) + 0.5) * band_points).alias("center"),
            (pl.col("price_bin").cast(pl.Float64) * band_points).alias("lo"),
            ((pl.col("price_bin").cast(pl.Float64) + 1.0) * band_points).alias("hi"),
        )
        .with_columns(
            pl.col("delta").abs().alias("abs_delta"),
            (pl.col("delta").abs() / pl.col("volume")).alias("delta_share"),
            pl.when(pl.col("delta") > 0).then(1).otherwise(-1).alias("side"),
        )
        .filter(
            (pl.col("volume") >= min_cell_volume)
            & (pl.col("abs_delta") > 0)
            & (pl.col("delta_share") >= min_delta_share)
        )
        .sort(["bar_us", "side", "price_bin"])
    )
    return cells


def merge_cells(cells: pl.DataFrame) -> list[Cluster]:
    clusters: list[Cluster] = []
    current: dict[str, float | int] | None = None
    last_bin: int | None = None

    def flush() -> None:
        nonlocal current
        if current is None:
            return
        volume = float(current["volume"])
        delta = float(current["delta"])
        abs_delta = abs(delta)
        weighted_abs = float(current["weighted_abs"])
        center = float(current["weighted_center"]) / weighted_abs if weighted_abs > 0 else (
            float(current["lo"]) + float(current["hi"])
        ) / 2.0
        clusters.append(
            Cluster(
                bar_us=int(current["bar_us"]),
                bar_ts=dt_from_us(int(current["bar_us"])),
                side=int(current["side"]),
                lo=float(current["lo"]),
                hi=float(current["hi"]),
                center=center,
                buy=float(current["buy"]),
                sell=float(current["sell"]),
                volume=volume,
                delta=delta,
                abs_delta=abs_delta,
                delta_share=abs_delta / volume if volume > 0 else 0.0,
                bins=int(current["bins"]),
            )
        )
        current = None

    for row in cells.iter_rows(named=True):
        bar_us = int(row["bar_us"])
        side = int(row["side"])
        price_bin = int(row["price_bin"])
        abs_delta = float(row["abs_delta"])
        starts_new = (
            current is None
            or int(current["bar_us"]) != bar_us
            or int(current["side"]) != side
            or last_bin is None
            or price_bin > last_bin + 1
        )
        if starts_new:
            flush()
            current = {
                "bar_us": bar_us,
                "side": side,
                "lo": float(row["lo"]),
                "hi": float(row["hi"]),
                "buy": float(row["buy"]),
                "sell": float(row["sell"]),
                "volume": float(row["volume"]),
                "delta": float(row["delta"]),
                "weighted_abs": abs_delta,
                "weighted_center": float(row["center"]) * abs_delta,
                "bins": 1,
            }
        else:
            current["lo"] = min(float(current["lo"]), float(row["lo"]))
            current["hi"] = max(float(current["hi"]), float(row["hi"]))
            current["buy"] = float(current["buy"]) + float(row["buy"])
            current["sell"] = float(current["sell"]) + float(row["sell"])
            current["volume"] = float(current["volume"]) + float(row["volume"])
            current["delta"] = float(current["delta"]) + float(row["delta"])
            current["weighted_abs"] = float(current["weighted_abs"]) + abs_delta
            current["weighted_center"] = float(current["weighted_center"]) + float(row["center"]) * abs_delta
            current["bins"] = int(current["bins"]) + 1
        last_bin = price_bin

    flush()
    return clusters


def select_clusters(
    clusters: list[Cluster],
    min_cluster_delta: float,
    cluster_percentile: float,
    max_per_bar_side: int,
) -> tuple[list[Cluster], float]:
    threshold = max(min_cluster_delta, percentile([c.abs_delta for c in clusters], cluster_percentile))
    selected = [c for c in clusters if c.abs_delta >= threshold]
    if max_per_bar_side <= 0:
        return selected, threshold

    grouped: dict[tuple[int, int], list[Cluster]] = {}
    for c in selected:
        grouped.setdefault((c.bar_us, c.side), []).append(c)

    capped: list[Cluster] = []
    for rows in grouped.values():
        capped.extend(sorted(rows, key=lambda c: c.abs_delta, reverse=True)[:max_per_bar_side])
    return sorted(capped, key=lambda c: (c.bar_us, c.center, c.side)), threshold


def cluster_size(abs_delta: float, threshold: float, cap: float, min_size: float, max_size: float) -> float:
    if cap <= threshold:
        return (min_size + max_size) / 2.0
    norm = max(0.0, min(1.0, (abs_delta - threshold) / (cap - threshold)))
    return min_size + math.sqrt(norm) * (max_size - min_size)


def write_cluster_csv(path: str, clusters: list[Cluster]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "bar_ts",
                "side",
                "lo",
                "hi",
                "center",
                "buy",
                "sell",
                "volume",
                "delta",
                "abs_delta",
                "delta_share",
                "bins",
            ]
        )
        for c in clusters:
            w.writerow(
                [
                    c.bar_ts.isoformat(),
                    "buy" if c.side > 0 else "sell",
                    f"{c.lo:.2f}",
                    f"{c.hi:.2f}",
                    f"{c.center:.2f}",
                    f"{c.buy:.0f}",
                    f"{c.sell:.0f}",
                    f"{c.volume:.0f}",
                    f"{c.delta:.0f}",
                    f"{c.abs_delta:.0f}",
                    f"{c.delta_share:.3f}",
                    c.bins,
                ]
            )


def draw_candles(ax: plt.Axes, bars: pl.DataFrame, bar_minutes: int) -> None:
    width = (bar_minutes / (24.0 * 60.0)) * 0.72
    wick_color = "#3a3a3a"
    up_fill = "#f7f7f7"
    down_fill = "#8b8b8b"
    edge = "#262626"

    for row in bars.iter_rows(named=True):
        x = mdates.date2num(row["bar_ts"])
        open_price = float(row["open"])
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        ax.vlines(x, low, high, color=wick_color, linewidth=0.8, zorder=2)

        body_lo = min(open_price, close)
        body_hi = max(open_price, close)
        height = max(body_hi - body_lo, TICK_SIZE * 0.5)
        if body_hi == body_lo:
            body_lo -= height / 2.0
        fill = up_fill if close >= open_price else down_fill
        rect = Rectangle(
            (x - width / 2.0, body_lo),
            width,
            height,
            facecolor=fill,
            edgecolor=edge,
            linewidth=0.55,
            zorder=3,
        )
        ax.add_patch(rect)


def draw_bubbles(
    ax: plt.Axes,
    clusters: list[Cluster],
    bar_minutes: int,
    threshold: float,
    args: argparse.Namespace,
) -> None:
    if not clusters:
        return

    cap = percentile([c.abs_delta for c in clusters], 99.0)
    bar_width = bar_minutes / (24.0 * 60.0)
    side_offset = bar_width * 0.16
    for side, color, label, offset_sign in (
        (1, "#159447", "buy aggression", 1),
        (-1, "#d64a3a", "sell aggression", -1),
    ):
        rows = [c for c in clusters if c.side == side]
        if not rows:
            continue
        xs = [mdates.date2num(c.bar_ts) + offset_sign * side_offset for c in rows]
        ys = [c.center for c in rows]
        sizes = [
            cluster_size(c.abs_delta, threshold, cap, args.min_bubble_size, args.max_bubble_size)
            for c in rows
        ]
        ax.scatter(
            xs,
            ys,
            s=sizes,
            c=color,
            alpha=0.42,
            edgecolors=color,
            linewidths=0.65,
            label=label,
            zorder=4,
        )

    if args.label_top > 0:
        for c in sorted(clusters, key=lambda item: item.abs_delta, reverse=True)[: args.label_top]:
            x = mdates.date2num(c.bar_ts) + (side_offset if c.side > 0 else -side_offset)
            ax.text(
                x,
                c.center,
                f"{c.delta:+.0f}",
                fontsize=7,
                ha="center",
                va="center",
                color="#111111",
                zorder=5,
            )


def plot_chart(
    bars: pl.DataFrame,
    clusters: list[Cluster],
    threshold: float,
    load_start: dt.datetime,
    load_end: dt.datetime,
    first_tick: dt.datetime,
    last_tick: dt.datetime,
    view_start: dt.datetime,
    view_end: dt.datetime,
    args: argparse.Namespace,
    png_path: str,
) -> None:
    view_bars = filter_us(bars, view_start, view_end, "bar_us")
    view_clusters = [c for c in clusters if us(view_start) <= c.bar_us < us(view_end)]
    if view_bars.height == 0:
        raise ValueError("no bars in requested view")

    fig, (ax_price, ax_cvd) = plt.subplots(
        2,
        1,
        figsize=(16, 9),
        sharex=True,
        gridspec_kw={"height_ratios": [4.3, 1.0], "hspace": 0.04},
    )
    fig.patch.set_facecolor("#fbfbfb")
    ax_price.set_facecolor("#fbfbfb")
    ax_cvd.set_facecolor("#fbfbfb")

    draw_candles(ax_price, view_bars, args.bar_min)
    draw_bubbles(ax_price, view_clusters, args.bar_min, threshold, args)

    x0 = mdates.date2num(view_start)
    x1 = mdates.date2num(view_end)
    ax_price.set_xlim(x0, x1)
    ax_price.grid(True, axis="y", color="#e4e4e4", linewidth=0.7)
    ax_price.grid(True, axis="x", color="#efefef", linewidth=0.55)
    ax_price.set_ylabel("NQ price")
    ax_price.legend(loc="upper left", frameon=False, fontsize=9)

    rth_day = dt.date.fromisoformat(args.date)
    for marker, label in (
        (ny_dt(rth_day, "09:30"), "RTH"),
        (ny_dt(rth_day, "10:30"), "IB"),
    ):
        if view_start <= marker <= view_end:
            x = mdates.date2num(marker)
            ax_price.axvline(x, color="#222222", linewidth=0.8, alpha=0.45, linestyle="--")
            ax_price.text(x, ax_price.get_ylim()[1], label, fontsize=8, ha="left", va="top", color="#333333")

    view_cvd = filter_us(bars, view_start, view_end, "bar_us")
    xs = [mdates.date2num(row["bar_ts"]) for row in view_cvd.iter_rows(named=True)]
    ys = [float(row["cvd"]) for row in view_cvd.iter_rows(named=True)]
    ax_cvd.plot(xs, ys, color="#333333", linewidth=1.0)
    ax_cvd.axhline(0, color="#888888", linewidth=0.7)
    ax_cvd.fill_between(xs, ys, 0, where=[y >= 0 for y in ys], color="#159447", alpha=0.16)
    ax_cvd.fill_between(xs, ys, 0, where=[y < 0 for y in ys], color="#d64a3a", alpha=0.16)
    ax_cvd.grid(True, axis="y", color="#e4e4e4", linewidth=0.7)
    ax_cvd.set_ylabel("CVD")

    locator = mdates.AutoDateLocator(minticks=5, maxticks=11, tz=NY)
    ax_cvd.xaxis.set_major_locator(locator)
    ax_cvd.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator, tz=NY))

    title = (
        f"BubbleTape prototype | {args.symbol_dir} {args.date} {args.bar_min}m "
        f"| view {ny_label(view_start)}-{ny_label(view_end)} ET"
    )
    subtitle = (
        f"load {ny_label(load_start, True)} to {ny_label(load_end, True)}; "
        f"ticks {ny_label(first_tick, True)} to {ny_label(last_tick, True)}; "
        f"band {args.band_points:g}pt; absDelta >= {threshold:.0f} "
        f"(p{args.cluster_percentile:g}, share >= {args.min_delta_share:.0%}); "
        f"view bubbles {len(view_clusters)}"
    )
    fig.suptitle(title, fontsize=13, fontweight="bold", y=0.982)
    fig.text(0.5, 0.952, subtitle, ha="center", fontsize=9, color="#444444")
    fig.subplots_adjust(top=0.92, left=0.065, right=0.985, bottom=0.075)
    fig.savefig(png_path, dpi=150)
    plt.close(fig)


def main() -> None:
    args = parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    rth_day = dt.date.fromisoformat(args.date)
    load_start = ny_dt(rth_day, args.session_start)
    load_end = ny_dt(rth_day, args.session_end)
    view_start = ny_dt(rth_day, args.view_start, load_start)
    view_end = ny_dt(rth_day, args.view_end, load_end)

    ticks = add_ny_ts(load_capture_window("ticks", args.symbol_dir, load_start, load_end))
    if ticks.height == 0:
        raise ValueError("no ticks loaded")

    first_tick = ticks.select(pl.col("ts").min()).item()
    last_tick = ticks.select(pl.col("ts").max()).item()
    bars = build_bars(ticks, args.bar_min)
    cells = build_cells(
        ticks,
        args.bar_min,
        args.band_points,
        args.min_cell_volume,
        args.min_delta_share,
    )
    all_clusters = merge_cells(cells)
    selected_clusters, threshold = select_clusters(
        all_clusters,
        args.min_cluster_delta,
        args.cluster_percentile,
        args.max_clusters_per_bar_side,
    )
    view_clusters = [c for c in selected_clusters if us(view_start) <= c.bar_us < us(view_end)]

    base = (
        f"bubble_tape_{args.symbol_dir}_{args.date}_{args.bar_min}m_"
        f"{view_slug(view_start, view_end)}_band{args.band_points:g}_p{args.cluster_percentile:g}"
    )
    png_path = os.path.join(args.out_dir, base + ".png")
    csv_path = os.path.join(args.out_dir, base + ".clusters.csv")

    write_cluster_csv(csv_path, view_clusters)
    plot_chart(
        bars,
        selected_clusters,
        threshold,
        load_start,
        load_end,
        first_tick,
        last_tick,
        view_start,
        view_end,
        args,
        png_path,
    )

    print(f"BubbleTape prototype {args.symbol_dir} {args.date}")
    print(f"requested: {ny_label(load_start, True)} -> {ny_label(load_end, True)}")
    print(f"loaded ticks: {ticks.height:,} ({ny_label(first_tick, True)} -> {ny_label(last_tick, True)})")
    print(f"bars: {bars.height:,}; candidate cells: {cells.height:,}; merged clusters: {len(all_clusters):,}")
    print(f"selected clusters: {len(selected_clusters):,}; view clusters: {len(view_clusters):,}")
    print(
        f"threshold: absDelta >= {threshold:.0f}; band={args.band_points:g}pt; "
        f"delta_share>={args.min_delta_share:.0%}"
    )
    print(f"png: {png_path}")
    print(f"csv: {csv_path}")


if __name__ == "__main__":
    main()
