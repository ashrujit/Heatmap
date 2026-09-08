import copy
import unittest

import episode_study as e
from test_study import BASE, event, root


class EpisodeTests(unittest.TestCase):
    def replay(self, rows, warm=()):
        observer = e.Observer("long", root(), warm)
        for t, events in e.groupby(rows, lambda r: r["t"]):
            batch = list(events)
            observer.step(t, batch[-1].get("price", 115), batch)
        return observer

    def fixture(self):
        return [event(5, "proof", "demand", 105, 106, price=115),
                event(10, "proof", "demand", 105, 106, "RailTested", price=105),
                event(11, "claim", "supply", 110, 111, price=108),
                event(20, "proof", "demand", 105, 106, "RailHeld", price=109),
                event(30, "claim", "supply", 110, 111, "RailFailed", price=118)]

    def test_shared_episode_with_defense_and_typed_failure(self):
        o = self.replay(self.fixture())
        self.assertEqual(1, len(o.completed))
        self.assertEqual(["typed_clear"], [r["signature"] for r in o.offers])
        self.assertEqual(["proof"], o.offers[0]["support"])

    def test_short_is_the_price_reflection_of_long(self):
        def reflect(row):
            return {**row, "lo": 300 - row["hi"], "hi": 300 - row["lo"],
                    "price": 300 - row["price"],
                    "side": "supply" if row["side"] == "demand" else "demand"}
        seed = root()
        short = e.Observer("short", {**seed, "price": 300 - seed["price"], "seed": reflect(seed["seed"])})
        for row in map(reflect, self.fixture()):
            short.step(row["t"], row["price"], [row])
        long = self.replay(self.fixture())
        self.assertEqual([(r["t"], r["signature"], r["support"]) for r in long.offers],
                         [(r["t"], r["signature"], r["support"]) for r in short.offers])

    def test_owned_but_untested_is_not_defended(self):
        rows = [r for r in self.fixture() if r["kind"] not in ("RailHeld", "RailTested")]
        o = self.replay(rows)
        self.assertEqual([], o.offers[0]["defended"])
        self.assertEqual("clearance_without_defended_member", o.offers[0]["completion"])

    def test_every_relevant_opposing_member_must_fail(self):
        rows = self.fixture()
        rows.insert(3, event(12, "companion", "supply", 109, 110, price=108))
        self.assertEqual([], self.replay(rows).offers)
        rows.append(event(31, "companion", "supply", 109, 110, "RailFailed", price=119))
        self.assertEqual(BASE + 31_000_000, self.replay(rows).offers[0]["t"])

    def test_partial_member_failure_does_not_destroy_defended_group(self):
        rows = self.fixture()
        rows.insert(1, event(6, "other", "demand", 106, 107, price=115))
        rows.insert(5, event(21, "other", "demand", 106, 107, "RailFailed", price=109))
        rows.sort(key=lambda r: r["t"])
        o = self.replay(rows)
        self.assertEqual(["other"], o.offers[0]["failed"])
        self.assertEqual(["proof"], o.offers[0]["defended"])

    def test_old_untested_root_does_not_rescue_failed_attacked_area(self):
        rows = self.fixture()[:3] + [event(20, "proof", "demand", 105, 106, "RailFailed", price=104)]
        o = self.replay(rows)
        self.assertEqual([], o.offers)
        self.assertEqual([BASE + 20_000_000], o.episode.breaches)
        o.step(BASE + 30_000_000, 118, [event(30, "claim", "supply", 110, 111, "RailFailed", price=118)])
        self.assertEqual([], o.offers)
        self.assertEqual("attacked_structure_failed", o.completed[-1]["resolution"])

    def test_breached_stack_can_rebuild_while_same_opposition_remains_live(self):
        rows = self.fixture()[:3] + [event(20, "proof", "demand", 105, 106, "RailFailed", price=104),
                                    event(25, "replacement", "demand", 105, 106, price=109),
                                    event(30, "claim", "supply", 110, 111, "RailFailed", price=118)]
        o = self.replay(rows)
        self.assertEqual("clearance_rebuilt_after_breach", o.offers[0]["completion"])
        self.assertEqual(["replacement"], o.offers[0]["support"])
        self.assertEqual(["proof"], o.offers[0]["failed"])

    def test_range_union_keeps_holes_and_ignores_duplicate_fragments(self):
        self.assertEqual([[100, 101], [105, 106]], e.union([(100, 101), (100, 100.5), (100.75, 101), (105, 106)]))

    def test_equivalent_fragmentation_preserves_permissions_and_coverage(self):
        rows = self.fixture()
        split = []
        for r in rows:
            mid = (r["lo"] + r["hi"]) / 2
            split.extend([{**r, "id": r["id"] + "a", "hi": mid},
                          {**r, "id": r["id"] + "b", "lo": mid}])
        one, many = self.replay(rows), self.replay(split)
        select = lambda o: [(r["t"], r["signature"], r["support_coverage"], r["claim_coverage"]) for r in o.offers]
        self.assertEqual(select(one), select(many))
        self.assertEqual(len(one.completed), len(many.completed))

    def test_failure_and_new_opposition_in_same_sample_cannot_add_early(self):
        rows = self.fixture() + [event(30, "new", "supply", 112, 113, price=118, order=301)]
        self.assertEqual([], self.replay(rows).offers)

    def test_repeated_hold_is_not_new_permission(self):
        rows = self.fixture() + [event(40, "proof", "demand", 105, 106, "RailHeld", price=118),
                                 event(50, "proof", "demand", 105, 106, "RailHeld", price=118)]
        self.assertEqual(1, len(self.replay(rows).offers))

    def test_same_area_can_support_a_new_attack_after_departure(self):
        rows = self.fixture() + [event(40, "proof", "demand", 105, 106, "RailTested", price=106),
                                 event(41, "claim2", "supply", 110, 111, price=108),
                                 event(50, "proof", "demand", 105, 106, "RailHeld", price=109),
                                 event(60, "claim2", "supply", 110, 111, "RailFailed", price=119)]
        offers = self.replay(rows).offers
        self.assertEqual(2, len(offers))
        self.assertEqual(offers[0]["support_coverage"], offers[1]["support_coverage"])

    def test_claim_observation_does_not_require_new_favorable_band_first(self):
        rows = self.fixture() + [event(40, "claim2", "supply", 120, 121, price=117),
                                 event(50, "newproof", "demand", 115, 116, price=118),
                                 event(60, "claim2", "supply", 120, 121, "RailFailed", price=125)]
        self.assertEqual(2, len(self.replay(rows).offers))

    def test_resolved_repair_waits_for_later_proof_without_forgetting_failure(self):
        rows = self.fixture() + [event(40, "claim2", "supply", 120, 121, price=117),
                                 event(50, "claim2", "supply", 120, 121, "RailFailed", price=125),
                                 event(60, "newproof", "demand", 122, 123, price=126)]
        offers = self.replay(rows).offers
        self.assertEqual(2, len(offers))
        self.assertEqual(BASE + 60_000_000, offers[-1]["t"])
        self.assertEqual(BASE + 50_000_000, offers[-1]["claim_failure_t"])

    def test_new_attack_supersedes_unused_old_failure(self):
        rows = self.fixture() + [event(40, "claim2", "supply", 120, 121, price=117),
                                 event(50, "claim2", "supply", 120, 121, "RailFailed", price=125),
                                 event(55, "claim3", "supply", 124, 125, price=121),
                                 event(60, "newproof", "demand", 122, 123, price=126)]
        self.assertEqual(1, len(self.replay(rows).offers))

    def test_live_prefill_claim_is_adopted_but_prefill_failure_is_not(self):
        warm = [event(-5, "claim", "supply", 110, 111)]
        rows = [event(5, "proof", "demand", 105, 106, price=109),
                event(30, "claim", "supply", 110, 111, "RailFailed", price=118)]
        self.assertEqual("typed_clear", self.replay(rows, warm).offers[0]["signature"])
        warm.append(event(-1, "claim", "supply", 110, 111, "RailFailed", price=118))
        self.assertEqual([], self.replay(rows[:1], warm).offers)

    def test_test_hold_without_claim_is_explicit_alternative(self):
        rows = [event(5, "proof", "demand", 105, 106, price=115),
                event(10, "proof", "demand", 105, 106, "RailTested", price=105),
                event(20, "proof", "demand", 105, 106, "RailHeld", price=110)]
        o = self.replay(rows)
        self.assertEqual(["defense_only"], [r["signature"] for r in o.offers])
        o.step(BASE + 30_000_000, 116)
        self.assertEqual(["defense_only", "defense_departed"], [r["signature"] for r in o.offers])

    def test_future_suffix_does_not_rewrite_prefix(self):
        rows = self.fixture()
        o = self.replay(rows)
        before = copy.deepcopy(o.offers)
        o.step(BASE + 40_000_000, 120, [event(40, "future", "supply", 118, 119, price=120)])
        self.assertEqual(before, o.offers[:len(before)])

    def test_gap_censors_instead_of_resurrecting_group(self):
        rows = self.fixture()[:3] + [{"t": BASE + 15_000_000, "kind": "Reset"}] + self.fixture()[3:]
        o = self.replay(rows)
        self.assertEqual([], o.offers)
        self.assertEqual("evidence_gap", o.completed[-1]["resolution"])


