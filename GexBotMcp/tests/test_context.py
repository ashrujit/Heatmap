from __future__ import annotations

import unittest

from pathlib import Path
import sys


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gexbot_mcp.context import build_decision_context, snapshot_summary  # noqa: E402


SAMPLE = {
    "timestamp": 1777492800,
    "ticker": "SPX",
    "min_dte": 0,
    "sec_min_dte": 1,
    "spot": 7138.55,
    "zero_gamma": 7112.95,
    "major_pos_vol": 7135,
    "major_pos_oi": 7200,
    "major_neg_vol": 7100,
    "major_neg_oi": 6900,
    "strikes": [
        [6890, -228.01, -86.9, [-240.55]],
        [7135, 1145886.722, 997473.336, [0]],
        [7140, 170979.742, 51521.105, [0]],
        [7200, 88.2, 400000.0, [0]],
    ],
    "sum_gex_vol": 1712585.519,
    "sum_gex_oi": 51521.105,
    "delta_risk_reversal": 0.118,
}


class ContextTests(unittest.TestCase):
    def test_build_decision_context_normalizes_major_levels(self) -> None:
        result = build_decision_context(
            SAMPLE,
            package="classic",
            category="gex_full",
            center_price=7138.55,
            radius_points=20,
            max_strikes=3,
            tick_size=0.25,
            zone_ticks=4,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["ticker"], "SPX")
        self.assertEqual(result["as_of_utc"], "2026-04-29T20:00:00Z")
        self.assertEqual(result["regime_hint"]["name"], "positive_gamma")
        self.assertEqual(result["major_levels"][0]["role"], "zero_gamma")
        self.assertEqual(result["major_levels"][0]["range"], {"lower": 7111.95, "upper": 7113.95})
        self.assertEqual([item["strike"] for item in result["nearby_strikes"]], [7140.0, 7135.0])
        self.assertEqual(result["wall_context"]["call_wall"]["price"], 7135.0)
        self.assertEqual(result["wall_context"]["put_wall"]["price"], 7100.0)
        self.assertEqual(result["wall_context"]["oi_call_wall"]["price"], 7200.0)
        self.assertEqual(result["wall_context"]["derived_from_strikes"]["max_positive_gex_volume"]["strike"], 7135.0)
        self.assertEqual(result["wall_context"]["derived_from_strikes"]["max_negative_gex_oi"]["strike"], 6890.0)
        self.assertIn("Kahn entry/add authorization by itself", result["decision_boundary"]["not_usable_for"])
        self.assertEqual(result["kahn_mapping"]["integration_stage"], "proposal_only")

    def test_snapshot_summary_handles_raw_payload(self) -> None:
        result = snapshot_summary(SAMPLE)

        self.assertEqual(result["ticker"], "SPX")
        self.assertEqual(result["strike_count"], 4)
        self.assertIn("zero_gamma", result["keys"])


if __name__ == "__main__":
    unittest.main()
