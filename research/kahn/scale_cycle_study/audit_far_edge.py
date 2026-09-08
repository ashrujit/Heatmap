"""Explain frozen permissions using only histories available at that permission."""
import bisect
import json

import far_edge_study as f
import study as s


def main():
    classifications, extrema, new_lineage = [], [], []
    markets = {}
    for case in f.fixtures():
        key = (case.symbol, case.day)
        if key not in markets:
            markets[key] = f.load_market(case)
        market = markets[key]
        for root in s.root_seeds(case, market):
            folder = f.OUT / case.name / f"root-{root['root_n']}" / "warm"
            runs = {model: s.read_lines(folder / model / "offers.jsonl") for model in f.MODELS}
            times = {model: {r["t"] for r in rows if r["signature"] == "typed_clear"} for model, rows in runs.items()}
            for offer in runs["frozen"]:
                if offer["signature"] != "typed_clear":
                    continue
                ctx = {"case": case.name, "root_n": root["root_n"], "time": offer["time"], "start": offer["start"]}
                classifications.append({**ctx, **{model: offer["t"] in ts for model, ts in times.items()},
                                        "support": json.dumps(offer["support"]), "members": json.dumps(offer["members"])})
                for rail_id in offer["members"]:
                    history = [r for r in market.events if r.get("id") == rail_id and r["t"] <= offer["t"]]
                    if rail_id == root["seed"]["id"] and not history:
                        history = [root["seed"]]
                    if not history:
                        continue
                    latest = history[-1]
                    known = min(r["t"] for r in history)
                    start = max(offer["start_t"], known)
                    quotes = [q["mid"] for q in market.quotes if start <= q["t"] <= offer["t"]]
                    lo = bisect.bisect_left(market.trade_times, start)
                    hi = bisect.bisect_right(market.trade_times, offer["t"])
                    trades = market.trade_prices[lo:hi]
                    edge = latest["lo"] if case.sign > 0 else latest["hi"]
                    adverse = lambda values: min(values) if case.sign > 0 else max(values)
                    extrema.append({**ctx, "rail_id": rail_id, "lo": latest["lo"], "hi": latest["hi"],
                        "is_support": rail_id in offer["support"], "known_since": s.clock(known),
                        "observed_from": s.clock(start), "far_edge": edge,
                        "quote_adverse_price": adverse(quotes) if quotes else None,
                        "trade_adverse_price": adverse(trades) if trades else None,
                        "quote_crossed_edge": bool(quotes) and case.sign * (adverse(quotes) - edge) < 0,
                        "trade_crossed_edge": bool(trades) and case.sign * (adverse(trades) - edge) < 0,
                        "typed_failure_during_episode": any(r["kind"] == "RailFailed" and r["t"] >= offer["start_t"] for r in history)})
            for offer in runs["edge_local_trade"]:
                breach = offer["far_edge_breaches"][0]
                new_lineage.append({"case": case.name, "root_n": root["root_n"], "time": offer["time"],
                    "start": offer["start"], "first_breach_time": s.clock(breach["t"]),
                    "first_breach_id": breach["id"], "first_breach_price": breach["price"],
                    "first_breach_lo": breach["lo"], "first_breach_hi": breach["hi"], "first_breach_reason": breach["reason"],
                    "completion": offer["completion"], "support": json.dumps(offer["support"]),
                    "failed": json.dumps(offer["failed"]), "claims": json.dumps(offer["claims"]),
                    "support_coverage": json.dumps(offer["support_coverage"]),
                    "claim_coverage": json.dumps(offer["claim_coverage"]),
                    "excursion_bounds": json.dumps(offer["excursion_bounds"])})
    for name, rows in (("old_offer_classification", classifications), ("old_member_extrema", extrema),
                       ("new_offer_lineage", new_lineage)):
        s.write_csv(f.OUT / f"{name}.csv", rows)
    s.write_json(f.OUT / "audit_manifest.json", {"script_sha256": f.sha(__file__),
        "comparison_manifest_sha256": f.sha(f.OUT / "manifest.json"),
        "qualification": "Exact-time matches are not one-to-one episode matches. Member extrema are retrospective descriptions truncated at permission, not model inputs; require an actually observed crossing of an already known claim in the model."})
    print(json.dumps({"old_permissions": len(classifications), "member_rows": len(extrema), "new_permissions": len(new_lineage)}))


if __name__ == "__main__":
    main()
