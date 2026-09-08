"""Episode diagnostics, real-stream fragmentation and prefix checks."""
import hashlib
import json
from pathlib import Path

import episode_study as e
import study as s


def fragmented(market, root):
    other = e.Market.__new__(e.Market)
    other.quotes, other.qt, other.directory = market.quotes, market.qt, market.directory
    other.events = []
    for r in market.events:
        if not r.get("id") or r["id"] == root["seed"]["id"]:
            other.events.append(r)
            continue
        mid = ((round(r["lo"] / e.TICK) + round(r["hi"] / e.TICK)) // 2) * e.TICK
        other.events.extend([{**r, "id": r["id"] + "/a", "hi": mid},
                             {**r, "id": r["id"] + "/b", "lo": min(r["hi"], mid + e.TICK)}])
    return other


def canonical(observer):
    return [(r["t"], r["signature"], r["support_coverage"], r["claim_coverage"])
            for r in observer.offers]


def crossing(case, market, offer):
    if not offer["claim_coverage"]:
        return {"traversal_seconds": None}
    intervals = [sorted(case.sign * x for x in pair) for pair in offer["claim_coverage"]]
    back, front = min(p[0] for p in intervals), max(p[1] for p in intervals)
    quotes = [q for q in market.quotes if offer["start_t"] <= q["t"] <= offer["t"]]
    adverse = [q for q in quotes if case.sign * q["mid"] <= back]
    leave = adverse[-1]["t"] if adverse else None
    clear = next((q["t"] for q in quotes if leave is not None and q["t"] > leave and case.sign * q["mid"] > front), None)
    return {"traversal_seconds": round((clear - leave) / 1e6, 3) if clear is not None else None,
            "claim_hull_ticks": round((front - back) / e.TICK, 3),
            "last_adverse_quote": s.clock(leave), "first_clear_quote": s.clock(clear),
            "clear_to_permission_seconds": round((offer["t"] - clear) / 1e6, 3) if clear else None}


def main():
    validations, diagnostics, density, breach_comparison = [], [], [], []
    for case in e.cases():
        market = e.Market(case.symbol, case.day)
        window = [r for r in market.events if s.stamp(case.day, case.start) <= r["t"] <= s.stamp(case.day, case.end)]
        density.append({"case": case.name, "transitions": len(window),
                        "same_side_owned": sum(r["kind"] == "RailOwned" and r["side"] == case.same for r in window),
                        "same_side_held": sum(r["kind"] == "RailHeld" and r["side"] == case.same for r in window),
                        "opposite_failed": sum(r["kind"] == "RailFailed" and r["side"] != case.same for r in window)})
        for root in s.root_seeds(case, market):
            observer = e.observe(case, market, root, warm=True)
            split = e.observe(case, fragmented(market, root), root, warm=True)
            cutoff = root["t"] + (root["end_t"] - root["t"]) // 2
            shorter = {**root, "end_t": cutoff, "end_reason": "prefix_cutoff"}
            prefix = e.observe(case, market, shorter, warm=True)
            expected = [r for r in canonical(observer) if r[0] <= cutoff]
            validations.append({"case": case.name, "root_n": root["root_n"],
                                "fragmentation_equal": canonical(observer) == canonical(split),
                                "prefix_equal": expected == canonical(prefix),
                                "offers": len(observer.offers), "split_offers": len(split.offers)})
            if canonical(observer) != canonical(split):
                s.write_json(e.OUT / f"fragmentation-difference-{case.name}-{root['root_n']}.json",
                             {"original": canonical(observer), "split": canonical(split)})
            reset = e.observe(case, market, root, warm=True, retain_breached=False)
            key = lambda o: [s.clock(r["t"]) for r in o.offers if r["signature"] == "typed_clear"]
            breach_comparison.append({"case": case.name, "root_n": root["root_n"],
                                      "retained_attack": ";".join(key(observer)), "reset_on_breach": ";".join(key(reset))})
            for r in observer.offers:
                assert r["support_last_t"] <= r["t"]
                assert r["claim_failure_t"] is None or r["claim_failure_t"] <= r["t"]
                diagnostics.append({"case": case.name, "root_n": root["root_n"], "episode": r["episode"],
                                    "time": r["time"], "signature": r["signature"], "completion": r["completion"],
                                    "members": len(r["members"]), "member_areas": len(r["member_coverage"]),
                                    "attacked": len(r["attacked"]), "defended": len(r["defended"]),
                                    "defended_areas": len(r["defended_coverage"]), "failed": len(r["failed"]),
                                    "claims": len(r["claims"]), "claim_areas": len(r["claim_coverage"]),
                                    "support_age_seconds": round((r["t"] - r["support_last_t"]) / 1e6, 3),
                                    **crossing(case, market, r)})
    s.write_csv(e.OUT / "episode_diagnostics.csv", diagnostics)
    s.write_csv(e.OUT / "event_density.csv", density)
    s.write_csv(e.OUT / "breach_boundary_comparison.csv", breach_comparison)
    s.write_json(e.OUT / "validation.json", {"checks": validations,
                 "source_hashes": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                                   for name in ("episode_study.py", "audit_episodes.py", "test_episode_study.py")},
                 "prefix_all_pass": all(r["prefix_equal"] for r in validations),
                 "fragmentation_all_pass": all(r["fragmentation_equal"] for r in validations)})
    print(json.dumps(validations, indent=2))
    print(json.dumps(density, indent=2))


if __name__ == "__main__":
    main()
