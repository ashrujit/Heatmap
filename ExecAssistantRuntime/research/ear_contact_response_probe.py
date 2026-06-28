"""EAR-focused contact-response overlay for recent MarketRecorder captures.

This keeps the current EAR/LevelLedger candidate grammar as the baseline, then
asks whether event-level book response around those candidates would have
changed execution decisions. It is research-only: thresholds reported here are
exploratory and must not be copied into runtime without a held-out replay pass.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import glob
import math
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median
from types import SimpleNamespace

import polars as pl

ROOT = Path(__file__).resolve().parents[2]
LL_RESEARCH = ROOT / "LevelLedger" / "research"
RESEARCH = ROOT / "research"
MR_RESEARCH = ROOT / "MarketRecorder" / "research"
sys.path.insert(0, str(LL_RESEARCH))
sys.path.insert(0, str(RESEARCH))
sys.path.insert(0, str(MR_RESEARCH))

from candidate_timing_probe import replay_session  # noqa: E402
from capture_loader import (  # noqa: E402
    MARKET_RECORDER_ROOT,
    load_capture_window,
    snapshot_columns,
    tick_columns,
    us,
)
from replay_levelledger import parse_ny  # noqa: E402
from snapshot_ofi_proxy_probe import build_snapshot_series  # noqa: E402
from validate_book_events import (  # noqa: E402
    DELTA,
    GAP,
    RESET_BEGIN,
    BookReplay,
    event_files_with_carry,
)


WINDOWS_SEC = (2, 5, 10)
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
CHUNK_PART_RE = re.compile(r"-p\d+(?=\.parquet$)")
TICK_SIZE = 0.25


@dataclass(frozen=True)
class SessionSpec:
    date: str
    symbol: str
    window: str

    @property
    def label(self) -> str:
        return f"{self.date}:{self.symbol}"


@dataclass
class Health:
    files: int = 0
    carry_days: int = 0
    rows_processed: int = 0
    valid_deltas: int = 0
    resets: int = 0
    gaps: int = 0
    crossed_levels_evicted: int = 0
    crossed_quotes_evicted: int = 0


@dataclass
class AnchorMetrics:
    session: str
    anchor_id: int
    candidate_id: int
    evidence_side: str
    direction: str
    formed_ts: datetime
    anchor_ts: datetime
    end_ts: datetime | None
    outcome: str
    min_tick: int
    max_tick: int
    event_count: int
    score: float
    kind_count: int
    duration_sec: float
    form_age_sec: float
    gap_contaminated: bool
    same_start: float | None = None
    opp_start: float | None = None
    valid_book: bool = False
    invalidated_by_gap: bool = False
    same_add: dict[int, float] = field(default_factory=lambda: {w: 0.0 for w in WINDOWS_SEC})
    same_remove: dict[int, float] = field(default_factory=lambda: {w: 0.0 for w in WINDOWS_SEC})
    opp_add: dict[int, float] = field(default_factory=lambda: {w: 0.0 for w in WINDOWS_SEC})
    opp_remove: dict[int, float] = field(default_factory=lambda: {w: 0.0 for w in WINDOWS_SEC})
    same_end: dict[int, float | None] = field(default_factory=lambda: {w: None for w in WINDOWS_SEC})
    opp_end: dict[int, float | None] = field(default_factory=lambda: {w: None for w in WINDOWS_SEC})
    future_ticks: dict[int, float | None] = field(default_factory=dict)
    attack_vol: dict[int, float] = field(default_factory=lambda: {w: 0.0 for w in WINDOWS_SEC})
    aligned_vol: dict[int, float] = field(default_factory=lambda: {w: 0.0 for w in WINDOWS_SEC})

    @property
    def side_sign(self) -> int:
        return 1 if self.evidence_side == "demand" else -1

    @property
    def anchor_us(self) -> int:
        return us(self.anchor_ts)

    @property
    def max_end_us(self) -> int:
        return self.anchor_us + max(WINDOWS_SEC) * 1_000_000

    def in_band(self, price_tick: int) -> bool:
        return self.min_tick <= price_tick <= self.max_tick

    def side_depth(self, replay: BookReplay, side: int) -> float:
        levels = replay.bid_levels if side > 0 else replay.ask_levels
        return sum(size for tick, size in levels.items() if self.min_tick <= tick <= self.max_tick)

    def sample_start(self, replay: BookReplay) -> None:
        if not replay.valid:
            self.valid_book = False
            return
        self.same_start = self.side_depth(replay, self.side_sign)
        self.opp_start = self.side_depth(replay, -self.side_sign)
        self.valid_book = True

    def sample_end(self, replay: BookReplay, window: int) -> None:
        if replay.valid:
            self.same_end[window] = self.side_depth(replay, self.side_sign)
            self.opp_end[window] = self.side_depth(replay, -self.side_sign)
        else:
            self.invalidated_by_gap = True

    def observe_delta(self, side: int, price_tick: int, delta_size: float, event_us: int) -> None:
        if not self.in_band(price_tick) or delta_size == 0.0:
            return
        age_sec = (event_us - self.anchor_us) / 1_000_000
        if age_sec < 0:
            return
        for window in WINDOWS_SEC:
            if age_sec > window:
                continue
            same = side == self.side_sign
            if same and delta_size > 0:
                self.same_add[window] += delta_size
            elif same:
                self.same_remove[window] += -delta_size
            elif delta_size > 0:
                self.opp_add[window] += delta_size
            else:
                self.opp_remove[window] += -delta_size

    def to_row(self) -> dict[str, object]:
        row: dict[str, object] = {
            "session": self.session,
            "anchor_id": self.anchor_id,
            "candidate_id": self.candidate_id,
            "evidence_side": self.evidence_side,
            "direction": self.direction,
            "formed_ts": self.formed_ts.isoformat(),
            "anchor_ts": self.anchor_ts.isoformat(),
            "end_ts": self.end_ts.isoformat() if self.end_ts else "",
            "outcome": self.outcome,
            "min_tick": self.min_tick,
            "max_tick": self.max_tick,
            "event_count": self.event_count,
            "score": self.score,
            "kind_count": self.kind_count,
            "duration_sec": self.duration_sec,
            "form_age_sec": self.form_age_sec,
            "gap_contaminated": self.gap_contaminated,
            "valid_book": self.valid_book,
            "invalidated_by_gap": self.invalidated_by_gap,
            "same_start": self.same_start,
            "opp_start": self.opp_start,
        }
        for horizon, value in self.future_ticks.items():
            row[f"future_{horizon}s_ticks"] = value
        for window in WINDOWS_SEC:
            same_start = self.same_start if self.same_start is not None else math.nan
            same_end = self.same_end[window]
            same_net = self.same_add[window] - self.same_remove[window]
            opp_net = self.opp_add[window] - self.opp_remove[window]
            attack = self.attack_vol[window]
            same_depth_change = (
                same_end - same_start
                if same_end is not None and math.isfinite(same_start)
                else None
            )
            opp_depth_change = (
                self.opp_end[window] - self.opp_start
                if self.opp_end[window] is not None and self.opp_start is not None
                else None
            )
            held_ratio = (
                same_end / max(1.0, same_start)
                if same_end is not None and math.isfinite(same_start)
                else None
            )
            replenishment = (
                attack + ((same_end or 0.0) - same_start)
                if same_end is not None and math.isfinite(same_start)
                else None
            )
            row.update(
                {
                    f"same_add_{window}s": self.same_add[window],
                    f"same_remove_{window}s": self.same_remove[window],
                    f"opp_add_{window}s": self.opp_add[window],
                    f"opp_remove_{window}s": self.opp_remove[window],
                    f"same_net_{window}s": same_net,
                    f"opp_net_{window}s": opp_net,
                    f"same_end_{window}s": same_end,
                    f"opp_end_{window}s": self.opp_end[window],
                    f"same_depth_change_{window}s": same_depth_change,
                    f"opp_depth_change_{window}s": opp_depth_change,
                    f"held_ratio_{window}s": held_ratio,
                    f"attack_vol_{window}s": attack,
                    f"aligned_vol_{window}s": self.aligned_vol[window],
                    f"replenishment_{window}s": replenishment,
                    f"reload_ratio_{window}s": (
                        replenishment / max(1.0, attack)
                        if replenishment is not None
                        else None
                    ),
                    f"hidden_ratio_{window}s": (
                        attack / max(1.0, same_start)
                        if math.isfinite(same_start)
                        else None
                    ),
                }
            )
        return row


def parse_session(value: str, default_window: str) -> SessionSpec:
    parts = value.split(":", 2)
    if len(parts) < 2:
        raise argparse.ArgumentTypeError("session must be YYYY-MM-DD:SYMBOL[:HH:MM-HH:MM]")
    date, symbol = parts[0], parts[1]
    window = parts[2] if len(parts) == 3 else default_window
    start, end = parse_window(date, window)
    if end <= start:
        raise argparse.ArgumentTypeError("session window end must be after start")
    return SessionSpec(date=date, symbol=symbol, window=window)


def parse_window(date: str, window: str) -> tuple[datetime, datetime]:
    start_s, end_s = window.split("-", 1)
    return parse_ny(date, start_s), parse_ny(date, end_s)


def replay_args(args: argparse.Namespace, spec: SessionSpec) -> SimpleNamespace:
    return SimpleNamespace(
        capture_root=args.capture_root,
        window=spec.window,
        warmup_min=args.warmup_min,
        gap_threshold_sec=args.gap_threshold_sec,
        event_z=args.event_z,
        book_lookback_sec=args.book_lookback_sec,
        cluster_min_events=args.cluster_min_events,
        cluster_ticks=args.cluster_ticks,
        cluster_sec=args.cluster_sec,
        cluster_min_score=args.cluster_min_score,
        confirm_ticks=args.confirm_ticks,
        confirm_sec=args.confirm_sec,
        test_buffer_ticks=args.test_buffer_ticks,
        fail_buffer_ticks=args.fail_buffer_ticks,
        fail_confirm_ticks=args.fail_confirm_ticks,
        fail_sec=args.fail_sec,
        hold_confirm_ticks=args.hold_confirm_ticks,
    )


def chunk_groups(files: list[str]) -> list[list[str]]:
    groups: dict[str, list[str]] = {}
    order: list[str] = []
    for path in files:
        key = os.path.join(os.path.dirname(path), CHUNK_PART_RE.sub("", os.path.basename(path)))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(path)
    return [groups[key] for key in order]


def event_deltas(replay: BookReplay, row: dict) -> list[tuple[int, int, float]]:
    if int(row["event_kind"]) != DELTA or not replay.seeded or not replay.valid:
        return []
    quote_id = int(row["quote_id_hash"])
    prior = replay.quotes.get(quote_id)
    if bool(row["closed"]):
        if prior is None:
            return []
        return [(prior.side, prior.price_tick, -prior.size)]

    side = int(row["side"])
    price_tick = int(row["price_tick"])
    size = float(row["size"])
    if quote_id == 0 or side not in (-1, 1) or price_tick == -(2**63):
        return []
    if not math.isfinite(size) or size < 0:
        return []
    if prior is None:
        return [(side, price_tick, size)] if size > 0 else []
    if prior.side == side and prior.price_tick == price_tick:
        delta = size - prior.size
        return [(side, price_tick, delta)] if abs(delta) > 1e-9 else []
    result = [(prior.side, prior.price_tick, -prior.size)]
    if size > 0:
        result.append((side, price_tick, size))
    return result


def stream_book_metrics(
    capture_root: str,
    spec: SessionSpec,
    anchors: list[AnchorMetrics],
    stop: datetime,
    max_carry_days: int,
) -> Health:
    files, carry_days = event_files_with_carry(capture_root, spec.symbol, spec.date, max_carry_days)
    health = Health(files=len(files), carry_days=carry_days)
    ordered = sorted(anchors, key=lambda item: item.anchor_us)
    next_anchor = 0
    active: list[AnchorMetrics] = []
    replay = BookReplay()
    stop_us = us(stop)

    def activate_until(event_us: int) -> None:
        nonlocal next_anchor
        while next_anchor < len(ordered) and ordered[next_anchor].anchor_us <= event_us:
            anchor = ordered[next_anchor]
            anchor.sample_start(replay)
            active.append(anchor)
            next_anchor += 1

    def sample_due(event_us: int) -> None:
        for anchor in active:
            for window in WINDOWS_SEC:
                if anchor.same_end[window] is None and anchor.anchor_us + window * 1_000_000 <= event_us:
                    anchor.sample_end(replay, window)

    def prune_active(event_us: int) -> None:
        active[:] = [anchor for anchor in active if anchor.max_end_us > event_us]

    groups = chunk_groups(files)
    for group in groups:
        df = (
            pl.read_parquet(group, columns=EVENT_COLUMNS)
            .filter(pl.col("receipt_timestamp_us") <= stop_us)
            .sort(["receipt_timestamp_us", "sequence", "subsequence"])
        )
        for row in df.iter_rows(named=True):
            event_us = int(row["receipt_timestamp_us"])
            sample_due(event_us)
            prune_active(event_us)
            activate_until(event_us)
            if event_us > stop_us:
                break
            kind = int(row["event_kind"])
            if kind in (GAP, RESET_BEGIN):
                for anchor in active:
                    anchor.invalidated_by_gap = True
            deltas = event_deltas(replay, row)
            for anchor in active:
                if not anchor.valid_book:
                    continue
                for side, price_tick, delta in deltas:
                    anchor.observe_delta(side, price_tick, delta, event_us)
            crossed_before = replay.crossed_levels_evicted
            replay.apply(row)
            health.rows_processed += 1
            if kind == DELTA and replay.valid:
                health.valid_deltas += 1
            if kind == RESET_BEGIN:
                health.resets += 1
            elif kind == GAP:
                health.gaps += 1
            if replay.crossed_levels_evicted > crossed_before:
                health.crossed_levels_evicted = replay.crossed_levels_evicted
                health.crossed_quotes_evicted = replay.crossed_quotes_evicted
        if df.height and int(df[-1, "receipt_timestamp_us"]) > stop_us:
            break

    sample_due(stop_us + max(WINDOWS_SEC) * 1_000_000)
    return health


def add_tick_metrics(capture_root: str, spec: SessionSpec, anchors: list[AnchorMetrics]) -> None:
    start, end = parse_window(spec.date, spec.window)
    metric_end = end + timedelta(seconds=max(WINDOWS_SEC) + 1)
    ticks = load_capture_window(
        "ticks",
        spec.symbol,
        start,
        metric_end,
        tick_columns(),
        inclusive_end=True,
    )
    times = ticks["timestamp_us"].to_list()
    prices = ticks["price"].to_list()
    sizes = ticks["size"].to_list()
    signs = ticks["aggressor_sign"].to_list()
    for anchor in anchors:
        lo = bisect.bisect_left(times, anchor.anchor_us)
        for window in WINDOWS_SEC:
            hi = bisect.bisect_right(times, anchor.anchor_us + window * 1_000_000)
            attack = 0.0
            aligned = 0.0
            for idx in range(lo, hi):
                price = float(prices[idx])
                price_tick = int(round(price / TICK_SIZE))
                if not anchor.in_band(price_tick):
                    continue
                size = float(sizes[idx])
                sign = int(signs[idx])
                if sign == -anchor.side_sign:
                    attack += size
                elif sign == anchor.side_sign:
                    aligned += size
            anchor.attack_vol[window] = attack
            anchor.aligned_vol[window] = aligned


def snapshot_depth(row: dict, anchor: AnchorMetrics, side: int) -> float:
    total = 0.0
    ref = int(row["ref_tick"])
    prefix = "bid" if side > 0 else "ask"
    for idx in range(30):
        size = float(row[f"{prefix}_size_{idx}"])
        if not math.isfinite(size) or size <= 0:
            continue
        tick = ref + int(row[f"{prefix}_offset_{idx}"])
        if anchor.min_tick <= tick <= anchor.max_tick:
            total += size
    return total


def add_snapshot_depth_metrics(capture_root: str, spec: SessionSpec, anchors: list[AnchorMetrics]) -> None:
    start, end = parse_window(spec.date, spec.window)
    snapshots = load_capture_window(
        "snapshots",
        spec.symbol,
        start - timedelta(seconds=3),
        end + timedelta(seconds=max(WINDOWS_SEC) + 3),
        snapshot_columns(30),
        inclusive_end=True,
    )
    times = snapshots["timestamp_us"].to_list()
    rows = snapshots.to_dicts()

    def row_at(target_us: int) -> tuple[dict | None, float]:
        idx = bisect.bisect_right(times, target_us) - 1
        if idx < 0:
            return None, math.inf
        age = max(0.0, (target_us - int(times[idx])) / 1_000_000)
        return rows[idx], age

    for anchor in anchors:
        start_row, start_age = row_at(anchor.anchor_us)
        if start_row is None or start_age > 2.5:
            continue
        anchor.same_start = snapshot_depth(start_row, anchor, anchor.side_sign)
        anchor.opp_start = snapshot_depth(start_row, anchor, -anchor.side_sign)
        anchor.valid_book = True
        for window in WINDOWS_SEC:
            end_row, end_age = row_at(anchor.anchor_us + window * 1_000_000)
            if end_row is None or end_age > 2.5:
                anchor.invalidated_by_gap = True
                continue
            anchor.same_end[window] = snapshot_depth(end_row, anchor, anchor.side_sign)
            anchor.opp_end[window] = snapshot_depth(end_row, anchor, -anchor.side_sign)


def add_future_metrics(capture_root: str, spec: SessionSpec, anchors: list[AnchorMetrics]) -> None:
    start, end = parse_window(spec.date, spec.window)
    snapshots = load_capture_window(
        "snapshots",
        spec.symbol,
        start,
        end + timedelta(seconds=65),
        snapshot_columns(30),
        inclusive_end=True,
    )
    series = build_snapshot_series(snapshots, gap_threshold_sec=5.0)
    for anchor in anchors:
        for horizon in (10, 30, 60):
            anchor.future_ticks[horizon] = series.directional_future(
                anchor.anchor_ts,
                anchor.side_sign,
                horizon,
            )


def build_anchors(result, min_duration_sec: float) -> list[AnchorMetrics]:
    anchors: list[AnchorMetrics] = []
    for episode in result.episodes:
        if episode.direction != "favor":
            continue
        if episode.duration_sec < min_duration_sec:
            continue
        anchors.append(
            AnchorMetrics(
                session=result.label,
                anchor_id=len(anchors) + 1,
                candidate_id=episode.candidate_id,
                evidence_side=episode.evidence_side,
                direction=episode.direction,
                formed_ts=episode.formed_ts,
                anchor_ts=episode.start_ts,
                end_ts=episode.end_ts,
                outcome=episode.outcome,
                min_tick=episode.min_tick,
                max_tick=episode.max_tick,
                event_count=episode.event_count,
                score=episode.score,
                kind_count=episode.kind_count,
                duration_sec=episode.duration_sec,
                form_age_sec=episode.form_age_sec,
                gap_contaminated=episode.gap_contaminated,
            )
        )
    return anchors


def num(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def rank_auc(rows: list[dict[str, object]], metric: str) -> tuple[int, float | None]:
    pairs: list[tuple[float, int]] = []
    for row in rows:
        if row.get("outcome") not in ("confirmed", "reset"):
            continue
        value = num(row.get(metric))
        if value is None:
            continue
        pairs.append((value, 1 if row["outcome"] == "confirmed" else 0))
    pos = sum(label for _, label in pairs)
    neg = len(pairs) - pos
    if pos == 0 or neg == 0:
        return len(pairs), None
    ordered = sorted(enumerate(pairs), key=lambda item: item[1][0])
    ranks = [0.0] * len(pairs)
    i = 0
    while i < len(ordered):
        j = i + 1
        while j < len(ordered) and ordered[j][1][0] == ordered[i][1][0]:
            j += 1
        avg = (i + 1 + j) / 2.0
        for k in range(i, j):
            ranks[ordered[k][0]] = avg
        i = j
    rank_sum_pos = sum(rank for rank, (_, label) in zip(ranks, pairs) if label == 1)
    auc = (rank_sum_pos - pos * (pos + 1) / 2.0) / (pos * neg)
    return len(pairs), auc


def percentile(values: list[float], q: float) -> float | None:
    values = sorted(v for v in values if math.isfinite(v))
    if not values:
        return None
    idx = max(0, min(len(values) - 1, math.ceil(q * len(values)) - 1))
    return values[idx]


def outcome_rate(rows: list[dict[str, object]]) -> tuple[int, int, float | None]:
    resolved = [row for row in rows if row.get("outcome") in ("confirmed", "reset")]
    if not resolved:
        return 0, 0, None
    confirmed = sum(1 for row in resolved if row.get("outcome") == "confirmed")
    return confirmed, len(resolved), confirmed / len(resolved)


def bucket_line(rows: list[dict[str, object]], metric: str) -> str:
    values = [num(row.get(metric)) for row in rows]
    clean_values = [v for v in values if v is not None]
    lo = percentile(clean_values, 0.25)
    hi = percentile(clean_values, 0.75)
    if lo is None or hi is None:
        return f"- `{metric}`: insufficient data"
    low_rows = [row for row in rows if (num(row.get(metric)) is not None and num(row.get(metric)) <= lo)]
    high_rows = [row for row in rows if (num(row.get(metric)) is not None and num(row.get(metric)) >= hi)]
    low_c, low_n, low_rate = outcome_rate(low_rows)
    high_c, high_n, high_rate = outcome_rate(high_rows)
    n_auc, auc = rank_auc(rows, metric)
    low_s = "n/a" if low_rate is None else f"{low_c}/{low_n} {low_rate * 100:.1f}%"
    high_s = "n/a" if high_rate is None else f"{high_c}/{high_n} {high_rate * 100:.1f}%"
    auc_s = "n/a" if auc is None else f"{auc:.3f}"
    return (
        f"- `{metric}`: low<=p25 {low_s}, high>=p75 {high_s}, "
        f"AUC={auc_s} n={n_auc}"
    )


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_report(
    path: Path,
    specs: list[SessionSpec],
    session_results,
    health_by_session: dict[str, Health],
    rows: list[dict[str, object]],
    csv_path: Path,
) -> None:
    clean = [
        row
        for row in rows
        if not row.get("gap_contaminated")
        and row.get("valid_book") is True
        and row.get("invalidated_by_gap") is False
    ]
    resolved = [row for row in clean if row.get("outcome") in ("confirmed", "reset")]
    confirmed, total, rate = outcome_rate(clean)
    metrics = [
        "held_ratio_2s",
        "held_ratio_5s",
        "reload_ratio_2s",
        "reload_ratio_5s",
        "replenishment_5s",
        "hidden_ratio_5s",
        "attack_vol_5s",
        "same_depth_change_5s",
        "opp_depth_change_5s",
        "future_30s_ticks",
    ]

    lines = [
        "# EAR Contact Response Probe",
        "",
        "Research-only replay. Baseline population is current EAR-style favor-displacement episodes from the existing ownership/candidate grammar. Fast-pass contact metrics use canonical snapshot depth plus tape after the displacement starts; raw add/remove deltas are optional.",
        "",
        "## Sessions",
    ]
    for spec in specs:
        result = session_results[spec.label]
        health = health_by_session.get(spec.label, Health())
        lines.append(
            f"- {spec.label} {spec.window}: candidates={result.candidate_count}, "
            f"episodes={len(result.episodes)}, favor_anchors="
            f"{sum(1 for row in rows if row['session'] == spec.label)}, "
            f"snapshot_gaps={result.gap_count}, book_files={health.files}, "
            f"carry_days={health.carry_days}, book_rows={health.rows_processed}, "
            f"book_gaps={health.gaps}, crossed_repairs={health.crossed_levels_evicted}"
        )
    rate_s = "n/a" if rate is None else f"{confirmed}/{total} {rate * 100:.1f}%"
    lines.extend(
        [
            "",
            "## Baseline",
            f"- Clean resolved favor-displacement anchors: {rate_s}",
            f"- CSV: `{csv_path}`",
            "",
            "## Contact/Reload Separation",
        ]
    )
    for metric in metrics:
        lines.append(bucket_line(resolved, metric))

    lines.extend(
        [
            "",
            "## Exploratory Gate Read",
        ]
    )
    attack_values = [num(row.get("attack_vol_5s")) for row in resolved]
    reload_values = [num(row.get("reload_ratio_5s")) for row in resolved]
    hidden_values = [num(row.get("hidden_ratio_5s")) for row in resolved]
    attack_p50 = percentile([v for v in attack_values if v is not None], 0.50)
    attack_p75 = percentile([v for v in attack_values if v is not None], 0.75)
    reload_p75 = percentile([v for v in reload_values if v is not None], 0.75)
    hidden_p75 = percentile([v for v in hidden_values if v is not None], 0.75)
    if attack_p50 is not None and reload_p75 is not None:
        attacked = [
            row
            for row in resolved
            if (num(row.get("attack_vol_5s")) or 0.0) >= attack_p50
        ]
        reload_top = [
            row
            for row in attacked
            if (num(row.get("reload_ratio_5s")) is not None and num(row.get("reload_ratio_5s")) >= reload_p75)
        ]
        weak_response = [
            row
            for row in attacked
            if (num(row.get("reload_ratio_5s")) is not None and num(row.get("reload_ratio_5s")) < 0.0)
        ]
        lines.append(f"- Attack threshold p50={attack_p50:.2f}; reload p75={reload_p75:.2f}.")
        for label, subset in (("attacked", attacked), ("top_reload_response", reload_top), ("negative_reload_response", weak_response)):
            c, n, r = outcome_rate(subset)
            lines.append(f"- `{label}`: {c}/{n} {r * 100:.1f}%" if r is not None else f"- `{label}`: n/a")
    if hidden_p75 is not None:
        hidden_top = [
            row
            for row in resolved
            if (num(row.get("hidden_ratio_5s")) is not None and num(row.get("hidden_ratio_5s")) >= hidden_p75)
        ]
        c, n, r = outcome_rate(hidden_top)
        lines.append(f"- Thin-attack ratio p75={hidden_p75:.2f}: {c}/{n} {r * 100:.1f}%" if r is not None else "- Thin-attack ratio: n/a")
    if attack_p75 is not None:
        high_attack = [
            row
            for row in resolved
            if (num(row.get("attack_vol_5s")) is not None and num(row.get("attack_vol_5s")) >= attack_p75)
        ]
        high_attack_held = [
            row
            for row in high_attack
            if (num(row.get("held_ratio_5s")) is not None and num(row.get("held_ratio_5s")) >= 1.0)
        ]
        high_attack_depth_ok = [
            row
            for row in high_attack
            if (num(row.get("same_depth_change_5s")) is not None and num(row.get("same_depth_change_5s")) >= 0.0)
        ]
        high_attack_depth_bad = [
            row
            for row in high_attack
            if (num(row.get("same_depth_change_5s")) is not None and num(row.get("same_depth_change_5s")) < 0.0)
        ]
        lines.append(f"- Attack p75={attack_p75:.2f} paired checks:")
        for label, subset in (
            ("high_attack", high_attack),
            ("high_attack_and_held_ratio_ge_1", high_attack_held),
            ("high_attack_and_depth_nonnegative", high_attack_depth_ok),
            ("high_attack_and_depth_negative", high_attack_depth_bad),
        ):
            c, n, r = outcome_rate(subset)
            lines.append(f"  - `{label}`: {c}/{n} {r * 100:.1f}%" if r is not None else f"  - `{label}`: n/a")

    lines.extend(
        [
            "",
            "## Interpretation Guardrails",
            "- These gates are selected in-sample and are only useful for deciding what to test next.",
            "- `reload_ratio` follows Udit's aggregate idea: attack volume plus same-side size change, normalized by attack.",
            "- `hidden_ratio` is attack volume divided by displayed same-side depth in the candidate band. In this EAR population it behaved as thin support under attack, not supportive hidden liquidity.",
            "- Today may be partial/live. Treat June 23-24 as the completed-session base.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def default_sessions(capture_root: str, symbol: str, window: str, days: int) -> list[str]:
    symbol_root = Path(capture_root) / symbol
    dates = sorted(
        path.name
        for path in symbol_root.iterdir()
        if path.is_dir() and re.match(r"\d{4}-\d{2}-\d{2}$", path.name)
    )
    return [f"{date}:{symbol}:{window}" for date in dates[-days:]]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture-root", default=MARKET_RECORDER_ROOT)
    parser.add_argument("--session", action="append")
    parser.add_argument("--symbol-dir", default="NQU6")
    parser.add_argument("--days", type=int, default=3)
    parser.add_argument("--window", default="09:30-16:00")
    parser.add_argument("--warmup-min", type=int, default=90)
    parser.add_argument("--gap-threshold-sec", type=float, default=5.0)
    parser.add_argument("--max-carry-days", type=int, default=7)
    parser.add_argument(
        "--book-events",
        action="store_true",
        help="Also stream raw book-events for add/remove deltas. Slower; snapshot depth is always used.",
    )
    parser.add_argument("--min-duration-sec", type=float, default=0.0)
    parser.add_argument("--event-z", type=float, default=2.5)
    parser.add_argument("--book-lookback-sec", type=int, default=30)
    parser.add_argument("--cluster-min-events", type=int, default=3)
    parser.add_argument("--cluster-ticks", type=int, default=10)
    parser.add_argument("--cluster-sec", type=int, default=90)
    parser.add_argument("--cluster-min-score", type=float, default=8.0)
    parser.add_argument("--confirm-ticks", type=int, default=8)
    parser.add_argument("--confirm-sec", type=int, default=10)
    parser.add_argument("--test-buffer-ticks", type=int, default=4)
    parser.add_argument("--fail-buffer-ticks", type=int, default=2)
    parser.add_argument("--fail-confirm-ticks", type=int, default=24)
    parser.add_argument("--fail-sec", type=int, default=20)
    parser.add_argument("--hold-confirm-ticks", type=int, default=10)
    parser.add_argument("--out-dir", default=str(RESEARCH / "out"))
    args = parser.parse_args()

    raw_sessions = args.session or default_sessions(args.capture_root, args.symbol_dir, args.window, args.days)
    specs = [parse_session(value, args.window) for value in raw_sessions]
    all_rows: list[dict[str, object]] = []
    session_results = {}
    health_by_session: dict[str, Health] = {}

    for spec in specs:
        result = replay_session(replay_args(args, spec), spec.date, spec.symbol)
        session_results[spec.label] = result
        anchors = build_anchors(result, args.min_duration_sec)
        if anchors:
            _, end = parse_window(spec.date, spec.window)
            add_snapshot_depth_metrics(args.capture_root, spec, anchors)
            add_tick_metrics(args.capture_root, spec, anchors)
            add_future_metrics(args.capture_root, spec, anchors)
            if args.book_events:
                health_by_session[spec.label] = stream_book_metrics(
                    args.capture_root,
                    spec,
                    anchors,
                    end + timedelta(seconds=max(WINDOWS_SEC) + 1),
                    args.max_carry_days,
                )
            else:
                health_by_session[spec.label] = Health()
        else:
            health_by_session[spec.label] = Health()
        all_rows.extend(anchor.to_row() for anchor in anchors)

    dates = "_".join(spec.date for spec in specs)
    out_dir = Path(args.out_dir)
    csv_path = out_dir / f"ear_contact_response_{dates}.csv"
    report_path = RESEARCH / f"EAR_CONTACT_RESPONSE_{dates}.md"
    write_csv(csv_path, all_rows)
    write_report(report_path, specs, session_results, health_by_session, all_rows, csv_path)
    print(f"wrote {csv_path}")
    print(f"wrote {report_path}")


if __name__ == "__main__":
    main()
