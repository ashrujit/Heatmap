"""Readable rail histories and sanitized historical-runtime boundary, NQ only."""
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

import campaign_cycles as c
import study as s


def rail_histories():
    histories, lineage = [], []
    for day, root in (("2026-09-03", 2), ("2026-09-04", 1)):
        events = s.read_lines(c.OUT / f"{day}-events.jsonl")
        rails = defaultdict(list)
        for e in events:
            if e.get("id"):
                rails[e["id"]].append(e)
        for rail, rows in rails.items():
            first = rows[0]
            histories.append({"day": day, "rail_id": rail, "side": first["side"],
                              "lo": first["lo"], "hi": first["hi"],
                              "history": "; ".join(s.clock(e["t"]) + " " + e["kind"] for e in rows)})
        directory = c.OUT / f"NQ-{day}-cycles" / f"root-{root}"
        for capacity in (10, 100):
            baseline = {r["order"]: r for r in s.read_lines(directory / f"current-cap{capacity}/policy.jsonl")}
            for row in s.read_lines(directory / f"cycle_joint_zone-cap{capacity}/policy.jsonl"):
                if row["action"] != "AllowAdd" or not row["emitted"]:
                    continue
                cycle = row["cycle"]
                proof = next(e for e in reversed(rails[cycle["chosen_id"]]) if e["order"] <= row["order"])
                current = baseline[row["order"]]
                lineage.append({"day": day, "capacity": capacity, "add_time": s.clock(row["t"]),
                                "quantity": row["after"]["quantity"], "claim_id": cycle["claim_id"],
                                "claim_start": s.clock(s.iso_us(cycle["claim_started"])),
                                "claim_failed": s.clock(s.iso_us(cycle["failed_at"])),
                                "claim_lo": cycle["claim"]["lower"], "claim_hi": cycle["claim"]["upper"],
                                "proof_id": proof["id"], "proof_time": s.clock(proof["t"]),
                                "proof_kind": proof["kind"], "proof_lo": proof["lo"], "proof_hi": proof["hi"],
                                "proof_before_claim": proof["t"] < s.iso_us(cycle["claim_started"]),
                                "proof_age_seconds": round((row["t"] - proof["t"]) / 1e6, 3),
                                "source_reason_at_same_event": current["reason"],
                                "source_repair_before": current["before"]["repair_id"],
                                "source_repair_failed_before": current["before"]["failed"],
                                "proof_history_until_add": "; ".join(s.clock(e["t"]) + " " + e["kind"]
                                    for e in rails[proof["id"]] if e["order"] <= row["order"])})
    s.write_csv(c.OUT / "rail_histories.csv", histories)
    s.write_csv(c.OUT / "cycle_add_lineage.csv", lineage)
    return lineage


def runtime_boundary():
    path = Path.home() / "Documents/KahnRuntime/NQ/decisions.jsonl"
    selected = {"runtime_initialized", "runtime_stopped", "campaign_loaded", "campaign_state",
                "campaign_execution_paused", "evidence_warmup_started", "book_unusable",
                "order_submit_result", "root_probe_stop_flattened", "policy_decision",
                "position_reconciled"}
    fields = ("ts_utc", "event", "reason", "reason_code", "phase", "action", "role", "accepted",
              "quantity", "simulated_position_quantity", "live_position_quantity", "root_stop_ticks",
              "accepted_add_count", "instance_max_quantity", "campaign_max_position_quantity",
              "trading_enabled", "shadow_fill_simulation", "side", "status", "scale_mode",
              "ll_cluster_ticks", "ll_failure_confirm_ticks", "ll_failure_seconds", "book_sample_ms")
    rows = []
    for n, line in enumerate(path.open(encoding="utf-8"), 1):
        r = json.loads(line)
        if r.get("ts_utc"):
            rows.append((n, r))
    summary, timeline = [], []
    for day, start in (("2026-09-03", "10:55"), ("2026-09-04", "10:00")):
        lo, hi = s.stamp(day, start), s.stamp(day, "11:30")
        window = [(n, r) for n, r in rows if lo <= s.iso_us(r["ts_utc"]) <= hi]
        counts = Counter(r["event"] for _, r in window)
        inactive = Counter(r.get("phase", "unknown") for _, r in window if r["event"] == "evidence_seen_inactive")
        order_roles = Counter(r.get("role", "unknown") for _, r in window if r["event"] == "order_submit_result" and r.get("accepted"))
        prior = {}
        for n, r in rows:
            if s.iso_us(r["ts_utc"]) >= lo:
                break
            if r["event"] in ("runtime_initialized", "campaign_state", "campaign_loaded", "position_reconciled"):
                prior[r["event"]] = {"line": n, **{k: r[k] for k in fields if k in r}}
        summary.append({"day": day, "start": start, "end": "11:30", "event_counts": dict(counts),
                        "inactive_log_phases": dict(inactive), "accepted_submission_roles": dict(order_roles),
                        "last_logged_context_before_window": prior})
        for n, r in window:
            if r["event"] in selected:
                timeline.append({"day": day, "line": n, "time": s.clock(s.iso_us(r["ts_utc"])),
                                 **{k: r[k] for k in fields if k in r}})
    s.write_csv(c.OUT / "runtime_boundary.csv", timeline)
    s.write_json(c.OUT / "runtime_boundary.json", {"source": str(path),
                 "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "windows": summary,
                 "limits": "Recorded profile events, not continuous proof of position or loaded-binary identity. No account/order identifiers exported."})
    return summary


def main():
    lineage = rail_histories()
    boundary = runtime_boundary()
    for r in lineage:
        if r["capacity"] == 100:
            print(json.dumps(r))
    for r in boundary:
        print(json.dumps({k: v for k, v in r.items() if k != "last_logged_context_before_window"}))


if __name__ == "__main__":
    main()
