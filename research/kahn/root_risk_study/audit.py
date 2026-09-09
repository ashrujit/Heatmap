"""Codex-authored, read-only input audit of Kahn root ownership candidates."""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re


LIVE_KINDS = {"RailOwned", "RailHeld", "RailTested"}
RAIL_KINDS = LIVE_KINDS | {"RailFailed"}
EVENT_ID = re.compile(r"^live-ll-(\d+)-")


def stamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def rail_id(event_id: str | None) -> int | None:
    match = EVENT_ID.match(event_id or "")
    return int(match[1]) if match else None


def overlap(a: dict, b: dict) -> bool:
    return a["min_tick"] <= b["max_tick"] and b["min_tick"] <= a["max_tick"]


class Ledger:
    def __init__(self):
        self.generation = 0
        self.ready = False
        self.reset_at = None
        self.rails = {}
        self.candidates = {}
        self.campaign_id = None
        self.campaign_loaded_at = None
        self.epoch = None
        self.settings = {}

    def consume(self, row: dict, line: int) -> None:
        event = row.get("event")
        if event == "runtime_initialized":
            self.settings = {k: v for k, v in row.items() if k.startswith("ll_")}
        if event in {"runtime_initialized", "evidence_warmup_started"}:
            self.generation += 1
            self.rails.clear()
            self.candidates.clear()
            self.ready = False
            self.reset_at = row["ts_utc"]
            self.epoch = None
        if event == "evidence_warmup_completed":
            self.ready = True
        if event == "book_unusable":
            self.ready = False
        if event == "repair_episode":
            self.epoch = row.get("epoch", self.epoch)
        if event == "campaign_loaded":
            self.campaign_id = row["campaign_id"]
            self.campaign_loaded_at = row["ts_utc"]
        if event != "ll_transition":
            return
        self.ready = row.get("actionable", self.ready)
        at = row.get("event_utc", row["ts_utc"])
        candidate = row.get("candidate_id")
        if candidate is not None and row["kind"] == "CandidateFormed":
            self.candidates[candidate] = {"formed_at": at, "formed_line": line,
                                          "source_side": row.get("candidate_side")}
        if row["kind"] not in RAIL_KINDS or row.get("band_role") != "Rail":
            return
        identity = row["band_id"]
        rail = self.rails.setdefault(identity, {
            "id": identity, "first_seen_at": at, "first_seen_line": line,
            "owned_at": None, "owned_line": None, "failed_at": None,
            "held_at": None, "tested_at": None,
            **self.candidates.get(identity, {}),
        })
        rail.update(side=row["band_side"], source=row["band_source"],
                    min_tick=row["band_min_tick"], max_tick=row["band_max_tick"],
                    state=row["band_state"], last_at=at, last_line=line,
                    live=row["kind"] != "RailFailed")
        if row["kind"] == "RailOwned":
            rail["owned_at"] = rail["owned_at"] or at
            rail["owned_line"] = rail["owned_line"] or line
        elif row["kind"] == "RailFailed":
            rail["failed_at"] = at
        elif row["kind"] == "RailHeld":
            rail["held_at"] = at
        elif row["kind"] == "RailTested":
            rail["tested_at"] = at

    def entry_snapshot(self, row: dict, line: int) -> dict:
        identity = rail_id(row.get("evidence_id"))
        trigger = deepcopy(self.rails.get(identity))
        side = row["evidence_side"]
        if row.get("evidence_kind") == "RailFailed":
            side = {"Demand": "Supply", "Supply": "Demand"}[side]
        same = [deepcopy(r) for r in self.rails.values()
                if r["side"] == side and r["live"] and r["owned_at"]]
        directional = []
        if trigger:
            for owner in same:
                behind = (owner["min_tick"] > trigger["max_tick"] if side == "Supply"
                          else owner["max_tick"] < trigger["min_tick"])
                if not behind:
                    continue
                owner = deepcopy(owner)
                owner["known_before_trigger_formed"] = (
                    stamp(owner["owned_at"]) <= stamp(trigger["formed_at"])
                    if trigger.get("formed_at") else None)
                owner["last_defense_at"] = owner["held_at"] or owner["owned_at"]
                directional.append(owner)
        directional.sort(key=lambda r: (r["min_tick"], r["id"]))
        return {
            "entry_line": line, "entry_at": row["ts_utc"],
            "campaign_id": row["campaign_id"], "reason": row["reason_code"],
            "evidence_kind": row["evidence_kind"], "campaign_side": side,
            "association_status": "not_resolved_by_this_audit",
            "generation": self.generation, "epoch": self.epoch,
            "ll_ready": self.ready, "ll_reset_at": self.reset_at,
            "campaign_loaded_at": self.campaign_loaded_at,
            "configured_risk_anchor": row.get("risk_anchor"),
            "execution_attempts_before": row.get("execution_attempt_count"),
            "trigger": trigger, "live_same_side": same,
            "directional_candidates": directional,
            "overlapping_candidate_pairs": [
                [a["id"], b["id"]] for i, a in enumerate(directional)
                for b in directional[i + 1:] if overlap(a, b)],
            "settings": deepcopy(self.settings),
        }


