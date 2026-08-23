"""Extract EAR conversion rails and their first-test verdicts from events.jsonl.

This replaces the synthetic LevelLedger replay as the event source for
direct-conversion research. Three reasons the synthetic layer was dropped:

1. Population mismatch. The LL replay recovers only roughly half to
   three-quarters of the rails EAR actually forms, so a study built on it is
   measuring a related-but-different set of events from the one EAR trades.
2. Outcome mismatch. The synthetic band lifecycle labelled the 2026-07-24
   12:10:42 add `retest_held` when the trade lost 9 points. EAR's own
   RailTested/RailHeld/RailFailed stream is the authority on whether a rail
   survived a test.
3. EAR's band boundaries are what execution actually keyed on.

Verdict semantics: every rail eventually emits `RailFailed`, because price
permanently leaves every level sooner or later. A cumulative "did it ever fail"
verdict is therefore useless - it is FAILED for essentially all rails. The
meaningful question, and the trader's own phrasing, is whether the rail survived
its FIRST test.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")
TICK_SIZE = 0.25

DEFAULT_EVENTS = Path.home() / "Documents" / "ExecAssistantRuntime" / "events.jsonl"

RAIL_KINDS = {"RailOwned", "RailTested", "RailHeld", "RailFailed"}


@dataclass
class Rail:
    band_id: int
    date: str
    owned_utc: datetime
    owned_et: str
    side: str  # Demand | Supply
    source: str  # Consumed | Lean
    min_tick: int
    max_tick: int
    history: list[tuple[datetime, str]] = field(default_factory=list)

    @property
    def min_price(self) -> float:
        return self.min_tick * TICK_SIZE

    @property
    def max_price(self) -> float:
        return self.max_tick * TICK_SIZE

    def first_test(self) -> tuple[str, datetime | None]:
        """Verdict at the first resolved test, plus that test's timestamp."""
        for ts, kind in sorted(self.history):
            if kind == "RailHeld":
                return "SURVIVED", ts
            if kind == "RailFailed":
                return "FAILED_FIRST_TEST", ts
        return "never_tested", None

    def test_count(self) -> int:
        return sum(1 for _, k in self.history if k == "RailTested")

    def holds(self) -> int:
        return sum(1 for _, k in self.history if k == "RailHeld")

    def final_fail_utc(self) -> datetime | None:
        fails = [ts for ts, k in self.history if k == "RailFailed"]
        return max(fails) if fails else None


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def load_rails(
    events_path: Path,
    dates: set[str] | None = None,
    sources: set[str] | None = None,
) -> list[Rail]:
    rails: dict[int, Rail] = {}
    history: dict[int, list[tuple[datetime, str]]] = defaultdict(list)

    with events_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if '"evidence_transition"' not in line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = event.get("kind")
            if kind not in RAIL_KINDS:
                continue
            band_id = event.get("band_id")
            if band_id is None:
                continue
            ts = parse_ts(event["ts_utc"])
            local = ts.astimezone(NY)
            day = local.date().isoformat()
            if dates and day not in dates:
                continue
            if kind == "RailOwned":
                source = event.get("band_source")
                if sources and source not in sources:
                    continue
                rails[band_id] = Rail(
                    band_id=band_id,
                    date=day,
                    owned_utc=ts,
                    owned_et=local.strftime("%H:%M:%S.%f")[:-3],
                    side=event.get("band_side"),
                    source=source,
                    min_tick=int(event.get("band_min_tick")),
                    max_tick=int(event.get("band_max_tick")),
                )
            else:
                history[band_id].append((ts, kind))

    for band_id, rail in rails.items():
        rail.history = history.get(band_id, [])
    # Band ids restart per runtime session, so a rail is only trustworthy when
    # its history follows its own ownership timestamp.
    for rail in rails.values():
        rail.history = [(ts, k) for ts, k in rail.history if ts >= rail.owned_utc]
    return sorted(rails.values(), key=lambda r: r.owned_utc)


FIELDS = [
    "date",
    "band_id",
    "owned_et",
    "owned_utc",
    "side",
    "source",
    "min_price",
    "max_price",
    "width_pts",
    "first_test_verdict",
    "first_test_et",
    "seconds_to_first_test",
    "test_count",
    "hold_count",
    "final_fail_et",
    "life_sec",
]


def rail_row(rail: Rail) -> dict[str, Any]:
    verdict, ts = rail.first_test()
    final = rail.final_fail_utc()
    return {
        "date": rail.date,
        "band_id": rail.band_id,
        "owned_et": rail.owned_et,
        "owned_utc": rail.owned_utc.isoformat(),
        "side": rail.side,
        "source": rail.source,
        "min_price": rail.min_price,
        "max_price": rail.max_price,
        "width_pts": round(rail.max_price - rail.min_price, 2),
        "first_test_verdict": verdict,
        "first_test_et": ts.astimezone(NY).strftime("%H:%M:%S.%f")[:-3] if ts else "",
        "seconds_to_first_test": round((ts - rail.owned_utc).total_seconds(), 2) if ts else "",
        "test_count": rail.test_count(),
        "hold_count": rail.holds(),
        "final_fail_et": final.astimezone(NY).strftime("%H:%M:%S.%f")[:-3] if final else "",
        "life_sec": round((final - rail.owned_utc).total_seconds(), 2) if final else "",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", default=str(DEFAULT_EVENTS))
    parser.add_argument("--dates", default="", help="comma-separated ET dates; blank = all")
    parser.add_argument("--source", default="Consumed", help="Consumed | Lean | all")
    parser.add_argument("--out", default="")
    parser.add_argument("--window", default="", help="HH:MM-HH:MM ET filter for the printed summary")
    parser.add_argument("--side", default="", help="Demand | Supply filter for printed summary")
    args = parser.parse_args()

    dates = {d.strip() for d in args.dates.split(",") if d.strip()} or None
    sources = None if args.source == "all" else {args.source}
    rails = load_rails(Path(args.events), dates, sources)
    rows = [rail_row(r) for r in rails]

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        print(f"wrote {out} ({len(rows)} rails)")

    sel = rows
    if args.side:
        sel = [r for r in sel if r["side"] == args.side]
    if args.window:
        lo, hi = args.window.split("-")
        sel = [r for r in sel if lo <= r["owned_et"][:5] <= hi]

    tested = [r for r in sel if r["first_test_verdict"] != "never_tested"]
    survived = [r for r in tested if r["first_test_verdict"] == "SURVIVED"]
    print(f"rails={len(sel)} tested={len(tested)} survived_first_test={len(survived)}"
          + (f" ({len(survived)/len(tested):.1%})" if tested else ""))
    for r in sel:
        print(f"  {r['date']} {r['owned_et']} {r['side']:6s}/{r['source']:8s} "
              f"{r['min_price']}-{r['max_price']:<9} {r['first_test_verdict']:18s} "
              f"t+{r['seconds_to_first_test']}s tests={r['test_count']} holds={r['hold_count']} life={r['life_sec']}")


if __name__ == "__main__":
    main()
