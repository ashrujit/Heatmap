import unittest

import far_edge_study as f
from test_study import BASE, event, root


class FarEdgeTests(unittest.TestCase):
    def test_fixture_names_are_unique(self):
        names = [case.name for case in f.fixtures()]
        self.assertEqual(len(names), len(set(names)))

    def replay(self, rows, cls=f.ExcursionObserver):
        observer = cls("long", root())
        for t, batch in f.old.groupby(rows, lambda r: r["t"]):
            batch = list(batch)
            observer.step(t, batch[-1]["price"], batch)
        return observer

    def fixture(self, low=104.75):
        return [event(5, "proof", "demand", 105, 106, price=115),
                event(10, "proof", "demand", 105, 106, "RailTested", price=106),
                event(11, "claim", "supply", 109, 110, price=low),
                event(20, "proof", "demand", 105, 106, "RailHeld", price=111),
                event(30, "claim", "supply", 109, 110, "RailFailed", price=116)]

    def test_upper_edge_touch_is_not_repair(self):
        self.assertEqual([], self.replay(self.fixture(106)).offers)

    def test_inside_or_exact_far_edge_is_not_repair(self):
        for low in (105.5, 105):
            with self.subTest(low=low):
                self.assertEqual([], self.replay(self.fixture(low)).offers)

    def test_far_edge_cross_without_formal_failure_is_repair(self):
        obs = self.replay(self.fixture())
        self.assertEqual(1, len(obs.offers))
        self.assertEqual(BASE + 11_000_000, obs.offers[0]["start_t"])
        self.assertEqual(["proof"], obs.offers[0]["defended"])
        self.assertEqual([], obs.offers[0]["failed"])

    def test_quote_only_cross_does_not_need_a_new_test_message(self):
        obs = self.replay(self.fixture()[:2])
        obs.step(BASE + 10_500_000, 104.75)
        self.assertEqual(BASE + 10_500_000, obs.episode.start)

    def test_actual_trade_cross_between_quotes_is_observed(self):
        obs = self.replay(self.fixture()[:2])
        obs.step(BASE + 11_000_000, 108, [self.fixture()[2]],
                 path=[(BASE + 10_200_000, 104.75), (BASE + 10_800_000, 108)])
        self.assertEqual(BASE + 10_200_000, obs.episode.start)

    def test_trade_before_new_claim_is_not_a_retroactive_test(self):
        obs = f.ExcursionObserver("long", root())
        obs.step(BASE + 5_000_000, 115, [self.fixture()[0]],
                 path=[(BASE + 1_000_000, 104), (BASE + 4_000_000, 115)])
        self.assertIsNone(obs.episode)

    def test_opposing_ownership_alone_does_not_open_episode(self):
        obs = self.replay([event(10, "claim", "supply", 109, 110, price=108)])
        self.assertIsNone(obs.episode)

    def test_warm_opposing_claim_alone_does_not_open_episode(self):
        obs = f.ExcursionObserver("long", root(), [event(-5, "claim", "supply", 109, 110)])
        self.assertIsNone(obs.episode)

    def test_old_opposition_failed_before_breach_is_not_permission(self):
        rows = self.fixture()
        rows.insert(1, event(6, "old", "supply", 109, 110, "RailFailed", price=115))
        rows = [r for r in rows if r["id"] != "claim"]
        rows.insert(3, event(11, "proof", "demand", 105, 106, "RailTested", price=104.75))
        rows.sort(key=lambda r: r["t"])
        self.assertEqual([], self.replay(rows).offers)

    def test_rebuilt_proof_inside_repair_needs_no_retest(self):
        rows = self.fixture()[:3] + [
            event(15, "proof", "demand", 105, 106, "RailFailed", price=104),
            event(20, "new", "demand", 106, 107, price=111), self.fixture()[-1]]
        obs = self.replay(rows)
        self.assertEqual(["new"], obs.offers[0]["support"])
        self.assertEqual([], obs.offers[0]["defended"])

    def test_failure_of_one_claim_cannot_clear_live_companion(self):
        rows = self.fixture()
        rows.insert(3, event(12, "companion", "supply", 110, 111, price=108))
        self.assertEqual([], self.replay(rows).offers)

    def test_outside_opposition_is_not_a_member(self):
        rows = self.fixture()
        rows.insert(3, event(12, "remote", "supply", 125, 126, price=108))
        obs = self.replay(rows)
        self.assertEqual(["claim"], obs.offers[0]["claims"])

    def test_unrelated_later_owned_cannot_reuse_departed_repair(self):
        rows = self.fixture()[:3] + [
            event(15, "proof", "demand", 105, 106, "RailFailed", price=104),
            self.fixture()[-1], event(350, "remote", "demand", 140, 141, price=148)]
        obs = self.replay(rows)
        self.assertEqual([], obs.offers)
        self.assertEqual("departed_without_associated_proof", obs.completed[-1]["resolution"])

    def test_same_sample_new_live_claim_blocks_completion(self):
        rows = self.fixture() + [event(30, "companion", "supply", 110, 111, price=116)]
        self.assertEqual([], self.replay(rows).offers)

    def test_repeated_hold_does_not_create_another_repair(self):
        rows = self.fixture() + [event(40, "proof", "demand", 105, 106, "RailHeld", price=118)]
        self.assertEqual(1, len(self.replay(rows).offers))

    def test_new_far_edge_attack_can_reuse_same_area(self):
        rows = self.fixture() + [event(40, "proof", "demand", 105, 106, "RailTested", price=104.75),
            event(41, "claim2", "supply", 109, 110, price=108),
            event(50, "proof", "demand", 105, 106, "RailHeld", price=111),
            event(60, "claim2", "supply", 109, 110, "RailFailed", price=119)]
        self.assertEqual(2, len(self.replay(rows).offers))

    def test_new_attack_after_resolution_does_not_need_old_extreme_break(self):
        rows = self.fixture()
        rows[-1] = {**rows[-1], "price": 112}
        rows += [event(40, "proof", "demand", 105, 106, "RailTested", price=104.75),
                 event(41, "claim2", "supply", 109, 110, price=108),
                 event(50, "proof", "demand", 105, 106, "RailHeld", price=111),
                 event(60, "claim2", "supply", 109, 110, "RailFailed", price=113)]
        obs = self.replay(rows)
        self.assertEqual(2, len(obs.offers))
        self.assertEqual("resolved_then_new_far_edge_attack", obs.completed[0]["resolution"])

    def test_explicit_parent_fragmentation_preserves_boundaries(self):
        rows = self.fixture(105.5)
        fragments = []
        for r in rows:
            for suffix, lo, hi in (("a", r["lo"], r["lo"]), ("b", r["lo"] + .25, r["hi"])):
                fragments.append({**r, "id": r["id"] + suffix, "lo": lo, "hi": hi,
                                  "claim_id": r["id"], "claim_lo": r["lo"], "claim_hi": r["hi"]})
        self.assertEqual(f.canonical(self.replay(rows)), f.canonical(self.replay(fragments)))

    def test_short_reflects_long(self):
        def reflect(row):
            return {**row, "lo": 300 - row["hi"], "hi": 300 - row["lo"],
                    "price": 300 - row["price"], "side": "supply" if row["side"] == "demand" else "demand"}
        seed = root()
        obs = f.ExcursionObserver("short", {**seed, "price": 300 - seed["price"], "seed": reflect(seed["seed"])})
        for row in map(reflect, self.fixture()):
            obs.step(row["t"], row["price"], [row])
        self.assertEqual([r["t"] for r in self.replay(self.fixture()).offers], [r["t"] for r in obs.offers])

    def test_gate_removes_touch_only_old_offer(self):
        obs = self.replay(self.fixture(106), f.EdgeGate)
        self.assertEqual([], obs.offers)
        self.assertTrue(obs.rejected)

    def test_gap_stops_observation(self):
        obs = self.replay(self.fixture()[:3])
        obs.step(BASE + 15_000_000, 108, [{"t": BASE + 15_000_000, "kind": "Reset"}])
        for row in self.fixture()[3:]:
            obs.step(row["t"], row["price"], [row])
        self.assertEqual([], obs.offers)
        self.assertTrue(obs.stopped)


if __name__ == "__main__":
    unittest.main()