class InventoryTests(unittest.TestCase):
    def fixture(self, second=False):
        r = root()
        r["end_t"], r["end_reason"] = BASE + 40_000_000, "window_end"
        m = e.Market.__new__(e.Market)
        prices = [(0, 102), (10, 110), (11, 110), (12, 105), (40, 115)]
        m.events = [event(5, "proof", "demand", 105, 106)]
        offers = [{"t": BASE + 10_000_000, "time": "10:01:10", "episode": 1,
                   "signature": "typed_clear", "support": ["proof"]}]
        if second:
            prices = [(0, 102), (10, 110), (11, 110), (20, 120), (21, 120), (30, 111.5), (31, 108), (40, 115)]
            m.events += [event(15, "proof2", "demand", 115, 116),
                         event(30, "proof2", "demand", 115, 116, "RailFailed", price=111.5)]
            offers += [{"t": BASE + 20_000_000, "time": "10:01:20", "episode": 2,
                        "signature": "typed_clear", "support": ["proof2"]}]
        m.quotes = [{"t": BASE + sec * 1_000_000, "bid": p, "ask": p + .25, "mid": p + .125} for sec, p in prices]
        m.qt = [q["t"] for q in m.quotes]
        case = e.s.Case("NQ", "2026-09-03", "long", "10:01", "10:02", "test")
        return case, m, r, offers

    def test_be_arms_on_fill_quote_before_next_quote_crosses_it(self):
        case, m, r, offers = self.fixture()
        result = e.simulate(case, m, r, offers, 2, "typed_only", "root_only")
        self.assertIn("weighted_be_proxy", result["risk_exits"])
        self.assertEqual(BASE + 12_000_000, result["actions"][-1]["t"])

    def test_reducing_high_entry_tranche_does_not_lower_position_average(self):
        case, m, r, offers = self.fixture(second=True)
        result = e.simulate(case, m, r, offers, 2, "typed_only", "tranche_groups")
        at_trim = next(x for x in result["inventory"] if x["t"] == BASE + 30_000_000)
        self.assertEqual(111, at_trim["position_average"])
        self.assertIn("added_group_failed", result["risk_exits"])
        self.assertIn("weighted_be_proxy", result["risk_exits"])

    def test_group_management_updates_even_when_add_budget_is_spent(self):
        case, m, r, offers = self.fixture(second=True)
        result = e.simulate(case, m, r, offers, 1, "typed_only", "latest_group_campaign")
        self.assertEqual(1, result["accepted_adds"])
        self.assertIn("latest_confirmed_group_failed", result["risk_exits"])

    def test_multiple_signatures_of_one_episode_cannot_multiply_adds(self):
        case, m, r, offers = self.fixture()
        offers.append({**offers[0], "signature": "defense_departed"})
        result = e.simulate(case, m, r, offers, 3, "test_defense", "root_only")
        self.assertEqual(1, result["accepted_adds"])

    def test_new_opposition_before_delayed_fill_rejects_offer(self):
        case, m, r, offers = self.fixture()
        m.events.append(event(10.5, "new_claim", "supply", 108, 109))
        result = e.simulate(case, m, r, offers, 3, "typed_only", "root_only")
        self.assertEqual(0, result["accepted_adds"])
        self.assertEqual("new_or_live_opposition", result["decisions"][0]["result"])

    def test_missing_support_is_not_assumed_owned_at_fill(self):
        case, m, r, offers = self.fixture()
        m.events.clear()
        result = e.simulate(case, m, r, offers, 3, "typed_only", "root_only")
        self.assertEqual(0, result["accepted_adds"])
        self.assertEqual("support_not_current", result["decisions"][0]["result"])


if __name__ == "__main__":
    unittest.main()
