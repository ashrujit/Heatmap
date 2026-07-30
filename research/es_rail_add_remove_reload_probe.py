"""Raw book-event add/remove/reload probe for ES rail contacts.

This is the second pass after ``es_rail_mechanism_probe.py``. The mechanism
probe used 1 Hz snapshot depth; this one replays MarketRecorder quote events so
same-side reload and pull can be separated from coarse snapshot net changes.
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median
from zoneinfo import ZoneInfo

import polars as pl


ROOT = Path(__file__).resolve().parents[1]
MR_RESEARCH = ROOT / "MarketRecorder" / "research"
sys.path.insert(0, str(ROOT / "research"))
sys.path.insert(0, str(MR_RESEARCH))

from capture_loader import MARKET_RECORDER_ROOT, us  # noqa: E402
from validate_book_events import (  # noqa: E402
    DELTA,
    GAP,
    RESET_BEGIN,
    BookReplay,
    event_files_with_carry,
)


NY = ZoneInfo("America/New_York")
TICK_SIZE = 0.25
WINDOWS_SEC = (0.25, 1.0, 2.0, 5.0, 10.0)
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
class ContactAnchor:
    contact_index: int
    row: dict[str, str]
    contact_ts: datetime
    low_tick: int
    high_tick: int
    probe_low_tick: int
    probe_high_tick: int
    owner_side: int
    valid_book: bool = False
    invalidated_by_gap: bool = False
    owner_start: float | None = None
    opp_start: float | None = None
    owner_add: dict[float, float] = field(default_factory=lambda: {w: 0.0 for w in WINDOWS_SEC})
    owner_remove: dict[float, float] = field(default_factory=lambda: {w: 0.0 for w in WINDOWS_SEC})
    opp_add: dict[float, float] = field(default_factory=lambda: {w: 0.0 for w in WINDOWS_SEC})
    opp_remove: dict[float, float] = field(default_factory=lambda: {w: 0.0 for w in WINDOWS_SEC})
    owner_end: dict[float, float | None] = field(default_factory=lambda: {w: None for w in WINDOWS_SEC})
    opp_end: dict[float, float | None] = field(default_factory=lambda: {w: None for w in WINDOWS_SEC})

    @property
    def contact_us(self) -> int:
        return us(self.contact_ts)

    @property
    def max_end_us(self) -> int:
        return self.contact_us + int(max(WINDOWS_SEC) * 1_000_000)

    @property
    def side(self) -> str:
        return self.row["side"]

    def in_probe(self, price_tick: int) -> bool:
        return self.probe_low_tick <= price_tick <= self.probe_high_tick

    def side_depth(self, replay: BookReplay, side: int) -> float:
        levels = replay.bid_levels if side > 0 else replay.ask_levels
        return sum(size for tick, size in levels.items() if self.probe_low_tick <= tick <= self.probe_high_tick)

    def sample_start(self, replay: BookReplay) -> None:
        if not replay.valid:
            return
        self.owner_start = self.side_depth(replay, self.owner_side)
        self.opp_start = self.side_depth(replay, -self.owner_side)
        self.valid_book = True

    def sample_end(self, replay: BookReplay, window: float) -> None:
        if not replay.valid:
            self.invalidated_by_gap = True
            return
        self.owner_end[window] = self.side_depth(replay, self.owner_side)
        self.opp_end[window] = self.side_depth(replay, -self.owner_side)

    def observe_delta(self, side: int, price_tick: int, delta_size: float, event_us: int) -> None:
        if not self.valid_book or not self.in_probe(price_tick) or abs(delta_size) < 1e-9:
            return
        age_sec = (event_us - self.contact_us) / 1_000_000
        if age_sec < 0:
            return
        for window in WINDOWS_SEC:
            if age_sec > window:
                continue
            if side == self.owner_side:
                if delta_size > 0:
                    self.owner_add[window] += delta_size
                else:
                    self.owner_remove[window] += -delta_size
            else:
                if delta_size > 0:
                    self.opp_add[window] += delta_size
                else:
                    self.opp_remove[window] += -delta_size

    def to_row(self) -> dict[str, object]:
        source = self.row.get("source", "")
        source_kind = "consumed" if source.endswith("_consumed") else "lean" if source.endswith("_lean") else source
        out: dict[str, object] = {
            "date": self.row["date"],
            "contact_ts": self.row["contact_ts"],
            "band_id": self.row["band_id"],
            "side": self.row["side"],
            "source": source,
            "source_kind": source_kind,
            "cohort": self.row["cohort"],
            "resolution": self.row["resolution"],
            "band_low": self.row["band_low"],
            "band_high": self.row["band_high"],
            "probe_low": price(self.probe_low_tick),
            "probe_high": price(self.probe_high_tick),
            "proximity_cost_ticks": parse_float(self.row.get("proximity_cost_ticks")),
            "puncture_ticks": parse_float(self.row.get("puncture_ticks")),
            "exit_entry_speed_ratio": parse_float(self.row.get("exit_entry_speed_ratio")),
            "valid_book": self.valid_book,
            "invalidated_by_gap": self.invalidated_by_gap,
            "owner_start": self.owner_start,
            "opp_start": self.opp_start,
        }
        for window in WINDOWS_SEC:
            label = window_label(window)
            owner_end = self.owner_end[window]
            opp_end = self.opp_end[window]
            owner_net = self.owner_add[window] - self.owner_remove[window]
            opp_net = self.opp_add[window] - self.opp_remove[window]
            owner_depth_change = (
                owner_end - self.owner_start
                if owner_end is not None and self.owner_start is not None
                else None
            )
            opp_depth_change = (
                opp_end - self.opp_start if opp_end is not None and self.opp_start is not None else None
            )
            owner_churn = self.owner_add[window] + self.owner_remove[window]
            opp_churn = self.opp_add[window] + self.opp_remove[window]
            out.update(
                {
                    f"owner_add_{label}": self.owner_add[window],
                    f"owner_remove_{label}": self.owner_remove[window],
                    f"owner_net_{label}": owner_net,
                    f"owner_churn_{label}": owner_churn,
                    f"owner_end_{label}": owner_end,
                    f"owner_depth_change_{label}": owner_depth_change,
                    f"owner_held_ratio_{label}": (
                        owner_end / max(1.0, self.owner_start)
                        if owner_end is not None and self.owner_start is not None
                        else None
                    ),
                    f"owner_reload_ratio_{label}": self.owner_add[window] / max(1.0, self.owner_remove[window]),
                    f"owner_renewal_share_{label}": (
                        self.owner_add[window] / owner_churn if owner_churn > 0 else None
                    ),
                    f"opp_add_{label}": self.opp_add[window],
                    f"opp_remove_{label}": self.opp_remove[window],
                    f"opp_net_{label}": opp_net,
                    f"opp_churn_{label}": opp_churn,
                    f"opp_end_{label}": opp_end,
                    f"opp_depth_change_{label}": opp_depth_change,
                    f"opp_pull_ratio_{label}": self.opp_remove[window] / max(1.0, self.opp_add[window]),
                }
            )
        return out


def parse_float(value: str | float | int | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        f = float(value)
    except ValueError:
        return None
    return f if math.isfinite(f) else None


def parse_ts(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=NY)


def tick_key(price_value: str | float) -> int:
    return int(round(float(price_value) / TICK_SIZE))


def price(tick: int) -> float:
    return tick * TICK_SIZE


def window_label(window: float) -> str:
    return f"{int(window * 1000)}ms" if window < 1 else f"{int(window)}s"


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
    """Return book deltas before applying a row.

    This mirrors the EAR contact-response probe so quote moves out of a band
    are counted as removals at their prior level.
    """

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


def load_contacts(path: Path, band_expand_ticks: int) -> list[ContactAnchor]:
    anchors: list[ContactAnchor] = []
    with path.open(newline="", encoding="utf-8") as f:
        for idx, row in enumerate(csv.DictReader(f), start=1):
            contact_ts = parse_ts(row["contact_ts"])
            low_tick = tick_key(row["band_low"])
            high_tick = tick_key(row["band_high"])
            side = row["side"]
            if side == "demand":
                owner_side = 1
            elif side == "supply":
                owner_side = -1
            else:
                raise ValueError(f"unknown side {side}")
            anchors.append(
                ContactAnchor(
                    contact_index=idx,
                    row=row,
                    contact_ts=contact_ts,
                    low_tick=low_tick,
                    high_tick=high_tick,
                    probe_low_tick=low_tick - band_expand_ticks,
                    probe_high_tick=high_tick + band_expand_ticks,
                    owner_side=owner_side,
                )
            )
    return anchors


def stream_day(
    capture_root: str,
    symbol_dir: str,
    date: str,
    anchors: list[ContactAnchor],
    max_carry_days: int,
) -> Health:
    files, carry_days = event_files_with_carry(capture_root, symbol_dir, date, max_carry_days)
    health = Health(files=len(files), carry_days=carry_days)
    ordered = sorted(anchors, key=lambda anchor: anchor.contact_us)
    next_anchor = 0
    active: list[ContactAnchor] = []
    replay = BookReplay()
    stop_us = max(anchor.max_end_us for anchor in ordered) if ordered else 0

    def activate_until(event_us: int) -> None:
        nonlocal next_anchor
        while next_anchor < len(ordered) and ordered[next_anchor].contact_us <= event_us:
            anchor = ordered[next_anchor]
            anchor.sample_start(replay)
            active.append(anchor)
            next_anchor += 1

    def sample_due(event_us: int) -> None:
        for anchor in active:
            for window in WINDOWS_SEC:
                if anchor.owner_end[window] is None and anchor.contact_us + int(window * 1_000_000) <= event_us:
                    anchor.sample_end(replay, window)

    def prune_active(event_us: int) -> None:
        active[:] = [anchor for anchor in active if anchor.max_end_us > event_us]

    for group in chunk_groups(files):
        df = (
            pl.read_parquet(group, columns=EVENT_COLUMNS)
            .filter(pl.col("receipt_timestamp_us") <= stop_us)
            .sort(["receipt_timestamp_us", "sequence", "subsequence"])
        )
        if df.is_empty():
            continue
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
                for side, price_tick, delta in deltas:
                    anchor.observe_delta(side, price_tick, delta, event_us)

            crossed_before = replay.crossed_levels_evicted
            replay.apply(row)
            health.rows_processed += 1
            if kind == DELTA and replay.valid:
                health.valid_deltas += 1
            elif kind == RESET_BEGIN:
                health.resets += 1
            elif kind == GAP:
                health.gaps += 1
            if replay.crossed_levels_evicted > crossed_before:
                health.crossed_levels_evicted = replay.crossed_levels_evicted
                health.crossed_quotes_evicted = replay.crossed_quotes_evicted
        if int(df[-1, "receipt_timestamp_us"]) > stop_us:
            break

    sample_due(stop_us + int(max(WINDOWS_SEC) * 1_000_000))
    return health


def clean_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        row
        for row in rows
        if row.get("valid_book") is True and row.get("invalidated_by_gap") is False
    ]


def num(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def pct(numer: int, denom: int) -> float | None:
    return numer / denom * 100.0 if denom else None


def med(rows: list[dict[str, object]], key: str) -> float | None:
    values = [value for row in rows if (value := num(row.get(key))) is not None]
    return median(values) if values else None


def positive_rate(rows: list[dict[str, object]], key: str) -> float | None:
    values = [value for row in rows if (value := num(row.get(key))) is not None]
    if not values:
        return None
    return sum(1 for value in values if value > 0) / len(values) * 100.0


def group_summary(rows: list[dict[str, object]], keys: list[str]) -> list[dict[str, object]]:
    groups: dict[tuple[object, ...], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        groups[tuple(row.get(key, "") for key in keys)].append(row)

    out: list[dict[str, object]] = []
    for group_key, bucket in sorted(groups.items()):
        result: dict[str, object] = {key: value for key, value in zip(keys, group_key)}
        result.update(
            {
                "n": len(bucket),
                "hold_pct": pct(sum(1 for row in bucket if row.get("resolution") == "HOLD"), len(bucket)),
                "med_speed_ratio": med(bucket, "exit_entry_speed_ratio"),
                "med_puncture_ticks": med(bucket, "puncture_ticks"),
                "med_owner_start": med(bucket, "owner_start"),
                "med_owner_add_2s": med(bucket, "owner_add_2s"),
                "med_owner_remove_2s": med(bucket, "owner_remove_2s"),
                "med_owner_net_2s": med(bucket, "owner_net_2s"),
                "owner_net_positive_2s_pct": positive_rate(bucket, "owner_net_2s"),
                "med_owner_held_ratio_2s": med(bucket, "owner_held_ratio_2s"),
                "med_owner_reload_ratio_2s": med(bucket, "owner_reload_ratio_2s"),
                "med_opp_pull_ratio_2s": med(bucket, "opp_pull_ratio_2s"),
                "med_owner_add_5s": med(bucket, "owner_add_5s"),
                "med_owner_remove_5s": med(bucket, "owner_remove_5s"),
                "med_owner_net_5s": med(bucket, "owner_net_5s"),
                "owner_net_positive_5s_pct": positive_rate(bucket, "owner_net_5s"),
                "med_owner_held_ratio_5s": med(bucket, "owner_held_ratio_5s"),
                "med_owner_reload_ratio_5s": med(bucket, "owner_reload_ratio_5s"),
                "med_opp_pull_ratio_5s": med(bucket, "opp_pull_ratio_5s"),
                "med_owner_net_10s": med(bucket, "owner_net_10s"),
                "med_owner_held_ratio_10s": med(bucket, "owner_held_ratio_10s"),
            }
        )
        out.append(result)
    return out


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def fmt(value: object, places: int = 2) -> str:
    f = num(value)
    if f is None:
        return "n/a"
    return f"{f:.{places}f}"


def md_table(rows: list[dict[str, object]], keys: list[str]) -> list[str]:
    if not rows:
        return ["n/a"]
    lines = [
        "| " + " | ".join(keys) + " |",
        "| " + " | ".join("---" for _ in keys) + " |",
    ]
    for row in rows:
        cells: list[str] = []
        for key in keys:
            value = row.get(key)
            if isinstance(value, float):
                cells.append(fmt(value, 2))
            elif value is None:
                cells.append("")
            else:
                cells.append(str(value))
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def interesting_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    wanted = [
        ("2026-07-29", "14:20"),
        ("2026-07-29", "14:23"),
        ("2026-07-29", "14:37"),
        ("2026-07-29", "14:56"),
        ("2026-07-29", "15:01"),
        ("2026-07-29", "15:04"),
        ("2026-07-29", "15:10"),
        ("2026-07-28", "10:00"),
        ("2026-07-28", "11:"),
    ]
    selected: list[dict[str, object]] = []
    for row in rows:
        ts = str(row.get("contact_ts", ""))
        for day, hhmm in wanted:
            if ts.startswith(day) and f" {hhmm}" in ts:
                selected.append(row)
                break
    return selected[:24]


def write_findings(
    path: Path,
    rows: list[dict[str, object]],
    clean: list[dict[str, object]],
    health_by_day: dict[str, Health],
    by_cohort: list[dict[str, object]],
    by_source_kind: list[dict[str, object]],
    by_source_kind_cohort: list[dict[str, object]],
    csv_path: Path,
    band_expand_ticks: int,
) -> None:
    invalid = len(rows) - len(clean)
    held_puncture = [row for row in clean if row.get("cohort") == "HELD_PUNCTURE"]
    failed_reentry = [row for row in clean if row.get("cohort") == "FAILED_REENTRY"]
    failed = [row for row in clean if row.get("cohort") == "FAILED"]
    held_no_puncture = [row for row in clean if row.get("cohort") == "HELD_NO_PUNCTURE"]
    lines = [
        "# ES Rail Add/Remove/Reload Probe",
        "",
        f"Source contacts: `{csv_path}`",
        f"Probe band: rail low/high plus {band_expand_ticks} ticks on both sides.",
        "Timing caveat: contacts are anchored to the second stored in the synthetic-band CSV; sub-second rows are directional, not execution precise.",
        "",
        "## Replay Health",
    ]
    for day, health in sorted(health_by_day.items()):
        lines.append(
            f"- {day}: files={health.files}, carry_days={health.carry_days}, "
            f"rows={health.rows_processed}, valid_deltas={health.valid_deltas}, "
            f"resets={health.resets}, gaps={health.gaps}, crossed_repairs={health.crossed_levels_evicted}"
        )
    lines.extend(
        [
            f"- Contacts: total={len(rows)}, clean={len(clean)}, invalid_or_gap={invalid}",
            "",
            "## Cohorts",
        ]
    )
    lines.extend(
        md_table(
            by_cohort,
            [
                "cohort",
                "n",
                "hold_pct",
                "med_speed_ratio",
                "med_puncture_ticks",
                "med_owner_net_2s",
                "owner_net_positive_2s_pct",
                "med_owner_held_ratio_2s",
                "med_owner_reload_ratio_2s",
                "med_opp_pull_ratio_2s",
                "med_owner_net_5s",
                "owner_net_positive_5s_pct",
                "med_owner_held_ratio_5s",
                "med_owner_reload_ratio_5s",
            ],
        )
    )
    lines.extend(["", "## Source Kind"])
    lines.extend(
        md_table(
            by_source_kind,
            [
                "source_kind",
                "n",
                "hold_pct",
                "med_puncture_ticks",
                "med_owner_net_2s",
                "med_owner_held_ratio_2s",
                "med_owner_reload_ratio_2s",
                "med_owner_net_5s",
                "med_owner_held_ratio_5s",
                "med_owner_reload_ratio_5s",
            ],
        )
    )
    lines.extend(["", "## Source Kind x Cohort"])
    lines.extend(
        md_table(
            by_source_kind_cohort,
            [
                "source_kind",
                "cohort",
                "n",
                "hold_pct",
                "med_puncture_ticks",
                "med_owner_net_2s",
                "med_owner_held_ratio_2s",
                "med_owner_reload_ratio_2s",
                "med_owner_net_5s",
                "med_owner_held_ratio_5s",
                "med_owner_reload_ratio_5s",
            ],
        )
    )
    lines.extend(
        [
            "",
            "## Read",
            f"- Held-puncture rows: n={len(held_puncture)}, median 2s owner net={fmt(med(held_puncture, 'owner_net_2s'))}, median 5s owner net={fmt(med(held_puncture, 'owner_net_5s'))}, median speed ratio={fmt(med(held_puncture, 'exit_entry_speed_ratio'))}.",
            f"- Held-no-puncture rows: n={len(held_no_puncture)}, median 2s owner net={fmt(med(held_no_puncture, 'owner_net_2s'))}, median 5s owner net={fmt(med(held_no_puncture, 'owner_net_5s'))}, median speed ratio={fmt(med(held_no_puncture, 'exit_entry_speed_ratio'))}.",
            f"- Failed-reentry rows: n={len(failed_reentry)}, median 2s owner net={fmt(med(failed_reentry, 'owner_net_2s'))}, median 5s owner net={fmt(med(failed_reentry, 'owner_net_5s'))}, median held ratio 5s={fmt(med(failed_reentry, 'owner_held_ratio_5s'))}.",
            f"- Failed rows: n={len(failed)}, median 2s owner net={fmt(med(failed, 'owner_net_2s'))}, median 5s owner net={fmt(med(failed, 'owner_net_5s'))}, median held ratio 5s={fmt(med(failed, 'owner_held_ratio_5s'))}.",
            "",
            "Interpretation: owner reload is gross owner-side add relative to owner-side remove inside/around the rail. Owner net/held ratio are stricter survival checks; they can stay weak even when gross reload is high if both add and remove churn are elevated.",
            "",
            "## Selected Rows",
        ]
    )
    selected = interesting_rows(clean)
    lines.extend(
        md_table(
            selected,
            [
                "date",
                "contact_ts",
                "band_id",
                "side",
                "source_kind",
                "cohort",
                "band_low",
                "band_high",
                "puncture_ticks",
                "exit_entry_speed_ratio",
                "owner_net_2s",
                "owner_held_ratio_2s",
                "owner_reload_ratio_2s",
                "owner_net_5s",
                "owner_held_ratio_5s",
                "owner_reload_ratio_5s",
                "opp_pull_ratio_2s",
            ],
        )
    )
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--contacts",
        type=Path,
        default=ROOT / "research" / "out" / "es_rail_mechanism_20260728_20260729" / "mechanism_contacts.csv",
    )
    parser.add_argument("--capture-root", default=MARKET_RECORDER_ROOT)
    parser.add_argument("--symbol-dir", default="ESU6")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "research" / "out" / "es_rail_add_remove_reload_20260728_20260729")
    parser.add_argument("--band-expand-ticks", type=int, default=2)
    parser.add_argument("--max-carry-days", type=int, default=7)
    args = parser.parse_args()

    anchors = load_contacts(args.contacts, args.band_expand_ticks)
    by_day: dict[str, list[ContactAnchor]] = defaultdict(list)
    for anchor in anchors:
        by_day[anchor.row["date"]].append(anchor)

    health_by_day: dict[str, Health] = {}
    for day, day_anchors in sorted(by_day.items()):
        health_by_day[day] = stream_day(
            args.capture_root,
            args.symbol_dir,
            day,
            day_anchors,
            args.max_carry_days,
        )

    rows = [anchor.to_row() for anchor in anchors]
    clean = clean_rows(rows)
    by_cohort = group_summary(clean, ["cohort"])
    by_source_kind = group_summary(clean, ["source_kind"])
    by_source_kind_cohort = group_summary(clean, ["source_kind", "cohort"])
    by_day_source_kind_cohort = group_summary(clean, ["date", "source_kind", "cohort"])

    args.out_dir.mkdir(parents=True, exist_ok=True)
    contact_csv = args.out_dir / "add_remove_contacts.csv"
    write_csv(contact_csv, rows)
    write_csv(args.out_dir / "clean_add_remove_contacts.csv", clean)
    write_csv(args.out_dir / "by_cohort.csv", by_cohort)
    write_csv(args.out_dir / "by_source_kind.csv", by_source_kind)
    write_csv(args.out_dir / "by_source_kind_cohort.csv", by_source_kind_cohort)
    write_csv(args.out_dir / "by_day_source_kind_cohort.csv", by_day_source_kind_cohort)
    write_findings(
        args.out_dir / "findings.md",
        rows,
        clean,
        health_by_day,
        by_cohort,
        by_source_kind,
        by_source_kind_cohort,
        contact_csv,
        args.band_expand_ticks,
    )
    print(f"wrote {len(rows)} contacts ({len(clean)} clean) to {args.out_dir}")


if __name__ == "__main__":
    main()
