"""Frozen shared-episode stress tests on the user's September 1-2 NQ fixtures."""
import argparse
from collections import Counter
from dataclasses import replace
from datetime import datetime, timedelta
import hashlib
import inspect
import json
from pathlib import Path

import polars as pl

import audit_episodes as audit
import episode_study as e
import study as s


OUT = s.REPO / "research/out/kahn-episode-stress-20260907"
DATA = OUT / "data"
FROZEN_EPISODE_SHA256 = "c1233c36407ad32ff14b357aa8d29b19ca6cdda10fa261df6313867c2ecee02a"
CASES = (
    s.Case("NQ", "2026-09-02", "long", "10:00", "10:30", "stress-1000"),
    s.Case("NQ", "2026-09-02", "long", "11:00", "11:30", "stress-1100"),
    s.Case("NQ", "2026-09-01", "short", "11:50", "12:30", "stress-1150"),
    s.Case("NQ", "2026-09-01", "short", "11:50", "12:40", "stress-1150-extended"),
)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_frozen():
    actual = sha(Path(e.__file__))
    if actual != FROZEN_EPISODE_SHA256:
        raise RuntimeError("Episode model changed; do not silently retune the stress test.")


def market(day):
    result = e.Market.__new__(e.Market)
    result.directory = DATA / f"NQ-{day}"
    result.events = s.read_lines(result.directory / "events.jsonl")
    result.quotes = pl.read_parquet(result.directory / "quotes.parquet").to_dicts()
    result.qt = [q["t"] for q in result.quotes]
    return result


def prepare():
    verify_frozen()
    for day, end in (("2026-09-01", "12:45"), ("2026-09-02", "11:35")):
        s.prepare("NQ", day, output=DATA, end_time=end, include_gex=False)


def lineage():
    verify_frozen()
    checks = []
    for day in ("2026-09-01", "2026-09-02"):
        folder = DATA / f"NQ-{day}"
        s.run_engine("rails", folder / "snapshots.jsonl", folder / "lineage-events.jsonl",
                     10, 24, 20, folder / "lineage.jsonl")
        equal = sha(folder / "events.jsonl") == sha(folder / "lineage-events.jsonl")
        checks.append({"day": day, "event_stream_unchanged": equal})
        if not equal:
            raise RuntimeError("Lineage export changed the primary rail stream.")
    s.write_json(OUT / "lineage_manifest.json", {"checks": checks,
                 "engine_dll_sha256": sha(s.ENGINE),
                 "probe_source_sha256": sha(Path(__file__).parent / "EngineProbe/Program.cs")})
    print(json.dumps(checks))


def shift_case(case, minutes):
    start = datetime.fromisoformat(case.day + "T" + case.start) + timedelta(minutes=minutes)
    return replace(case, start=start.strftime("%H:%M"), label=case.label + f"-start{minutes:+d}")


def validate(case, m, root, observer, warm):
    split = e.observe(case, audit.fragmented(m, root), root, warm=warm)
    cutoff = root["t"] + (root["end_t"] - root["t"]) // 2
    prefix = e.observe(case, m, {**root, "end_t": cutoff, "end_reason": "prefix_cutoff"}, warm=warm)
    return {"case": case.name, "root_n": root["root_n"], "warm": warm,
            "fragmentation_equal": audit.canonical(observer) == audit.canonical(split),
            "prefix_equal": [r for r in audit.canonical(observer) if r[0] <= cutoff] == audit.canonical(prefix)}


def current_core(case, m, root, directory):
    cfg = {"side": case.side, "seed_t": root["t"], "seed_order": root["seed"]["order"],
           "end_t": root["end_t"], "root": [root["seed"]["lo"], root["seed"]["hi"]],
           "root_price": root["price"], "arena": [1, 100000], "max_quantity": 8,
           "full_campaign": True, "state_variant": "current"}
    s.write_json(directory / "current-seed.json", cfg)
    s.run_engine("policy", directory / "current-seed.json", m.directory / "events.jsonl", directory / "current-policy.jsonl")
    rows = s.read_lines(directory / "current-policy.jsonl")
    adds = [r for r in rows if r["action"] == "AllowAdd" and r["emitted"]]
    exits = [r for r in rows if r["emitted"] and r["action"] in ("Flatten", "Retire", "Reduce")]
    return {"case": case.name, "root_n": root["root_n"], "adds": len(adds),
            "add_times": ";".join(s.clock(r["t"]) for r in adds),
            "risk_actions": ";".join(s.clock(r["t"]) + ":" + r["reason"] for r in exits),
            "noop_repair_clears": sum(r["action"] == "TrackScaleCandidate" and r["before"].get("repair") is not None
                                     and r["after"].get("repair") is None
                                     and r["before"].get("candidate_id") == r["after"].get("candidate_id") for r in rows)}


