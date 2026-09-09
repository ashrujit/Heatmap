"""Research reconstruction invariants; no production policy assertions."""

import unittest

from audit import Ledger, reconstruct


def event(kind, identity=1, side="Supply", low=120, high=124, at="10:00:00"):
    return {"event": "ll_transition", "ts_utc": "2026-09-09T" + at + "Z",
            "event_utc": "2026-09-09T" + at + "Z", "kind": kind,
            "actionable": True, "band_role": "Rail", "band_id": identity,
            "band_side": side, "band_source": "Lean", "band_min_tick": low,
            "band_max_tick": high, "band_state": "Failed" if kind == "RailFailed" else "Owned"}


def probe(side="Demand", at="10:02:00"):
    return {"event": "policy_decision", "action": "AllowProbe",
            "ts_utc": "2026-09-09T" + at + "Z", "campaign_id": "nq-short-campaign-test",
            "reason_code": "counter_claim_failed_at_trap_probe", "evidence_kind": "RailFailed",
            "evidence_side": side, "evidence_id": "live-ll-2-RailFailed-0"}


class ReconstructionTests(unittest.TestCase):
    def test_campaign_change_preserves_live_rails(self):
        ledger = Ledger()
        ledger.consume(event("RailOwned"), 1)
        ledger.consume({"event": "campaign_loaded", "campaign_id": "new", "ts_utc": "2026-09-09T10:01:00Z"}, 2)
        self.assertTrue(ledger.rails[1]["live"])

    def test_epoch_change_discards_old_identity(self):
        ledger = Ledger()
        ledger.consume(event("RailOwned"), 1)
        ledger.consume({"event": "evidence_warmup_started", "ts_utc": "2026-09-09T10:01:00Z"}, 2)
        self.assertFalse(ledger.rails)
        self.assertFalse(ledger.ready)

    def test_failed_rail_cannot_be_candidate(self):
        ledger = Ledger()
        ledger.consume(event("RailOwned"), 1)
        ledger.consume(event("RailFailed"), 2)
        ledger.consume(event("RailFailed", 2, "Demand", 100, 104), 3)
        self.assertFalse(ledger.entry_snapshot(probe(), 4)["directional_candidates"])

    def test_future_rail_does_not_change_entry(self):
        rows = [(1, event("RailFailed", 2, "Demand", 100, 104)), (2, probe())]
        before = reconstruct(rows, "2026-09-09T10:00:00Z", "2026-09-09T10:04:00Z")
        rows.append((3, event("RailOwned", at="10:03:00")))
        after = reconstruct(rows, "2026-09-09T10:00:00Z", "2026-09-09T10:04:00Z")
        self.assertEqual(before, after)

    def test_snapshot_does_not_mutate_with_future_failure(self):
        ledger = Ledger()
        ledger.consume(event("RailOwned"), 1)
        ledger.consume(event("RailFailed", 2, "Demand", 100, 104), 2)
        snapshot = ledger.entry_snapshot(probe(), 3)
        ledger.consume(event("RailFailed", at="10:03:00"), 4)
        self.assertTrue(snapshot["directional_candidates"][0]["live"])

    def test_multiple_candidates_are_not_silently_selected(self):
        ledger = Ledger()
        ledger.consume(event("RailOwned"), 1)
        ledger.consume(event("RailOwned", 3, low=121, high=125), 2)
        ledger.consume(event("RailFailed", 2, "Demand", 100, 104), 3)
        snapshot = ledger.entry_snapshot(probe(), 4)
        self.assertEqual(len(snapshot["directional_candidates"]), 2)
        self.assertEqual(snapshot["overlapping_candidate_pairs"], [[1, 3]])

    def test_hold_without_ownership_history_is_not_complete_provenance(self):
        ledger = Ledger()
        ledger.consume(event("RailHeld"), 1)
        ledger.consume(event("RailFailed", 2, "Demand", 100, 104), 2)
        self.assertFalse(ledger.entry_snapshot(probe(), 3)["directional_candidates"])

    def test_long_symmetry(self):
        ledger = Ledger()
        ledger.consume(event("RailOwned", 1, "Demand", 80, 84), 1)
        ledger.consume(event("RailFailed", 2, "Supply", 100, 104), 2)
        row = probe("Supply")
        row["campaign_id"] = "nq-long-campaign-test"
        snapshot = ledger.entry_snapshot(row, 3)
        self.assertEqual([r["id"] for r in snapshot["directional_candidates"]], [1])

    def test_counter_side_does_not_depend_on_campaign_name(self):
        ledger = Ledger()
        ledger.consume(event("RailOwned"), 1)
        ledger.consume(event("RailFailed", 2, "Demand", 100, 104), 2)
        row = probe()
        row["campaign_id"] = "operator-selected-name"
        self.assertEqual(ledger.entry_snapshot(row, 3)["campaign_side"], "Supply")

    def test_tested_is_not_failed(self):
        ledger = Ledger()
        ledger.consume(event("RailOwned"), 1)
        ledger.consume(event("RailTested", at="10:01:00"), 2)
        ledger.consume(event("RailFailed", 2, "Demand", 100, 104), 3)
        snapshot = ledger.entry_snapshot(probe(), 4)
        self.assertEqual([r["id"] for r in snapshot["directional_candidates"]], [1])
        self.assertIsNone(snapshot["directional_candidates"][0]["failed_at"])

    def test_candidate_diagnostics_do_not_mutate_inventory(self):
        ledger = Ledger()
        ledger.consume(event("RailOwned"), 1)
        ledger.consume(event("RailFailed", 2, "Demand", 100, 104), 2)
        snapshot = ledger.entry_snapshot(probe(), 3)
        self.assertNotIn("known_before_trigger_formed", snapshot["live_same_side"][0])
        self.assertEqual(snapshot["association_status"], "not_resolved_by_this_audit")


if __name__ == "__main__":
    unittest.main()
