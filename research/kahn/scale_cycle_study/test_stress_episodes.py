import unittest
from types import SimpleNamespace
from unittest.mock import patch

import audit_stress
import episode_study as e
import stress_episodes as st
from test_study import BASE, event, root


class StressTests(unittest.TestCase):
    def test_episode_model_remains_frozen(self):
        st.verify_frozen()

    def test_new_windows_and_extension_are_fixed(self):
        self.assertEqual([("10:00", "10:30"), ("11:00", "11:30"), ("11:50", "12:30"), ("11:50", "12:40")],
                         [(c.start, c.end) for c in st.CASES])

    def test_start_sensitivity_does_not_move_endpoint(self):
        earlier = st.shift_case(st.CASES[2], -1)
        self.assertEqual("11:49", earlier.start)
        self.assertEqual("12:30", earlier.end)

    def test_prepare_uses_isolated_output_and_no_gamma(self):
        with patch.object(st.s, "prepare") as prepare:
            st.prepare()
        self.assertEqual(2, prepare.call_count)
        for call in prepare.call_args_list:
            self.assertEqual(st.DATA, call.kwargs["output"])
            self.assertFalse(call.kwargs["include_gex"])

    def test_risk_context_never_reads_future_state(self):
        rows = [event(5, "proof", "demand", 105, 106),
                event(30, "proof", "demand", 105, 106, "RailFailed")]
        self.assertEqual("RailOwned", audit_stress.states_at(rows, BASE + 20_000_000)["proof"]["kind"])

    def test_adverse_only_path_has_zero_favorable_excursion(self):
        market = SimpleNamespace(quotes=[{"t": BASE + 1_000_000, "bid": 99, "ask": 99.25}])
        result = {"actions": [{"action": "add", "t": BASE, "price": 100, "episode": 1,
                               "signal_time": "10:00:00", "time": "10:00:01"}]}
        rows = st.outcome(st.CASES[0], market, {"end_t": BASE + 2_000_000}, result)
        self.assertEqual(0, rows[0]["mfe_ticks_label"])
        self.assertEqual(4, rows[0]["mae_ticks_label"])

    def test_frozen_model_exposes_unbounded_resolved_repair_wait(self):
        # Record a weakness of the frozen hypothesis, not a desired future contract.
        observer = e.Observer("long", root())
        rows = [event(10, "claim", "supply", 110, 111, price=108),
                event(20, "claim", "supply", 110, 111, "RailFailed", price=118),
                event(350, "new", "demand", 140, 141, price=148)]
        for row in rows:
            observer.step(row["t"], row["price"], [row])
        self.assertEqual(1, len(observer.offers))
        context = audit_stress.permission_context(rows, observer.offers[0])
        self.assertEqual(330, context["failure_age_seconds"])
        self.assertEqual([], context["defended"])


if __name__ == "__main__":
    unittest.main()
