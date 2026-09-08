"""NQ-only full-morning structural scale audit, with GEX and zones excluded."""
import hashlib
import json
import math
from collections import Counter

import study as s


OUT = s.REPO / "research/out/kahn-nq-cycles-20260906"
VARIANTS = ("current", "preserve_noop", "preserve_all", "cycle_joint_range", "cycle_joint", "cycle_joint_zone")


def be_diagnostic(case, market, root, actions):
    """Quote-based backstop path check, not a simulated broker order or P&L."""
    fills = []
    for action in actions:
        if action["action"] != "AllowAdd":
            continue
        q = market.quote(action["t"] + 250_000, forward=True)
        if q is None:
            return {"be_status": "missing_fill_quote"}
        price = q["ask"] + .25 if case.sign > 0 else q["bid"] - .25
        fills.append({"t": q["t"], "price": price, "time": s.clock(q["t"]), "signal_time": action["time"]})
    risk_end = min((a["t"] for a in actions if a["action"] in ("Flatten", "Retire")),
                   default=s.stamp(case.day, "11:30"))
    quantity, average, index, armed = 2, root["price"], 0, False
    last_trigger = None
    for q in market.quotes:
        if q["t"] < root["t"] or q["t"] > risk_end:
            continue
        while index < len(fills) and fills[index]["t"] <= q["t"]:
            average = (average * quantity + fills[index]["price"] * 2) / (quantity + 2)
            quantity += 2
            index += 1
        if quantity <= 2:
            continue
        trigger = (math.ceil(average / .25 - 1e-9) if case.sign > 0 else math.floor(average / .25 + 1e-9)) * .25
        executable = q["bid"] if case.sign > 0 else q["ask"]
        touched = case.sign * (executable - trigger) <= 0
        if touched and armed:
            return {"be_status": "touch_proxy", "be_touch_time": s.clock(q["t"]),
                    "be_trigger": trigger, "be_quote_quantity": quantity, "quote_fills": fills}
        if not touched:
            armed = True
            last_trigger = trigger
    return {"be_status": "no_touch_before_risk_exit_or_1130", "be_trigger": last_trigger,
            "be_quote_quantity": quantity, "quote_fills": fills}


