import csv
import unittest

import study as s


BASE = s.stamp("2026-09-03", "10:01")
CASE = s.Case("ES", "2026-09-03", "long", "10:00", "11:00", "test")


def event(seconds, rail, side, lo, hi, kind="RailOwned", price=115, order=None):
    return {"t": BASE + int(seconds * 1e6), "id": rail, "side": side,
            "lo": lo, "hi": hi, "kind": kind, "price": price,
            "order": int(seconds * 10) if order is None else order,
            "ready": True, "source": "Consumed", "epoch": 1}


def root():
    return {"case": CASE.name, "root_n": 1, "t": BASE, "price": 102,
            "seed": event(-1, "root", "demand", 100, 101, price=102),
            "end_t": BASE + 600_000_000}


def market(events=(), quotes=(), gex=()):
    m = s.Market.__new__(s.Market)
    m.events = list(events)
    m.quotes = list(quotes)
    m.qt = [q["t"] for q in quotes]
    m.tt, m.tp = [], []
    m.gex = {cat: list(gex) for cat in s.CATEGORIES}
    m.gt = {cat: [r["available_t"] for r in gex] for cat in s.CATEGORIES}
    m.postures = {}
    return m


def gamma(seconds, zero=100, api_seconds=None, available_seconds=None):
    t = BASE + int(seconds * 1e6)
    api = t if api_seconds is None else BASE + int(api_seconds * 1e6)
    return {"id": int(seconds), "t": t, "api_t": api,
            "available_t": max(t, api) if available_seconds is None else BASE + int(available_seconds * 1e6),
            "zero_gamma": zero, "call_wall": 120, "put_wall": 90}


