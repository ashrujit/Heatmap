"""Compare the C# core to the frozen observer without changing old artifacts.

This adapter uses EngineProbe's complete Process(snapshot) export contract and
the original snapshots to supply empty samples. Arbitrary external JSONL with
equal timestamps does NOT meet that contract. No broker fills or P&L modeled.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
STUDY = REPO / "research/kahn/scale_cycle_study"
sys.path.insert(0, str(STUDY))
import episode_study as frozen
import stress_episodes as stress
import study as s

DLL = REPO / "KahnRuntime.Tests/bin/Release/net10.0/KahnRuntime.Tests.dll"
DEFAULT_OUT = REPO / "research/out/kahn-shared-core-20260907"
RUN_BINARY_HASH = None


def transition(event, lineage):
    epoch, rail = event["id"].split(":", 1)
    result = {"epoch": epoch, "rail_id": rail, "kind": event["kind"], "side": event["side"],
              "coverage": [round(event["lo"] / .25), round(event["hi"] / .25)]}
    known = lineage.get(event["id"])
    if known and known["t"] <= event["t"]:
        result["formed_t"] = known["formed_t"]
    return result


def inputs(case, market, root, warm, *, lineage=None, price_basis="executable"):
    epoch = str(root["seed"]["epoch"])
    lower = s.stamp(case.day, case.start) if warm and root["root_n"] == 1 else root["seed"]["t"]
    upper = root["end_t"]
    events = [e for e in market.events if lower <= e["t"] <= upper]
    if any(e["kind"] != "Reset" and str(e["epoch"]) != epoch for e in events):
        raise RuntimeError("Fixture spans epochs; split at the reset rather than inventing continuity.")
    groups = {}
    for e in events:
        if e["kind"] != "Reset":
            if not e["ready"]:
                raise RuntimeError("Unready evidence in fixture window.")
            groups.setdefault(e["t"], []).append(e)
    samples = {r["t"] for r in s.read_lines(market.directory / "snapshots.jsonl") if lower <= r["t"] <= upper}
    if set(groups) - samples:
        raise RuntimeError("An event has no source snapshot boundary.")
    quotes = {q["t"]: q for q in market.quotes if lower <= q["t"] <= upper}
    times = sorted(samples | set(quotes) | {root["t"]})
    first = times[0]
    quote = market.quote(first)
    if quote is None:
        raise RuntimeError("Missing initial quote.")
    price_key = "mid" if price_basis == "midpoint" else "bid" if case.side == "long" else "ask"
    header = {"side": case.side, "root": [round(root["seed"][v] / .25) for v in ("lo", "hi")],
              "epoch": epoch, "t": first, "price_ticks": quote[price_key] / .25}
    result = [header]
    sequence = 0
    for t in times:
        q = quotes.get(t) or market.quote(t)
        if q is None:
            result.append({"op": "gap", "t": t})
            break
        if t in samples:
            result.append({"op": "sample", "t": t, "epoch": epoch, "sequence": sequence,
                           "price_ticks": q[price_key] / .25,
                           "events": [transition(e, lineage or {}) for e in groups.get(t, [])]})
            sequence += 1
        else:
            result.append({"op": "price", "t": t, "price_ticks": q[price_key] / .25})
        if t == root["t"]:
            result.append({"op": "begin", "t": t, "price_ticks": root["price"] / .25,
                           "key": transition(root["seed"], lineage or {}),
                           "warm": warm and root["root_n"] == 1})
    return result


def run(rows, folder, name):
    if hashlib.sha256(DLL.read_bytes()).hexdigest() != RUN_BINARY_HASH:
        raise RuntimeError("Replay binary changed during the run; do not combine different builds.")
    source, output = folder / f"{name}-input.jsonl", folder / f"{name}-output.jsonl"
    s.write_lines(source, rows)
    subprocess.run([str(s.DOTNET), str(DLL), "replay", str(source), str(output)], check=True,
                   capture_output=True, text=True)
    result = s.read_lines(output)
    summary = result[-1]
    if summary.get("suspended"):
        raise RuntimeError(f"Replay suspended: {folder.name}/{name}: {summary}")
    return [r for r in result if r["kind"] == "offer"], Counter(
        r["reason"] for r in result if r["kind"] == "audit")


def fragmented(rows):
    result = []
    for row in rows:
        if row.get("op") != "sample":
            result.append(row)
            continue
        events = []
        for event in row["events"]:
            lo, hi = event["coverage"]
            middle = (lo + hi) // 2
            events.extend([{**event, "rail_id": event["rail_id"] + "a", "coverage": [lo, middle]},
                           {**event, "rail_id": event["rail_id"] + "b", "coverage": [middle, hi]}])
        result.append({**row, "events": events})
    # Root remains a geometric risk seed; the split root is known as two members.
    return result


def canonical(offers):
    return [(r["t"], r["coverage"]) for r in offers]


def main():
    global RUN_BINARY_HASH
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--checks", action="store_true", help="also replay prefixes and equivalent fragmentation")
    parser.add_argument("--price-basis", choices=("executable", "midpoint"), default="executable")
    args = parser.parse_args()
    stress.verify_frozen()
    output = args.out.resolve()
    allowed = (REPO / "research/out").resolve()
    if not output.is_relative_to(allowed) or output == allowed:
        raise ValueError("Replay output must be a dedicated folder under research/out.")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Choose an empty output folder; prior implementation runs are retained.")
    sources = list((REPO / "KahnRuntime/Scaling").glob("*.cs")) + [Path(__file__),
        REPO / "KahnRuntime.Tests/ScalingReplay.cs", DLL, Path(frozen.__file__)]
    source_hashes = {str(p.relative_to(REPO)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    RUN_BINARY_HASH = hashlib.sha256(DLL.read_bytes()).hexdigest()
    cases = list(frozen.cases()) + list(stress.CASES)
    cases += [replace(stress.CASES[-1], start=start, label=label)
              for start, label in (("11:55", "stress-1155"), ("12:00", "stress-1200"))]
    markets = {}
    summaries, offers_out, checks = [], [], []
    for case in cases:
        key = (case.symbol, case.day)
        if key not in markets:
            markets[key] = stress.market(case.day) if case.day in ("2026-09-01", "2026-09-02") else frozen.Market(*key)
        market = markets[key]
        for root in s.root_seeds(case, market):
            for warm in (False, True):
                context = {"case": case.name, "root_n": root["root_n"], "warm": warm,
                           "root_time": s.clock(root["t"]), "root_end": s.clock(root["end_t"]),
                           "end_reason": root["end_reason"]}
                folder = output / case.name / f"root-{root['root_n']}" / ("warm" if warm else "cold")
                rows = inputs(case, market, root, warm, price_basis=args.price_basis)
                actual, audit = run(rows, folder, "core")
                baseline = [r for r in frozen.observe(case, market, root, warm=warm).offers if r["signature"] == "typed_clear"]
                baseline_times, actual_times = {r["t"] for r in baseline}, {r["t"] for r in actual}
                summary = {**context, "frozen_offers": len(baseline), "core_offers": len(actual),
                           "frozen_times": ";".join(s.clock(r["t"]) for r in baseline),
                           "core_times": ";".join(s.clock(r["t"]) for r in actual),
                           "added_times": ";".join(s.clock(t) for t in sorted(actual_times - baseline_times)),
                           "removed_times": ";".join(s.clock(t) for t in sorted(baseline_times - actual_times)),
                           "unrelated_extension_closures": audit["unrelated_extension"]}
                summaries.append(summary)
                offers_out.extend({**context, **r, "time": s.clock(r["t"])} for r in actual)
                if args.checks:
                    cut = root["t"] + (root["end_t"] - root["t"]) // 2
                    prefix, _ = run([rows[0]] + [r for r in rows[1:] if r["t"] <= cut], folder, "prefix")
                    split, _ = run(fragmented(rows), folder, "fragmented")
                    checks.append({**context, "prefix_equal": canonical(prefix) == canonical([r for r in actual if r["t"] <= cut]),
                                   "fragmented_equal": canonical(split) == canonical(actual)})
                print(json.dumps(summary), flush=True)
    s.write_csv(output / "summary.csv", summaries)
    s.write_lines(output / "offers.jsonl", offers_out)
    s.write_json(output / "checks.json", checks)
    if source_hashes != {str(p.relative_to(REPO)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}:
        raise RuntimeError("Source changed during the replay; results are not a single-build validation.")
    s.write_json(output / "manifest.json", {
        "contract": "broad_test_or_opposing_claim_with_typed_failure_and_associated_current_support",
        "status": "offline core, not production worker/order integration",
        "price_basis": args.price_basis, "frozen_price_basis": "midpoint",
        "windows": len(cases), "runs": len(summaries), "checks": len(checks),
        "prefix_failures": sum(not r["prefix_equal"] for r in checks),
        "fragmentation_differences": sum(not r["fragmented_equal"] for r in checks),
        "sources": source_hashes,
        "inputs": {str(m.directory.relative_to(REPO)): {
            name: hashlib.sha256((m.directory / name).read_bytes()).hexdigest()
            for name in ("events.jsonl", "quotes.parquet", "snapshots.jsonl")} for m in markets.values()},
        "limitations": ["counterfactual roots, not historical broker fills", "no inventory, BE or harvest replay",
                        "cold paths start with the complete seed sample, not only the selected root transition",
                        "formation remains unknown in this baseline comparison", "no GEX gating"]})
    if any(not r["prefix_equal"] for r in checks):
        raise RuntimeError("A future suffix changed an earlier permission.")


if __name__ == "__main__":
    main()
