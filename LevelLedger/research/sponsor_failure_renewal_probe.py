"""Replay sponsor failures and nearby same-side renewal.

This probe targets a practical EAR question:

Strict sponsor failure exits immediately. If retries remain, EAR waits for a
fresh seed. When the sponsor failure was fake, the sponsor side may renew at
or near the failed area and the later fresh seed may be materially worse.

The primary labels are structural LL/EAR outcomes, not fixed-horizon price
excursion.
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Iterable

import polars as pl


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RESEARCH = ROOT / "research"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(RESEARCH))

from candidate_timing_probe import CandidateTimingProbe, load_filtered_snapshots  # noqa: E402
from capture_loader import MARKET_RECORDER_ROOT  # noqa: E402
from ownership_bands_probe import Transition, opposite  # noqa: E402
from replay_levelledger import (  # noqa: E402
    BOOK_LOOKBACK_SEC,
    EVENT_Z_THRESHOLD,
    abbrev,
    build_sample,
    ny_hms,
    parse_ny,
    snapshot_timing_summary,
)


DEFAULT_OUTPUT_DIR = ROOT / "research" / "out"


@dataclass(frozen=True)
class SessionSpec:
    date: str
    symbol: str
    window: str

    @property
    def label(self) -> str:
        return f"{self.date}:{self.symbol}"


@dataclass
class ReplayRun:
    spec: SessionSpec
    window_start: datetime
    window_end: datetime
    probe: CandidateTimingProbe
    snapshots: pl.DataFrame
    snapshot_gaps: int


def parse_session(value: str, default_window: str) -> SessionSpec:
    parts = value.split(":", 2)
    if len(parts) < 2:
        raise argparse.ArgumentTypeError("session must be YYYY-MM-DD:SYMBOL[:HH:MM-HH:MM]")
    window = parts[2] if len(parts) > 2 else default_window
    start, end = parse_window(parts[0], window)
    if end <= start:
        raise argparse.ArgumentTypeError("session window end must be after start")
    return SessionSpec(parts[0], parts[1], window)


def parse_window(date: str, window: str) -> tuple[datetime, datetime]:
    start_s, end_s = window.split("-", 1)
    return parse_ny(date, start_s), parse_ny(date, end_s)


def side_sign(side: str) -> int:
    return 1 if side == "demand" else -1


def center_tick(tr: Transition) -> float:
    return (tr.min_tick + tr.max_tick) / 2.0


def range_distance(left_min: int, left_max: int, right_min: int, right_max: int) -> int:
    if left_max < right_min:
        return right_min - left_max
    if right_max < left_min:
        return left_min - right_max
    return 0


def distance_from(origin: Transition, candidate: Transition) -> int:
    return range_distance(origin.min_tick, origin.max_tick, candidate.min_tick, candidate.max_tick)


def worse_ticks(side: str, from_tick: int, to_tick: int) -> int:
    if side == "demand":
        return to_tick - from_tick
    return from_tick - to_tick


def transition_price(tr: Transition) -> str:
    return abbrev(tr.current_mid_tick)


def replay_run(args: argparse.Namespace, spec: SessionSpec) -> ReplayRun:
    window_start, window_end = parse_window(spec.date, spec.window)
    replay_start = window_start - timedelta(minutes=args.warmup_min)
    snapshots = load_filtered_snapshots(
        args.capture_root,
        spec.symbol,
        spec.date,
        replay_start,
        window_end,
    )
    _, _, _, gaps = snapshot_timing_summary(snapshots, args.gap_threshold_sec)
    probe = CandidateTimingProbe(
        session=spec.label,
        gap_threshold_sec=args.gap_threshold_sec,
        event_z=args.event_z,
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
        book_lookback_sec=args.book_lookback_sec,
    )
    for row in snapshots.iter_rows(named=True):
        probe.on_sample(build_sample(row))
    probe.finish(window_end)
    return ReplayRun(spec, window_start, window_end, probe, snapshots, len(gaps))


def near_same_side_renewal(origin: Transition, tr: Transition, args: argparse.Namespace) -> bool:
    if tr.ts <= origin.ts:
        return False
    if (tr.ts - origin.ts).total_seconds() > args.renewal_sec:
        return False
    if tr.side != origin.side:
        return False
    if tr.action not in ("OWNED", "CONSUMED", "HOLD"):
        return False
    return distance_from(origin, tr) <= args.renewal_ticks


def same_side_band_beyond_failure(origin: Transition, tr: Transition, args: argparse.Namespace) -> bool:
    if tr.ts <= origin.ts:
        return False
    if (tr.ts - origin.ts).total_seconds() > args.renewal_sec:
        return False
    if tr.side != origin.side:
        return False
    if tr.action not in ("OWNED", "CONSUMED"):
        return False
    if distance_from(origin, tr) > args.beyond_ticks:
        return False
    if origin.side == "supply":
        return center_tick(tr) >= origin.max_tick
    return center_tick(tr) <= origin.min_tick


def fresh_same_side_band(tr: Transition) -> bool:
    return tr.action == "OWNED" and tr.source == f"{tr.side}_lean"


def later_same_side_seed(origin: Transition, tr: Transition, args: argparse.Namespace) -> bool:
    if tr.ts <= origin.ts:
        return False
    if (tr.ts - origin.ts).total_seconds() > args.seed_lookahead_sec:
        return False
    return tr.side == origin.side and tr.action in ("OWNED", "CONSUMED")


def nearby_after(origin: Transition, tr: Transition, args: argparse.Namespace) -> bool:
    if tr.ts <= origin.ts:
        return False
    if (tr.ts - origin.ts).total_seconds() > args.structure_lookahead_sec:
        return False
    return distance_from(origin, tr) <= args.structure_distance_ticks


def structural_outcome(origin: Transition, transitions: Iterable[Transition], args: argparse.Namespace) -> tuple[str, str, str]:
    sponsor_side = origin.side
    opposite_side = opposite(sponsor_side)
    for tr in sorted(transitions, key=lambda item: item.ts):
        if not nearby_after(origin, tr, args):
            continue
        if tr.action == "FAIL" and tr.side == opposite_side:
            return "sponsor_destroyed_opposite", tr.action, tr.side
        if tr.action in ("OWNED", "CONSUMED", "HOLD") and tr.side == sponsor_side:
            return "sponsor_renewed", tr.action, tr.side
        if tr.action in ("OWNED", "CONSUMED", "HOLD") and tr.side == opposite_side:
            return "opposition_renewed", tr.action, tr.side
        if tr.action == "FAIL" and tr.side == sponsor_side:
            return "sponsor_failed_again", tr.action, tr.side
    return "no_structural_followthrough", "", ""


def renewal_kind(renewal: Transition | None) -> str:
    if renewal is None:
        return "none"
    if renewal.action == "CONSUMED":
        return "direct_conversion"
    if renewal.action == "HOLD":
        return "hold"
    return "fresh_ownership"


def first_band_test(renewal: Transition, transitions: Iterable[Transition]) -> Transition | None:
    tests = [
        tr for tr in transitions
        if tr.band_id == renewal.band_id
        and tr.ts > renewal.ts
        and tr.action == "TEST"
    ]
    return min(tests, key=lambda item: item.ts) if tests else None


def failure_area_revisited(fail: Transition, snapshots: pl.DataFrame, args: argparse.Namespace) -> tuple[bool, float | None]:
    start_us = int(fail.ts.timestamp() * 1_000_000)
    end_us = int((fail.ts + timedelta(seconds=args.revisit_lookahead_sec)).timestamp() * 1_000_000)
    lo = fail.min_tick - args.revisit_buffer_ticks
    hi = fail.max_tick + args.revisit_buffer_ticks
    subset = snapshots.filter(
        (pl.col("timestamp_us") > start_us)
        & (pl.col("timestamp_us") <= end_us)
        & (pl.col("ref_tick") >= lo)
        & (pl.col("ref_tick") <= hi)
    )
    if subset.height == 0:
        return False, None
    first_us = int(subset["timestamp_us"][0])
    return True, (first_us - start_us) / 1_000_000


def probe_rows(run: ReplayRun, args: argparse.Namespace) -> list[dict[str, object]]:
    transitions = [
        tr for tr in run.probe.transitions
        if run.window_start <= tr.ts <= run.window_end
    ]
    transitions.sort(key=lambda item: item.ts)
    rows: list[dict[str, object]] = []
    for fail in transitions:
        if fail.action != "FAIL":
            continue
        renewals = [tr for tr in transitions if near_same_side_renewal(fail, tr, args)]
        beyond_bands = [tr for tr in transitions if same_side_band_beyond_failure(fail, tr, args)]
        seeds = [tr for tr in transitions if later_same_side_seed(fail, tr, args)]
        first_renewal = min(renewals, key=lambda item: item.ts) if renewals else None
        first_beyond = min(beyond_bands, key=lambda item: item.ts) if beyond_bands else None
        first_seed = min(seeds, key=lambda item: item.ts) if seeds else None
        outcome, next_action, next_side = structural_outcome(fail, transitions, args)
        revisited, revisit_delay_sec = failure_area_revisited(fail, run.snapshots, args)
        post_renewal_outcome = ""
        post_renewal_action = ""
        post_renewal_side = ""
        if first_renewal is not None:
            post_renewal_outcome, post_renewal_action, post_renewal_side = structural_outcome(
                first_renewal,
                transitions,
                args,
            )
        row: dict[str, object] = {
            "session": run.spec.label,
            "fail_ts": fail.ts.isoformat(),
            "fail_ny": ny_hms(fail.ts),
            "sponsor_side": fail.side,
            "fail_band_id": fail.band_id,
            "fail_source": fail.source,
            "fail_min_tick": fail.min_tick,
            "fail_max_tick": fail.max_tick,
            "fail_mid_tick": fail.current_mid_tick,
            "fail_mid_price": transition_price(fail),
            "fail_score": fail.score,
            "fail_event_count": fail.event_count,
            "snapshot_gaps": run.snapshot_gaps,
            "near_renewal": first_renewal is not None,
            "renewal_kind": renewal_kind(first_renewal),
            "beyond_same_side_band": first_beyond is not None,
            "beyond_fresh_same_side_band": first_beyond is not None and fresh_same_side_band(first_beyond),
            "failure_area_revisited": revisited,
            "failure_area_revisit_delay_sec": revisit_delay_sec,
            "structure_outcome": outcome,
            "next_action": next_action,
            "next_side": next_side,
            "post_renewal_outcome": post_renewal_outcome,
            "post_renewal_action": post_renewal_action,
            "post_renewal_side": post_renewal_side,
        }
        if first_renewal is not None:
            row.update(
                {
                    "renewal_ts": first_renewal.ts.isoformat(),
                    "renewal_ny": ny_hms(first_renewal.ts),
                    "renewal_action": first_renewal.action,
                    "renewal_source": first_renewal.source,
                    "renewal_band_id": first_renewal.band_id,
                    "renewal_min_tick": first_renewal.min_tick,
                    "renewal_max_tick": first_renewal.max_tick,
                    "renewal_mid_tick": first_renewal.current_mid_tick,
                    "renewal_mid_price": transition_price(first_renewal),
                    "renewal_delay_sec": (first_renewal.ts - fail.ts).total_seconds(),
                    "renewal_distance_ticks": distance_from(fail, first_renewal),
                    "renewal_worse_ticks": worse_ticks(fail.side, fail.current_mid_tick, first_renewal.current_mid_tick),
                }
            )
        if first_beyond is not None:
            first_test = first_band_test(first_beyond, transitions)
            time_to_test = (
                (first_test.ts - first_beyond.ts).total_seconds()
                if first_test is not None
                else None
            )
            row.update(
                {
                    "beyond_ts": first_beyond.ts.isoformat(),
                    "beyond_ny": ny_hms(first_beyond.ts),
                    "beyond_action": first_beyond.action,
                    "beyond_source": first_beyond.source,
                    "beyond_band_id": first_beyond.band_id,
                    "beyond_min_tick": first_beyond.min_tick,
                    "beyond_max_tick": first_beyond.max_tick,
                    "beyond_mid_tick": first_beyond.current_mid_tick,
                    "beyond_mid_price": transition_price(first_beyond),
                    "beyond_delay_sec": (first_beyond.ts - fail.ts).total_seconds(),
                    "beyond_distance_ticks": distance_from(fail, first_beyond),
                    "beyond_worse_ticks": worse_ticks(fail.side, fail.current_mid_tick, first_beyond.current_mid_tick),
                    "beyond_time_to_test_sec": time_to_test,
                    "beyond_untested_for_window": time_to_test is None or time_to_test >= args.untested_sec,
                }
            )
        if first_seed is not None:
            row.update(
                {
                    "seed_ts": first_seed.ts.isoformat(),
                    "seed_ny": ny_hms(first_seed.ts),
                    "seed_action": first_seed.action,
                    "seed_source": first_seed.source,
                    "seed_band_id": first_seed.band_id,
                    "seed_min_tick": first_seed.min_tick,
                    "seed_max_tick": first_seed.max_tick,
                    "seed_mid_tick": first_seed.current_mid_tick,
                    "seed_mid_price": transition_price(first_seed),
                    "seed_delay_sec": (first_seed.ts - fail.ts).total_seconds(),
                    "seed_distance_ticks": distance_from(fail, first_seed),
                    "seed_worse_ticks": worse_ticks(fail.side, fail.current_mid_tick, first_seed.current_mid_tick),
                }
            )
        rows.append(row)
    return rows


def pct(value: int, total: int) -> str:
    if total <= 0:
        return "n/a"
    return f"{100.0 * value / total:.1f}%"


def summarize(rows: list[dict[str, object]], fields: list[str]) -> list[str]:
    groups: dict[tuple[str, ...], Counter[str]] = defaultdict(Counter)
    for row in rows:
        key = tuple(str(row.get(field, "")) for field in fields)
        groups[key][str(row.get("structure_outcome", ""))] += 1
    if not groups:
        return ["No rows."]
    outcomes = sorted({outcome for counter in groups.values() for outcome in counter})
    lines = [
        "| " + " | ".join(fields) + " | n | " + " | ".join(outcomes) + " |",
        "| " + " | ".join("---" for _ in fields) + " | ---: | " + " | ".join("---:" for _ in outcomes) + " |",
    ]
    for key in sorted(groups):
        counter = groups[key]
        total = sum(counter.values())
        cells = [f"{counter[outcome]} ({pct(counter[outcome], total)})" for outcome in outcomes]
        lines.append("| " + " | ".join(key) + f" | {total} | " + " | ".join(cells) + " |")
    return lines


def numeric_summary(rows: list[dict[str, object]], field: str) -> str:
    values = [
        float(row[field])
        for row in rows
        if field in row and row[field] not in ("", None) and math.isfinite(float(row[field]))
    ]
    if not values:
        return "n/a"
    ordered = sorted(values)
    p75 = ordered[min(len(ordered) - 1, math.ceil(0.75 * len(ordered)) - 1)]
    p90 = ordered[min(len(ordered) - 1, math.ceil(0.90 * len(ordered)) - 1)]
    return f"n={len(values)} median={median(values):.1f} p75={p75:.1f} p90={p90:.1f}"


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_report(path: Path, rows: list[dict[str, object]], runs: list[ReplayRun], args: argparse.Namespace) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    direct = [row for row in rows if row.get("renewal_kind") == "direct_conversion"]
    renewed = [row for row in rows if row.get("near_renewal")]
    beyond = [row for row in rows if row.get("beyond_same_side_band")]
    fresh_beyond = [row for row in rows if row.get("beyond_fresh_same_side_band")]
    untested_beyond = [row for row in beyond if row.get("beyond_untested_for_window")]
    revisited = [row for row in rows if row.get("failure_area_revisited")]
    lines = [
        "# Sponsor Failure Renewal Probe",
        "",
        "Primary outcome is whether a failed sponsor side renews nearby and later proves structural consequence.",
        "",
        "## Sessions",
        "",
    ]
    for run in runs:
        lines.append(
            f"- `{run.spec.label}` `{run.spec.window}` transitions={len(run.probe.transitions)} "
            f"fail_rows={sum(1 for row in rows if row['session'] == run.spec.label)} "
            f"snapshot_gaps={run.snapshot_gaps}"
        )
    lines.extend(
        [
            "",
            "## Counts",
            "",
            f"- sponsor failure rows: `{len(rows)}`",
            f"- near same-side renewals: `{len(renewed)}` ({pct(len(renewed), len(rows))})",
            f"- direct-conversion renewals: `{len(direct)}` ({pct(len(direct), len(rows))})",
            f"- same-side bands beyond failure: `{len(beyond)}` ({pct(len(beyond), len(rows))})",
            f"- fresh same-side bands beyond failure: `{len(fresh_beyond)}` ({pct(len(fresh_beyond), len(rows))})",
            f"- beyond bands untested for window: `{len(untested_beyond)}` ({pct(len(untested_beyond), len(beyond))})",
            f"- failure area revisited: `{len(revisited)}` ({pct(len(revisited), len(rows))})",
            "",
            "## Outcome By Renewal Kind",
            "",
        ]
    )
    lines.extend(summarize(rows, ["renewal_kind"]))
    if renewed:
        lines.extend(["", "## Post-Renewal Outcome By Renewal Kind", ""])
        post_rows = [
            {**row, "structure_outcome": row.get("post_renewal_outcome", "")}
            for row in renewed
        ]
        lines.extend(summarize(post_rows, ["renewal_kind"]))
    lines.extend(["", "## Outcome By Side And Renewal Kind", ""])
    lines.extend(summarize(rows, ["sponsor_side", "renewal_kind"]))
    lines.extend(["", "## Outcome By Same-Side Band Beyond Failure", ""])
    lines.extend(summarize(rows, ["beyond_same_side_band", "beyond_fresh_same_side_band"]))
    if beyond:
        lines.extend(["", "## Outcome By Beyond Band Test State", ""])
        lines.extend(summarize(beyond, ["beyond_untested_for_window"]))
    lines.extend(["", "## Outcome By Failure Area Revisit", ""])
    lines.extend(summarize(rows, ["failure_area_revisited"]))
    lines.extend(
        [
            "",
            "## Price Penalty",
            "",
            f"- renewal worse ticks: {numeric_summary(renewed, 'renewal_worse_ticks')}",
            f"- beyond-band worse ticks: {numeric_summary(beyond, 'beyond_worse_ticks')}",
            f"- seed worse ticks: {numeric_summary([row for row in rows if 'seed_worse_ticks' in row], 'seed_worse_ticks')}",
            f"- direct-conversion renewal worse ticks: {numeric_summary(direct, 'renewal_worse_ticks')}",
            f"- beyond-band time to test: {numeric_summary(beyond, 'beyond_time_to_test_sec')}",
            f"- failure-area revisit delay: {numeric_summary(revisited, 'failure_area_revisit_delay_sec')}",
            "",
            "Positive worse ticks mean a later/re-entry location is worse for the sponsor side: higher for demand, lower for supply.",
            "",
            "## Parameters",
            "",
            f"- renewal_sec: `{args.renewal_sec}`",
            f"- renewal_ticks: `{args.renewal_ticks}`",
            f"- beyond_ticks: `{args.beyond_ticks}`",
            f"- untested_sec: `{args.untested_sec}`",
            f"- revisit_lookahead_sec: `{args.revisit_lookahead_sec}`",
            f"- revisit_buffer_ticks: `{args.revisit_buffer_ticks}`",
            f"- seed_lookahead_sec: `{args.seed_lookahead_sec}`",
            f"- structure_lookahead_sec: `{args.structure_lookahead_sec}`",
            f"- structure_distance_ticks: `{args.structure_distance_ticks}`",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", action="append", required=True, help="YYYY-MM-DD:SYMBOL[:HH:MM-HH:MM]")
    parser.add_argument("--window", default="09:30-16:00")
    parser.add_argument("--capture-root", default=MARKET_RECORDER_ROOT)
    parser.add_argument("--warmup-min", type=int, default=90)
    parser.add_argument("--event-z", type=float, default=EVENT_Z_THRESHOLD)
    parser.add_argument("--book-lookback-sec", type=int, default=BOOK_LOOKBACK_SEC)
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
    parser.add_argument("--gap-threshold-sec", type=float, default=5.0)
    parser.add_argument("--renewal-sec", type=int, default=180)
    parser.add_argument("--renewal-ticks", type=int, default=24)
    parser.add_argument("--beyond-ticks", type=int, default=40)
    parser.add_argument("--untested-sec", type=int, default=180)
    parser.add_argument("--revisit-lookahead-sec", type=int, default=600)
    parser.add_argument("--revisit-buffer-ticks", type=int, default=4)
    parser.add_argument("--seed-lookahead-sec", type=int, default=600)
    parser.add_argument("--structure-lookahead-sec", type=int, default=600)
    parser.add_argument("--structure-distance-ticks", type=int, default=80)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--tag", default="")
    args = parser.parse_args()

    specs = [parse_session(value, args.window) for value in args.session]
    tag = args.tag or "_".join(f"{spec.date}_{spec.symbol}" for spec in specs)
    rows: list[dict[str, object]] = []
    runs: list[ReplayRun] = []
    for spec in specs:
        run = replay_run(args, spec)
        runs.append(run)
        rows.extend(probe_rows(run, args))

    out_dir = Path(args.output_dir)
    csv_path = out_dir / f"sponsor_failure_renewal_probe_{tag}.csv"
    report_path = out_dir / f"sponsor_failure_renewal_probe_{tag}.md"
    write_csv(csv_path, rows)
    write_report(report_path, rows, runs, args)
    print(f"wrote {csv_path}")
    print(f"wrote {report_path}")


if __name__ == "__main__":
    main()
