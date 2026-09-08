"""Read-only diagnostics of frozen stress permissions and risk exits."""
import json
from pathlib import Path

import episode_study as e
import stress_episodes as st
import study as s


def states_at(events, t):
    states = {}
    for event in events:
        if event["t"] > t:
            break
        if event["kind"] == "Reset":
            states.clear()
        elif event.get("id"):
            states[event["id"]] = event
    return states


def permission_context(events, offer, lineage=None):
    known = [r for r in events if r["t"] <= offer["t"]]
    owned = {r["id"]: r["t"] for r in known if r["kind"] == "RailOwned"}
    return {"time": offer["time"], "episode": offer["episode"], "signature": offer["signature"],
            "completion": offer["completion"], "claim_failure_time": s.clock(offer["claim_failure_t"]),
            "failure_age_seconds": round((offer["t"] - offer["claim_failure_t"]) / 1e6, 3)
            if offer["claim_failure_t"] is not None else None,
            "claim_clearance_ticks": offer["claim_clearance_ticks"],
            "support_owned_times": {k: s.clock(owned.get(k)) for k in offer["support"]},
            "support_formation": {k: {"formed": s.clock(lineage[k]["formed_t"]),
                                      "owned": s.clock(lineage[k]["owned_t"]),
                                      "source_side": lineage[k]["source_side"],
                                      "source": lineage[k]["source"],
                                      "formed_after_repair_failure": lineage[k]["formed_t"] > offer["claim_failure_t"]
                                      if offer["claim_failure_t"] is not None else None}
                                  for k in offer["support"] if lineage and k in lineage and lineage[k]["t"] <= offer["t"]},
            "support": offer["support"], "defended": offer["defended"], "claims": offer["claims"]}


def main():
    st.verify_frozen()
    permissions, risk_rows, endpoint_checks = [], [], []
    for case in st.CASES:
        m = st.market(case.day)
        lineage_path = m.directory / "lineage.jsonl"
        lineage = {r["id"]: r for r in s.read_lines(lineage_path)} if lineage_path.exists() else {}
        for root in s.root_seeds(case, m):
            context = {"case": case.name, "root_n": root["root_n"]}
            folder = st.OUT / case.name / f"root-{root['root_n']}" / "warm"
            offers = s.read_lines(folder / "offers.jsonl")
            permissions.extend(e.csv_rows([permission_context(m.events, r, lineage) for r in offers], context))
            for management in ("root_only", "tranche_groups", "latest_group_campaign"):
                run = json.loads((folder / f"typed_only-3-{management}.json").read_text())
                for action in run["actions"]:
                    if action["action"] != "exit" or action["reason"] == "window_mark":
                        continue
                    states = states_at(m.events, action["t"])
                    adds = [a for a in run["actions"] if a["action"] == "add" and a["t"] < action["t"]]
                    inventory_before = [q for q in run["inventory"] if q["t"] < action["t"]]
                    q = m.quote(action["t"])
                    supports = sorted({k for a in adds for k in a["support"]})
                    ending_event = next((r for r in m.events if r["order"] == root.get("failure_order")), {})
                    risk_rows.append({**context, "management": management, "time": action["time"],
                                      "reason": action["reason"], "quantity": action["quantity"],
                                      "exit_price_proxy": action["price"],
                                      "root_id": root["seed"]["id"],
                                      "root_state": states.get(root["seed"]["id"], {}).get("kind"),
                                      "root_cutoff_event_id": ending_event.get("id") if action["reason"] == "root_failure" else None,
                                      "support_states": {k: states.get(k, {}).get("kind") for k in supports},
                                      "position_average_before": inventory_before[-1]["position_average"] if inventory_before else None,
                                      "be_trigger_before": inventory_before[-1]["be_trigger"] if inventory_before else None,
                                      "bid": q["bid"] if q else None, "ask": q["ask"] if q else None,
                                      "later_typed_offer_times_label": [r["time"] for r in offers
                                                                       if r["signature"] == "typed_clear" and r["t"] > action["t"]]})
            if case.label == "stress-1150":
                longer = st.OUT / (case.name + "-extended") / f"root-{root['root_n']}" / "warm"
                cutoff = s.stamp(case.day, "12:30")
                later = [r for r in s.read_lines(longer / "offers.jsonl") if r["t"] <= cutoff]
                endpoint_checks.append({**context, "extension_preserves_primary_offers": offers == later})
    s.write_csv(st.OUT / "permission_context.csv", permissions)
    s.write_json(st.OUT / "risk_exit_context.json", risk_rows)
    s.write_json(st.OUT / "endpoint_validation.json", endpoint_checks)
    s.write_json(st.OUT / "audit_manifest.json", {
        "audit_sha256": st.sha(Path(__file__)), "study_manifest_sha256": st.sha(st.OUT / "manifest.json"),
        "frozen_episode_sha256": st.FROZEN_EPISODE_SHA256,
    })
    print(json.dumps(risk_rows, indent=2))
    print(json.dumps(endpoint_checks))


if __name__ == "__main__":
    main()