def run(case, market, root, variant, capacity):
    directory = OUT / case.name / f"root-{root['root_n']}" / f"{variant}-cap{capacity}"
    directory.mkdir(parents=True, exist_ok=True)
    cfg = {"side": case.side, "seed_t": root["t"], "seed_order": root["seed"]["order"],
           "end_t": s.stamp(case.day, "11:30"), "root": [root["seed"]["lo"], root["seed"]["hi"]],
           "root_price": root["price"], "arena": [1, 100000], "max_quantity": capacity,
           "full_campaign": True, "state_variant": variant}
    s.write_json(directory / "seed.json", cfg)
    s.run_engine("policy", directory / "seed.json", market.directory / "events.jsonl", directory / "policy.jsonl")
    rows = s.read_lines(directory / "policy.jsonl")
    by_order = {e["order"]: e for e in market.events}
    failed_at = {}
    for e in market.events:
        if e["kind"] == "RailFailed":
            failed_at[e["id"]] = e["t"]
    audit, actions = [], []
    for r in rows:
        e = by_order[r["order"]]
        before, after = r.get("before", {}), r.get("after", {})
        clear = before.get("repair") is not None and after.get("repair") is None
        unchanged = before.get("candidate_id") == after.get("candidate_id")
        same = e.get("side") == case.same and e["kind"] in s.KINDS
        suppressed = before.get("suppressed_until") and s.iso_us(before["suppressed_until"]) >= r["t"]
        pending_event = by_order.get(int(before["pending_id"].split("-")[-1])) if before.get("pending_id") else None
        pending_failure_t = failed_at.get(pending_event["id"]) if pending_event else None
        pending_failed = pending_failure_t is not None and pending_failure_t <= r["t"]
        promotion = (r["action"] == "AllowAdd" and r["emitted"] and before.get("pending") is not None
                     and after.get("active") == before["pending"])
        item = {"case": case.name, "root_n": root["root_n"], "variant": variant, "capacity": capacity,
                "t": r["t"], "time": s.clock(r["t"]), "order": e["order"], "event": e["kind"],
                "rail_id": e.get("id"), "side": e.get("side"), "lo": e.get("lo"), "hi": e.get("hi"),
                "price": e.get("price"), "action": r["action"], "reason": r["reason"], "emitted": r["emitted"],
                "quantity": after.get("quantity"), "accepted_adds": after.get("accepted_adds"),
                "repair_cleared": clear, "candidate_unchanged": unchanged,
                "same_side_while_suppressed": bool(same and suppressed),
                "preserved_repair": r.get("preserved_repair", False),
                "pending_failed_before": pending_failed,
                "promoted_failed_pending": bool(promotion and pending_failed),
                "pending_failure_time": s.clock(pending_failure_t) if pending_failed else None,
                "cycle_claim": (r.get("cycle") or {}).get("claim_id"),
                "cycle_proof": (r.get("cycle") or {}).get("chosen_id"),
                "active_lo": after.get("active", {}).get("lower") if after.get("active") else None,
                "active_hi": after.get("active", {}).get("upper") if after.get("active") else None,
                "pending_lo": after.get("pending", {}).get("lower") if after.get("pending") else None,
                "pending_hi": after.get("pending", {}).get("upper") if after.get("pending") else None,
                "repair_id_before": before.get("repair_id"), "candidate_id_before": before.get("candidate_id")}
        audit.append(item)
        if r["emitted"] and r["action"] in ("AllowAdd", "Flatten", "Reduce", "Retire", "HoldRoot"):
            actions.append(item)
    summary = {"case": case.name, "root_n": root["root_n"], "root_time": s.clock(root["t"]),
               "root_price": root["price"], "variant": variant, "capacity": capacity,
               "adds": sum(a["action"] == "AllowAdd" for a in actions),
               "add_times": ";".join(a["time"] for a in actions if a["action"] == "AllowAdd"),
               "risk_actions": ";".join(a["time"] + ":" + a["reason"] for a in actions if a["action"] != "AllowAdd"),
               "candidate_repair_clears": sum(a["repair_cleared"] and a["action"] == "TrackScaleCandidate" for a in audit),
               "noop_repair_clears": sum(a["repair_cleared"] and a["candidate_unchanged"] and a["action"] == "TrackScaleCandidate" for a in audit),
               "favorable_suppressed": sum(a["same_side_while_suppressed"] for a in audit),
               "promoted_failed_pending": sum(a["promoted_failed_pending"] for a in audit),
               "end_quantity": audit[-1]["quantity"] if audit else 2,
               "reasons": dict(Counter(a["reason"] for a in audit))}
    summary.update(be_diagnostic(case, market, root, actions))
    return audit, actions, summary


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    audits, actions, summaries = [], [], []
    for day, side, start in (("2026-09-03", "long", "10:55"), ("2026-09-04", "short", "10:00")):
        case = s.Case("NQ", day, side, start, "11:30", "cycles")
        market = s.Market("NQ", day)
        window = [e for e in market.events if s.stamp(day, start) <= e["t"] <= s.stamp(day, "11:30")]
        s.write_lines(OUT / f"{day}-events.jsonl", window)
        s.write_csv(OUT / f"{day}-events.csv", [{**e, "time": s.clock(e["t"])} for e in window])
        print(case.name, Counter((e.get("side"), e["kind"]) for e in window), flush=True)
        for root in s.root_seeds(case, market):
            for capacity in (10, 100):
                for variant in VARIANTS:
                    audit, executed, summary = run(case, market, root, variant, capacity)
                    audits.extend(audit)
                    actions.extend(executed)
                    summaries.append(summary)
                    print(json.dumps({k: v for k, v in summary.items() if k not in ("reasons", "quote_fills")}), flush=True)
    s.write_csv(OUT / "event_audit.csv", audits)
    s.write_csv(OUT / "actions.csv", actions)
    s.write_json(OUT / "summary.json", summaries)
    s.write_json(OUT / "manifest.json", {
        "scope": "NQ Sep 3 10:55-11:30 long; Sep 4 10:00-11:30 short; no GEX/zone constraints",
        "interventions": {"current": "unchanged source policy/state",
                          "preserve_noop": "bypass only repair clearing when favorable tracking does not advance candidate",
                          "preserve_all": "bypass repair clearing on all favorable candidate tracking",
                          "cycle_joint_range": "cycle_joint but same-side proof must also overlap/pass the repair range",
                          "cycle_joint": "exact-ID typed repair failure plus current advancing surviving proof; proof can precede claim; price beyond repair; consume once per accepted add",
                          "cycle_joint_zone": "cycle_joint plus all still-live opposite rails within two ticks of repair must fail"},
        "limits": "Structural policy simulation, not live fills; event midpoint adds; BE assessed separately, no harvest; capacity 100 diagnostic only",
        "prototype_caveat": "Joint variants bundle retained observation, preserved repair, exact identity, pre-claim proof and price reclaim. They replace serial Press admission and its repair suppression, not only event ordering. Latest-claim approximation, no proof age limit, no broker/expiry worker.",
        "source_hashes": {name: hashlib.sha256((s.REPO / "KahnRuntime" / name).read_bytes()).hexdigest()
                          for name in ("CampaignContracts.cs", "CampaignPolicy.cs", "LevelLedgerEvidenceEngine.cs")},
        "research_hashes": {name: hashlib.sha256((s.ENGINE.parents[3] / name).read_bytes()).hexdigest()
                            for name in ("Program.cs", "EngineProbe.csproj")},
        "driver_hashes": {name: hashlib.sha256((s.REPO / "research/kahn/scale_cycle_study" / name).read_bytes()).hexdigest()
                          for name in ("study.py", "campaign_cycles.py", "test_campaign_cycles.py", "audit_cycles.py", "render_cycles.py")},
        "input_hashes": {f"NQ-{day}/{name}": hashlib.sha256((s.OUT / f"NQ-{day}" / name).read_bytes()).hexdigest()
                         for day in ("2026-09-03", "2026-09-04")
                         for name in ("events.jsonl", "quotes.parquet", "quality.json")},
    })


if __name__ == "__main__":
    main()
