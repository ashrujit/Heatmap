"""Offline inventory diagnostic with explicit synthetic fills and no invented targets."""
import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
import replay_fixtures as core


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--holdout-day", help="Prepare a separate date; fixed windows and both directions, no outcome selection")
    parser.add_argument("--engine", type=Path, help="Isolated EngineProbe rails exporter for new captures")
    parser.add_argument("--holdout-data", type=Path, help="Reuse previously hashed prepared captures without rewriting them")
    args = parser.parse_args()
    out = args.out.resolve()
    if not out.is_relative_to((core.REPO / "research/out").resolve()) or out.exists():
        raise ValueError("Use a new dedicated research/out directory")
    core.stress.verify_frozen()
    sources = list((core.REPO / "KahnRuntime").glob("*.cs")) + list((core.REPO / "KahnRuntime/Scaling").glob("*.cs"))
    sources += [Path(__file__), Path(core.__file__), core.DLL, core.REPO / "KahnRuntime.Tests/SessionReplay.cs"]
    if args.engine:
        core.s.ENGINE = args.engine.resolve()
        sources.append(core.s.ENGINE)
    hashes = {str(p.relative_to(core.REPO)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    cases = list(core.frozen.cases()) + list(core.stress.CASES)
    cases += [replace(core.stress.CASES[-1], start=start, label=label)
              for start, label in (("11:55", "stress-1155"), ("12:00", "stress-1200"))]
    if args.holdout_day:
        data_root = args.holdout_data.resolve() if args.holdout_data else out / "data"
        cases = [core.s.Case(symbol, args.holdout_day, side, start, end, f"additional-{side}-{start.replace(':', '')}")
                 for symbol in ("ES", "NQ") for side in ("long", "short")
                 for start, end in (("09:35", "10:00"), ("10:00", "10:30"), ("10:30", "11:00"))]
        if not args.holdout_data:
            for symbol in ("ES", "NQ"):
                core.s.prepare(symbol, args.holdout_day, output=data_root, end_time="11:05", include_gex=False)
    markets, summary = {}, []
    for case in cases:
        key = (case.symbol, case.day)
        if key not in markets:
            if args.holdout_day:
                market = core.frozen.Market.__new__(core.frozen.Market)
                market.directory = data_root / f"{case.symbol}-{case.day}"
                market.events = core.s.read_lines(market.directory / "events.jsonl")
                market.quotes = core.frozen.pl.read_parquet(market.directory / "quotes.parquet").to_dicts()
                market.qt = [q["t"] for q in market.quotes]
                markets[key] = market
            else:
                markets[key] = core.stress.market(case.day) if case.day in ("2026-09-01", "2026-09-02") else core.frozen.Market(*key)
        market = markets[key]
        for root in core.s.root_seeds(case, market):
            rows = core.inputs(case, market, root, True)
            for row in rows[1:]:
                quote = market.quote(row["t"])
                if quote is None: raise ValueError("missing BBO")
                row.update(bid_ticks=quote["bid"] / .25, ask_ticks=quote["ask"] / .25, quote_t=quote["t"])
            folder = out / case.name / f"root-{root['root_n']}"
            source, result = folder / "input.jsonl", folder / "output.jsonl"
            core.s.write_lines(source, rows)
            subprocess.run([str(core.s.DOTNET), str(core.DLL), "session-replay", str(source), str(result)],
                           check=True, capture_output=True, text=True)
            output = core.s.read_lines(result)
            row = {"case": case.name, "root_n": root["root_n"], "root_time": core.s.clock(root["t"]),
                   "root_selector_end": root["end_reason"], **output[-1],
                   "add_times": [core.s.clock(r["t"]) for r in output if r["kind"] == "add_proxy_fill"]}
            summary.append(row)
            print(json.dumps({k: row[k] for k in ("case", "root_n", "adds", "peak_quantity", "final_quantity", "exit", "add_times")}), flush=True)
    core.s.write_json(out / "summary.json", summary)
    if hashes != {str(p.relative_to(core.REPO)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}:
        raise RuntimeError("sources changed during replay")
    core.s.write_json(out / "manifest.json", {"sources": hashes, "runs": len(summary),
        "inputs": {str(m.directory.relative_to(core.REPO)): {name: hashlib.sha256((m.directory / name).read_bytes()).hexdigest()
                  for name in ("events.jsonl", "quotes.parquet", "snapshots.jsonl")} for m in markets.values()},
        "holdout_day": args.holdout_day,
        "limitations": ["fixed-window additional date check" if args.holdout_day else "selected research windows, not untouched holdouts", "counterfactual seeds and BBO plus one tick fill proxies",
                        "unbounded diagnostic arena; no supplied targets or historical harvest fills",
                        "does not validate Quantower callback ordering, exchange stops, slippage or profitability"]})


if __name__ == "__main__": main()