def window_quality(case, m):
    lo, hi = s.stamp(case.day, case.start), s.stamp(case.day, case.end)
    events = [r for r in m.events if lo <= r["t"] <= hi]
    quotes = [q for q in m.quotes if lo <= q["t"] <= hi]
    return {"case": case.name, "start": case.start, "end": case.end, "quotes": len(quotes),
            "first_quote": s.clock(quotes[0]["t"]) if quotes else None,
            "last_quote": s.clock(quotes[-1]["t"]) if quotes else None,
            "largest_quote_gap_seconds": max(((b["t"] - a["t"]) / 1e6 for a, b in zip(quotes, quotes[1:])), default=None),
            "resets": [r for r in events if r["kind"] == "Reset"],
            "event_counts": dict(Counter(r.get("side", "") + ":" + r["kind"] for r in events))}


def outcome(case, m, root, result):
    paths = []
    for action in result["actions"]:
        if action["action"] != "add":
            continue
        exit_t = next((a["t"] for a in result["actions"] if a["action"] == "exit"
                       and a["t"] >= action["t"] and action["episode"] in a["episodes"]), root["end_t"])
        q = [row for row in m.quotes if action["t"] <= row["t"] <= exit_t]
        changes = [case.sign * ((row["bid"] if case.sign > 0 else row["ask"]) - action["price"]) / e.TICK for row in q]
        paths.append({"episode": action["episode"], "signal_time": action["signal_time"],
                      "fill_time": action["time"], "fill_price": action["price"],
                      "observed_until": s.clock(exit_t),
                      "mfe_ticks_label": max(0, max(changes)) if changes else None,
                      "mae_ticks_label": max(0, -min(changes)) if changes else None,
                      "seconds_held": round((exit_t - action["t"]) / 1e6, 3)})
    return paths


