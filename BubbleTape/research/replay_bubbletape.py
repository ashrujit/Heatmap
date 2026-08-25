"""Replay BubbleTape bubbles from MarketRecorder tick captures.

The live indicator can group executions by Quantower Last.TradeId when the feed
provides it. MarketRecorder tick parquet currently stores timestamp, price,
size, and aggressor sign, so this replay usually exercises BubbleTape's
same-side price/time fallback grouping.
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "research"))
from capture_loader import load_capture_window, tick_columns


TICK_SIZE = 0.25
NY = ZoneInfo("America/New_York")

SOURCE_TRADES = 0
SOURCE_DELTA = 1
SOURCE_BOTH = 2
CLUSTER_DELTA = 0
CLUSTER_TRADE = 1


@dataclass
class Settings:
    bar_minutes: int = 5
    price_band_ticks: int = 8
    strength_filter: int = 1
    bubble_source: int = SOURCE_TRADES
    min_cell_volume: float = 12.0
    min_delta_share: float = 0.25
    min_cluster_delta: float = 30.0
    max_clusters_per_bar_side: int = 4
    min_trade_group_volume: float = 50.0
    fallback_group_window_ms: int = 250


@dataclass
class TradePrint:
    timestamp_us: int
    price: float
    size: float
    aggressor_sign: int
    trade_id: str = ""


@dataclass
class CellState:
    bin_tick: int
    min_tick: int = 2**63 - 1
    max_tick: int = -(2**63)
    buy_volume: float = 0.0
    sell_volume: float = 0.0
    volume: float = 0.0
    prints: int = 0

    def add(self, tick: int, size: float, sign: int) -> None:
        self.min_tick = min(self.min_tick, tick)
        self.max_tick = max(self.max_tick, tick)
        self.volume += size
        if sign > 0:
            self.buy_volume += size
        elif sign < 0:
            self.sell_volume += size
        self.prints += 1


@dataclass
class TradeGroupState:
    key: str
    side: int
    identity_backed: bool
    min_tick: int = 2**63 - 1
    max_tick: int = -(2**63)
    first_us: int = 2**63 - 1
    last_us: int = 0
    volume: float = 0.0
    weighted_center: float = 0.0
    prints: int = 0

    def add(self, tick: int, size: float, timestamp_us: int) -> None:
        self.min_tick = min(self.min_tick, tick)
        self.max_tick = max(self.max_tick, tick)
        self.first_us = min(self.first_us, timestamp_us)
        self.last_us = max(self.last_us, timestamp_us)
        self.volume += size
        self.weighted_center += tick * size
        self.prints += 1

    @property
    def center_tick(self) -> float:
        if self.volume > 0:
            return self.weighted_center / self.volume
        return (self.min_tick + self.max_tick) / 2.0


@dataclass
class Cluster:
    min_tick: int
    max_tick: int
    center_tick: float
    side: int
    buy_volume: float
    sell_volume: float
    volume: float
    delta: float
    abs_delta: float
    weighted_center: float
    weighted_abs: float
    bins: int
    source: int
    identity_backed: bool
    prints: int

    @classmethod
    def from_cell(cls, cell: CellState) -> "Cluster":
        delta = cell.buy_volume - cell.sell_volume
        abs_delta = abs(delta)
        center = (cell.min_tick + cell.max_tick) / 2.0
        return cls(
            min_tick=cell.min_tick,
            max_tick=cell.max_tick,
            center_tick=center,
            side=1 if delta > 0 else -1,
            buy_volume=cell.buy_volume,
            sell_volume=cell.sell_volume,
            volume=cell.volume,
            delta=delta,
            abs_delta=abs_delta,
            weighted_center=center * abs_delta,
            weighted_abs=abs_delta,
            bins=1,
            source=CLUSTER_DELTA,
            identity_backed=False,
            prints=cell.prints,
        )

    @classmethod
    def from_trade_group(cls, group: TradeGroupState) -> "Cluster":
        return cls(
            min_tick=group.min_tick,
            max_tick=group.max_tick,
            center_tick=group.center_tick,
            side=group.side,
            buy_volume=group.volume if group.side > 0 else 0.0,
            sell_volume=group.volume if group.side < 0 else 0.0,
            volume=group.volume,
            delta=group.side * group.volume,
            abs_delta=group.volume,
            weighted_center=group.center_tick * group.volume,
            weighted_abs=group.volume,
            bins=max(1, group.max_tick - group.min_tick + 1),
            source=CLUSTER_TRADE,
            identity_backed=group.identity_backed,
            prints=group.prints,
        )

    def add_cell(self, cell: CellState) -> None:
        delta = cell.buy_volume - cell.sell_volume
        abs_delta = abs(delta)
        center = (cell.min_tick + cell.max_tick) / 2.0
        self.min_tick = min(self.min_tick, cell.min_tick)
        self.max_tick = max(self.max_tick, cell.max_tick)
        self.buy_volume += cell.buy_volume
        self.sell_volume += cell.sell_volume
        self.volume += cell.volume
        self.delta += delta
        self.abs_delta = abs(self.delta)
        self.weighted_center += center * abs_delta
        self.weighted_abs += abs_delta
        self.bins += 1
        self.prints += cell.prints
        if self.weighted_abs > 0:
            self.center_tick = self.weighted_center / self.weighted_abs
        else:
            self.center_tick = (self.min_tick + self.max_tick) / 2.0


@dataclass
class BarState:
    start_utc: datetime
    open_tick: int
    high_tick: int
    low_tick: int
    close_tick: int
    volume: float = 0.0
    delta: float = 0.0
    prints: int = 0
    cells: dict[int, CellState] = field(default_factory=dict)
    trade_groups: dict[str, TradeGroupState] = field(default_factory=dict)


@dataclass
class CandidateBar:
    start_utc: datetime
    display_utc: datetime
    open_tick: int
    high_tick: int
    low_tick: int
    close_tick: int
    volume: float
    delta: float
    prints: int
    clusters: list[Cluster]


@dataclass
class BubbleView:
    bar_start_utc: datetime
    display_utc: datetime
    center_tick: int
    min_tick: int
    max_tick: int
    side: int
    source: int
    identity_backed: bool
    prints: int
    buy_volume: float
    sell_volume: float
    volume: float
    delta: float
    abs_delta: float
    delta_share: float
    bins: int
    visual01: float
    threshold: float
    cap: float


class BubbleTapeReplay:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.bar: BarState | None = None
        self.candidate_bars: list[CandidateBar] = []
        self.ignored_zero_sign = 0

    def on_trade(self, trade: TradePrint) -> None:
        if not math.isfinite(trade.price) or trade.price <= 0:
            return
        if not math.isfinite(trade.size) or trade.size <= 0:
            return

        tick = price_to_tick(trade.price)
        start_utc = bar_start_utc(trade.timestamp_us, self.settings.bar_minutes)
        if self.bar is None:
            self.bar = BarState(start_utc, tick, tick, tick, tick)
        elif self.bar.start_utc != start_utc:
            self.finalize_bar()
            self.bar = BarState(start_utc, tick, tick, tick, tick)

        bar = self.bar
        bar.high_tick = max(bar.high_tick, tick)
        bar.low_tick = min(bar.low_tick, tick)
        bar.close_tick = tick
        bar.volume += trade.size
        bar.delta += trade.size * trade.aggressor_sign
        bar.prints += 1

        bin_tick = bin_tick_for(tick, self.settings.price_band_ticks)
        cell = bar.cells.get(bin_tick)
        if cell is None:
            cell = CellState(bin_tick)
            bar.cells[bin_tick] = cell
        cell.add(tick, trade.size, trade.aggressor_sign)

        if trade.aggressor_sign == 0:
            self.ignored_zero_sign += 1
            return

        group_key = trade_group_key(trade, tick, self.settings)
        group = bar.trade_groups.get(group_key)
        if group is None:
            group = TradeGroupState(
                group_key,
                1 if trade.aggressor_sign > 0 else -1,
                bool(trade.trade_id.strip()),
            )
            bar.trade_groups[group_key] = group
        group.add(tick, trade.size, trade.timestamp_us)

    def finalize_bar(self) -> None:
        if self.bar is None:
            return
        bar = self.bar
        clusters = build_all_clusters(bar, self.settings)
        self.candidate_bars.append(
            CandidateBar(
                start_utc=bar.start_utc,
                display_utc=bar.start_utc + timedelta(minutes=self.settings.bar_minutes / 2.0),
                open_tick=bar.open_tick,
                high_tick=bar.high_tick,
                low_tick=bar.low_tick,
                close_tick=bar.close_tick,
                volume=bar.volume,
                delta=bar.delta,
                prints=bar.prints,
                clusters=clusters,
            )
        )
        self.bar = None

    def bubbles(self) -> tuple[list[BubbleView], float, float]:
        active_values = [
            cluster.abs_delta
            for bar in self.candidate_bars
            for cluster in active_clusters(bar.clusters, self.settings.bubble_source)
        ]
        threshold = max(
            self.settings.min_cluster_delta,
            percentile(active_values, strength_percentile(self.settings.strength_filter)),
        )
        cap = max(threshold + 1.0, percentile(active_values, 99.0))

        out: list[BubbleView] = []
        for bar in self.candidate_bars:
            clusters = [
                c
                for c in active_clusters(bar.clusters, self.settings.bubble_source)
                if c.abs_delta >= threshold
            ]
            by_side: dict[int, list[Cluster]] = defaultdict(list)
            for cluster in clusters:
                by_side[cluster.side].append(cluster)

            selected: list[Cluster] = []
            for side_clusters in by_side.values():
                selected.extend(
                    sorted(side_clusters, key=lambda c: c.abs_delta, reverse=True)[
                        : self.settings.max_clusters_per_bar_side
                    ]
                )

            for cluster in sorted(selected, key=lambda c: c.center_tick):
                delta_share = abs(cluster.delta) / cluster.volume if cluster.volume > 0 else 0.0
                out.append(
                    BubbleView(
                        bar_start_utc=bar.start_utc,
                        display_utc=bar.display_utc,
                        center_tick=round_to_even(cluster.center_tick),
                        min_tick=cluster.min_tick,
                        max_tick=cluster.max_tick,
                        side=cluster.side,
                        source=cluster.source,
                        identity_backed=cluster.identity_backed,
                        prints=cluster.prints,
                        buy_volume=cluster.buy_volume,
                        sell_volume=cluster.sell_volume,
                        volume=cluster.volume,
                        delta=cluster.delta,
                        abs_delta=cluster.abs_delta,
                        delta_share=delta_share,
                        bins=cluster.bins,
                        visual01=visual_strength(cluster.abs_delta, threshold, cap),
                        threshold=threshold,
                        cap=cap,
                    )
                )

        return out, threshold, cap


def parse_ny(day: str, value: str) -> datetime:
    fmt = "%Y-%m-%d %H:%M:%S" if value.count(":") == 2 else "%Y-%m-%d %H:%M"
    return datetime.strptime(f"{day} {value}", fmt).replace(tzinfo=NY)


def ny_hms(ts: datetime) -> str:
    return ts.astimezone(NY).strftime("%H:%M:%S")


def price_to_tick(price: float) -> int:
    return int(round(price / TICK_SIZE))


def tick_to_price(tick: int) -> float:
    return tick * TICK_SIZE


def price_label(tick: int) -> str:
    return f"{tick_to_price(tick):.2f}"


def range_label(min_tick: int, max_tick: int) -> str:
    if min_tick == max_tick:
        return price_label(min_tick)
    return f"{price_label(min_tick)}-{price_label(max_tick)}"


def bar_start_utc(timestamp_us: int, bar_minutes: int) -> datetime:
    utc = datetime.fromtimestamp(timestamp_us / 1_000_000, tz=timezone.utc)
    local = utc.astimezone(NY)
    minutes = max(1, bar_minutes)
    minute = (local.minute // minutes) * minutes
    return datetime(
        local.year,
        local.month,
        local.day,
        local.hour,
        minute,
        tzinfo=NY,
    ).astimezone(timezone.utc)


def bin_tick_for(tick: int, price_band_ticks: int) -> int:
    width = max(1, price_band_ticks)
    return math.floor(tick / width) * width


def trade_group_key(trade: TradePrint, tick: int, settings: Settings) -> str:
    if trade.trade_id.strip():
        return f"id:{trade.aggressor_sign}:{trade.trade_id.strip()}"
    bucket_us = max(25, settings.fallback_group_window_ms) * 1_000
    bucket = trade.timestamp_us // bucket_us
    return f"fb:{trade.aggressor_sign}:{bin_tick_for(tick, settings.price_band_ticks)}:{bucket}"


def build_all_clusters(bar: BarState, settings: Settings) -> list[Cluster]:
    clusters: list[Cluster] = []
    clusters.extend(build_delta_clusters(bar, settings))
    clusters.extend(build_trade_group_clusters(bar, settings))
    return clusters


def build_delta_clusters(bar: BarState, settings: Settings) -> list[Cluster]:
    candidates: list[CellState] = []
    for cell in bar.cells.values():
        if cell.volume < settings.min_cell_volume:
            continue
        delta = cell.buy_volume - cell.sell_volume
        abs_delta = abs(delta)
        if abs_delta <= 0:
            continue
        if abs_delta / max(1.0, cell.volume) < settings.min_delta_share:
            continue
        candidates.append(cell)

    out: list[Cluster] = []
    current: Cluster | None = None
    last_bin: int | None = None
    for cell in sorted(
        candidates,
        key=lambda c: (1 if c.buy_volume - c.sell_volume > 0 else -1, c.bin_tick),
    ):
        side = 1 if cell.buy_volume - cell.sell_volume > 0 else -1
        starts_new = (
            current is None
            or current.side != side
            or last_bin is None
            or cell.bin_tick > last_bin + settings.price_band_ticks
        )
        if starts_new:
            if current is not None:
                out.append(current)
            current = Cluster.from_cell(cell)
        else:
            current.add_cell(cell)
        last_bin = cell.bin_tick
    if current is not None:
        out.append(current)
    return out


def build_trade_group_clusters(bar: BarState, settings: Settings) -> list[Cluster]:
    return [
        Cluster.from_trade_group(group)
        for group in bar.trade_groups.values()
        if group.volume >= settings.min_trade_group_volume
    ]


def active_clusters(clusters: list[Cluster], bubble_source: int) -> list[Cluster]:
    if bubble_source == SOURCE_TRADES:
        return [c for c in clusters if c.source == CLUSTER_TRADE]
    if bubble_source == SOURCE_DELTA:
        return [c for c in clusters if c.source == CLUSTER_DELTA]
    return list(clusters)


def strength_percentile(strength_filter: int) -> float:
    if strength_filter <= 0:
        return 92.0
    if strength_filter >= 2:
        return 96.0
    return 94.0


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = math.ceil((pct / 100.0) * len(ordered)) - 1
    idx = max(0, min(len(ordered) - 1, idx))
    return ordered[idx]


def visual_strength(abs_delta: float, threshold: float, cap: float) -> float:
    if cap <= threshold:
        return 0.65
    norm = (abs_delta - threshold) / (cap - threshold)
    norm = max(0.0, min(1.0, norm))
    return math.sqrt(norm)


def round_to_even(value: float) -> int:
    return int(round(value))


def source_value(value: str) -> int:
    v = value.lower()
    if v == "trades":
        return SOURCE_TRADES
    if v == "delta":
        return SOURCE_DELTA
    if v == "both":
        return SOURCE_BOTH
    raise argparse.ArgumentTypeError("source must be trades, delta, or both")


def strength_value(value: str) -> int:
    v = value.lower()
    if v in ("0", "low"):
        return 0
    if v in ("1", "normal"):
        return 1
    if v in ("2", "high"):
        return 2
    raise argparse.ArgumentTypeError("strength must be low, normal, or high")


def side_label(side: int) -> str:
    return "BUY" if side > 0 else "SELL"


def source_label(source: int) -> str:
    return "trade" if source == CLUSTER_TRADE else "delta"


def load_trades(symbol_dir: str, start: datetime, end: datetime) -> list[TradePrint]:
    columns = tick_columns() + ["trade_id"]
    try:
        df = load_capture_window("ticks", symbol_dir, start, end, columns)
    except Exception as exc:
        if "trade_id" not in str(exc).lower():
            raise
        df = load_capture_window("ticks", symbol_dir, start, end, tick_columns())

    has_trade_id = "trade_id" in df.columns
    out: list[TradePrint] = []
    for row in df.iter_rows(named=True):
        sign = int(row["aggressor_sign"])
        sign = 1 if sign > 0 else (-1 if sign < 0 else 0)
        trade_id = ""
        if has_trade_id and row.get("trade_id") is not None:
            trade_id = str(row["trade_id"])
        out.append(
            TradePrint(
                timestamp_us=int(row["timestamp_us"]),
                price=float(row["price"]),
                size=float(row["size"]),
                aggressor_sign=sign,
                trade_id=trade_id,
            )
        )
    return out


def write_csv(path: Path, bubbles: list[BubbleView]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "bar",
                "display",
                "side",
                "price_range",
                "center",
                "label_size",
                "source",
                "identity_backed",
                "prints",
                "buy_volume",
                "sell_volume",
                "volume",
                "delta",
                "delta_share",
                "bins",
                "visual01",
            ]
        )
        for b in bubbles:
            writer.writerow(
                [
                    ny_hms(b.bar_start_utc),
                    ny_hms(b.display_utc),
                    side_label(b.side),
                    range_label(b.min_tick, b.max_tick),
                    price_label(b.center_tick),
                    round(b.abs_delta),
                    source_label(b.source),
                    int(b.identity_backed),
                    b.prints,
                    f"{b.buy_volume:.0f}",
                    f"{b.sell_volume:.0f}",
                    f"{b.volume:.0f}",
                    f"{b.delta:.0f}",
                    f"{b.delta_share:.3f}",
                    b.bins,
                    f"{b.visual01:.3f}",
                ]
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--symbol-dir", default="ESU6")
    parser.add_argument("--window", default="09:30-14:30")
    parser.add_argument("--warmup-min", type=int, default=90)
    parser.add_argument("--bar-minutes", type=int, default=5)
    parser.add_argument("--price-band-ticks", type=int, default=8)
    parser.add_argument("--strength", type=strength_value, default=1)
    parser.add_argument("--source", type=source_value, default=SOURCE_TRADES)
    parser.add_argument("--min-cell-volume", type=float, default=12.0)
    parser.add_argument("--min-delta-share", type=float, default=0.25)
    parser.add_argument("--min-cluster-delta", type=float, default=30.0)
    parser.add_argument("--max-clusters-per-bar-side", type=int, default=4)
    parser.add_argument("--min-trade-group-volume", type=float, default=50.0)
    parser.add_argument("--fallback-group-window-ms", type=int, default=250)
    parser.add_argument("--price-min", type=float)
    parser.add_argument("--price-max", type=float)
    parser.add_argument("--csv-out", type=Path)
    args = parser.parse_args()

    start_s, end_s = args.window.split("-", 1)
    window_start = parse_ny(args.date, start_s)
    window_end = parse_ny(args.date, end_s)
    replay_start = window_start - timedelta(minutes=max(0, args.warmup_min))

    settings = Settings(
        bar_minutes=max(1, min(60, args.bar_minutes)),
        price_band_ticks=max(1, min(400, args.price_band_ticks)),
        strength_filter=args.strength,
        bubble_source=args.source,
        min_cell_volume=max(0.0, args.min_cell_volume),
        min_delta_share=max(0.01, min(0.99, args.min_delta_share)),
        min_cluster_delta=max(0.0, args.min_cluster_delta),
        max_clusters_per_bar_side=max(1, min(20, args.max_clusters_per_bar_side)),
        min_trade_group_volume=max(1.0, args.min_trade_group_volume),
        fallback_group_window_ms=max(25, min(2000, args.fallback_group_window_ms)),
    )

    trades = load_trades(args.symbol_dir, replay_start, window_end)
    replay = BubbleTapeReplay(settings)
    for trade in trades:
        replay.on_trade(trade)
    replay.finalize_bar()

    all_bubbles, threshold, cap = replay.bubbles()
    visible = [
        b
        for b in all_bubbles
        if window_start <= b.bar_start_utc < window_end
        and (args.price_min is None or tick_to_price(b.max_tick) >= args.price_min)
        and (args.price_max is None or tick_to_price(b.min_tick) <= args.price_max)
    ]

    if args.csv_out:
        write_csv(args.csv_out, visible)

    print(
        f"{args.date} {args.window} {args.symbol_dir} "
        f"source={['trades','delta','both'][settings.bubble_source]} "
        f"strength={['low','normal','high'][settings.strength_filter]} "
        f"bars={len(replay.candidate_bars):,} "
        f"ticks={len(trades):,} "
        f"bubbles={len(visible):,} "
        f"threshold={threshold:.0f} cap={cap:.0f} "
        f"fallback_ms={settings.fallback_group_window_ms}"
    )
    if replay.ignored_zero_sign:
        print(f"ignored_zero_sign_ticks={replay.ignored_zero_sign:,}")
    if args.csv_out:
        print(f"csv={args.csv_out}")

    print("\nBubbleTape bubbles:")
    print("bar      side  range             center   label src    prints  buy   sell  delta  share visual")
    for b in visible:
        print(
            f"{ny_hms(b.bar_start_utc)[:5]}   "
            f"{side_label(b.side):<4}  "
            f"{range_label(b.min_tick, b.max_tick):<16} "
            f"{price_label(b.center_tick):>7} "
            f"{round(b.abs_delta):>7} "
            f"{source_label(b.source):<6} "
            f"{b.prints:>6} "
            f"{b.buy_volume:>5.0f} "
            f"{b.sell_volume:>6.0f} "
            f"{b.delta:>6.0f} "
            f"{b.delta_share:>5.2f} "
            f"{b.visual01:>5.2f}"
        )


if __name__ == "__main__":
    main()