class CausalStudyTests(unittest.TestCase):
    def fixture(self):
        return [event(10, "claim", "supply", 110, 111),
                event(20, "proof", "demand", 112, 113),
                event(30, "claim", "supply", 110, 111, "RailFailed")]

    def test_retained_proof_qualifies_only_at_failure(self):
        rows, _ = s.model_candidates(CASE, market(self.fixture()), root())
        joint = [r for r in rows if r["method"] == "joint_range"]
        self.assertEqual([BASE + 30_000_000], [r["t"] for r in joint])
        self.assertTrue(joint[0]["proof_precedes_failure"])
        self.assertFalse(any(r["method"] == "serial_identity" for r in rows))

    def test_serial_waits_for_next_proof(self):
        events = self.fixture() + [event(40, "new", "demand", 112, 113)]
        rows, _ = s.model_candidates(CASE, market(events), root())
        self.assertEqual([BASE + 40_000_000], [r["t"] for r in rows if r["method"] == "serial_identity"])

    def test_unrelated_failure_cannot_complete_claim(self):
        events = self.fixture()
        events[-1] = {**events[-1], "id": "neighbor"}
        rows, _ = s.model_candidates(CASE, market(events), root())
        self.assertTrue(all(r["method"] == "direct_favorable" for r in rows))

    def test_tested_proof_is_not_current_confirmation(self):
        events = self.fixture()
        events.insert(2, event(25, "proof", "demand", 112, 113, "RailTested"))
        rows, _ = s.model_candidates(CASE, market(events), root())
        self.assertFalse(any(r["method"].startswith("joint") for r in rows))
    @unittest.skipUnless(s.ENGINE.exists(), "Build the standalone EngineProbe first")
    def test_vetoed_add_does_not_end_later_candidate_search(self):
        events = [event(5, "candidate", "demand", 105, 106),
                  event(10, "claim", "supply", 110, 111),
                  event(30, "claim", "supply", 110, 111, "RailFailed"),
                  event(40, "proof1", "demand", 112, 113),
                  event(50, "proof2", "demand", 113, 114, price=116)]
        s.OUT.mkdir(parents=True, exist_ok=True)
        p = s.OUT / "policy-test"
        s.write_lines(p / "events.jsonl", events)
        s.write_json(p / "config.json", {"side": "long", "seed_t": BASE, "seed_order": -1,
                     "end_t": BASE + 60_000_000, "root": [100, 101], "root_price": 102,
                     "arena": [1, 100000], "gates": {"later": [500]}})
        s.run_engine("policy", p / "config.json", p / "events.jsonl", p / "output.jsonl")
        rows = s.read_lines(p / "output.jsonl")
        accepted = {r["scenario"]: r["order"] for r in rows if r["action"] == "AllowAdd" and r["emitted"]}
        self.assertEqual({"none": 400, "later": 500}, accepted)
        veto = next(r for r in rows if r["scenario"] == "later" and r["order"] == 400)
        self.assertTrue(veto["vetoed"])
        self.assertEqual(veto["before"], veto["after"])

    def test_price_reclaim_does_not_imply_range_reclaim(self):
        events = self.fixture()
        events[1] = event(20, "proof", "demand", 105, 106)
        rows, _ = s.model_candidates(CASE, market(events), root())
        self.assertTrue(any(r["method"] == "joint_price" for r in rows))
        self.assertFalse(any(r["method"] == "joint_range" for r in rows))

    def test_warm_claim_is_explicit_not_silently_inherited(self):
        events = self.fixture()
        events[0] = event(-5, "claim", "supply", 110, 111)
        cold, _ = s.model_candidates(CASE, market(events), root())
        warm, _ = s.model_candidates(CASE, market(events), root(), warm=True)
        self.assertFalse(any(r["method"] == "joint_range" for r in cold))
        picked = [r for r in warm if r["method"] == "warm_joint_range"]
        self.assertEqual(1, len(picked))
        self.assertTrue(picked[0]["pre_fill_claim"])

    def test_future_events_do_not_rewrite_prefix(self):
        first, _ = s.model_candidates(CASE, market(self.fixture()), root())
        later = self.fixture() + [event(45, "future", "supply", 120, 121)]
        full, _ = s.model_candidates(CASE, market(later), root())
        self.assertEqual(first, [r for r in full if r["t"] <= BASE + 30_000_000])

    def test_pre_fill_failure_is_not_reusable_add_authority(self):
        events = [event(-10, "claim", "supply", 110, 111),
                  event(-5, "claim", "supply", 110, 111, "RailFailed"),
                  event(20, "proof", "demand", 112, 113)]
        rows, _ = s.model_candidates(CASE, market(events), root(), warm=True)
        self.assertFalse(rows)

    def test_stale_gap_and_observed_cross_are_distinct(self):
        quotes = [{"t": BASE + i * 1_000_000, "mid": 105, "bid": 104.75, "ask": 105.25}
                  for i in (0, 30, 61, 63, 64)]
        m = market(quotes=quotes, gex=[gamma(0, 100), gamma(63, 100)])
        row = {"t": BASE + 64_000_000, "price": 105, "proof_lo": 102, "proof_hi": 103,
               "proof_t": BASE + 30_000_000}
        fields = s.gamma_fields(CASE, m, row, "gex_full")
        self.assertTrue(fields["rail_renewed_ok"])
        self.assertFalse(fields["rail_rearmed_ok"])

    def test_same_batch_order_is_preserved(self):
        claim = event(10, "claim", "supply", 110, 111)
        proof = event(30, "proof", "demand", 112, 113, order=300)
        failure = event(30, "claim", "supply", 110, 111, "RailFailed", order=301)
        rows, _ = s.model_candidates(CASE, market([claim, proof, failure]), root())
        self.assertEqual([301], [r["order"] for r in rows if r["method"] == "joint_range"])
        self.assertFalse(any(r["method"] == "serial_identity" for r in rows))

    def test_missing_future_and_stale_gamma(self):
        m = market(gex=[gamma(5, api_seconds=10)])
        self.assertFalse(m.gamma(BASE + 9_000_000)["fresh"])
        self.assertTrue(m.gamma(BASE + 10_000_000)["fresh"])
        stale = market(gex=[gamma(0, api_seconds=-61)])
        self.assertFalse(stale.gamma(BASE)["fresh"])

    def test_gamma_renewal_requires_new_proof_after_relocation(self):
        quotes = [{"t": BASE + i * 1_000_000, "mid": 105, "bid": 104.75, "ask": 105.25} for i in range(4)]
        m = market(quotes=quotes, gex=[gamma(0, 100), gamma(2, 110)])
        short = s.Case("ES", "2026-09-03", "short", "10:00", "11:00", "test")
        row = {"t": BASE + 3_000_000, "price": 105, "proof_lo": 106, "proof_hi": 107,
               "proof_t": BASE + 1_000_000}
        fields = s.gamma_fields(short, m, row, "gex_full")
        self.assertTrue(fields["rail_side_ok"])
        self.assertFalse(fields["rail_renewed_ok"])
        self.assertTrue(s.gamma_fields(short, m, {**row, "proof_t": BASE + 2_000_000}, "gex_full")["rail_renewed_ok"])

    def test_quotes_cannot_look_forward_implicitly(self):
        m = market(quotes=[{"t": BASE + 1_000_000, "mid": 105, "bid": 104.75, "ask": 105.25}])
        self.assertIsNone(m.quote(BASE))
        self.assertEqual(BASE + 1_000_000, m.quote(BASE, forward=True)["t"])
        self.assertIsNone(m.quote(BASE - 2_000_000, forward=True))

    def test_reset_discards_prior_claim_and_proof(self):
        events = self.fixture()
        events.insert(2, {"t": BASE + 25_000_000, "kind": "Reset"})
        rows, _ = s.model_candidates(CASE, market(events), root())
        self.assertFalse(any(r["method"].startswith("joint") for r in rows))

    @unittest.skipUnless((s.OUT / "first_add_comparison.csv").exists(), "Run the study first")
    def test_generated_outputs_have_no_future_permission_inputs(self):
        with (s.OUT / "roots.csv").open(newline="") as f:
            roots = {(r["case"], r["root_n"]): r for r in csv.DictReader(f)}
        with (s.OUT / "first_add_comparison.csv").open(newline="") as f:
            rows = list(csv.DictReader(f))
        for row in rows:
            if row["selected"] != "True":
                continue
            root = roots[(row["case"], row["root_n"])]
            t, fill = int(row["t"]), int(row["fill_t"])
            self.assertLessEqual(int(root["t"]), t)
            self.assertGreaterEqual(fill, t + 250_000)
            self.assertLess(fill, int(root["end_t"]))
            self.assertLessEqual(int(row["proof_t"]), t)
            if row["gex_available_t"]:
                self.assertLessEqual(int(row["gex_available_t"]), t)
            if row["gate"] != "none":
                self.assertEqual("True", row["gex_fresh"])
                self.assertLessEqual(float(row["gex_age_sec"]), 60)
            if row["failure_t"]:
                self.assertLessEqual(int(row["repair_t"]), int(row["failure_t"]))
                self.assertLessEqual(int(row["failure_t"]), t)
                if row["method"].startswith("warm_"):
                    self.assertGreater(int(row["failure_t"]), int(root["t"]))


if __name__ == "__main__":
    unittest.main()