def analyze():
    verify_frozen()
    markets = {day: market(day) for day in {c.day for c in CASES}}
    roots_out, offers_out, episodes_out, summaries, actions_out, paths_out = [], [], [], [], [], []
    validations, diagnostics, current, quality, sensitivity = [], [], [], [], []
    for case in CASES:
        m = markets[case.day]
        quality.append(window_quality(case, m))
        roots = s.root_seeds(case, m)
        for root in roots:
            context = {"case": case.name, "side": case.side, "root_n": root["root_n"]}
            directory = OUT / case.name / f"root-{root['root_n']}"
            s.write_json(directory / "root.json", root)
            roots_out.append({**context, "time": s.clock(root["t"]), "price": root["price"],
                              "seed_id": root["seed"]["id"], "seed_kind": root["seed"]["kind"],
                              "seed_lo": root["seed"]["lo"], "seed_hi": root["seed"]["hi"],
                              "end": s.clock(root["end_t"]), "end_reason": root["end_reason"]})
            current.append(current_core(case, m, root, directory))
            for warm in (False, True):
                context = {**context, "warm": warm}
                folder = directory / ("warm" if warm else "cold")
                observer = e.observe(case, m, root, warm=warm)
                validations.append(validate(case, m, root, observer, warm))
                reset = e.observe(case, m, root, warm=warm, retain_breached=False)
                s.write_lines(folder / "reset_on_breach_offers.jsonl", reset.offers)
                for name, rows in (("episodes", observer.completed), ("offers", observer.offers), ("trace", observer.trace)):
                    s.write_lines(folder / f"{name}.jsonl", rows)
                offers_out.extend(e.csv_rows(observer.offers, context))
                episodes_out.extend(e.csv_rows(observer.completed, context))
                for r in observer.offers:
                    diagnostics.append({**context, "time": r["time"], "episode": r["episode"],
                                        "signature": r["signature"], "completion": r["completion"],
                                        "members": len(r["members"]), "attacked": len(r["attacked"]),
                                        "defended": len(r["defended"]), "failed": len(r["failed"]),
                                        "claims": len(r["claims"]), **audit.crossing(case, m, r)})
                for admission in ("typed_only", "departure_defense", "test_defense"):
                    for maximum in (0, 2, 3):
                        for management in ("root_only", "tranche_groups", "latest_group_campaign"):
                            if maximum == 0 and (admission != "typed_only" or management != "root_only"):
                                continue
                            config = {**context, "admission": admission, "max_adds": maximum, "management": management}
                            result = e.simulate(case, m, root, observer.offers, maximum, admission, management)
                            s.write_json(folder / f"{admission}-{maximum}-{management}.json", {**config, **result})
                            summaries.append({**config, **{k: v for k, v in result.items() if k not in ("actions", "inventory", "decisions")}})
                            actions_out.extend(e.csv_rows(result["actions"], config))
                            paths_out.extend(e.csv_rows(outcome(case, m, root, result), config))
                print(json.dumps({**context, "root_time": s.clock(root["t"]), "root_end": s.clock(root["end_t"]),
                                  "end_reason": root["end_reason"], "offers": dict(Counter(r["signature"] for r in observer.offers))}), flush=True)
        for shift in (-1, 0, 1):
            shifted = shift_case(case, shift)
            for root in s.root_seeds(shifted, m):
                observer = e.observe(shifted, m, root, warm=True)
                result = e.simulate(shifted, m, root, observer.offers, 3, "typed_only", "tranche_groups")
                sensitivity.append({"case": case.name, "shift_minutes": shift, "root_n": root["root_n"],
                                    "root_time": s.clock(root["t"]), "root_end": s.clock(root["end_t"]),
                                    "end_reason": root["end_reason"], "accepted_adds": result["accepted_adds"],
                                    "add_times": result["add_times"], "risk_exits": result["risk_exits"]})
    for name, rows in (("roots", roots_out), ("offers", offers_out), ("episodes", episodes_out),
                       ("inventory_summary", summaries), ("actions", actions_out), ("add_paths", paths_out),
                       ("episode_diagnostics", diagnostics), ("current_source_summary", current),
                       ("start_sensitivity", sensitivity)):
        s.write_csv(OUT / f"{name}.csv", rows)
    s.write_json(OUT / "window_quality.json", quality)
    s.write_json(OUT / "validation.json", {"checks": validations,
                 "fragmentation_all_pass": all(r["fragmentation_equal"] for r in validations),
                 "prefix_all_pass": all(r["prefix_equal"] for r in validations)})
    s.write_json(OUT / "manifest.json", {
        "scope": [vars(c) for c in CASES], "frozen_episode_sha256": FROZEN_EPISODE_SHA256,
        "design": "User-selected new fixtures, not random holdouts; unchanged Sep 6 observer/admission/inventory rules; no GEX. Sep 1 primary cutoff 12:30, fixed extension 12:40; starts plus/minus one minute.",
        "root_contract": "Unchanged first-ready same-side OWN/HOLD after window start; delayed BBO seed; nearby typed same-side failure or gap ends root; max three retries. Root selection is not a validated entry policy.",
        "current_baseline": "Linked current policy, same forced roots and root cutoffs, max eight units; event-midpoint additions, no integrated BE/harvest; do not compare its cashflow with delayed-fill experiments.",
        "limits": "All earlier episode-study limitations remain. Future prices used only for separately labeled excursions. Risk trims and BBO BE, no paid harvest/fees/broker lifecycle. No retuning to desired add counts.",
        "source_hashes": {name: sha(s.REPO / "KahnRuntime" / name) for name in ("CampaignContracts.cs", "CampaignPolicy.cs", "LevelLedgerEvidenceEngine.cs")},
        "research_hashes": {name: sha(Path(__file__).with_name(name)) for name in ("stress_episodes.py", "episode_study.py", "study.py", "audit_episodes.py", "test_stress_episodes.py")},
        "probe_source_sha256": sha(Path(__file__).parent / "EngineProbe/Program.cs"),
        "root_function_sha256": hashlib.sha256(inspect.getsource(s.root_seeds).encode()).hexdigest(),
        "engine_dll_sha256": sha(s.ENGINE),
        "input_hashes": {f"NQ-{day}/{name}": sha(DATA / f"NQ-{day}" / name)
                         for day in markets for name in ("events.jsonl", "snapshots.jsonl", "quotes.parquet", "quality.json")},
    })
    print(json.dumps({"roots": len(roots_out), "validation_checks": len(validations), "output": str(OUT)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare", "analyze", "lineage"))
    args = parser.parse_args()
    {"prepare": prepare, "analyze": analyze, "lineage": lineage}[args.mode]()
