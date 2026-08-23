"""Classify how the consumed side of a direct conversion actually died.

Research question: when LevelLedger records a `CONSUMED` transition (supply
consumed demand, or demand consumed supply), was the losing side *absorbed*
(eaten by the tape) or *withdrawn* (cancelled with no matching tape)? Under the
current EAR heuristic both look identical, but only the first means anyone was
actually overwhelmed.

Method follows the Skurry `RestingWalls` dissolution-classification concept, but
runs offline against MarketRecorder raw book events. The measurement atom is the
per-(price_tick, side) size delta reconstructed from quote events and then
decomposed against the trade tape.

Accounting is NET, not gross. A first pass integrating raw adds/removes found
~150 contracts of gross removal in a 2-second window over a band displaying 12,
across 653 delta events: on NQ, gross level flow is dominated by cancel/replace
flicker and says nothing about whether anyone was overwhelmed. So this uses the
`LevelStackTracker` formulation, where conservation over a window gives

    size_end = size_start - eaten - cancelled + added
    replenishment = added - cancelled = (size_end - size_start) + eaten

    replenishment > 0  -> supplied more than was taken from them (defending)
    replenishment ~ 0  -> replaced exactly what was consumed
    replenishment < 0  -> net withdrawal beyond what was eaten (pulled)

Dissolution is then how much of the band's disappearance the tape can account
for, and replenishment sign is tracked as a separate reading rather than folded
into the same label. Gross flow is retained only as a churn descriptor.

Per-order identity is deliberately NOT assumed. Quote ids are used only as
bookkeeping to compute aggregate level deltas (9.6% of ids change price during a
session, and Skurry retired its iceberg detector because prop-firm ids look
synthetic). Displayed size is seeded from the canonical 1 Hz snapshot at the
window start and reconciled against the canonical snapshot at the window end;
the residual is reported, never silently repaired.
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import polars as pl

from _paths import OUTPUT_ROOT, REPO_ROOT as ROOT, SCRIPT_ROOT

sys.path.insert(0, str(ROOT / "MarketRecorder" / "research"))

from capture_loader import (  # noqa: E402
    load_capture_window,
    market_recorder_files,
    snapshot_columns,
    tick_columns,
)
from validate_book_events import BookReplay  # noqa: E402

NY = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")
TICK_SIZE = 0.25

DELTA = 1
RESET_BEGIN = 2
RESET_ITEM = 3
RESET_END = 4
GAP = 5

EVENT_COLUMNS = [
    "receipt_timestamp_us",
    "sequence",
    "subsequence",
    "reset_epoch",
    "event_kind",
    "side",
    "price_tick",
    "size",
    "closed",
    "quote_id_hash",
    "reset_item_count",
]

# Column index positions inside EVENT_COLUMNS, for tuple-based row iteration.
C_TS, C_SEQ, C_SUB, C_EPOCH, C_KIND, C_SIDE, C_TICK, C_SIZE, C_CLOSED, C_QID, C_ITEMS = range(11)

BID = 1
ASK = -1

# Attack-window search bounds. The consumption that a CONSUMED transition
# confirms always precedes the transition timestamp, so the window is derived
# from the tape rather than from the confirmation clock.
MAX_LOOKBACK_S = 900
MIN_WINDOW_S = 2.0
MAX_WINDOW_S = 600.0
FALLBACK_WINDOW_S = 120.0
POST_BREAK_S = 30.0

# The engagement window walks back from the break for as long as price stays at
# or inside the band edge plus this tolerance. Bands are narrow (median 5 ticks),
# so anchoring on the final crossing alone collapses to a 2-second window and
# misses the whole period the level was being worked.
ENGAGE_TOL_TICKS = 2

# Classification thresholds. Deliberately coarse: this is a three-way split of a
# ratio, not a tuned gate.
ABSORBED_MIN = 0.70
WITHDRAWN_MAX = 0.30
# Replenishment sign, as a fraction of the engagement's scale. Normalising by
# starting displayed size alone is degenerate: 38 of 167 bands display nothing
# at all when price arrives (the LL band marks where L2 events clustered
# earlier, not resting size at attack time), which sends the ratio to infinity
# and auto-classifies them as defending. Scale is therefore the larger of what
# they had and what they faced, with a floor near typical NQ level size.
DEFEND_MIN = 0.25
RETREAT_MAX = -0.25
SCALE_FLOOR = 5.0


def provision_scale(seed: float, eaten: float) -> float:
    seed_v = 0.0 if math.isnan(seed) else seed
    eaten_v = 0.0 if math.isnan(eaten) else eaten
    return max(seed_v, eaten_v, SCALE_FLOOR)


def price_to_tick(price: float) -> int:
    return int(round(price / TICK_SIZE))


def parse_utc(value: str) -> datetime:
    text = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def to_us(ts: datetime) -> int:
    return int(ts.timestamp() * 1_000_000)


@dataclass
class Window:
    """One measurement interval attached to one conversion event."""

    event_idx: int
    phase: str  # "attack" | "post"
    start_us: int
    end_us: int
    lo_tick: int
    hi_tick: int
    loser_side: int
    winner_side: int
    # Band sizes are read directly off the reconstructed book rather than
    # integrated from deltas: eviction of mechanically crossed levels happens
    # inside the replay and is invisible to the delta stream, so an incremental
    # running total drifts upward exactly where stale quotes linger.
    seed_loser_size: float = math.nan
    end_loser_size: float = math.nan
    max_loser: float = math.nan
    min_loser: float = math.nan
    seed_winner_size: float = math.nan
    end_winner_size: float = math.nan
    added_loser: float = 0.0
    removed_loser: float = 0.0
    added_winner: float = 0.0
    removed_winner: float = 0.0
    delta_events: int = 0
    opened: bool = False
    closed_out: bool = False

    @property
    def cum_loser(self) -> float:
        if math.isnan(self.seed_loser_size) or math.isnan(self.end_loser_size):
            return math.nan
        return self.end_loser_size - self.seed_loser_size

    def observe(self, side: int, delta: float) -> None:
        self.delta_events += 1
        if side == self.loser_side:
            if delta > 0:
                self.added_loser += delta
            else:
                self.removed_loser += -delta
        elif side == self.winner_side:
            if delta > 0:
                self.added_winner += delta
            else:
                self.removed_winner += -delta

    def sample(self, loser_size: float, winner_size: float, *, opening: bool) -> None:
        if opening:
            self.seed_loser_size = loser_size
            self.seed_winner_size = winner_size
            self.max_loser = loser_size
            self.min_loser = loser_size
            self.opened = True
        self.end_loser_size = loser_size
        self.end_winner_size = winner_size
        self.max_loser = loser_size if math.isnan(self.max_loser) else max(self.max_loser, loser_size)
        self.min_loser = loser_size if math.isnan(self.min_loser) else min(self.min_loser, loser_size)


@dataclass
class Conversion:
    idx: int
    date: str
    ts_utc: datetime
    ts_et: str
    band_id: str
    side: str  # winning side per LL
    consumed_side: str  # losing side
    lo_price: float
    hi_price: float
    lo_tick: int
    hi_tick: int
    loser_side: int
    winner_side: int
    width_pts: float
    max_abs_z: float
    score: float
    same_band_outcome: str
    life_sec: str
    raw: dict[str, str]
    first_test_utc: datetime | None = None
    touch_us: int = 0
    break_us: int = 0
    window_source: str = ""
    eaten: float = 0.0
    tape_total: float = 0.0
    tape_opposing: float = 0.0
    post_eaten: float = 0.0
    post_tape_total: float = 0.0
    recon_err: float = math.nan
    windows: dict[str, Window] = field(default_factory=dict)


def load_ear_rails(events_path: Path, dates: set[str] | None) -> list[Conversion]:
    """Build the study population from EAR's own conversion rails.

    Preferred over the synthetic LevelLedger replay: that replay recovers only
    about half to three-quarters of the rails EAR actually forms, and its band
    lifecycle mislabelled a known losing trade as held. EAR's rails carry the
    boundaries execution keyed on and the RailHeld/RailFailed stream that
    answers "did it survive a test" directly.
    """

    sys.path.insert(0, str(SCRIPT_ROOT))
    from ear_rails import load_rails, rail_row  # noqa: E402

    out: list[Conversion] = []
    for idx, rail in enumerate(load_rails(events_path, dates, {"Consumed"})):
        row = rail_row(rail)
        _, test_utc = rail.first_test()
        # rail.side is the side that OWNS the level after the conversion, i.e.
        # the winner; the consumed side is its opposite.
        winner_is_demand = rail.side == "Demand"
        consumed = "supply" if winner_is_demand else "demand"
        loser = ASK if winner_is_demand else BID
        out.append(
            Conversion(
                idx=idx,
                date=rail.date,
                ts_utc=rail.owned_utc,
                ts_et=f"{rail.date} {rail.owned_et}",
                band_id=str(rail.band_id),
                side="demand" if winner_is_demand else "supply",
                consumed_side=consumed,
                lo_price=rail.min_price,
                hi_price=rail.max_price,
                lo_tick=rail.min_tick,
                hi_tick=rail.max_tick,
                loser_side=loser,
                winner_side=-loser,
                width_pts=float(row["width_pts"]),
                max_abs_z=0.0,
                score=0.0,
                same_band_outcome=row["first_test_verdict"],
                life_sec=str(row["life_sec"]),
                raw=row,
                first_test_utc=test_utc,
            )
        )
    return out


def load_conversions(path: Path, dates: set[str] | None) -> list[Conversion]:
    out: list[Conversion] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for idx, row in enumerate(csv.DictReader(handle)):
            if dates and row["date"] not in dates:
                continue
            if row.get("action") != "CONSUMED":
                continue
            lo = float(row["price_lo"])
            hi = float(row["price_hi"])
            loser = BID if row["consumed_side"] == "demand" else ASK
            out.append(
                Conversion(
                    idx=idx,
                    date=row["date"],
                    ts_utc=parse_utc(row["event_ts_utc"]),
                    ts_et=row["event_ts_et"],
                    band_id=row["band_id"],
                    side=row["side"],
                    consumed_side=row["consumed_side"],
                    lo_price=lo,
                    hi_price=hi,
                    lo_tick=price_to_tick(lo),
                    hi_tick=price_to_tick(hi),
                    loser_side=loser,
                    winner_side=-loser,
                    width_pts=float(row.get("width_pts") or 0.0),
                    max_abs_z=float(row.get("max_abs_z") or 0.0),
                    score=float(row.get("score") or 0.0),
                    same_band_outcome=row.get("same_band_outcome", ""),
                    life_sec=row.get("life_sec", ""),
                    raw=row,
                )
            )
    return out


def resolve_attack_window(conv: Conversion, times: list[int], prices: list[float]) -> None:
    """Bracket the interval over which the losing side actually got taken out.

    For a consumed demand band the break is the first trade below the band after
    price was last at or above it; the mirror holds for consumed supply. This is
    tape-derived rather than read off the confirmation clock, because LL confirms
    a CONSUMED transition only after a sustained displacement.
    """

    t0 = to_us(conv.ts_utc)
    lo_bound = t0 - MAX_LOOKBACK_S * 1_000_000
    import bisect

    start_i = bisect.bisect_left(times, lo_bound)
    end_i = bisect.bisect_right(times, t0)
    if end_i <= start_i:
        conv.touch_us = t0 - int(FALLBACK_WINDOW_S * 1_000_000)
        conv.break_us = t0
        conv.window_source = "no_tape"
        return

    loser_is_bid = conv.loser_side == BID
    break_i = -1
    # Walk backwards to the last bar of the move that broke the band, then find
    # the first crossing of that move.
    for i in range(end_i - 1, start_i - 1, -1):
        p = prices[i]
        inside_or_beyond = p < conv.lo_price if loser_is_bid else p > conv.hi_price
        if not inside_or_beyond:
            break
        break_i = i
    if break_i < 0:
        # Price never sat beyond the band right before t0; fall back to the first
        # crossing anywhere in the lookback.
        for i in range(start_i, end_i):
            p = prices[i]
            if (p < conv.lo_price) if loser_is_bid else (p > conv.hi_price):
                break_i = i
                break
    if break_i < 0:
        conv.touch_us = t0 - int(FALLBACK_WINDOW_S * 1_000_000)
        conv.break_us = t0
        conv.window_source = "no_break"
        return

    # Engagement, not just the final crossing: walk back while price is still at
    # or inside the band edge (plus tolerance), and stop where it was clearly
    # away from the level. This is the period over which the losing side was
    # actually being worked.
    tol = ENGAGE_TOL_TICKS * TICK_SIZE
    engage_hi = conv.hi_price + tol
    engage_lo = conv.lo_price - tol
    touch_i = break_i
    for i in range(break_i - 1, start_i - 1, -1):
        p = prices[i]
        still_engaged = (p <= engage_hi) if loser_is_bid else (p >= engage_lo)
        if not still_engaged:
            break
        touch_i = i
    conv.touch_us = times[touch_i]
    conv.window_source = "tape" if touch_i < break_i else "instant_break"
    conv.break_us = times[break_i]

    span = (conv.break_us - conv.touch_us) / 1_000_000
    if span < MIN_WINDOW_S:
        conv.touch_us = conv.break_us - int(MIN_WINDOW_S * 1_000_000)
    elif span > MAX_WINDOW_S:
        conv.touch_us = conv.break_us - int(MAX_WINDOW_S * 1_000_000)


def snapshot_band_size(row: dict[str, Any], lo_tick: int, hi_tick: int, side: int) -> float:
    prefix = "bid" if side == BID else "ask"
    ref = int(row["ref_tick"])
    total = 0.0
    for idx in range(30):
        size = row[f"{prefix}_size_{idx}"]
        if size is None:
            continue
        size = float(size)
        if not math.isfinite(size) or size <= 0:
            continue
        offset = row[f"{prefix}_offset_{idx}"]
        if offset is None:
            continue
        tick = ref + int(offset)
        if lo_tick <= tick <= hi_tick:
            total += size
    return total


def nearest_snapshot(snap_times: list[int], snap_rows: list[dict[str, Any]], target_us: int) -> dict[str, Any] | None:
    import bisect

    if not snap_times:
        return None
    i = bisect.bisect_left(snap_times, target_us)
    best = None
    best_gap = None
    for j in (i - 1, i):
        if 0 <= j < len(snap_times):
            gap = abs(snap_times[j] - target_us)
            if best_gap is None or gap < best_gap:
                best_gap = gap
                best = snap_rows[j]
    if best_gap is not None and best_gap > 5_000_000:
        return None
    return best


def accumulate_tape(conv: Conversion, times: list[int], prices: list[float], sizes: list[float], signs: list[int]) -> None:
    import bisect

    lo_p = conv.lo_tick * TICK_SIZE
    hi_p = conv.hi_tick * TICK_SIZE
    # Aggressor that consumes the losing side: sells hit bids, buys lift asks.
    hitting = -1 if conv.loser_side == BID else 1

    def scan(start_us: int, end_us: int) -> tuple[float, float, float]:
        i = bisect.bisect_left(times, start_us)
        j = bisect.bisect_right(times, end_us)
        eaten = 0.0
        total = 0.0
        opposing = 0.0
        for k in range(i, j):
            p = prices[k]
            if p < lo_p - 1e-9 or p > hi_p + 1e-9:
                continue
            sz = sizes[k]
            total += sz
            if signs[k] == hitting:
                eaten += sz
            else:
                opposing += sz
        return eaten, total, opposing

    conv.eaten, conv.tape_total, conv.tape_opposing = scan(conv.touch_us, conv.break_us)
    post_end = conv.break_us + int(POST_BREAK_S * 1_000_000)
    conv.post_eaten, conv.post_tape_total, _ = scan(conv.break_us, post_end)


def stream_day(
    symbol_dir: str,
    day: str,
    windows: list[Window],
    batch_files: int = 40,
) -> dict[str, int]:
    """Single forward pass over the day's raw book events.

    Uses the `BookReplay` already validated against canonical snapshots, so
    mechanically-crossed level eviction is handled. Band sizes are read off the
    reconstructed level dictionaries at window open/close and whenever an event
    touches the band; gross add/remove flow is accumulated separately from the
    per-event delta decomposition purely as a churn descriptor.
    """

    date = datetime.fromisoformat(day).date()
    files = market_recorder_files(symbol_dir, "book_events", date)
    stats = {
        "files": len(files),
        "rows": 0,
        "deltas": 0,
        "gaps": 0,
        "resets": 0,
        "preseed": 0,
        "orphan_closes": 0,
    }
    if not files:
        return stats

    ordered = sorted(windows, key=lambda w: w.start_us)
    starts = [w.start_us for w in ordered]
    next_window = 0
    active: list[Window] = []

    replay = BookReplay()

    def band_size(window: Window, side: int) -> float:
        levels = replay.bid_levels if side == BID else replay.ask_levels
        total = 0.0
        for tick in range(window.lo_tick, window.hi_tick + 1):
            total += levels.get(tick, 0.0)
        return total

    def sample_window(window: Window, *, opening: bool) -> None:
        window.sample(
            band_size(window, window.loser_side),
            band_size(window, window.winner_side),
            opening=opening,
        )

    for base in range(0, len(files), batch_files):
        batch = files[base : base + batch_files]
        frame = (
            pl.read_parquet(batch, columns=EVENT_COLUMNS)
            .sort(["sequence", "subsequence"])
        )
        stats["rows"] += frame.height
        for row in frame.iter_rows():
            kind = row[C_KIND]
            event = {
                "event_kind": kind,
                "side": row[C_SIDE],
                "price_tick": row[C_TICK],
                "size": row[C_SIZE],
                "closed": row[C_CLOSED],
                "quote_id_hash": row[C_QID],
                "reset_epoch": row[C_EPOCH],
                "reset_item_count": row[C_ITEMS],
            }
            if kind != DELTA:
                replay.apply(event)
                continue

            stats["deltas"] += 1
            if not replay.seeded:
                stats["preseed"] += 1
                replay.apply(event)
                continue
            if not replay.valid:
                replay.apply(event)
                continue

            ts = row[C_TS]
            # Retire windows whose end has passed, sampling their closing book.
            if active:
                still: list[Window] = []
                for window in active:
                    if window.end_us < ts:
                        sample_window(window, opening=False)
                        window.closed_out = True
                    else:
                        still.append(window)
                active = still
            # Activate windows whose start has arrived, sampling their opening book.
            while next_window < len(ordered) and starts[next_window] <= ts:
                window = ordered[next_window]
                next_window += 1
                if window.end_us < ts:
                    # Degenerate window entirely between two events.
                    sample_window(window, opening=True)
                    window.closed_out = True
                    continue
                sample_window(window, opening=True)
                active.append(window)

            # Decompose the event into per-(side, tick) level deltas for churn.
            qid = row[C_QID]
            prior = replay.quotes.get(qid)
            deltas: tuple[tuple[int, int, float], ...] = ()
            if row[C_CLOSED]:
                if prior is None:
                    stats["orphan_closes"] += 1
                else:
                    deltas = ((prior.side, prior.price_tick, -prior.size),)
            else:
                side = row[C_SIDE]
                tick = row[C_TICK]
                size = float(row[C_SIZE])
                if qid != 0 and side in (BID, ASK) and math.isfinite(size) and size >= 0:
                    if prior is None:
                        deltas = ((side, tick, size),) if size > 0 else ()
                    elif prior.side == side and prior.price_tick == tick:
                        diff = size - prior.size
                        deltas = ((side, tick, diff),) if abs(diff) > 1e-9 else ()
                    else:
                        deltas = ((prior.side, prior.price_tick, -prior.size),)
                        if size > 0:
                            deltas = deltas + ((side, tick, size),)

            replay.apply(event)

            if not active:
                continue
            for window in active:
                touched = False
                for side, tick, diff in deltas:
                    if window.lo_tick <= tick <= window.hi_tick:
                        window.observe(side, diff)
                        touched = True
                if touched:
                    sample_window(window, opening=False)

    # Any window still open at end of stream gets a final read.
    for window in active:
        sample_window(window, opening=False)
    for window in ordered:
        if not window.opened:
            stats["unopened_windows"] = stats.get("unopened_windows", 0) + 1

    stats["crossed_levels_evicted"] = replay.crossed_levels_evicted
    stats["resets"] = replay.completed_resets
    return stats


def safe_div(num: float, den: float) -> float:
    return num / den if den > 1e-9 else math.nan


def classify(absorb_frac: float) -> str:
    if math.isnan(absorb_frac):
        return "no_depletion"
    if absorb_frac >= ABSORBED_MIN:
        return "absorbed"
    if absorb_frac <= WITHDRAWN_MAX:
        return "withdrawn"
    return "partial"


def classify_provision(replenishment: float, seed: float, eaten: float, absorb_frac: float) -> str:
    """Single non-circular reading of what the losing side did.

    Dissolution and replenishment are NOT independent axes: when replenishment
    is positive, `pull_uneaten` is zero and `absorb_frac` is mechanically 1.0.
    So the primary question is whether they kept providing, and the eaten-vs-
    pulled split is only meaningful for the ones that actually drained.
    """

    if math.isnan(replenishment) or math.isnan(seed):
        return "unknown"
    ratio = replenishment / provision_scale(seed, eaten)
    if ratio >= DEFEND_MIN:
        return "defending"
    if ratio > RETREAT_MAX:
        return "replaced"
    if math.isnan(absorb_frac):
        return "drained_unknown"
    return "drained_eaten" if absorb_frac >= 0.5 else "drained_pulled"


def fmt(value: Any, digits: int = 3) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return ""
        return f"{round(value, digits)}"
    return str(value)


OUT_FIELDS = [
    "date",
    "event_ts_et",
    "band_id",
    "winner_side",
    "consumed_side",
    "price_lo",
    "price_hi",
    "width_pts",
    "max_abs_z",
    "window_source",
    "touch_et",
    "break_et",
    "attack_span_s",
    "seed_loser_size",
    "end_loser_size",
    "max_loser_size",
    "min_loser_size",
    "net_change",
    "net_depletion",
    "eaten",
    "replenishment",
    "repl_ratio",
    "pull_uneaten",
    "absorb_frac",
    "dissolution",
    "provision_class",
    "gross_removed",
    "gross_added",
    "churn_ratio",
    "hidden_ratio",
    "tape_total",
    "tape_opposing",
    "winner_added_attack",
    "winner_removed_attack",
    "post_net_change",
    "post_eaten",
    "post_replenishment",
    "post_repl_ratio",
    "post_winner_added",
    "recon_err",
    "delta_events",
    "same_band_outcome",
    "life_sec",
]


def build_rows(conversions: list[Conversion]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for conv in conversions:
        attack = conv.windows.get("attack")
        post = conv.windows.get("post")
        seed = attack.seed_loser_size if attack else math.nan
        end_size = attack.end_loser_size if attack else math.nan
        net_change = attack.cum_loser if attack else math.nan
        net_depletion = max(0.0, -net_change) if attack else math.nan
        # added - cancelled, per the conservation identity in the module docstring.
        replenishment = net_change + conv.eaten if attack else math.nan
        pull_uneaten = max(0.0, -replenishment) if attack else math.nan
        absorb = (
            safe_div(conv.eaten, conv.eaten + pull_uneaten)
            if attack and (net_depletion > 1e-9 or conv.eaten > 1e-9)
            else math.nan
        )
        max_disp = attack.max_loser if attack else math.nan
        if math.isnan(max_disp) and attack:
            max_disp = seed
        post_net = post.cum_loser if post else math.nan
        post_repl = post_net + conv.post_eaten if post else math.nan
        rows.append(
            {
                "date": conv.date,
                "event_ts_et": conv.ts_et,
                "band_id": conv.band_id,
                "winner_side": conv.side,
                "consumed_side": conv.consumed_side,
                "price_lo": fmt(conv.lo_price, 2),
                "price_hi": fmt(conv.hi_price, 2),
                "width_pts": fmt(conv.width_pts, 2),
                "max_abs_z": fmt(conv.max_abs_z, 2),
                "window_source": conv.window_source,
                "touch_et": datetime.fromtimestamp(conv.touch_us / 1e6, UTC).astimezone(NY).strftime("%H:%M:%S.%f")[:-3],
                "break_et": datetime.fromtimestamp(conv.break_us / 1e6, UTC).astimezone(NY).strftime("%H:%M:%S.%f")[:-3],
                "attack_span_s": fmt((conv.break_us - conv.touch_us) / 1e6, 1),
                "seed_loser_size": fmt(seed, 1),
                "end_loser_size": fmt(end_size, 1),
                "max_loser_size": fmt(max_disp, 1),
                "min_loser_size": fmt(attack.min_loser if attack else None, 1),
                "net_change": fmt(net_change, 1),
                "net_depletion": fmt(net_depletion, 1),
                "eaten": fmt(conv.eaten, 1),
                "replenishment": fmt(replenishment, 1),
                "repl_ratio": fmt(
                    safe_div(replenishment, provision_scale(seed, conv.eaten)) if attack else math.nan
                ),
                "pull_uneaten": fmt(pull_uneaten, 1),
                "absorb_frac": fmt(absorb),
                "dissolution": classify(absorb),
                "provision_class": (
                    classify_provision(replenishment, seed, conv.eaten, absorb) if attack else "unknown"
                ),
                "gross_removed": fmt(attack.removed_loser if attack else None, 1),
                "gross_added": fmt(attack.added_loser if attack else None, 1),
                "churn_ratio": fmt(
                    safe_div(attack.removed_loser, max(seed, 1.0)) if attack else math.nan
                ),
                "hidden_ratio": fmt(safe_div(conv.eaten, max_disp if max_disp and max_disp > 0 else math.nan)),
                "tape_total": fmt(conv.tape_total, 1),
                "tape_opposing": fmt(conv.tape_opposing, 1),
                "winner_added_attack": fmt(attack.added_winner if attack else None, 1),
                "winner_removed_attack": fmt(attack.removed_winner if attack else None, 1),
                "post_net_change": fmt(post_net, 1),
                "post_eaten": fmt(conv.post_eaten, 1),
                "post_replenishment": fmt(post_repl, 1),
                "post_repl_ratio": fmt(safe_div(post_repl, max(seed, 1.0)) if post else math.nan),
                "post_winner_added": fmt(post.added_winner if post else None, 1),
                "recon_err": fmt(conv.recon_err, 1),
                "delta_events": fmt(attack.delta_events if attack else 0, 0),
                "same_band_outcome": conv.same_band_outcome,
                "life_sec": conv.life_sec,
            }
        )
    return rows


def summarize(rows: list[dict[str, str]]) -> list[str]:
    lines: list[str] = []
    total = len(rows)
    lines.append(f"- events: {total}")
    by_class: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_class[row["provision_class"]].append(row)
    lines.append("")
    lines.append("## What the losing side did")
    lines.append("")
    def med(items: list[dict[str, str]], key: str) -> str:
        vals = sorted(float(r[key]) for r in items if r[key])
        if not vals:
            return ""
        mid = len(vals) // 2
        return f"{vals[mid]:.2f}" if len(vals) % 2 else f"{(vals[mid - 1] + vals[mid]) / 2:.2f}"

    lines.append("| class | n | share | med absorb_frac | med repl_ratio | med hidden_ratio | med churn |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for name in ("defending", "replaced", "drained_eaten", "drained_pulled", "drained_unknown", "unknown"):
        items = by_class.get(name, [])
        if not items:
            continue
        lines.append(
            f"| {name} | {len(items)} | {len(items) / total:.1%} | "
            f"{med(items, 'absorb_frac')} | {med(items, 'repl_ratio')} | "
            f"{med(items, 'hidden_ratio')} | {med(items, 'churn_ratio')} |"
        )

    lines.append("")
    lines.append("## Provision class by day")
    lines.append("")
    days = sorted({row["date"] for row in rows})
    lines.append("| class | " + " | ".join(days) + " |")
    lines.append("|---|" + "---:|" * len(days))
    for name in ("defending", "replaced", "drained_eaten", "drained_pulled", "drained_unknown", "unknown"):
        items = by_class.get(name, [])
        if not items:
            continue
        cells = []
        for day in days:
            day_rows = [r for r in rows if r["date"] == day]
            hits = [r for r in day_rows if r["provision_class"] == name]
            cells.append(f"{len(hits)} ({len(hits) / max(len(day_rows), 1):.0%})")
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--events-csv",
        default=str(
            OUTPUT_ROOT
            / "direct_conversion_lifecycle_20260723_20260724"
            / "direct_conversion_events.csv"
        ),
    )
    parser.add_argument("--dates", default="2026-07-23,2026-07-24")
    parser.add_argument("--symbol-dir", default="NQU6")
    parser.add_argument(
        "--out-dir", default=str(OUTPUT_ROOT / "conversion_provision")
    )
    parser.add_argument(
        "--source",
        choices=("ear", "synthetic"),
        default="ear",
        help="ear = EAR's own Consumed rails (default); synthetic = LL replay CSV",
    )
    parser.add_argument(
        "--ear-events",
        default=str(Path.home() / "Documents" / "ExecAssistantRuntime" / "events.jsonl"),
    )
    parser.add_argument(
        "--anchor",
        choices=("consumption", "first_test"),
        default="consumption",
        help="consumption = the fight; first_test = the re-approach into contact",
    )
    parser.add_argument("--approach-sec", type=float, default=60.0)
    parser.add_argument(
        "--approach-lag-sec",
        type=float,
        default=0.0,
        help="close the approach window this many seconds BEFORE contact (anti-leakage)",
    )
    args = parser.parse_args()

    dates = [d.strip() for d in args.dates.split(",") if d.strip()]
    if args.source == "ear":
        conversions = load_ear_rails(Path(args.ear_events), set(dates))
    else:
        conversions = load_conversions(Path(args.events_csv), set(dates))

    if args.anchor == "first_test":
        # A never-tested rail has no re-approach to measure.
        conversions = [c for c in conversions if c.first_test_utc is not None]
    if not conversions:
        raise SystemExit("no conversions matched")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    health: list[str] = []
    for day in dates:
        day_convs = [c for c in conversions if c.date == day]
        if not day_convs:
            continue
        start = datetime.fromisoformat(day).replace(tzinfo=NY)
        end = start + timedelta(days=1)

        ticks = load_capture_window("ticks", args.symbol_dir, start, end, tick_columns())
        t_times = ticks["timestamp_us"].to_list()
        t_prices = ticks["price"].to_list()
        t_sizes = ticks["size"].to_list()
        t_signs = ticks["aggressor_sign"].to_list()

        snaps = load_capture_window("snapshots", args.symbol_dir, start, end, snapshot_columns())
        snap_rows = snaps.to_dicts()
        snap_times = [int(r["timestamp_us"]) for r in snap_rows]

        windows: list[Window] = []
        for conv in day_convs:
            if args.anchor == "first_test":
                # The re-approach into the first test. The window ENDS at
                # contact so no part of the test's resolution can leak into a
                # feature: RailHeld/RailFailed is only emitted afterwards.
                if conv.first_test_utc is None:
                    continue
                # A window ending exactly at contact leaks: at that instant the
                # book already encodes whether price is penetrating the band
                # (the loser's side only has size there once price has arrived),
                # which is the resolution rather than a predictor of it. The lag
                # closes the window before contact so features are causal.
                test_us = to_us(conv.first_test_utc)
                conv.break_us = test_us - int(args.approach_lag_sec * 1_000_000)
                conv.touch_us = conv.break_us - int(args.approach_sec * 1_000_000)
                conv.window_source = "first_test"
            else:
                resolve_attack_window(conv, t_times, t_prices)
            accumulate_tape(conv, t_times, t_prices, t_sizes, t_signs)

            attack = Window(
                event_idx=conv.idx,
                phase="attack",
                start_us=conv.touch_us,
                end_us=conv.break_us,
                lo_tick=conv.lo_tick,
                hi_tick=conv.hi_tick,
                loser_side=conv.loser_side,
                winner_side=conv.winner_side,
            )
            post = Window(
                event_idx=conv.idx,
                phase="post",
                start_us=conv.break_us,
                end_us=conv.break_us + int(POST_BREAK_S * 1_000_000),
                lo_tick=conv.lo_tick,
                hi_tick=conv.hi_tick,
                loser_side=conv.loser_side,
                winner_side=conv.winner_side,
            )
            conv.windows["attack"] = attack
            conv.windows["post"] = post
            windows.extend([attack, post])

        stats = stream_day(args.symbol_dir, day, windows)

        # Reconcile the replayed band size against the canonical snapshot at the
        # window OPEN, where the band is still live and inside snapshot depth.
        # Reconciling at the break instead would compare against a band that has
        # just moved to the wrong side of the market and legitimately reads zero.
        for conv in day_convs:
            attack = conv.windows.get("attack")
            if attack is None or math.isnan(attack.seed_loser_size):
                continue
            seed_row = nearest_snapshot(snap_times, snap_rows, conv.touch_us)
            if seed_row is None:
                continue
            canonical = snapshot_band_size(seed_row, conv.lo_tick, conv.hi_tick, conv.loser_side)
            conv.recon_err = attack.seed_loser_size - canonical

        health.append(
            f"- {day}: conversions={len(day_convs)} files={stats['files']} rows={stats['rows']} "
            f"deltas={stats['deltas']} resets={stats['resets']} gaps={stats['gaps']} "
            f"preseed={stats['preseed']} orphan_closes={stats['orphan_closes']} "
            f"evicted_levels={stats.get('crossed_levels_evicted', 0)} "
            f"unopened_windows={stats.get('unopened_windows', 0)}"
        )
        print(health[-1], flush=True)

    rows = build_rows(conversions)
    csv_path = out_dir / "conversion_provision.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    lines = ["# Conversion Provision Probe", "", "## Replay health", ""]
    lines.extend(health)
    lines.append("")
    lines.extend(summarize(rows))
    (out_dir / "findings.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(summarize(rows)))
    print(f"\nwrote {csv_path}")


if __name__ == "__main__":
    main()