def reconstruct(rows: list[tuple[int, dict]], start: str, end: str) -> list[dict]:
    ledger = Ledger()
    entries = []
    for line, row in rows:
        ledger.consume(row, line)
        if (row.get("event") == "policy_decision" and row.get("action") == "AllowProbe"
                and stamp(start) <= stamp(row["ts_utc"]) <= stamp(end)):
            entries.append(ledger.entry_snapshot(row, line))
    return entries


def add_outcomes(entries: list[dict], rows: list[tuple[int, dict]], end: str) -> list[dict]:
    """Separate future labels from immutable entry snapshots."""
    results = []
    for entry in entries:
        outcomes = []
        own = entry["trigger"] or {}
        considered = {r["id"] for r in entry["directional_candidates"]}
        considered.add(own.get("id"))
        boundary = end
        for line, row in rows:
            if line <= entry["entry_line"]:
                continue
            if stamp(row["ts_utc"]) > stamp(end):
                break
            event = row.get("event")
            if event in {"runtime_initialized", "evidence_warmup_started", "campaign_loaded"}:
                boundary = row["ts_utc"]
                break
            if event == "policy_decision" and row.get("action") == "AllowProbe":
                boundary = row["ts_utc"]
                break
            if event == "ll_transition" and row.get("kind") in RAIL_KINDS:
                if row.get("band_id") not in considered:
                    continue
                outcomes.append({"line": line, "at": row["ts_utc"], "event": event,
                                 "kind": row["kind"], "rail_id": row["band_id"],
                                 "side": row["band_side"], "min_tick": row["band_min_tick"],
                                 "max_tick": row["band_max_tick"], "mid_tick": row["mid_tick"]})
            elif event in {"policy_decision", "trade_fill", "close_submit", "breakeven_submit",
                           "breakeven_backstop_flat_reconciled", "control_received"}:
                outcomes.append({"line": line, **{k: row[k] for k in (
                    "ts_utc", "event", "action", "reason_code", "evidence_id", "order_id",
                    "trade_id", "quantity", "price", "trigger_price", "side") if k in row}})
        results.append({"entry_line": entry["entry_line"], "censored_at": boundary,
                        "events": outcomes})
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if stamp(args.end) <= stamp(args.start):
        parser.error("end must follow start")
    rows = []
    digest = hashlib.sha256()
    # Freeze a complete prefix. A concurrently appended partial line is not evidence.
    with args.log.open("rb") as stream:
        for line, raw in enumerate(stream, 1):
            if not raw.endswith(b"\n"):
                break
            row = json.loads(raw)
            if stamp(row["ts_utc"]) > stamp(args.end):
                break
            digest.update(raw)
            rows.append((line, row))
    if not rows:
        parser.error("no complete log records at or before end")
    entries = reconstruct(rows, args.start, args.end)
    outcomes = add_outcomes(entries, rows, args.end)
    args.out.mkdir(parents=True, exist_ok=True)
    result = {"author": "Codex", "research_only": True,
              "input": str(args.log.resolve()), "prefix_sha256": digest.hexdigest(),
              "prefix_last_line": rows[-1][0], "start": args.start, "end": args.end,
              "entry_snapshots": entries, "future_outcomes": outcomes}
    (args.out / "audit.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"entries": len(entries), "prefix_last_line": rows[-1][0],
                      "output": str((args.out / "audit.json").resolve())}))


if __name__ == "__main__":
    main()
