"""Regression fixtures for the offline full-campaign observer and source audit."""
import unittest

import campaign_cycles as c
import study as s
from test_study import BASE, event


@unittest.skipUnless(s.ENGINE.exists(), "Build the standalone EngineProbe first")
class CampaignCycleTests(unittest.TestCase):
    def replay(self, events, variant="current", capacity=10, end=600):
        directory = c.OUT / "tests" / self._testMethodName / variant
        s.write_json(directory / "seed.json", {
            "side": "long", "seed_t": BASE, "seed_order": -1,
            "end_t": BASE + end * 1_000_000, "root": [100, 101],
            "root_price": 102, "arena": [1, 100000], "full_campaign": True,
            "state_variant": variant, "max_quantity": capacity,
        })
        s.write_lines(directory / "events.jsonl", events)
        s.run_engine("policy", directory / "seed.json", directory / "events.jsonl", directory / "policy.jsonl")
        return s.read_lines(directory / "policy.jsonl")

    @staticmethod
    def adds(rows):
        return [r for r in rows if r["action"] == "AllowAdd" and r["emitted"]]

    @staticmethod
    def serial_fixture():
        return [event(5, "candidate", "demand", 105, 106),
                event(10, "claim", "supply", 110, 111),
                event(70, "claim", "supply", 110, 111, "RailFailed"),
                event(80, "proof", "demand", 112, 113),
                event(90, "candidate2", "demand", 120, 121, price=130),
                event(100, "claim2", "supply", 125, 126, price=130),
                event(150, "claim2", "supply", 125, 126, "RailFailed", price=130),
                event(160, "proof2", "demand", 127, 128, price=130)]

    def test_source_replay_continues_after_first_add(self):
        rows = self.replay(self.serial_fixture())
        self.assertEqual([800, 1600], [r["order"] for r in self.adds(rows)])
        self.assertEqual(6, rows[-1]["after"]["quantity"])
        self.assertEqual((112, 113), tuple(rows[-1]["after"]["active"][k] for k in ("lower", "upper")))

    def test_capacity_stops_adds_not_observation(self):
        rows = self.replay(self.serial_fixture(), capacity=4)
        self.assertEqual(1, len(self.adds(rows)))
        self.assertEqual(1600, rows[-1]["order"])
        self.assertEqual(4, rows[-1]["after"]["quantity"])

    def test_noop_candidate_must_not_erase_repair_in_intervention(self):
        events = [event(5, "candidate", "demand", 112, 113),
                  event(10, "claim", "supply", 110, 111),
                  event(60, "candidate", "demand", 112, 113, "RailHeld"),
                  event(70, "claim", "supply", 110, 111, "RailFailed"),
                  event(80, "proof", "demand", 115, 116, price=118)]
        current = self.replay(events)
        preserved = self.replay(events, "preserve_noop")
        self.assertEqual(current[2]["before"]["candidate_id"], current[2]["after"]["candidate_id"])
        self.assertIsNone(current[2]["after"]["repair"])
        self.assertIsNotNone(preserved[2]["after"]["repair"])
        self.assertEqual(0, len(self.adds(current)))
        self.assertEqual(1, len(self.adds(preserved)))

    def test_advancing_candidate_preservation_is_separate_hypothesis(self):
        events = [event(5, "candidate", "demand", 105, 106),
                  event(10, "claim", "supply", 110, 111),
                  event(60, "new", "demand", 112, 113),
                  event(70, "claim", "supply", 110, 111, "RailFailed"),
                  event(80, "proof", "demand", 115, 116, price=118)]
        self.assertEqual(0, len(self.adds(self.replay(events, "preserve_noop"))))
        self.assertEqual(1, len(self.adds(self.replay(events, "preserve_all"))))

    def test_surviving_proof_can_precede_formal_claim(self):
        events = [event(5, "proof", "demand", 105, 106),
                  event(10, "claim", "supply", 110, 111),
                  event(70, "claim", "supply", 110, 111, "RailFailed")]
        rows = self.replay(events, "cycle_joint")
        self.assertEqual([700], [r["order"] for r in self.adds(rows)])
        self.assertEqual("proof", self.adds(rows)[0]["cycle"]["chosen_id"])
        self.assertEqual(0, len(self.adds(self.replay(events))))

    def test_tested_proof_suspends_until_hold(self):
        events = [event(5, "proof", "demand", 105, 106),
                  event(10, "claim", "supply", 110, 111),
                  event(60, "proof", "demand", 105, 106, "RailTested"),
                  event(70, "claim", "supply", 110, 111, "RailFailed"),
                  event(80, "proof", "demand", 105, 106, "RailHeld")]
        self.assertEqual([800], [r["order"] for r in self.adds(self.replay(events, "cycle_joint"))])

    def test_retained_range_rule_is_not_the_same_as_price_reclaim(self):
        events = [event(5, "proof", "demand", 105, 106),
                  event(10, "claim", "supply", 110, 111),
                  event(70, "claim", "supply", 110, 111, "RailFailed"),
                  event(80, "newproof", "demand", 112, 113)]
        self.assertEqual([700], [r["order"] for r in self.adds(self.replay(events, "cycle_joint"))])
        self.assertEqual([800], [r["order"] for r in self.adds(self.replay(events, "cycle_joint_range"))])

    def test_neighbor_failure_is_not_exact_claim_failure(self):
        events = [event(5, "proof", "demand", 105, 106),
                  event(10, "claim", "supply", 110, 111),
                  event(70, "neighbor", "supply", 110, 111, "RailFailed"),
                  event(80, "proof", "demand", 105, 106, "RailHeld")]
        self.assertEqual(0, len(self.adds(self.replay(events, "cycle_joint"))))

    def test_zone_variant_waits_for_live_companion(self):
        events = [event(5, "proof", "demand", 105, 106),
                  event(10, "claim", "supply", 110, 111),
                  event(12, "companion", "supply", 110.5, 111.5),
                  event(70, "companion", "supply", 110.5, 111.5, "RailFailed"),
                  event(71, "claim", "supply", 110, 111, "RailFailed")]
        self.assertEqual([700], [r["order"] for r in self.adds(self.replay(events, "cycle_joint"))])
        self.assertEqual([710], [r["order"] for r in self.adds(self.replay(events, "cycle_joint_zone"))])

    def test_consumed_claim_and_nonadvancing_proof_cannot_repeat_add(self):
        events = [event(5, "proof", "demand", 105, 106),
                  event(10, "claim", "supply", 110, 111),
                  event(70, "claim", "supply", 110, 111, "RailFailed"),
                  event(80, "proof", "demand", 105, 106, "RailHeld"),
                  event(90, "claim2", "supply", 120, 121, price=125),
                  event(150, "claim2", "supply", 120, 121, "RailFailed", price=125),
                  event(160, "proof", "demand", 105, 106, "RailHeld", price=125)]
        self.assertEqual(1, len(self.adds(self.replay(events, "cycle_joint"))))

    def test_future_events_do_not_rewrite_observer_prefix(self):
        events = self.serial_fixture()
        prefix = self.replay(events[:4], "cycle_joint")
        full = self.replay(events, "cycle_joint")
        self.assertEqual(prefix, full[:4])

    def test_failed_pending_promotion_is_exposed_not_silently_fixed(self):
        events = self.serial_fixture()
        events.insert(4, event(85, "proof", "demand", 112, 113, "RailFailed"))
        rows = self.replay(events)
        failed = next(r for r in rows if r["order"] == 850)
        promoted = self.adds(rows)[-1]
        self.assertEqual(failed["before"]["pending"], failed["after"]["pending"])
        self.assertEqual(failed["after"]["pending"], promoted["after"]["active"])
        self.assertEqual(6, promoted["after"]["quantity"])

    def test_risk_failure_exits_and_does_not_reenter(self):
        events = [event(1, "root", "demand", 100, 101, "RailFailed")] + self.serial_fixture()
        rows = self.replay(events, "cycle_joint")
        self.assertEqual("Flatten", rows[0]["action"])
        self.assertEqual(0, rows[-1]["after"]["quantity"])
        self.assertEqual(0, len(self.adds(rows)))

    def test_epoch_reset_censors_campaign(self):
        events = self.serial_fixture()
        events.insert(2, {"t": BASE + 50_000_000, "order": 500, "kind": "Reset"})
        rows = self.replay(events, "cycle_joint")
        self.assertEqual("Censored", rows[-1]["action"])
        self.assertEqual(0, len(self.adds(rows)))

    def test_explicit_sponsor_failure_blocks_later_joint_add(self):
        events = [event(5, "proof", "demand", 105, 106),
                  event(10, "claim", "supply", 110, 111),
                  event(60, "root", "demand", 100, 101, "SponsorFailed"),
                  event(70, "claim", "supply", 110, 111, "RailFailed")]
        rows = self.replay(events, "cycle_joint")
        self.assertEqual(0, len(self.adds(rows)))
        self.assertEqual("Flatten", rows[2]["action"])
        self.assertEqual(0, rows[-1]["after"]["quantity"])


if __name__ == "__main__":
    unittest.main()
