from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


EVENT_LOG = Path(r"C:\Users\j\Documents\ExecAssistantRuntime\events.jsonl")
OUT_DIR = Path("research/out")
CSV_OUT = OUT_DIR / "ear_pause_release_events.csv"
REPORT_OUT = Path("research/EAR_PAUSE_RELEASE_2026-06-22_2026-06-25.md")
# All sessions covered by this probe are in June 2026, so New York is UTC-4.
NY = timezone(timedelta(hours=-4))
TICK_SIZE = 0.25


TERMINAL_STATES = {"Completed", "Cancelled", "Invalidated", "Expired", "Error", "Halted"}


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    # .NET writes seven fractional digits; Python accepts up to six.
    if "." in text:
        head, tail = text.split(".", 1)
        frac = tail
        suffix = ""
        for marker in ("+", "-"):
            pos = frac.find(marker)
            if pos > 0:
                suffix = frac[pos:]
                frac = frac[:pos]
                break
        text = f"{head}.{frac[:6]}{suffix}"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def ny_time(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return dt.astimezone(NY).strftime("%Y-%m-%d %H:%M:%S")


def price(tick: int | None) -> float | None:
    return None if tick is None else tick * TICK_SIZE


@dataclass
class Transition:
    line: int
    ts: datetime
    kind: str
    reason: str
    mid_tick: int | None
    bid: float | None
    ask: float | None
    band_id: int | None
    band_role: str | None
    band_side: str | None
    band_source: str | None
    band_state: str | None
    band_min_tick: int | None
    band_max_tick: int | None
    candidate_id: int | None
    candidate_side: str | None
    candidate_min_tick: int | None
    candidate_max_tick: int | None
    active_directive_id: str
    active_directive_side: str
    active_state: str


@dataclass
class DirectiveState:
    directive_id: str = ""
    side: str = ""
    state: str = "Idle"


def as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def load_transitions(path: Path) -> list[Transition]:
    transitions: list[Transition] = []
    state = DirectiveState()
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_no, line in enumerate(handle, 1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = parse_dt(event.get("event_utc") or event.get("ts_utc"))
            if ts is None:
                continue
            event_name = event.get("event")
            if event_name == "directive_accepted":
                state = DirectiveState(
                    directive_id=event.get("directive_id") or "",
                    side=event.get("side") or "",
                    state="Armed",
                )
                continue
            if event_name == "runtime_state":
                did = event.get("directive_id") or state.directive_id
                if did == state.directive_id:
                    state.state = event.get("to") or state.state
                continue
            if event_name != "evidence_transition":
                continue
            transitions.append(
                Transition(
                    line=line_no,
                    ts=ts,
                    kind=event.get("kind") or "",
                    reason=event.get("reason") or "",
                    mid_tick=as_int(event.get("mid_tick")),
                    bid=event.get("bid"),
                    ask=event.get("ask"),
                    band_id=as_int(event.get("band_id")),
                    band_role=event.get("band_role"),
                    band_side=event.get("band_side"),
                    band_source=event.get("band_source"),
                    band_state=event.get("band_state"),
                    band_min_tick=as_int(event.get("band_min_tick")),
                    band_max_tick=as_int(event.get("band_max_tick")),
                    candidate_id=as_int(event.get("candidate_id")),
                    candidate_side=event.get("candidate_side"),
                    candidate_min_tick=as_int(event.get("candidate_min_tick")),
                    candidate_max_tick=as_int(event.get("candidate_max_tick")),
                    active_directive_id=state.directive_id if state.state not in TERMINAL_STATES else "",
                    active_directive_side=state.side if state.state not in TERMINAL_STATES else "",
                    active_state=state.state,
                )
            )
    return transitions


def range_matches(a: Transition, b: Transition) -> bool:
    return (
        a.band_side == b.band_side
        and a.band_min_tick == b.band_min_tick
        and a.band_max_tick == b.band_max_tick
    )


def release_direction(side: str) -> str:
    return "Short" if side == "Demand" else "Long"


def desired_sponsor_side(side: str) -> str:
    return "Supply" if side == "Demand" else "Demand"


def favorable_move(side: str, start_tick: int, ticks: list[int]) -> tuple[int, int]:
    if not ticks:
        return 0, 0
    if side == "Demand":
        # LF clearing is short-direction.
        return max(0, start_tick - min(ticks)), max(0, max(ticks) - start_tick)
    # HF clearing is long-direction.
    return max(0, max(ticks) - start_tick), max(0, start_tick - min(ticks))


def distance_from_zone(side: str, mid_tick: int, min_tick: int, max_tick: int) -> int:
    if side == "Demand":
        return min_tick - mid_tick
    return mid_tick - max_tick


def sponsor_distance(side: str, zone_min: int, zone_max: int, sponsor_min: int, sponsor_max: int) -> int:
    if side == "Demand":
        # Short release wants new supply below the failed LF/demand zone.
        return zone_min - sponsor_max
    return sponsor_min - zone_max


def classify(transitions: list[Transition]) -> list[dict[str, Any]]:
    by_band: dict[tuple[str, int], list[Transition]] = {}
    for transition in transitions:
        if transition.band_id is not None:
            by_band.setdefault((transition.ts.astimezone(NY).date().isoformat(), transition.band_id), []).append(transition)

    parent_by_failure: dict[tuple[str, int], int] = {}
    last_owned_by_key: dict[tuple[str, str, int, int], Transition] = {}
    for transition in transitions:
        session = transition.ts.astimezone(NY).date().isoformat()
        if transition.kind == "RailOwned" and transition.band_id is not None:
            if transition.band_side and transition.band_min_tick is not None and transition.band_max_tick is not None:
                key = (session, transition.band_side, transition.band_min_tick, transition.band_max_tick)
                last_owned_by_key[key] = transition
        if (
            transition.kind == "FailureCandidateFormed"
            and transition.band_id is not None
            and transition.band_side
            and transition.band_min_tick is not None
            and transition.band_max_tick is not None
        ):
            key = (session, transition.band_side, transition.band_min_tick, transition.band_max_tick)
            parent = last_owned_by_key.get(key)
            if parent is not None:
                parent_by_failure[(session, transition.band_id)] = parent.band_id or 0

    mid_events = [t for t in transitions if t.mid_tick is not None]
    rows: list[dict[str, Any]] = []
    helds = [
        t
        for t in transitions
        if t.kind == "FailureHeld"
        and t.band_role == "FailureZone"
        and t.band_side in {"Demand", "Supply"}
        and t.band_id is not None
        and t.band_min_tick is not None
        and t.band_max_tick is not None
        and t.mid_tick is not None
    ]
    for held in helds:
        session = held.ts.astimezone(NY).date().isoformat()
        band_events = by_band.get((session, held.band_id or -1), [])
        clear = next((t for t in band_events if t.ts > held.ts and t.kind == "FailureInvalidated"), None)
        if clear is None:
            clear = next((t for t in band_events if t.ts > held.ts and t.kind == "FailureHeld"), None)
        parent_id = parent_by_failure.get((session, held.band_id or -1))
        parent_events = by_band.get((session, parent_id or -1), [])
        end_ts = clear.ts if clear else held.ts + timedelta(minutes=10)
        parent_test_after_held = any(
            t.kind == "RailTested" and held.ts < t.ts <= end_ts for t in parent_events
        )
        parent_hold_after_held = any(
            t.kind == "RailHeld" and held.ts < t.ts <= end_ts for t in parent_events
        )
        parent_failed = next(
            (t for t in parent_events if t.kind == "RailFailed" and held.ts < t.ts <= end_ts + timedelta(seconds=10)),
            None,
        )
        clear_mid = clear.mid_tick if clear and clear.mid_tick is not None else held.mid_tick
        clear_distance = distance_from_zone(
            held.band_side or "", clear_mid or held.mid_tick or 0,
            held.band_min_tick or 0, held.band_max_tick or 0)
        next_side = desired_sponsor_side(held.band_side or "")
        next_sponsor = next(
            (
                t for t in transitions
                if clear
                and t.ts > clear.ts
                and t.ts <= clear.ts + timedelta(minutes=10)
                and t.ts.astimezone(NY).date().isoformat() == session
                and t.kind == "RailOwned"
                and t.band_side == next_side
                and t.band_min_tick is not None
                and t.band_max_tick is not None
            ),
            None,
        )
        next_sponsor_s = (next_sponsor.ts - clear.ts).total_seconds() if clear and next_sponsor else None
        next_sponsor_dist = (
            sponsor_distance(
                held.band_side or "",
                held.band_min_tick or 0,
                held.band_max_tick or 0,
                next_sponsor.band_min_tick or 0,
                next_sponsor.band_max_tick or 0,
            )
            if next_sponsor
            else None
        )
        future_60 = [
            t.mid_tick for t in mid_events
            if clear and clear.ts < t.ts <= clear.ts + timedelta(seconds=60)
            and t.ts.astimezone(NY).date().isoformat() == session
        ]
        future_180 = [
            t.mid_tick for t in mid_events
            if clear and clear.ts < t.ts <= clear.ts + timedelta(seconds=180)
            and t.ts.astimezone(NY).date().isoformat() == session
        ]
        fav60, adv60 = favorable_move(held.band_side or "", clear_mid or held.mid_tick or 0, future_60)
        fav180, adv180 = favorable_move(held.band_side or "", clear_mid or held.mid_tick or 0, future_180)
        active_match = held.active_directive_side == release_direction(held.band_side or "")
        if clear is None:
            release_class = "open"
        elif parent_test_after_held:
            release_class = "tested_sponsor_release"
        elif clear_distance <= 20:
            release_class = "near_zone_untested_release"
        else:
            release_class = "late_untested_release"
        rows.append(
            {
                "session": held.ts.astimezone(NY).date().isoformat(),
                "held_ny": ny_time(held.ts),
                "failure_id": held.band_id,
                "kind": held.reason,
                "failure_side": held.band_side,
                "release_direction": release_direction(held.band_side or ""),
                "zone_low": price(held.band_min_tick),
                "zone_high": price(held.band_max_tick),
                "held_mid": price(held.mid_tick),
                "clear_ny": ny_time(clear.ts) if clear else "",
                "clear_kind": clear.kind if clear else "",
                "clear_mid": price(clear_mid),
                "clear_distance_ticks": clear_distance,
                "parent_rail_id": parent_id,
                "parent_test_after_held": parent_test_after_held,
                "parent_hold_after_held": parent_hold_after_held,
                "parent_failed_after_held": parent_failed is not None,
                "parent_failed_ny": ny_time(parent_failed.ts) if parent_failed else "",
                "active_directive_id": held.active_directive_id,
                "active_directive_side": held.active_directive_side,
                "active_state": held.active_state,
                "matches_active_directive": active_match,
                "next_same_dir_sponsor_id": next_sponsor.band_id if next_sponsor else "",
                "next_same_dir_sponsor_ny": ny_time(next_sponsor.ts) if next_sponsor else "",
                "next_same_dir_sponsor_low": price(next_sponsor.band_min_tick) if next_sponsor else "",
                "next_same_dir_sponsor_high": price(next_sponsor.band_max_tick) if next_sponsor else "",
                "next_same_dir_sponsor_seconds": next_sponsor_s,
                "next_same_dir_sponsor_distance_ticks": next_sponsor_dist,
                "favorable_60s_ticks": fav60,
                "adverse_60s_ticks": adv60,
                "favorable_180s_ticks": fav180,
                "adverse_180s_ticks": adv180,
                "release_class": release_class,
            }
        )
    return rows


def fmt_num(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, float):
        return f"{value:.1f}"
    return str(value)


def write_report(rows: list[dict[str, Any]]) -> None:
    days = sorted({row["session"] for row in rows})
    active = [row for row in rows if row["matches_active_directive"]]
    flat_active = [
        row for row in active
        if row["active_state"] in {"Armed", "Paused", "Waiting"}
    ]
    untested = [row for row in rows if row["release_class"] in {"near_zone_untested_release", "late_untested_release"}]
    active_untested = [row for row in active if row in untested]
    flat_active_untested = [row for row in flat_active if row in untested]
    near_active_untested = [row for row in active_untested if row["release_class"] == "near_zone_untested_release"]
    strong_flat_untested = [
        row for row in flat_active_untested
        if float(row["favorable_180s_ticks"] or 0) >= 40
        and float(row["adverse_180s_ticks"] or 0) <= 40
    ]
    bad_flat_untested = [
        row for row in flat_active_untested
        if float(row["adverse_180s_ticks"] or 0) > float(row["favorable_180s_ticks"] or 0)
    ]

    def count_by(items: list[dict[str, Any]], key: str) -> dict[str, int]:
        result: dict[str, int] = {}
        for item in items:
            result[str(item[key])] = result.get(str(item[key]), 0) + 1
        return dict(sorted(result.items()))

    lines: list[str] = []
    lines.append("# EAR Pause-Release Probe")
    lines.append("")
    lines.append(f"Source: `{EVENT_LOG}`")
    lines.append(f"Days covered: {', '.join(days)}")
    lines.append("")
    lines.append("## Counts")
    lines.append("")
    lines.append(f"- Held LF/HF objects: {len(rows)}")
    lines.append(f"- Held LF/HF matching active directive direction: {len(active)}")
    lines.append(f"- Flat-entry held LF/HF matching active directive direction: {len(flat_active)}")
    lines.append(f"- Untested releases: {len(untested)}")
    lines.append(f"- Untested releases matching active directive direction: {len(active_untested)}")
    lines.append(f"- Flat-entry untested releases matching active directive direction: {len(flat_active_untested)}")
    lines.append(f"- Near-zone untested releases matching active directive direction: {len(near_active_untested)}")
    lines.append(f"- Strong flat-entry untested releases: {len(strong_flat_untested)}")
    lines.append(f"- Bad flat-entry untested releases: {len(bad_flat_untested)}")
    lines.append(f"- Release classes: {count_by(rows, 'release_class')}")
    lines.append("")
    lines.append("## Flat-Entry Untested Releases")
    lines.append("")
    if flat_active_untested:
        lines.append("| held ET | LF/HF | zone | clear ET | clear dist | future 60/180 | next same-dir sponsor | class |")
        lines.append("| --- | --- | --- | --- | ---: | ---: | --- | --- |")
        for row in flat_active_untested:
            zone = f"{row['zone_low']:.2f}-{row['zone_high']:.2f}"
            future = f"{row['favorable_60s_ticks']}/{row['favorable_180s_ticks']} fav, {row['adverse_60s_ticks']}/{row['adverse_180s_ticks']} adv"
            sponsor = ""
            if row["next_same_dir_sponsor_id"] != "":
                sponsor = (
                    f"{row['next_same_dir_sponsor_ny'][11:]} "
                    f"{float(row['next_same_dir_sponsor_low']):.2f}-{float(row['next_same_dir_sponsor_high']):.2f} "
                    f"dist={fmt_num(row['next_same_dir_sponsor_distance_ticks'])}t"
                )
            lines.append(
                "| "
                + " | ".join(
                    [
                        row["held_ny"],
                        f"{row['kind']}->{row['release_direction']}",
                        zone,
                        row["clear_ny"],
                        fmt_num(row["clear_distance_ticks"]),
                        future,
                        sponsor,
                        row["release_class"],
                    ]
                )
                + " |"
            )
    else:
        lines.append("No flat-entry untested releases were found in the event log.")
    lines.append("")
    lines.append("## Strong Candidates")
    lines.append("")
    if strong_flat_untested:
        lines.append("| held ET | LF/HF | clear ET | future 180 | next same-dir sponsor | read |")
        lines.append("| --- | --- | --- | ---: | --- | --- |")
        for row in strong_flat_untested:
            sponsor = ""
            if row["next_same_dir_sponsor_id"] != "":
                sponsor = (
                    f"{row['next_same_dir_sponsor_ny'][11:]} "
                    f"{float(row['next_same_dir_sponsor_low']):.2f}-{float(row['next_same_dir_sponsor_high']):.2f} "
                    f"dist={fmt_num(row['next_same_dir_sponsor_distance_ticks'])}t"
                )
            read = "far sponsor" if row["next_same_dir_sponsor_distance_ticks"] not in {"", None} and float(row["next_same_dir_sponsor_distance_ticks"]) >= 20 else "near/inside sponsor"
            lines.append(
                "| "
                + " | ".join(
                    [
                        row["held_ny"],
                        f"{row['kind']}->{row['release_direction']}",
                        row["clear_ny"],
                        f"{row['favorable_180s_ticks']} fav / {row['adverse_180s_ticks']} adv",
                        sponsor,
                        read,
                    ]
                )
                + " |"
            )
    else:
        lines.append("No strong flat-entry untested releases met the provisional threshold.")
    lines.append("")
    lines.append("## Counterexamples")
    lines.append("")
    if bad_flat_untested:
        lines.append("| held ET | LF/HF | clear ET | future 180 | read |")
        lines.append("| --- | --- | --- | ---: | --- |")
        for row in bad_flat_untested:
            lines.append(
                "| "
                + " | ".join(
                    [
                        row["held_ny"],
                        f"{row['kind']}->{row['release_direction']}",
                        row["clear_ny"],
                        f"{row['favorable_180s_ticks']} fav / {row['adverse_180s_ticks']} adv",
                        "release alone is not enough",
                    ]
                )
                + " |"
            )
    else:
        lines.append("No bad flat-entry untested release counterexamples were found.")
    lines.append("")
    june25_open = [
        row for row in rows
        if row["held_ny"].startswith("2026-06-25 09:34")
    ]
    if june25_open:
        row = june25_open[0]
        lines.append("## June 25 Open Check")
        lines.append("")
        lines.append(
            "The 09:34 LF that paused the first short directive was not an untested "
            "release. Its parent demand rail was tested and held after the LF held, "
            "then the LF invalidated at 09:37:33 and the parent rail failed at "
            "09:37:36. The following 180 seconds showed "
            f"{row['favorable_180s_ticks']} favorable ticks and "
            f"{row['adverse_180s_ticks']} adverse ticks, with the next same-direction "
            f"supply sponsor at {row['next_same_dir_sponsor_ny'][11:]} "
            f"({float(row['next_same_dir_sponsor_low']):.2f}-"
            f"{float(row['next_same_dir_sponsor_high']):.2f}), "
            f"{row['next_same_dir_sponsor_distance_ticks']} ticks away."
        )
    lines.append("")
    lines.append("## Interpretation")
    lines.append("")
    lines.append(
        "This is a log-based probe. It detects whether the parent rail behind a held "
        "LF/HF was tested after the failure object held, whether the LF/HF cleared "
        "in the directive direction, and whether a later same-direction sponsor "
        "appeared away from the original zone."
    )
    lines.append("")
    lines.append(
        "A near-zone untested release is the closest candidate for a non-chasing "
        "pause-release entry: the pause cleared in the directive direction without "
        "asking the parent sponsor again, and the clear was still close enough to "
        "the LF/HF zone to be treated as a controlled continuation reference."
    )
    lines.append("")
    lines.append(
        "The counterexamples show that release alone cannot become a trigger. A "
        "tradeable version needs at least directive-side context, a tight clear "
        "near the LF/HF zone, and either immediate favorable continuation or a "
        "later same-direction sponsor that appears beyond the pause area."
    )
    lines.append("")
    REPORT_OUT.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    transitions = load_transitions(EVENT_LOG)
    rows = classify(transitions)
    with CSV_OUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else [])
        if rows:
            writer.writeheader()
            writer.writerows(rows)
    write_report(rows)
    print(f"transitions={len(transitions)} rows={len(rows)} csv={CSV_OUT} report={REPORT_OUT}")


if __name__ == "__main__":
    main()
