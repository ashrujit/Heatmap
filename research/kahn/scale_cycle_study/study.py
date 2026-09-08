"""Codex-authored causal Kahn scaling study for September 3-4, 2026.

Uses captured snapshots, the current linked C# LL/policy engine, and recorded
GexBot chain data. All positions are explicitly hypothetical research seeds.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import json
import math
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo
import sqlite3

import polars as pl

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "research"))
from capture_loader import load_capture_window, snapshot_columns  # noqa: E402

NY = ZoneInfo("America/New_York")
OUT = REPO / "research/out/kahn-scale-20260906"
DOTNET = Path.home() / "AppData/Local/Microsoft/dotnet/dotnet.exe"
ENGINE = Path(__file__).parent / "EngineProbe/bin/Release/net10.0/EngineProbe.dll"
KINDS = {"RailOwned", "RailHeld"}
CATEGORIES = ("gex_full", "gex_zero", "gex_one")
GATES = ("none", "price_side", "rail_side", "rail_renewed", "rail_rearmed", "negative_sum_vol")
METHODS = ("current_core", "direct_favorable", "serial_identity", "joint_range", "joint_price",
           "warm_serial_identity", "warm_joint_range", "warm_joint_price")


def stamp(day: str, hhmm: str) -> int:
    return int(datetime.fromisoformat(f"{day}T{hhmm}").replace(tzinfo=NY).timestamp() * 1e6)


def iso_us(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1e6)


def clock(t: int | None) -> str:
    return datetime.fromtimestamp(t / 1e6, NY).strftime("%H:%M:%S") if t is not None else ""


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, allow_nan=False), encoding="utf-8")


def write_lines(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, separators=(",", ":"), allow_nan=False) + "\n")


def read_lines(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def run_engine(*args: str | Path) -> None:
    subprocess.run([str(DOTNET), str(ENGINE), *map(str, args)], check=True)


def load_gex(day: str, symbol: str) -> dict[str, list[dict]]:
    db = REPO / "GexBotMcp/out/gexbot.sqlite"
    ticker = "ES_SPX" if symbol == "ES" else "NQ_NDX"
    con = sqlite3.connect(db.as_uri() + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    query = """SELECT id,recorded_at_utc,api_as_of_utc,category,spot,zero_gamma,
        call_wall,put_wall,sum_gex_vol,sum_gex_oi FROM snapshots
        WHERE ticker=? AND view='chain' AND ok=1
        AND substr(recorded_at_utc,1,10)=? ORDER BY recorded_at_utc,id"""
    result = {category: [] for category in CATEGORIES}
    for row in con.execute(query, (ticker, day)):
        r = dict(row)
        if r["category"] not in result or not r["api_as_of_utc"]:
            continue
        r["t"] = iso_us(r["recorded_at_utc"])
        r["api_t"] = iso_us(r["api_as_of_utc"])
        r["available_t"] = max(r["t"], r["api_t"])
        result[r["category"]].append(r)
    con.close()
    for rows in result.values():
        rows.sort(key=lambda r: (r["available_t"], r["id"]))
    return result


def prepare(symbol: str, day: str, *, output: Path = OUT, start_time: str = "09:00",
            end_time: str = "12:05", include_gex: bool = True) -> None:
    directory = output / f"{symbol}-{day}"
    directory.mkdir(parents=True, exist_ok=True)
    start = datetime.fromisoformat(day + "T" + start_time).replace(tzinfo=NY)
    end = datetime.fromisoformat(day + "T" + end_time).replace(tzinfo=NY)
    snap = load_capture_window("snapshots", symbol + "U6", start, end, snapshot_columns())
    snap = snap.sort("timestamp_us")
    duplicates = snap.height - snap["timestamp_us"].n_unique()
    snap = snap.unique(subset=["timestamp_us"], keep="last", maintain_order=True)
    raw_times = snap["timestamp_us"].to_list()
    gaps = [(a, b, (b - a) / 1e6) for a, b in zip(raw_times, raw_times[1:]) if b - a > 5e6]
    snapshots, quotes = [], []
    last_sample = -10**30
    invalid = 0
    for row in snap.iter_rows(named=True):
        t = row["timestamp_us"]
        levels = {}
        for side in ("bid", "ask"):
            levels[side] = [
                [(.25 * (row["ref_tick"] + row[f"{side}_offset_{i}"])), row[f"{side}_size_{i}"]]
                for i in range(30)
                if row[f"{side}_offset_{i}"] is not None
                and row[f"{side}_size_{i}"] is not None
                and math.isfinite(row[f"{side}_size_{i}"])
                and row[f"{side}_size_{i}"] > 0
            ]
        if not levels["bid"] or not levels["ask"] or levels["bid"][0][0] >= levels["ask"][0][0]:
            invalid += 1
            continue
        bid, ask = levels["bid"][0][0], levels["ask"][0][0]
        quotes.append({"t": t, "bid": bid, "ask": ask, "mid": (bid + ask) / 2})
        if t - last_sample >= 1_000_000:
            snapshots.append({"t": t, "bids": levels["bid"], "asks": levels["ask"]})
            last_sample = t
    write_lines(directory / "snapshots.jsonl", snapshots)
    pl.DataFrame(quotes).write_parquet(directory / "quotes.parquet")
    ticks = load_capture_window("ticks", symbol + "U6", start, end).sort("timestamp_us")
    ticks.write_parquet(directory / "ticks.parquet")
    # Preserve full tick order; duplicate timestamps are multiple real prints.
    bars = ticks.with_columns((pl.col("timestamp_us") // 60_000_000 * 60_000_000).alias("t"))
    bars = bars.group_by("t", maintain_order=True).agg(
        pl.col("price").first().alias("open"), pl.col("price").max().alias("high"),
        pl.col("price").min().alias("low"), pl.col("price").last().alias("close"),
        pl.col("size").sum().alias("volume"),
        (pl.col("size") * pl.col("aggressor_sign")).sum().alias("delta"),
    )
    bars.write_csv(directory / "bars_1m.csv")
    if include_gex:
        write_json(directory / "gex.json", load_gex(day, symbol))
    settings = {"cluster_ticks": 3 if symbol == "ES" else 10, "failure_ticks": 24, "failure_seconds": 20}
    run_engine("rails", directory / "snapshots.jsonl", directory / "events.jsonl", *settings.values())
    events = read_lines(directory / "events.jsonl")
    quality = {
        "symbol": symbol, "day": day, "snapshot_rows": snap.height,
        "duplicate_snapshot_times": duplicates, "invalid_snapshot_rows": invalid,
        "sampled_rows": len(snapshots), "first": clock(raw_times[0]), "last": clock(raw_times[-1]),
        "gaps_over_5s": [{"from": clock(a), "to": clock(b), "seconds": s} for a, b, s in gaps],
        "ticks": ticks.height, "settings": settings,
        "events": len(events), "epochs": sum(e["kind"] == "Reset" for e in events),
        "engine_source_sha256": hashlib.sha256((REPO / "KahnRuntime/LevelLedgerEvidenceEngine.cs").read_bytes()).hexdigest(),
    }
    write_json(directory / "quality.json", quality)
    print(json.dumps(quality), flush=True)


@dataclass
class Case:
    symbol: str
    day: str
    side: str
    start: str
    end: str
    label: str

    @property
    def name(self) -> str:
        return f"{self.symbol}-{self.day}-{self.label}"

    @property
    def sign(self) -> int:
        return 1 if self.side == "long" else -1

    @property
    def same(self) -> str:
        return "demand" if self.side == "long" else "supply"


def cases() -> list[Case]:
    return [Case(symbol, day, side, start, end, label)
            for symbol in ("ES", "NQ")
            for day, side, start, end, label in (
                ("2026-09-03", "long", "10:00", "10:50", "early-control"),
                ("2026-09-03", "long", "10:55", "12:00", "main"),
                ("2026-09-04", "short", "09:40", "10:00", "early-control"),
                ("2026-09-04", "short", "10:00", "11:45", "main"),
            )]


class Market:
    def __init__(self, symbol: str, day: str):
        self.directory = OUT / f"{symbol}-{day}"
        self.quotes = pl.read_parquet(self.directory / "quotes.parquet").to_dicts()
        self.qt = [q["t"] for q in self.quotes]
        ticks = pl.read_parquet(self.directory / "ticks.parquet")
        self.ticks = ticks
        self.tt = ticks["timestamp_us"].to_list()
        self.tp = ticks["price"].to_list()
        self.events = read_lines(self.directory / "events.jsonl")
        self.gex = json.loads((self.directory / "gex.json").read_text())
        self.gt = {cat: [r["available_t"] for r in rows] for cat, rows in self.gex.items()}
        self.postures = {}

    def quote(self, t: int, *, forward: bool = False) -> dict | None:
        i = bisect.bisect_left(self.qt, t) if forward else bisect.bisect_right(self.qt, t) - 1
        if i < 0 or i >= len(self.qt) or abs(self.qt[i] - t) > 2_000_000:
            return None
        return self.quotes[i]

    def gamma(self, t: int, category: str = "gex_full", max_age: int = 60) -> dict:
        i = bisect.bisect_right(self.gt[category], t) - 1
        if i < 0:
            return {"fresh": False, "reason": "missing"}
        row = self.gex[category][i]
        age = max(t - row["t"], t - row["api_t"]) / 1e6
        return {**row, "age_sec": age, "fresh": age <= max_age and row["zero_gamma"] is not None}

    def path(self, t0: int, t1: int) -> tuple[list[int], list[float]]:
        a, b = bisect.bisect_right(self.tt, t0), bisect.bisect_right(self.tt, t1)
        return self.tt[a:b], self.tp[a:b]

    def posture(self, t: int, side: str, category: str) -> dict:
        key = (side, category)
        if key not in self.postures:
            rows, since, cross_since, prior_known, prior = [], None, None, None, None
            sign = 1 if side == "long" else -1
            for q in self.quotes:
                g = self.gamma(q["t"], category)
                good = g["fresh"] and sign * (q["mid"] - g["zero_gamma"]) > 0
                since = (since if since is not None else q["t"]) if good else None
                if g["fresh"]:
                    cross_since = (cross_since if prior_known else q["t"]) if good else None
                    prior_known = good
                current = (since, cross_since)
                if prior != current:
                    rows.append({"t": q["t"], "favorable_since": since, "known_cross_since": cross_since})
                prior = current
            self.postures[key] = ([r["t"] for r in rows], rows)
        times, rows = self.postures[key]
        i = bisect.bisect_right(times, t) - 1
        return rows[i] if i >= 0 else {"favorable_since": None, "known_cross_since": None}


def beyond(side: str, band: dict, reference: dict) -> bool:
    return band["lo"] > reference["hi"] if side == "long" else band["hi"] < reference["lo"]


def overlap(a: dict, b: dict) -> bool:
    return a["hi"] >= b["lo"] and b["hi"] >= a["lo"]


def gap(a: dict, b: dict) -> float:
    return max(0, a["lo"] - b["hi"], b["lo"] - a["hi"])


def favorable_price(side: str, price: float, band: dict) -> bool:
    return price > band["hi"] if side == "long" else price < band["lo"]


def root_seeds(case: Case, market: Market) -> list[dict]:
    start, end = stamp(case.day, case.start), stamp(case.day, case.end)
    roots = []
    active = None
    for e in market.events:
        if e["t"] < start or e["t"] >= end:
            continue
        if active is not None:
            reset = e["kind"] == "Reset"
            failed = (not reset and e["kind"] == "RailFailed"
                      and e["side"] == case.same and gap(e, active["seed"]) <= .5)
            if reset or failed:
                active["end_t"] = e["t"]
                active["end_reason"] = "evidence_gap" if reset else "root_failure"
                active["failure_order"] = e["order"]
                roots.append(active)
                active = None
            continue
        if len(roots) >= 3:
            break
        if e["kind"] not in KINDS or e["side"] != case.same or not e["ready"]:
            continue
        q = market.quote(e["t"] + 250_000, forward=True)
        if q is None:
            continue
        price = q["ask"] + .25 if case.side == "long" else q["bid"] - .25
        active = {"case": case.name, "root_n": len(roots) + 1, "seed": e,
                  "t": q["t"], "price": price, "end_t": end, "end_reason": "window_end"}
    if active:
        roots.append(active)
    return roots


def model_candidates(case: Case, market: Market, root: dict, *, warm: bool = False) -> tuple[list[dict], list[dict]]:
    alive, observations, candidates = {}, [], []
    repair = None
    seen_direct = set()
    sign = case.sign

    def proposal(method: str, e: dict, proof: dict, claim: dict | None) -> None:
        # Pre-fill observation may retain a live claim, not an old failure token.
        if warm and claim and claim["failed"] <= root["t"]:
            return
        if sign * (e["price"] - root["price"]) <= 0:
            return
        if not beyond(case.side, proof, root["seed"]):
            return
        row = {"case": case.name, "root_n": root["root_n"], "method": method,
               "t": e["t"], "time": clock(e["t"]), "order": e["order"],
               "signal_kind": e["kind"], "price": e["price"],
               "proof_id": proof["id"], "proof_t": proof["t"],
               "proof_lo": proof["lo"], "proof_hi": proof["hi"], "source": proof["source"],
               "root_price": root["price"], "root_lo": root["seed"]["lo"], "root_hi": root["seed"]["hi"],
               "repair_id": claim["event"]["id"] if claim else None,
               "repair_t": claim["start"] if claim else None,
               "failure_t": claim["failed"] if claim else None,
               "repair_lo": claim["event"]["lo"] if claim else None,
               "repair_hi": claim["event"]["hi"] if claim else None,
               "proof_precedes_failure": bool(claim and proof["t"] < claim["failed"]),
               "pre_fill_claim": bool(claim and claim["start"] <= root["t"]),
               "repair_depth_ticks": claim["depth_ticks"] if claim else None}
        assert row["proof_t"] <= row["t"]
        if claim:
            assert row["repair_t"] <= row["failure_t"] <= row["t"]
        candidates.append(row)

    for e in market.events:
        if e["t"] >= root["end_t"]:
            break
        if e["kind"] == "Reset":
            alive.clear()
            repair = None
            continue
        if e["kind"] == "RailFailed":
            alive.pop(e["id"], None)
        else:
            alive[e["id"]] = e
        observing = e["t"] >= stamp(case.day, case.start) if warm else e["t"] > root["t"]
        if not observing or not e["ready"]:
            continue
        if e["kind"] in KINDS and e["side"] != case.same and beyond(case.side, e, root["seed"]):
            if repair is None or repair["event"]["id"] != e["id"] or repair["failed"] is not None:
                history_start = min(root["t"], stamp(case.day, case.start)) if warm else root["t"]
                _, prices = market.path(history_start, e["t"])
                tail = (max(prices) if sign > 0 else min(prices)) if prices else e["price"]
                repair = {"event": e, "start": e["t"], "failed": None,
                          "depth_ticks": max(0, sign * (tail - e["price"]) / .25)}
                observations.append({"case": case.name, "root_n": root["root_n"],
                                     "t": e["t"], "time": clock(e["t"]), "kind": "repair_observed",
                                     "id": e["id"], "lo": e["lo"], "hi": e["hi"],
                                     "depth_ticks": repair["depth_ticks"], "warm": warm})
            continue
        if (repair and e["kind"] == "RailFailed" and e["id"] == repair["event"]["id"]):
            repair["failed"] = e["t"]
            observations.append({"case": case.name, "root_n": root["root_n"],
                                 "t": e["t"], "time": clock(e["t"]), "kind": "repair_failed",
                                 "id": e["id"], "lo": e["lo"], "hi": e["hi"], "warm": warm})
        if e["t"] <= root["t"]:
            continue
        same_event = e["kind"] in KINDS and e["side"] == case.same
        if not warm and same_event and e["id"] not in seen_direct:
            before_count = len(candidates)
            proposal("direct_favorable", e, e, None)
            if len(candidates) > before_count:
                seen_direct.add(e["id"])
        if not repair or repair["failed"] is None:
            continue
        if not same_event and not (e["kind"] == "RailFailed" and e["id"] == repair["event"]["id"]):
            continue
        claim = repair["event"]
        if same_event and e["t"] >= repair["failed"] and (overlap(e, claim) or beyond(case.side, e, claim)):
            proposal("warm_serial_identity" if warm else "serial_identity", e, e, repair)
        proofs = [p for p in alive.values() if p["side"] == case.same and p["kind"] in KINDS
                  and p["t"] >= repair["start"] and p["t"] <= e["t"]
                  and beyond(case.side, p, root["seed"])
                  and favorable_price(case.side, e["price"], p)]
        proofs.sort(key=lambda p: (p["t"], p["order"]), reverse=True)
        range_proof = next((p for p in proofs if overlap(p, claim) or beyond(case.side, p, claim)), None)
        if range_proof:
            proposal("warm_joint_range" if warm else "joint_range", e, range_proof, repair)
        if proofs and favorable_price(case.side, e["price"], claim):
            proposal("warm_joint_price" if warm else "joint_price", e, proofs[0], repair)
    return candidates, observations


def core_candidate(case: Case, market: Market, root: dict, destination: Path, *, evaluate_gates: bool = True) -> tuple[list[dict], dict]:
    destination.mkdir(parents=True, exist_ok=True)
    config = {"side": case.side, "seed_t": root["t"], "seed_order": root["seed"]["order"],
              "end_t": root["end_t"], "root": [root["seed"]["lo"], root["seed"]["hi"]],
              "root_price": root["price"], "arena": [1, 100000]}
    gates = {f"{category}:{gate}": [] for category in CATEGORIES for gate in GATES if gate != "none"} if evaluate_gates else {}
    for e in market.events:
        if not gates or not root["t"] < e["t"] < root["end_t"] or e["kind"] not in KINDS:
            continue
        for category in CATEGORIES:
            g = gamma_fields(case, market, {**e, "proof_lo": e["lo"], "proof_hi": e["hi"], "proof_t": e["t"]}, category)
            for gate in GATES[1:]:
                if gate_passes(g, gate):
                    gates[f"{category}:{gate}"].append(e["order"])
    config["gates"] = gates
    write_json(destination / "seed.json", config)
    run_engine("policy", destination / "seed.json", market.directory / "events.jsonl", destination / "current_core.jsonl")
    rows = read_lines(destination / "current_core.jsonl")
    by_order = {e["order"]: e for e in market.events}
    proposals = []
    for row in rows:
        if row["action"] == "AllowAdd" and row["emitted"]:
            e = by_order[row["order"]]
            category, gate = row["scenario"].split(":") if ":" in row["scenario"] else (None, "none")
            proposals.append({"case": case.name, "root_n": root["root_n"], "method": "current_core",
                              "core_category": category, "core_gate": gate,
                              "t": e["t"], "time": clock(e["t"]), "order": e["order"],
                              "signal_kind": e["kind"], "price": e["price"], "proof_id": e["id"],
                              "proof_t": e["t"], "proof_lo": e["lo"], "proof_hi": e["hi"], "source": e["source"],
                              "root_price": root["price"], "root_lo": root["seed"]["lo"], "root_hi": root["seed"]["hi"],
                              "repair_id": row["before"]["repair_id"], "proof_precedes_failure": False})
    reasons = {}
    for row in rows:
        if row["scenario"] != "none":
            continue
        key = row["reason"]
        reasons[key] = reasons.get(key, 0) + 1
    return proposals, {"case": case.name, "root_n": root["root_n"], "reasons": reasons}


def gamma_fields(case: Case, market: Market, row: dict, category: str) -> dict:
    g = market.gamma(row["t"], category)
    fresh = g["fresh"]
    zero = g.get("zero_gamma")
    price_ok = bool(fresh and case.sign * (row["price"] - zero) > 0)
    rail_edge = row["proof_lo"] if case.sign > 0 else row["proof_hi"]
    rail_ok = bool(price_ok and case.sign * (rail_edge - zero) > 0)
    posture = market.posture(row["t"], case.side, category)
    favorable_since = posture["favorable_since"]
    cross_since = posture["known_cross_since"]
    wall = g.get("call_wall" if case.sign > 0 else "put_wall")
    return {"category": category, "gex_fresh": fresh, "gex_age_sec": g.get("age_sec"),
            "gex_snapshot_id": g.get("id"), "gex_available_t": g.get("available_t"),
            "zero_gamma": zero, "price_side_ok": price_ok, "rail_side_ok": rail_ok,
            "favorable_since": favorable_since,
            "known_cross_since": cross_since,
            "rail_renewed_ok": bool(rail_ok and cross_since is not None and row["proof_t"] >= cross_since),
            "rail_rearmed_ok": bool(rail_ok and favorable_since is not None and row["proof_t"] >= favorable_since),
            "directional_wall": wall,
            "wall_runway_ticks": case.sign * (wall - row["price"]) / .25 if wall is not None and fresh else None,
            "sum_gex_vol": g.get("sum_gex_vol"), "sum_gex_oi": g.get("sum_gex_oi"),
            "negative_sum_vol": bool(fresh and g.get("sum_gex_vol") is not None and g["sum_gex_vol"] < 0)}


def gate_passes(row: dict, gate: str) -> bool:
    return True if gate == "none" else row[gate if gate == "negative_sum_vol" else gate + "_ok"]


def score(case: Case, market: Market, root: dict, row: dict) -> dict:
    q = market.quote(row["t"] + 250_000, forward=True)
    if q is None or q["t"] >= root["end_t"]:
        return {"fillable": False, "score_reason": "no_fresh_post_signal_quote"}
    fill = q["ask"] + .25 if case.sign > 0 else q["bid"] - .25
    average = (root["price"] + fill) / 2
    executable = q["bid"] if case.sign > 0 else q["ask"]
    result = {"fillable": True, "fill_t": q["t"], "fill_time": clock(q["t"]), "fill_price": fill,
              "quote_delay_sec": (q["t"] - row["t"]) / 1e6, "weighted_average": average,
              "be_valid_at_add": case.sign * (executable - average) >= .25,
              "root_cushion_ticks": case.sign * (fill - root["price"]) / .25}
    for minutes in (1, 5, 15):
        end = min(root["end_t"], q["t"] + minutes * 60_000_000)
        times, prices = market.path(q["t"], end)
        if not prices:
            continue
        pnl = [case.sign * (p - fill) / .25 for p in prices]
        touches = [t for t, p in zip(times, prices) if case.sign * (p - average) <= 0]
        result.update({f"mfe_{minutes}m_ticks": round(max(0, max(pnl)), 2),
                       f"mae_{minutes}m_ticks": round(max(0, -min(pnl)), 2),
                       f"mark_{minutes}m_ticks": round(pnl[-1], 2),
                       f"be_touch_{minutes}m": bool(touches),
                       f"observed_{minutes}m_sec": (end - q["t"]) / 1e6})
    # Touch is a path diagnostic, not a modeled broker fill or realized P&L.
    return result


def gamma_timeline(case: Case, market: Market) -> list[dict]:
    start, end = stamp(case.day, case.start), stamp(case.day, case.end)
    result = []
    for category in CATEGORIES:
        previous = None
        for q in market.quotes:
            if q["t"] < start or q["t"] >= end:
                continue
            g = market.gamma(q["t"], category)
            if not g["fresh"]:
                status = "stale"
            else:
                displacement = case.sign * (q["mid"] - g["zero_gamma"])
                status = "favorable" if displacement > 0 else "adverse" if displacement < 0 else "boundary"
            if previous == status:
                continue
            result.append({"case": case.name, "category": category, "t": q["t"], "time": clock(q["t"]),
                           "status": status, "price": q["mid"], "zero_gamma": g.get("zero_gamma"),
                           "gex_age_sec": g.get("age_sec"), "snapshot_id": g.get("id")})
            previous = status
    return result


def analyze() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    markets = {}
    roots_out, proposals_out, comparisons, diagnostics, observations, crossings = [], [], [], [], [], []
    for case in cases():
        key = (case.symbol, case.day)
        if key not in markets:
            markets[key] = Market(*key)
        market = markets[key]
        roots = root_seeds(case, market)
        crossings.extend(gamma_timeline(case, market))
        for root in roots:
            roots_out.append({"case": case.name, "root_n": root["root_n"], "time": clock(root["t"]),
                              "t": root["t"], "price": root["price"], "lo": root["seed"]["lo"],
                              "hi": root["seed"]["hi"], "seed_id": root["seed"]["id"],
                              "end": clock(root["end_t"]), "end_t": root["end_t"], "end_reason": root["end_reason"]})
            candidates, observed = model_candidates(case, market, root)
            warm, warm_observed = model_candidates(case, market, root, warm=True)
            candidates.extend(warm)
            observed.extend(warm_observed)
            core, diagnosis = core_candidate(case, market, root, OUT / "core" / case.name / str(root["root_n"]))
            candidates.extend(core)
            candidates.sort(key=lambda row: (row["t"], row["order"]))
            diagnostics.append(diagnosis)
            observations.extend(observed)
            enriched = []
            for candidate in candidates:
                scored = score(case, market, root, candidate)
                for category in CATEGORIES:
                    if candidate.get("core_category") not in (None, category):
                        continue
                    joined = {**candidate, **gamma_fields(case, market, candidate, category), **scored}
                    assert joined.get("gex_available_t") is None or joined["gex_available_t"] <= joined["t"]
                    enriched.append(joined)
            proposals_out.extend(enriched)
            for method in METHODS:
                for category in CATEGORIES:
                    for gate in GATES:
                        subset = [r for r in enriched if r["method"] == method and r["category"] == category]
                        if method == "current_core":
                            subset = [r for r in subset if r["core_gate"] == gate]
                        subset = [r for r in subset if gate_passes(r, gate)]
                        first = next((r for r in subset if r["fillable"]), None)
                        comparisons.append(first | {"gate": gate, "selected": True} if first else {
                            "case": case.name, "root_n": root["root_n"], "method": method,
                            "category": category, "gate": gate, "selected": False,
                        })
        print(f"analyzed {case.name}: roots={len(roots)}", flush=True)
    write_csv(OUT / "roots.csv", roots_out)
    write_csv(OUT / "candidate_events.csv", proposals_out)
    write_csv(OUT / "first_add_comparison.csv", comparisons)
    write_csv(OUT / "repair_observations.csv", observations)
    write_csv(OUT / "gamma_crossings.csv", crossings)
    write_json(OUT / "core_diagnostics.json", diagnostics)
    write_json(OUT / "manifest.json", {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "roots": len(roots_out), "candidate_category_rows": len(proposals_out),
        "rules": {"seed": "first ready same-side ownership/hold after window start; retry after typed root failure, max 3",
                  "quote": "first snapshot >= signal+250ms, max 2s quote lag, BBO plus 1 tick slippage",
                  "gamma": "backward join by max(recorded_at, API timestamp); age <=60s on both clocks",
                  "baseline": "current linked policies, broad arena, no target or no-add zones to isolate scale mechanics",
                  "comparison": "first add only per fixed hypothetical root; no claim of realized P&L",
                  "warm": "observe current case-window claims before root fill, without issuing pre-fill candidates; failure must occur after root fill",
                  "gates": "price_side; whole rail_side; rail_renewed after last known directional cross; rail_rearmed also after stale gaps; negative_sum_vol is a non-equivalent diagnostic",
                  "core_gates": "replay independently for each gate; veto add without applying it, continue observation"},
        "source_hashes": {name: hashlib.sha256((REPO / "KahnRuntime" / name).read_bytes()).hexdigest()
                          for name in ("CampaignContracts.cs", "CampaignPolicy.cs", "LevelLedgerEvidenceEngine.cs")},
        "research_hashes": {name: hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest()
                            for name in ("study.py", "EngineProbe/Program.cs", "EngineProbe/EngineProbe.csproj")},
        "input_hashes": {f"{symbol}-{day}/{name}": hashlib.sha256((market.directory / name).read_bytes()).hexdigest()
                         for (symbol, day), market in markets.items()
                         for name in ("snapshots.jsonl", "ticks.parquet", "gex.json")},
    })


def sensitivity() -> None:
    output = []
    for base in [c for c in cases() if c.label == "main"]:
        market = Market(base.symbol, base.day)
        starts = ("10:54", "10:55", "10:56") if base.day.endswith("03") else ("09:59", "10:00", "10:01")
        for start in starts:
            case = Case(base.symbol, base.day, base.side, start, base.end, "start-" + start.replace(":", ""))
            for root in root_seeds(case, market):
                cold, _ = model_candidates(case, market, root)
                warm, _ = model_candidates(case, market, root, warm=True)
                core, _ = core_candidate(case, market, root, OUT / "sensitivity" / case.name / str(root["root_n"]), evaluate_gates=False)
                rows = sorted(cold + warm + core, key=lambda r: (r["t"], r["order"]))
                for method in METHODS:
                    first = next((r for r in rows if r["method"] == method), None)
                    output.append({"case": base.name, "window_start": start, "root_n": root["root_n"],
                                   "root_time": clock(root["t"]), "root_price": root["price"],
                                   "root_end": clock(root["end_t"]), "end_reason": root["end_reason"], "method": method,
                                   "first_time": first["time"] if first else None,
                                   "first_price": first["price"] if first else None})
            print(f"sensitivity {case.name}", flush=True)
    write_csv(OUT / "start_sensitivity.csv", output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["prepare", "analyze", "sensitivity"])
    parser.add_argument("--symbol", choices=["ES", "NQ"])
    parser.add_argument("--day", choices=["2026-09-03", "2026-09-04"])
    args = parser.parse_args()
    if args.mode == "prepare":
        for symbol in ([args.symbol] if args.symbol else ["ES", "NQ"]):
            for day in ([args.day] if args.day else ["2026-09-03", "2026-09-04"]):
                prepare(symbol, day)
    elif args.mode == "analyze":
        analyze()
    else:
        sensitivity()


if __name__ == "__main__":
    main()
